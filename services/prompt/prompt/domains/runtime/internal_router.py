"""Internal (console/BFF) runtime read — same resolution as workload fetch."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Response

from prompt.api.deps import db_conn, scoped_internal, settings_dep
from prompt.auth.schemas import InternalPrincipal
from prompt.config import Settings
from prompt.db.postgres import PgConn
from prompt.domains.runtime import service
from prompt.domains.runtime.schemas import RuntimeArtifactResponse
from prompt.errors import (
    AuthenticationError,
    NotFoundError,
    PreconditionFailedError,
    PromptError,
)

router = APIRouter(
    prefix="/v1/orgs/{org_id}/projects/{project_id}/runtime/read",
    tags=["runtime"],
)


@router.get(
    "/artifacts/{artifact_key}",
    response_model=RuntimeArtifactResponse,
    summary="Inspect resolved runtime artifact (internal)",
    description=(
        "Console/BFF read using internal service auth. Resolution rules, digests, "
        "ETag, and Evaluate-style digest headers match the workload runtime fetch API."
    ),
)
async def read_runtime_artifact_internal(
    artifact_key: str,
    response: Response,
    label: str | None = Query(default=None),
    revision_id: UUID | None = Query(default=None),
    pin_revision_id: UUID | None = Query(default=None),
    if_none_match: str | None = Header(default=None, alias="If-None-Match"),
    conn: PgConn = Depends(db_conn),
    settings: Settings = Depends(settings_dep),
    principal: InternalPrincipal = Depends(scoped_internal),
) -> RuntimeArtifactResponse | Response:
    from fastapi import HTTPException

    try:
        resolved = service.resolve_runtime_artifact_core(
            conn,
            settings,
            org_id=principal.organization_id,
            project_id=principal.project_id,
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
        raise HTTPException(status_code=401, detail=exc.message) from exc
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except PreconditionFailedError as exc:
        raise HTTPException(status_code=412, detail=exc.message) from exc
    except PromptError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
