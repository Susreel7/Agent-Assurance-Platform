"""Runtime fetch response models."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class RuntimeArtifactResponse(BaseModel):
    artifact_key: str
    kind: str
    revision_id: UUID
    revision_number: int
    label: str | None = None
    pinned_revision: bool = False
    content_digest: str
    schema_digest: str | None = None
    config_digest: str | None = None
    content: dict[str, Any]
    input_schema: dict[str, Any] | None = None
    config: dict[str, Any] | None = None
    resolved_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))
