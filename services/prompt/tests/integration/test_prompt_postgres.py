from __future__ import annotations

from uuid import uuid4

import pytest

from prompt.auth.schemas import WorkloadPrincipal
from prompt.config import Settings
from prompt.db.postgres import connect
from prompt.domains.artifacts import service as artifact_service
from prompt.domains.artifacts.schemas import ArtifactCreate, RevisionCreate
from prompt.domains.labels import service as label_service
from prompt.domains.labels.schemas import PromoteLabelRequest
from prompt.domains.runtime import service as runtime_service
from prompt.errors import ConflictError, NotFoundError, PreconditionFailedError

pytestmark = pytest.mark.integration


def test_immutability_and_encryption_at_rest(settings: Settings, org_project: tuple) -> None:
    org_id, project_id = org_project
    with connect(settings.database_url) as conn:
        artifact_service.create_artifact(
            conn,
            settings,
            org_id=org_id,
            project_id=project_id,
            payload=ArtifactCreate(artifact_key="demo.prompt", kind="prompt", display_name="Demo"),
            actor="tester",
        )
        rev = artifact_service.create_revision(
            conn,
            settings,
            org_id=org_id,
            project_id=project_id,
            artifact_key="demo.prompt",
            payload=RevisionCreate(
                content={"messages": [{"role": "user", "content": "Hello {{ name }}"}]},
                input_schema={"type": "object", "properties": {"name": {"type": "string"}}},
                is_draft=False,
            ),
            actor="tester",
        )
        from prompt.db import repository as repo

        cipher = repo.get_revision_ciphertext(conn, org_id, rev.id)
        assert cipher is not None
        assert b"Hello" not in cipher


def test_cross_tenant_isolation(settings: Settings, org_project: tuple) -> None:
    org_id, project_id = org_project
    other_org = uuid4()
    with connect(settings.database_url) as conn:
        artifact_service.create_artifact(
            conn,
            settings,
            org_id=org_id,
            project_id=project_id,
            payload=ArtifactCreate(artifact_key="tenant.a", kind="context"),
            actor="tester",
        )
        with pytest.raises(NotFoundError):
            artifact_service.get_artifact(conn, other_org, project_id, "tenant.a")


def test_label_cas_and_production_draft_guard(settings: Settings, org_project: tuple) -> None:
    org_id, project_id = org_project
    with connect(settings.database_url) as conn:
        artifact_service.create_artifact(
            conn,
            settings,
            org_id=org_id,
            project_id=project_id,
            payload=ArtifactCreate(artifact_key="prod.guard", kind="prompt"),
            actor="tester",
        )
        draft = artifact_service.create_revision(
            conn,
            settings,
            org_id=org_id,
            project_id=project_id,
            artifact_key="prod.guard",
            payload=RevisionCreate(
                content={"messages": [{"role": "user", "content": "draft"}]},
                is_draft=True,
            ),
            actor="tester",
        )
        with pytest.raises(PreconditionFailedError):
            label_service.promote_label(
                conn,
                settings,
                org_id=org_id,
                project_id=project_id,
                artifact_key="prod.guard",
                payload=PromoteLabelRequest(label_name="production", revision_id=draft.id),
                actor="tester",
                scopes=["prompt:label:production"],
            )
        stable = artifact_service.create_revision(
            conn,
            settings,
            org_id=org_id,
            project_id=project_id,
            artifact_key="prod.guard",
            payload=RevisionCreate(
                content={"messages": [{"role": "user", "content": "stable"}]},
                is_draft=False,
            ),
            actor="tester",
        )
        label_service.promote_label(
            conn,
            settings,
            org_id=org_id,
            project_id=project_id,
            artifact_key="prod.guard",
            payload=PromoteLabelRequest(label_name="production", revision_id=stable.id),
            actor="tester",
            scopes=["prompt:label:production"],
        )
        with pytest.raises(ConflictError):
            label_service.promote_label(
                conn,
                settings,
                org_id=org_id,
                project_id=project_id,
                artifact_key="prod.guard",
                payload=PromoteLabelRequest(
                    label_name="production",
                    revision_id=stable.id,
                    expected_version=999,
                ),
                actor="tester",
                scopes=["prompt:label:production"],
            )


