"""Shared FastAPI dependencies."""

from __future__ import annotations

from collections.abc import Generator
from uuid import UUID

from fastapi import Depends, Path

from evaluate.auth.internal import assert_path_scope, require_internal_principal
from evaluate.auth.schemas import InternalPrincipal
from evaluate.config import Settings, get_settings
from evaluate.db.postgres import PgConn, connect


def settings_dep() -> Settings:
    return get_settings()


def db_conn(settings: Settings = Depends(settings_dep)) -> Generator[PgConn, None, None]:
    with connect(settings.database_url) as conn:
        yield conn


def scoped_internal(
    org_id: UUID = Path(...),
    project_id: UUID = Path(...),
    principal: InternalPrincipal = Depends(require_internal_principal),
) -> InternalPrincipal:
    assert_path_scope(principal, org_id, project_id)
    return principal
