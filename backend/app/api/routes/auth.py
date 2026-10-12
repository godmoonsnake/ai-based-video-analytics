from fastapi import APIRouter, Depends
import time
from sqlalchemy import select
from app.db.session import get_db
from app.models.security import Principal, PrincipalScope

router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])


@router.get("/me")
def me(db=Depends(get_db)):
    scope = db.info["scope"]
    principal = db.get(Principal, scope.actor)
    grant = db.scalar(select(PrincipalScope).where(
        PrincipalScope.subject == scope.actor, PrincipalScope.tenant_id == scope.tenant,
        PrincipalScope.site_id == scope.site))
    if not principal or not grant:
        from fastapi import HTTPException
        raise HTTPException(401, "session grant no longer exists")
    return {"subject": scope.actor, "display_name": getattr(principal, "display_name", None) or scope.actor,
            "tenant_id": scope.tenant, "site_id": scope.site, "role": scope.role}


@router.post("/logout")
def logout(db=Depends(get_db)):
    scope = db.info["scope"]
    principal = db.get(Principal, scope.actor)
    if not principal:
        from fastapi import HTTPException
        raise HTTPException(401, "session revoked")
    principal.tokens_valid_after = max(principal.tokens_valid_after or 0, time.time())
    db.commit()
    return {"revoked": True}
