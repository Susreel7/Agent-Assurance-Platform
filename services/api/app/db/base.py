"""SQLAlchemy declarative base and shared column conventions.

ORM models are thin: they exist to type query results, not to hold behaviour. Business
logic lives in ``service.py``, SQL lives in ``repository.py``. Keeping models free of
relationships and cascades avoids the lazy-loading surprises that make an async codebase
hard to reason about.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, MetaData, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Explicit naming so hand-written migrations and the ORM agree on constraint names.
NAMING_CONVENTION = {
    "ix": "%(table_name)s_%(column_0_N_name)s_idx",
    "uq": "%(table_name)s_%(column_0_N_name)s_key",
    "ck": "%(table_name)s_%(constraint_name)s_check",
    "fk": "%(table_name)s_%(column_0_name)s_fkey",
    "pk": "%(table_name)s_pkey",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)

    type_annotation_map = {
        dict[str, Any]: JSONB,
        UUID: PgUUID(as_uuid=True),
    }


class TenantScoped:
    """Mixin for every tenant-owned table.

    Presence of this mixin is the signal that a table needs a row-level security policy
    in its migration. If you add this and forget the policy, the isolation test fails —
    which is the intended feedback loop.
    """

    org_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)


class Timestamped:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
