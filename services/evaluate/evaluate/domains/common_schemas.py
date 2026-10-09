"""Shared list response envelopes."""

from __future__ import annotations

from pydantic import BaseModel, Field


class PageMeta(BaseModel):
    total: int
    limit: int
    next_cursor: str | None = None


class PagedResponse[T](BaseModel):
    items: list[T]
    meta: PageMeta = Field(default_factory=lambda: PageMeta(total=0, limit=0))
