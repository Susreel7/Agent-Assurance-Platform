"""Runtime machine fetch API."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response

from prompt.api.deps import db_conn, settings_dep
from prompt.auth import workload as workload_auth
from prompt.config import Settings
from prompt.db.postgres import PgConn
from prompt.domains.runtime import service
from prompt.domains.runtime.schemas import RuntimeArtifactResponse
from prompt.errors import (
    AuthenticationError,
    AuthorizationError,
    NotFoundError,
    PreconditionFailedError,
    PromptError,
)

router = APIRouter(
    prefix="/v1/orgs/{org_id}/projects/{project_id}/runtime/artifacts",
    tags=["runtime"],
)


@router.get("/{artifact_key}", response_model=RuntimeArtifactResponse)
async def fetch_runtime_artifact(
    org_id: UUID,
    project_id: UUID,
    artifact_key: str,
    request: Request,
    response: Response,
    label: str | None = Query(default=None),
    revision_id: UUID | None = Query(default=None),
    pin_revision_id: UUID | None = Query(default=None),
    if_none_match: str | None = Header(default=None, alias="If-None-Match"),
    conn: PgConn = Depends(db_conn),
    settings: Settings = Depends(settings_dep),
) -> RuntimeArtifactResponse | Response:
    try:
        principal = await workload_auth.introspect_bearer(
            settings, request.headers.get("Authorization")
        )
        resolved = service.resolve_runtime_artifact(
            conn,
            settings,
            principal=principal,
            org_id=org_id,
            project_id=project_id,
            artifact_key=artifact_key,
            label=label,
            revision_id=revision_id,
            pin_revision_id=pin_revision_id,
        )
        etag = service.runtime_etag(resolved.content_digest)
        response.headers["ETag"] = etag
        response.headers["Cache-Control"] = service.runtime_cache_control(settings)
        service.apply_evaluate_digest_headers(response, resolved)
        if if_none_match and if_none_match.strip('"') == resolved.content_digest:
            return Response(status_code=304)
        return resolved
    except AuthenticationError as exc:
        from fastapi import HTTPException

        raise HTTPException(status_code=401, detail=exc.message) from exc
    except AuthorizationError as exc:
        from fastapi import HTTPException

        raise HTTPException(status_code=403, detail=exc.message) from exc
    except NotFoundError as exc:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail=exc.message) from exc
    except PreconditionFailedError as exc:
        from fastapi import HTTPException

        raise HTTPException(status_code=412, detail=exc.message) from exc
    except PromptError as exc:
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail=exc.message) from exc
