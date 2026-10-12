from sqlalchemy import Boolean, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from app.db.session import Base, Scoped, JSONBType


class CorrelationRun(Scoped, Base):
    __tablename__ = "correlation_run"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    policy_version: Mapped[str] = mapped_column(String)
    model_version: Mapped[str] = mapped_column(String)
    created_at: Mapped[float] = mapped_column(Float)
    supersedes: Mapped[str | None] = mapped_column(String)


class CorrelationHypothesis(Scoped, Base):
    __tablename__ = "correlation_hypothesis"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    run_id: Mapped[str] = mapped_column(String, index=True)
    from_key: Mapped[list] = mapped_column(JSONBType)
    to_key: Mapped[list] = mapped_column(JSONBType)
    signals: Mapped[dict] = mapped_column(JSONBType)
    score: Mapped[float] = mapped_column(Float)
    disposition: Mapped[str] = mapped_column(String)


class IncidentEpisode(Scoped, Base):
    __tablename__ = "incident_episode"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    incident_id: Mapped[int] = mapped_column(Integer, index=True)


class IncidentVersion(Scoped, Base):
    __tablename__ = "incident_version"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    incident_id: Mapped[int] = mapped_column(Integer, index=True)
    created_at: Mapped[float] = mapped_column(Float)
    requires_review: Mapped[bool] = mapped_column(Boolean)
    snapshot: Mapped[dict] = mapped_column(JSONBType)
