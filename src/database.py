"""SQLAlchemy models and database setup for Scout."""

from contextlib import contextmanager
from datetime import UTC, datetime
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    create_engine,
    text as sa_text,
)
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from src.paths import DATA_DIR

DB_PATH = DATA_DIR / "scout.db"

_engine = None
_SessionFactory = None


class Base(DeclarativeBase):
    pass


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        Index("ix_jobs_status", "status"),
        Index("ix_jobs_source", "source"),
        Index("ix_jobs_match_score", "match_score"),
        Index("ix_jobs_scraped_at", "scraped_at"),
    )

    id: str = Column(String, primary_key=True)  # SHA256(company+title+location)
    title: str = Column(Text, nullable=False)
    company: str = Column(Text, nullable=False)
    location: str = Column(Text, nullable=False)
    source: str = Column(Text, nullable=False)
    url: str = Column(Text)
    jd_text: str = Column(Text)
    match_score: float | None = Column(Float)
    ats_keywords: str | None = Column(Text)  # JSON array
    red_flags: str | None = Column(Text)  # JSON array
    recommended_action: str | None = Column(Text)  # 'apply'|'skip'|'manual_review'
    status: str = Column(Text, default="scraped")
    posted_at: datetime | None = Column(DateTime)
    deadline: datetime | None = Column(DateTime)
    resume_id: str | None = Column(String)
    applied_at: datetime | None = Column(DateTime)
    scraped_at: datetime = Column(DateTime, default=lambda: datetime.now(UTC))
    notion_page_id: str | None = Column(String)
    research_notes: str | None = Column(Text)  # User-added context for better tailoring
    dismissed_at: datetime | None = Column(DateTime)  # User-dismissed (hidden from default views)


class Resume(Base):
    __tablename__ = "resumes"

    id: str = Column(String, primary_key=True)
    job_id: str = Column(String, ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    pdf_path: str | None = Column(Text)
    docx_path: str | None = Column(Text)
    ats_score: float | None = Column(Float)
    tailored_json: str | None = Column(Text)
    created_at: datetime = Column(DateTime, default=lambda: datetime.now(UTC))


class Application(Base):
    __tablename__ = "applications"
    __table_args__ = (
        Index("ix_applications_job_id", "job_id"),
        Index("ix_applications_status", "status"),
        Index("ix_applications_created_at", "created_at"),
    )

    id: str = Column(String, primary_key=True)
    job_id: str = Column(String, ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    resume_id: str | None = Column(String)
    applied_via: str | None = Column(Text)  # 'greenhouse'|'lever'|'workday'
    form_responses: str | None = Column(Text)  # JSON of form fields filled
    status: str = Column(Text, default="applied")
    created_at: datetime = Column(DateTime, default=lambda: datetime.now(UTC))
    updated_at: datetime = Column(DateTime, default=lambda: datetime.now(UTC))
    first_response_at: datetime | None = Column(DateTime)
    last_email_at: datetime | None = Column(DateTime)
    interview_at: datetime | None = Column(DateTime)
    offer_at: datetime | None = Column(DateTime)
    rejected_at: datetime | None = Column(DateTime)
    notes: str | None = Column(Text)
    is_dry_run: bool = Column(Boolean, default=False)
    email_count: int = Column(Integer, default=0)
    error_message: str | None = Column(Text)


class ApplicationEvent(Base):
    """Timeline of events for each application -- enables full history tracking."""
    __tablename__ = "application_events"
    __table_args__ = (
        Index("ix_appevents_application_id", "application_id"),
        Index("ix_appevents_job_id", "job_id"),
    )

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    application_id: str = Column(String, ForeignKey("applications.id", ondelete="CASCADE"), nullable=False)
    job_id: str = Column(String, ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    event_type: str = Column(Text, nullable=False)
    timestamp: datetime = Column(DateTime, default=lambda: datetime.now(UTC))
    details: str | None = Column(Text)  # JSON with extra context
    source: str | None = Column(Text)  # 'bot'|'email'|'manual'|'scheduler'

# Valid event types:
# form_opened, fields_filled, resume_uploaded, cover_letter_filled,
# question_answered, submitted, dry_run_complete,
# email_received, status_changed, interview_scheduled,
# offer_received, rejected, ghosted, error


class Answer(Base):
    __tablename__ = "answers"

    portal: str = Column(String, primary_key=True)
    question_hash: str = Column(String, primary_key=True)
    answer: str = Column(Text, nullable=False)


def get_engine():
    """Create or return cached SQLAlchemy engine."""
    global _engine
    if _engine is None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        _engine = create_engine(
            f"sqlite:///{DB_PATH}",
            echo=False,
            pool_pre_ping=True,
            connect_args={"timeout": 15},  # WAL mode write timeout
        )
    return _engine


def init_db() -> None:
    """Create all tables if they don't exist. Call once at startup."""
    engine = get_engine()
    # Enable WAL mode for better concurrent read/write
    with engine.connect() as conn:
        conn.execute(sa_text("PRAGMA journal_mode=WAL"))
        conn.commit()
    Base.metadata.create_all(engine)
    # Lightweight migration: add columns that may be missing on older DBs
    with engine.connect() as conn:
        for col in ("posted_at", "deadline"):
            try:
                conn.execute(sa_text(f"ALTER TABLE jobs ADD COLUMN {col} DATETIME"))
                conn.commit()
            except Exception:
                pass  # column already exists
        # Add research_notes column if missing (added later)
        try:
            conn.execute(sa_text("ALTER TABLE jobs ADD COLUMN research_notes TEXT"))
            conn.commit()
        except Exception:
            pass
        # Add dismissed_at column if missing
        try:
            conn.execute(sa_text("ALTER TABLE jobs ADD COLUMN dismissed_at DATETIME"))
            conn.commit()
        except Exception:
            pass


def _get_session_factory():
    global _SessionFactory
    if _SessionFactory is None:
        _SessionFactory = sessionmaker(bind=get_engine())
    return _SessionFactory


def get_session() -> Session:
    """Return a new database session. Caller MUST close it (prefer managed_session)."""
    return _get_session_factory()()


@contextmanager
def managed_session():
    """Context manager that auto-commits on success, rolls back on error, always closes."""
    session = get_session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def record_event(
    application_id: str,
    job_id: str,
    event_type: str,
    details: dict | None = None,
    source: str = "bot",
    session: Session | None = None,
) -> None:
    """Record an application timeline event.

    Pass an open `session` to write within the caller's transaction; otherwise a
    short-lived session is used. Reusing the caller's session avoids a second
    SQLite writer deadlocking against an in-progress transaction.
    """
    import json
    event = ApplicationEvent(
        application_id=application_id,
        job_id=job_id,
        event_type=event_type,
        timestamp=datetime.now(UTC),
        details=json.dumps(details) if details else None,
        source=source,
    )
    if session is not None:
        session.add(event)
        return
    with managed_session() as own_session:
        own_session.add(event)
