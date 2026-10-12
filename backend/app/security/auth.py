"""OIDC access-token verification and explicit database grants.

The configured issuer and JWKS are trusted deployment settings, never token URLs.
Principal disable / tokens_valid_after revokes access without waiting for expiry.
"""
from functools import lru_cache
import json
from pathlib import Path

import jwt
from fastapi import HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.session import engine
from app.models.security import Principal, PrincipalScope
from app.security.context import Scope

ROLES = {"operator", "supervisor", "responder", "client_viewer", "auditor", "configuration_admin"}
MEDIA_ROLES = {"operator", "supervisor", "responder", "client_viewer", "auditor"}
REVIEW_ROLES = {"operator", "supervisor"}


@lru_cache
def jwks_client(url: str):
    return jwt.PyJWKClient(url, cache_jwk_set=True, lifespan=300, timeout=5)


def verify_token(token: str) -> dict:
    settings = get_settings()
    if not all((settings.oidc_issuer, settings.oidc_audience)) or not (settings.oidc_jwks_url or settings.oidc_jwks_file):
        raise HTTPException(503, "OIDC is not configured")
    if not settings.oidc_jwks_file and not settings.oidc_jwks_url.startswith("https://"):
        raise HTTPException(503, "JWKS must use HTTPS")
    try:
        if settings.oidc_jwks_file:
            # Trusted deployment file of PUBLIC RSA keys. Never fetched from a
            # token URL, and never used to bypass expiry or scope validation.
            header = jwt.get_unverified_header(token)
            if header.get("alg") != "RS256" or not header.get("kid"):
                raise ValueError("invalid signing key header")
            keys = json.loads(Path(settings.oidc_jwks_file).read_text(encoding="utf-8"))["keys"]
            matches = [item for item in keys if item.get("kid") == header["kid"] and
                       item.get("kty") == "RSA" and item.get("use", "sig") == "sig" and
                       item.get("alg", "RS256") == "RS256"]
            if len(matches) != 1:
                raise ValueError("unknown or ambiguous signing key")
            key = jwt.PyJWK.from_dict(matches[0], algorithm="RS256").key
        else:
            key = jwks_client(settings.oidc_jwks_url).get_signing_key_from_jwt(token).key
        return jwt.decode(token, key, algorithms=["RS256"], audience=settings.oidc_audience,
                          issuer=settings.oidc_issuer,
                          options={"require": ["exp", "iat", "sub", "iss", "aud"]})
    except (jwt.PyJWTError, ValueError, TypeError, KeyError, OSError):
        raise HTTPException(401, "invalid access token") from None


def authenticate(request: Request) -> Scope:
    settings = get_settings()
    if settings.auth_mode == "development" and settings.environment != "production":
        # No tenant/actor override headers in the unauthenticated offline demo.
        return Scope("development", "site_a", "development-operator", "supervisor")
    if settings.auth_mode != "oidc":
        raise HTTPException(503, "authentication configuration rejected")
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(401, "bearer access token required")
    claims = verify_token(token)
    # Control-plane tables are not media. No user-selectable SQL or scope bypass.
    with Session(engine) as db:
        principal = db.get(Principal, claims["sub"])
        if not principal or not principal.enabled or claims["iat"] <= principal.tokens_valid_after:
            raise HTTPException(401, "principal disabled or token revoked")
        tenant, site = claims.get("tenant_id"), claims.get("site_id")
        if not tenant or not site:
            raise HTTPException(403, "token is not bound to a tenant and site")
        grant = db.scalar(select(PrincipalScope).where(
            PrincipalScope.subject == principal.subject, PrincipalScope.tenant_id == tenant,
            PrincipalScope.site_id == site))
        if not grant or grant.role not in ROLES:
            raise HTTPException(403, "site access denied")
        if settings.require_mfa and grant.role in {"supervisor", "configuration_admin"}:
            if "mfa" not in claims.get("amr", []):
                raise HTTPException(403, "privileged access requires MFA")
        return Scope(tenant, site, principal.subject, grant.role)


def require_role(db, roles: set[str]):
    scope = db.info["scope"]
    if scope.role not in roles and scope.role != "worker":
        raise HTTPException(403, "action not permitted for this role")
    return scope
