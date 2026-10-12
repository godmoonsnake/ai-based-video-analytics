from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True)
class Scope:
    tenant: str
    site: str
    actor: str = "worker"
    role: str = "worker"


current_scope: ContextVar[Scope | None] = ContextVar("darson_scope", default=None)


@contextmanager
def scoped(scope: Scope):
    token = current_scope.set(scope)
    try:
        yield scope
    finally:
        current_scope.reset(token)


def session_scope() -> Scope:
    from app.config import get_settings

    value = current_scope.get()
    if value is not None:
        return value
    if get_settings().environment == "production":
        raise PermissionError("explicit tenant/site scope required")
    return Scope("development", "site_a", "development-operator", "supervisor")
