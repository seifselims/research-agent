"""SQLAlchemy ORM models: each class is one database table.

Alembic reads Base.metadata to generate migrations, so every model must live in (or be imported
into) this module. Alembic is the ONLY tool that changes the database schema, including the
Better Auth tables below.
"""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Enum, ForeignKey, Index, MetaData, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# Predictable names for indexes and constraints. Without this, Postgres invents names and
# Alembic can't reliably find them later to alter or drop them.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
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
