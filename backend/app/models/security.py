from sqlalchemy import Boolean, Float, ForeignKey, ForeignKeyConstraint, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class Tenant(Base):
    __tablename__ = "tenant"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)


class Site(Base):
    __tablename__ = "site"
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenant.id"), primary_key=True)
    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    timezone: Mapped[str] = mapped_column(String, default="Asia/Kolkata")


class Building(Base):
    __tablename__ = "building"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String)
    site_id: Mapped[str] = mapped_column(String)
    name: Mapped[str] = mapped_column(String)
    __table_args__ = (ForeignKeyConstraint(["tenant_id", "site_id"], ["site.tenant_id", "site.id"]),)


class Principal(Base):
    __tablename__ = "principal"
    subject: Mapped[str] = mapped_column(String, primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    tokens_valid_after: Mapped[float] = mapped_column(Float, default=0)


class PrincipalScope(Base):
    __tablename__ = "principal_scope"
    id: Mapped[int] = mapped_column(primary_key=True)
    subject: Mapped[str] = mapped_column(ForeignKey("principal.subject"))
    tenant_id: Mapped[str] = mapped_column(String)
    site_id: Mapped[str] = mapped_column(String)
    role: Mapped[str] = mapped_column(String)
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "site_id"], ["site.tenant_id", "site.id"]),
        UniqueConstraint("subject", "tenant_id", "site_id"),
    )
