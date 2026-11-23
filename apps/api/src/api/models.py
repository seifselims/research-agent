"""SQLAlchemy ORM models: each class is one database table.

Alembic reads Base.metadata to generate migrations, so every model must live in (or be imported
into) this module. Alembic is the ONLY tool that changes the database schema, including the
Better Auth tables below.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum,
    ForeignKey,
    Identity,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# Length of each embedding vector. Must equal EMBEDDING_DIMENSIONS in .env (the embedding model's
# output size). Changing it needs a new migration and re-embedding every chunk.
EMBEDDING_DIMENSIONS = 768

# Predictable names for indexes and constraints. Without this, Postgres invents names and
# Alembic can't reliably find them later to alter or drop them.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",  # all columns, e.g. uq_sources_job_id_url
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def created_at_column(name: str = "created_at") -> Mapped[datetime]:
    return mapped_column(name, DateTime(timezone=True), server_default=func.now())


# ---------------------------------------------------------------------------------------------
# Better Auth tables
#
# Used by the Next.js app (apps/web/src/lib/auth.ts). They must match exactly what Better Auth
# expects, so table and column names follow Better Auth's camelCase defaults ("emailVerified").
# The Python attribute names are snake_case; the first argument of mapped_column() is the real
# column name. Better Auth generates the ids (random text) and sets "updatedAt" itself.
#
# To check after upgrading Better Auth or adding a plugin, compare against the SQL printed by
# `npx @better-auth/cli generate` in apps/web, then update these models and add a migration.
# ---------------------------------------------------------------------------------------------


class User(Base):
    __tablename__ = "user"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    email: Mapped[str] = mapped_column(Text, unique=True)
    email_verified: Mapped[bool] = mapped_column("emailVerified")
    image: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_column("createdAt")
    updated_at: Mapped[datetime] = mapped_column(
        "updatedAt", DateTime(timezone=True), server_default=func.now()
    )

    # lazy="raise": accessing user.jobs without loading it explicitly raises an error instead
    # of silently running a query, which async SQLAlchemy can't do anyway.
    # passive_deletes=True: when a user is deleted, let Postgres's ON DELETE CASCADE remove their
    # jobs. Without it, SQLAlchemy tries to set the jobs' user_id to NULL first, which fails.
    jobs: Mapped[list[ResearchJob]] = relationship(
        back_populates="user",
        lazy="raise",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class Session(Base):
    __tablename__ = "session"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    expires_at: Mapped[datetime] = mapped_column("expiresAt", DateTime(timezone=True))
    token: Mapped[str] = mapped_column(Text, unique=True)
    created_at: Mapped[datetime] = created_at_column("createdAt")
    updated_at: Mapped[datetime] = mapped_column("updatedAt", DateTime(timezone=True))
    ip_address: Mapped[str | None] = mapped_column("ipAddress", Text)
    user_agent: Mapped[str | None] = mapped_column("userAgent", Text)
    user_id: Mapped[str] = mapped_column(
        "userId", Text, ForeignKey("user.id", ondelete="CASCADE"), index=True
    )


class Account(Base):
    """A login method for a user: e.g. email+password (providerId="credential") or GitHub."""

    __tablename__ = "account"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    account_id: Mapped[str] = mapped_column("accountId", Text)
    provider_id: Mapped[str] = mapped_column("providerId", Text)
    user_id: Mapped[str] = mapped_column(
        "userId", Text, ForeignKey("user.id", ondelete="CASCADE"), index=True
    )
    access_token: Mapped[str | None] = mapped_column("accessToken", Text)
    refresh_token: Mapped[str | None] = mapped_column("refreshToken", Text)
    id_token: Mapped[str | None] = mapped_column("idToken", Text)
    access_token_expires_at: Mapped[datetime | None] = mapped_column(
        "accessTokenExpiresAt", DateTime(timezone=True)
    )
    refresh_token_expires_at: Mapped[datetime | None] = mapped_column(
        "refreshTokenExpiresAt", DateTime(timezone=True)
    )
    scope: Mapped[str | None] = mapped_column(Text)
    password: Mapped[str | None] = mapped_column(Text)  # hashed by Better Auth
    created_at: Mapped[datetime] = created_at_column("createdAt")
    updated_at: Mapped[datetime] = mapped_column("updatedAt", DateTime(timezone=True))


class Verification(Base):
    """Short-lived tokens, e.g. for email verification and password reset."""

    __tablename__ = "verification"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    identifier: Mapped[str] = mapped_column(Text, index=True)
    value: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column("expiresAt", DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at_column("createdAt")
    updated_at: Mapped[datetime] = mapped_column(
        "updatedAt", DateTime(timezone=True), server_default=func.now()
    )


class Jwks(Base):
    """Signing keys for the JWT plugin. The API verifies tokens with the public keys."""

    __tablename__ = "jwks"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    public_key: Mapped[str] = mapped_column("publicKey", Text)
    private_key: Mapped[str] = mapped_column("privateKey", Text)  # encrypted by Better Auth
    created_at: Mapped[datetime] = mapped_column("createdAt", DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column("expiresAt", DateTime(timezone=True))
    alg: Mapped[str | None] = mapped_column(Text)
    crv: Mapped[str | None] = mapped_column(Text)


# ---------------------------------------------------------------------------------------------
# Application tables (owned by the API, snake_case names)
# ---------------------------------------------------------------------------------------------


class TimestampMixin:
    """Adds created_at / updated_at columns, filled in by Postgres itself."""

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ResearchJob(TimestampMixin, Base):
    __tablename__ = "research_jobs"

    # uuid7 is time-ordered, so new rows land at the end of the index (faster than random uuid4)
    # and ids can't be guessed by counting like 1, 2, 3.
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid7)
    # Better Auth user ids are text. ondelete="CASCADE": deleting a user deletes their jobs too.
    user_id: Mapped[str] = mapped_column(Text, ForeignKey("user.id", ondelete="CASCADE"))
    query: Mapped[str] = mapped_column(Text)
    # Stored as a short string with a CHECK constraint rather than a native Postgres ENUM type,
    # which is awkward to change in migrations when a new status is added later.
    status: Mapped[JobStatus] = mapped_column(
        Enum(
            JobStatus,
            native_enum=False,
            create_constraint=True,
            length=20,
            values_callable=lambda e: [m.value for m in e],  # store "queued", not "QUEUED"
        ),
        default=JobStatus.QUEUED,
        server_default=JobStatus.QUEUED.value,
    )
    error: Mapped[str | None] = mapped_column(Text)  # set only when status is FAILED

    user: Mapped[User] = relationship(back_populates="jobs", lazy="raise")

    __table_args__ = (
        # Speeds up "this user's jobs, newest first", the most common query.
        Index("ix_research_jobs_user_id_created_at", "user_id", "created_at"),
    )


# Every table below belongs to a research job (directly or through a source) and uses
# ON DELETE CASCADE, so deleting a job removes everything it produced in one statement.


class JobEvent(Base):
    """One progress update from a running job ("searching", "found 8 sources", ...).

    The frontend streams these live. The id is a plain increasing number (not a UUID) so events
    sort in the exact order they were written, and a client that reconnects can ask for
    "everything after event 41".
    """

    __tablename__ = "job_events"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("research_jobs.id", ondelete="CASCADE"))
    # Short machine-readable kind, e.g. "status", "search", "source", "error". Free text rather
    # than an enum because the agent (later parts) will define the exact set.
    type: Mapped[str] = mapped_column(String(50))
    message: Mapped[str] = mapped_column(Text)  # human-readable line shown in the UI
    data: Mapped[dict[str, Any] | None] = mapped_column(JSONB)  # optional structured details
    created_at: Mapped[datetime] = created_at_column()

    __table_args__ = (
        # "Events for this job, in order, after id X": the streaming query.
        Index("ix_job_events_job_id_id", "job_id", "id"),
    )


class Report(TimestampMixin, Base):
    """The finished research report. At most one per job."""

    __tablename__ = "reports"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid7)
    job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("research_jobs.id", ondelete="CASCADE"), unique=True
    )
    # Copied from the job so "list my reports" and ownership checks don't need a join.
    user_id: Mapped[str] = mapped_column(Text, ForeignKey("user.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text)  # markdown, with citations like [1], [2]

    __table_args__ = (Index("ix_reports_user_id_created_at", "user_id", "created_at"),)


class Source(Base):
    """A web page the agent found and read during a job. Reports cite these."""

    __tablename__ = "sources"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid7)
    # Linked to the job rather than the report: sources are collected while the job runs,
    # before any report exists.
    job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("research_jobs.id", ondelete="CASCADE"), index=True
    )
    url: Mapped[str] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_column()

    # The same page is stored only once per job.
    __table_args__ = (UniqueConstraint("job_id", "url"),)


class SourceChunk(Base):
    """A piece of a source's text (a few hundred words) plus its embedding.

    The embedding is a list of numbers representing the chunk's meaning. pgvector compares them
    to find the chunks most relevant to a question, even without matching words.
    """

    __tablename__ = "source_chunks"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sources.id", ondelete="CASCADE"), index=True
    )
    # Copied from the source so "most relevant chunks for this job" needs no join.
    job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("research_jobs.id", ondelete="CASCADE"), index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer)  # position within the source: 0, 1, 2...
    content: Mapped[str] = mapped_column(Text)
    # Nullable: a chunk is saved first and embedded afterwards, which can fail and be retried.
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIMENSIONS))

    __table_args__ = (
        UniqueConstraint("source_id", "chunk_index"),
        # HNSW: pgvector's approximate nearest-neighbour index, so similarity search stays fast
        # as the table grows. vector_cosine_ops matches queries using cosine distance (<=>).
        Index(
            "ix_source_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )


class RunMetrics(Base):
    """Cost and performance numbers for one job: the 'receipt'. One row per job."""

    __tablename__ = "run_metrics"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid7)
    job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("research_jobs.id", ondelete="CASCADE"), unique=True
    )
    model: Mapped[str | None] = mapped_column(Text)  # main LLM used, e.g. "gemini/..."
    llm_calls: Mapped[int] = mapped_column(Integer, server_default="0")
    input_tokens: Mapped[int] = mapped_column(BigInteger, server_default="0")
    output_tokens: Mapped[int] = mapped_column(BigInteger, server_default="0")
    sources_fetched: Mapped[int] = mapped_column(Integer, server_default="0")
    # Numeric (exact decimal), not float: money shouldn't pick up rounding errors.
    estimated_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = created_at_column()


class RateLimit(Base):
    """How many times a user did an action in one time window (e.g. jobs started this hour).

    One row per (user, action, window). The API increments it with a single atomic
    INSERT ... ON CONFLICT DO UPDATE SET count = count + 1, which stays correct even with
    several API processes, then rejects the request if the count is over the limit.
    """

    __tablename__ = "rate_limits"

    user_id: Mapped[str] = mapped_column(
        Text, ForeignKey("user.id", ondelete="CASCADE"), primary_key=True
    )
    action: Mapped[str] = mapped_column(String(50), primary_key=True)  # e.g. "create_job"
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    count: Mapped[int] = mapped_column(Integer, server_default="0")
