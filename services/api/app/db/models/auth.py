"""Models for migration 0022 — auth providers and server-side console sessions."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    LargeBinary,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, INET, JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantScoped, Timestamped


class AuthProvider(Base, TenantScoped, Timestamped):
    """One way into an account. Replaces the browser's build-time OIDC constants."""

    __tablename__ = "auth_providers"
    __table_args__ = (UniqueConstraint("org_id", "id"),)

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    issuer: Mapped[str | None] = mapped_column(Text)
    client_id: Mapped[str | None] = mapped_column(Text)
    client_secret_ref: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    jwks_uri: Mapped[str | None] = mapped_column(Text)
    authorize_url: Mapped[str | None] = mapped_column(Text)
    token_url: Mapped[str | None] = mapped_column(Text)
    scopes: Mapped[str] = mapped_column(Text, nullable=False, default="openid profile email")
    claim_map: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    group_claim: Mapped[str | None] = mapped_column(Text)
    email_domains: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    onboarding_mode: Mapped[str] = mapped_column(Text, nullable=False, default="invite")
    require_mfa_claim: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    precedence: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AuthSession(Base, TenantScoped, Timestamped):
    """A console session. The cookie carries an opaque reference; this row is the truth.

    ``token_hash`` is a digest, never the token, so a dump of this table cannot be
    replayed as anybody. Two expiries rather than one: ``expires_at`` slides forward with
    use, ``absolute_expires_at`` never moves, and the session is dead when either passes.
    """

    __tablename__ = "auth_sessions"
    __table_args__ = (
        UniqueConstraint("org_id", "id"),
        ForeignKeyConstraint(
            ["org_id", "member_id"],
            ["members.org_id", "members.id"],
            ondelete="CASCADE",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    member_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    provider_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    token_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    identity_issuer: Mapped[str] = mapped_column(Text, nullable=False)
    identity_subject: Mapped[str] = mapped_column(Text, nullable=False)
    identity_email: Mapped[str | None] = mapped_column(Text)
    identity_groups: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    absolute_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_reason: Mapped[str | None] = mapped_column(Text)
    mfa_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    client_ip: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(Text)