def test_rollback_and_runtime_etag(settings: Settings, org_project: tuple) -> None:
    org_id, project_id = org_project
    principal = WorkloadPrincipal(
        subject="w",
        organization_id=org_id,
        project_id=project_id,
        modules=["prompt"],
        scopes=["prompt:read"],
    )
    with connect(settings.database_url) as conn:
        artifact_service.create_artifact(
            conn,
            settings,
            org_id=org_id,
            project_id=project_id,
            payload=ArtifactCreate(artifact_key="roll.me", kind="prompt"),
            actor="tester",
        )
        v1 = artifact_service.create_revision(
            conn,
            settings,
            org_id=org_id,
            project_id=project_id,
            artifact_key="roll.me",
            payload=RevisionCreate(
                content={"messages": [{"role": "user", "content": "v1"}]},
                is_draft=False,
            ),
            actor="tester",
        )
        artifact_service.create_revision(
            conn,
            settings,
            org_id=org_id,
            project_id=project_id,
            artifact_key="roll.me",
            payload=RevisionCreate(
                content={"messages": [{"role": "user", "content": "v2"}]},
                is_draft=False,
            ),
            actor="tester",
        )
        rolled = artifact_service.rollback_revision(
            conn,
            settings,
            org_id=org_id,
            project_id=project_id,
            artifact_key="roll.me",
            target_revision_id=v1.id,
            is_draft=False,
            actor="tester",
        )
        assert rolled.content["messages"][0]["content"] == "v1"
        label_service.promote_label(
            conn,
            settings,
            org_id=org_id,
            project_id=project_id,
            artifact_key="roll.me",
            payload=PromoteLabelRequest(label_name="production", revision_id=rolled.id),
            actor="tester",
            scopes=["prompt:label:production"],
        )
        resolved = runtime_service.resolve_runtime_artifact(
            conn,
            settings,
            principal=principal,
            org_id=org_id,
            project_id=project_id,
            artifact_key="roll.me",
            label="production",
            revision_id=None,
        )
        etag = runtime_service.runtime_etag(resolved.content_digest)
        assert etag.startswith('"')


@pytest.mark.asyncio
async def test_playground_upstream_failure(
    settings: Settings, org_project: tuple, monkeypatch: pytest.MonkeyPatch
) -> None:
    org_id, project_id = org_project

    async def _fail(*_args, **_kwargs):  # noqa: ANN001
        return 503, {"x-request-id": "r1"}, b"{}"

    from prompt.domains.playground import service as playground_service

    monkeypatch.setattr(playground_service, "_call_router", _fail)
    from prompt.auth.schemas import InternalPrincipal
    from prompt.domains.playground.schemas import ArtifactRef, PlaygroundRunRequest

    with connect(settings.database_url) as conn:
        artifact_service.create_artifact(
            conn,
            settings,
            org_id=org_id,
            project_id=project_id,
            payload=ArtifactCreate(artifact_key="pg.fail", kind="prompt"),
            actor="tester",
        )
        rev = artifact_service.create_revision(
            conn,
            settings,
            org_id=org_id,
            project_id=project_id,
            artifact_key="pg.fail",
            payload=RevisionCreate(
                content={"messages": [{"role": "user", "content": "hi"}]},
                is_draft=False,
            ),
            actor="tester",
        )
        principal = InternalPrincipal(actor="tester", organization_id=org_id, project_id=project_id)
        result = await playground_service.run_playground(
            conn,
            settings,
            principal=principal,
            payload=PlaygroundRunRequest(
                artifacts=[ArtifactRef(revision_id=rev.id)],
                model_alias="mock-model",
            ),
            workload_bearer="token",
        )
    assert result.status == "failed"
    assert result.error_message
