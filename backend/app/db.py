"""Memory: household profile, application ledger, session summaries, action log."""
import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker
from sqlalchemy.pool import StaticPool

from . import config

_kwargs = {}
if not config.DATABASE_URL.startswith("sqlite"):
    # Managed databases close idle connections. Checking first turns a dead connection into a fresh one, not an error.
    _kwargs.update(pool_pre_ping=True, pool_recycle=300, pool_size=5, max_overflow=5)
if config.DATABASE_URL.startswith("sqlite"):
    _kwargs["connect_args"] = {"check_same_thread": False}
    if ":memory:" in config.DATABASE_URL:
        _kwargs["poolclass"] = StaticPool

engine = create_engine(config.DATABASE_URL, **_kwargs)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def new_id() -> str:
    return uuid.uuid4().hex[:12]


class Base(DeclarativeBase):
    pass


class Household(Base):
    __tablename__ = "households"
    id: Mapped[str] = mapped_column(String(12), primary_key=True, default=new_id)
    display_name: Mapped[str | None] = mapped_column(String(120))
    village: Mapped[str | None] = mapped_column(String(120))
    operator: Mapped[str | None] = mapped_column(String(120))
    stage: Mapped[str] = mapped_column(String(20), default="INTERVIEW")
    agent_state: Mapped[dict] = mapped_column(JSON, default=dict)
    questions_asked: Mapped[int] = mapped_column(Integer, default=0)
    session_no: Mapped[int] = mapped_column(Integer, default=1)
    is_seed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    facts: Mapped[list["Fact"]] = relationship(cascade="all, delete-orphan", lazy="selectin")
    applications: Mapped[list["Application"]] = relationship(cascade="all, delete-orphan", lazy="selectin")


class Fact(Base):
    __tablename__ = "facts"
    __table_args__ = (UniqueConstraint("household_id", "key"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    household_id: Mapped[str] = mapped_column(ForeignKey("households.id"))
    key: Mapped[str] = mapped_column(String(60))
    value: Mapped[object] = mapped_column(JSON)
    source: Mapped[str] = mapped_column(String(20))
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    updated_at: Mapped[datetime] = mapped_column(DateTime)


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    household_id: Mapped[str] = mapped_column(ForeignKey("households.id"), index=True)
    role: Mapped[str] = mapped_column(String(12))
    hi: Mapped[str] = mapped_column(Text)
    en: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(20), default="text")
    session_no: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime)


class SessionSummary(Base):
    __tablename__ = "session_summaries"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    household_id: Mapped[str] = mapped_column(ForeignKey("households.id"), index=True)
    session_no: Mapped[int] = mapped_column(Integer)
    summary: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime)


class Application(Base):
    __tablename__ = "applications"
    id: Mapped[str] = mapped_column(String(12), primary_key=True, default=new_id)
    household_id: Mapped[str] = mapped_column(ForeignKey("households.id"), index=True)
    scheme_id: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(24), default="draft")
    fields: Mapped[dict] = mapped_column(JSON, default=dict)
    documents: Mapped[list] = mapped_column(JSON, default=list)
    readback_hash: Mapped[str | None] = mapped_column(String(64))
    confirmed_hash: Mapped[str | None] = mapped_column(String(64))
    confirmed_by: Mapped[str | None] = mapped_column(String(60))
    reference: Mapped[str | None] = mapped_column(String(40))
    frames: Mapped[int] = mapped_column(Integer, default=0)
    fill_accuracy: Mapped[float | None] = mapped_column(Float)
    next_action: Mapped[dict | None] = mapped_column(JSON)
    due_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime)
    events: Mapped[list["StatusEvent"]] = relationship(cascade="all, delete-orphan", lazy="selectin", order_by="StatusEvent.at")


class StatusEvent(Base):
    __tablename__ = "status_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id"), index=True)
    status: Mapped[str] = mapped_column(String(24))
    at: Mapped[datetime] = mapped_column(DateTime)


class Reminder(Base):
    __tablename__ = "reminders"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id"), index=True)
    kind: Mapped[str] = mapped_column(String(30))
    due_at: Mapped[datetime] = mapped_column(DateTime)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime)


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    household_id: Mapped[str] = mapped_column(ForeignKey("households.id"), index=True)
    application_id: Mapped[str | None] = mapped_column(String(12))
    kind: Mapped[str] = mapped_column(String(20))
    hi: Mapped[str] = mapped_column(Text)
    en: Mapped[str] = mapped_column(Text)
    delivery: Mapped[str] = mapped_column(String(20), default="in_app")
    created_at: Mapped[datetime] = mapped_column(DateTime)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    household_id: Mapped[str | None] = mapped_column(String(12), index=True)
    tool: Mapped[str] = mapped_column(String(40))
    inputs: Mapped[dict] = mapped_column(JSON)
    output: Mapped[dict] = mapped_column(JSON)
    actor: Mapped[str] = mapped_column(String(60), default="agent")
    outcome: Mapped[str] = mapped_column(String(20), default="ok")
    created_at: Mapped[datetime] = mapped_column(DateTime)


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(40), primary_key=True)
    value: Mapped[object] = mapped_column(JSON)


def init_db() -> None:
    Base.metadata.create_all(engine)
