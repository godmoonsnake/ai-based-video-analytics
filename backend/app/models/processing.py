from sqlalchemy import Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.db.session import Base, Scoped, JSONBType


class ProcessingJob(Scoped, Base):
    """Transactional outbox and leased work record; IDs encode semantic uniqueness."""
    __tablename__ = "processing_job"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    kind: Mapped[str] = mapped_column(String, index=True)
    payload: Mapped[dict] = mapped_column(JSONBType)
    status: Mapped[str] = mapped_column(String, default="pending", index=True)
    lease_owner: Mapped[str | None] = mapped_column(String)
    lease_expiry: Mapped[float | None] = mapped_column(Float)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    next_retry: Mapped[float] = mapped_column(Float, default=0)
    error_class: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[float] = mapped_column(Float)
    completed_at: Mapped[float | None] = mapped_column(Float)


class SourceLease(Scoped, Base):
    __tablename__ = "source_lease"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    owner: Mapped[str] = mapped_column(String)
    expires_at: Mapped[float] = mapped_column(Float)
    last_seen: Mapped[float | None] = mapped_column(Float)
    fault: Mapped[str | None] = mapped_column(Text)
