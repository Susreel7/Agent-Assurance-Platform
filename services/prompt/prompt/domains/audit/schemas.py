"""Audit listing models."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class AuditEntryOut(BaseModel):
    id: UUID
    action: str
    resource_type: str
    resource_id: UUID
    actor: str
    detail: dict[str, Any]
    created_at: datetime


class AuditListResponse(BaseModel):
    items: list[AuditEntryOut]
    next_cursor: datetime | None = None
