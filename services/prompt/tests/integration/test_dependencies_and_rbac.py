from __future__ import annotations

import pytest

from prompt.auth.rbac import SCOPE_LABEL_PRODUCTION
from prompt.db.postgres import connect
from prompt.domains.artifacts import service as artifact_service
from prompt.domains.artifacts.schemas import ArtifactCreate, ArtifactDependencyRef, RevisionCreate
from prompt.domains.labels import service as label_service
from prompt.domains.labels.schemas import PromoteLabelRequest
from prompt.errors import AuthorizationError, ValidationError

pytestmark = pytest.mark.integration


def test_dependency_cycle_and_rbac(settings, org_project: tuple) -> None:  # noqa: ANN001
    org_id, project_id = org_project
    with connect(settings.database_url) as conn:
        artifact_service.create_artifact(
            conn,
            settings,
            org_id=org_id,
            project_id=project_id,
            payload=ArtifactCreate(artifact_key="a.dep", kind="prompt"),
            actor="tester",
        )
        artifact_service.create_artifact(
            conn,
            settings,
            org_id=org_id,
            project_id=project_id,
            payload=ArtifactCreate(artifact_key="b.dep", kind="prompt"),
            actor="tester",
        )
        a_stable = artifact_service.create_revision(
            conn,
            settings,
            org_id=org_id,
            project_id=project_id,
            artifact_key="a.dep",
            payload=RevisionCreate(
                content={"messages": [{"role": "user", "content": "a"}]},
                is_draft=False,
            ),
            actor="tester",
        )
        label_service.promote_label(
            conn,
            settings,
            org_id=org_id,
            project_id=project_id,
            artifact_key="a.dep",
            payload=PromoteLabelRequest(label_name="production", revision_id=a_stable.id),
            actor="tester",
            scopes=[SCOPE_LABEL_PRODUCTION],
        )
        b_rev = artifact_service.create_revision(
            conn,
            settings,
            org_id=org_id,
            project_id=project_id,
            artifact_key="b.dep",
            payload=RevisionCreate(
                content={"messages": [{"role": "user", "content": "b"}]},
                dependencies=[ArtifactDependencyRef(artifact_key="a.dep", label="production")],
            ),
            actor="tester",
        )
        with pytest.raises(ValidationError):
            artifact_service.create_revision(
                conn,
                settings,
                org_id=org_id,
                project_id=project_id,
                artifact_key="a.dep",
                payload=RevisionCreate(
                    content={"messages": [{"role": "user", "content": "a2"}]},
                    dependencies=[
                        ArtifactDependencyRef(artifact_key="b.dep", revision_id=b_rev.id)
                    ],
                ),
                actor="tester",
            )

        with pytest.raises(AuthorizationError):
            label_service.promote_label(
                conn,
                settings,
                org_id=org_id,
                project_id=project_id,
                artifact_key="b.dep",
                payload=PromoteLabelRequest(label_name="production", revision_id=b_rev.id),
                actor="tester",
                scopes=[],
            )
