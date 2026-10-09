"""Model routing persistence — SQL only."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, insert, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.company import Engagement, EngagementAgent
from app.db.models.model_routing import (
    GatewayRequestLog,
    ModelCatalogAlias,
    ModelCatalogEntry,
    ModelDeployment,
    ModelRoute,
    ModelRouteTarget,
    RouterConfigSnapshot,
    RouterSigningKey,
)
from app.db.models.workload_identity import (
    Project,
    WorkloadCredential,
    WorkloadCredentialGeneration,
)


def _catalog_scope(org_id: UUID) -> Any:
    return or_(ModelCatalogEntry.org_id.is_(None), ModelCatalogEntry.org_id == org_id)


async def list_catalog_entries(
    session: AsyncSession,
    org_id: UUID,
    *,
    classification: str | None = None,
    search: str | None = None,
    limit: int = 200,
    offset: int = 0,
) -> list[ModelCatalogEntry]:
    stmt = select(ModelCatalogEntry).where(_catalog_scope(org_id))
    if classification:
        stmt = stmt.where(ModelCatalogEntry.classification_state == classification)
    if search:
        pattern = f"%{search.lower()}%"
        stmt = stmt.where(
            func.lower(ModelCatalogEntry.model_id).like(pattern)
            | func.lower(ModelCatalogEntry.provider).like(pattern)
        )
    stmt = stmt.where(
        ModelCatalogEntry.valid_to.is_(None) | (ModelCatalogEntry.valid_to >= date.today())
    )
    stmt = (
        stmt.order_by(
            ModelCatalogEntry.classification_state.desc(),
            ModelCatalogEntry.provider,
            ModelCatalogEntry.model_id,
        )
        .limit(limit)
        .offset(offset)
    )
    return list((await session.execute(stmt)).scalars())


async def count_catalog_entries(
    session: AsyncSession,
    org_id: UUID,
    *,
    classification: str | None = None,
    search: str | None = None,
) -> int:
    stmt = select(func.count()).select_from(ModelCatalogEntry).where(_catalog_scope(org_id))
    if classification:
        stmt = stmt.where(ModelCatalogEntry.classification_state == classification)
    if search:
        pattern = f"%{search.lower()}%"
        stmt = stmt.where(
            func.lower(ModelCatalogEntry.model_id).like(pattern)
            | func.lower(ModelCatalogEntry.provider).like(pattern)
        )
    stmt = stmt.where(
        ModelCatalogEntry.valid_to.is_(None) | (ModelCatalogEntry.valid_to >= date.today())
    )
    return (await session.execute(stmt)).scalar_one()


async def get_catalog_entry_by_provider_model(
    session: AsyncSession,
    org_id: UUID,
    provider: str,
    model_id: str,
) -> ModelCatalogEntry | None:
    stmt = (
        select(ModelCatalogEntry)
        .where(
            _catalog_scope(org_id),
            func.lower(ModelCatalogEntry.provider) == provider.lower(),
            func.lower(ModelCatalogEntry.model_id) == model_id.lower(),
            ModelCatalogEntry.valid_to.is_(None) | (ModelCatalogEntry.valid_to >= date.today()),
        )
        .order_by(ModelCatalogEntry.org_id.desc().nulls_last())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def resolve_alias(
    session: AsyncSession, org_id: UUID, alias: str
) -> ModelCatalogEntry | None:
    stmt = (
        select(ModelCatalogEntry)
        .join(
            ModelCatalogAlias,
            ModelCatalogAlias.catalog_entry_id == ModelCatalogEntry.id,
        )
        .where(
            or_(ModelCatalogAlias.org_id.is_(None), ModelCatalogAlias.org_id == org_id),
            func.lower(ModelCatalogAlias.alias) == alias.lower(),
        )
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def insert_catalog_entry(
    session: AsyncSession, org_id: UUID | None, values: dict[str, Any]
) -> ModelCatalogEntry:
    stmt = insert(ModelCatalogEntry).values(org_id=org_id, **values).returning(ModelCatalogEntry)
    return (await session.execute(stmt)).scalar_one()


async def insert_gateway_log(
    session: AsyncSession, org_id: UUID, values: dict[str, Any]
) -> GatewayRequestLog:
    stmt = insert(GatewayRequestLog).values(org_id=org_id, **values).returning(GatewayRequestLog)
    return (await session.execute(stmt)).scalar_one()


async def get_primary_engagement_for_agent(
    session: AsyncSession, org_id: UUID, agent_id: UUID
) -> Engagement | None:
    stmt = (
        select(Engagement)
        .join(EngagementAgent, EngagementAgent.engagement_id == Engagement.id)
        .where(
            EngagementAgent.org_id == org_id,
            EngagementAgent.agent_id == agent_id,
            EngagementAgent.removed_at.is_(None),
        )
        .order_by(Engagement.starts_on.desc().nulls_last())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def get_project(session: AsyncSession, org_id: UUID, project_id: UUID) -> Project | None:
    stmt = select(Project).where(Project.org_id == org_id, Project.id == project_id)
    return (await session.execute(stmt)).scalar_one_or_none()


async def insert_deployment(
    session: AsyncSession, org_id: UUID, values: dict[str, Any]
) -> ModelDeployment:
    stmt = insert(ModelDeployment).values(org_id=org_id, **values).returning(ModelDeployment)
    return (await session.execute(stmt)).scalar_one()


async def get_deployment(
    session: AsyncSession, org_id: UUID, project_id: UUID, deployment_id: UUID
) -> ModelDeployment | None:
    stmt = select(ModelDeployment).where(
        ModelDeployment.org_id == org_id,
        ModelDeployment.project_id == project_id,
        ModelDeployment.id == deployment_id,
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def list_deployments(
    session: AsyncSession,
    org_id: UUID,
    project_id: UUID,
    *,
    include_disabled: bool,
    limit: int,
    offset: int,
) -> tuple[list[ModelDeployment], int]:
    base = select(ModelDeployment).where(
        ModelDeployment.org_id == org_id,
        ModelDeployment.project_id == project_id,
    )
    if not include_disabled:
        base = base.where(ModelDeployment.disabled_at.is_(None))
    total = await session.scalar(select(func.count()).select_from(base.subquery()))
    rows = await session.execute(
        base.order_by(ModelDeployment.name, ModelDeployment.id).limit(limit).offset(offset)
    )
    return list(rows.scalars()), int(total or 0)


async def update_deployment(
    session: AsyncSession,
    org_id: UUID,
    project_id: UUID,
    deployment_id: UUID,
    values: dict[str, Any],
) -> ModelDeployment | None:
    stmt = (
        update(ModelDeployment)
        .where(
            ModelDeployment.org_id == org_id,
            ModelDeployment.project_id == project_id,
            ModelDeployment.id == deployment_id,
            ModelDeployment.disabled_at.is_(None),
        )
        .values(**values)
        .returning(ModelDeployment)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def disable_deployment(
    session: AsyncSession,
    org_id: UUID,
    project_id: UUID,
    deployment_id: UUID,
    disabled_at: datetime,
) -> ModelDeployment | None:
    stmt = (
        update(ModelDeployment)
        .where(
            ModelDeployment.org_id == org_id,
            ModelDeployment.project_id == project_id,
            ModelDeployment.id == deployment_id,
            ModelDeployment.disabled_at.is_(None),
        )
        .values(disabled_at=disabled_at)
        .returning(ModelDeployment)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def list_enabled_deployments(
    session: AsyncSession, org_id: UUID, project_id: UUID
) -> list[ModelDeployment]:
    stmt = (
        select(ModelDeployment)
        .where(
            ModelDeployment.org_id == org_id,
            ModelDeployment.project_id == project_id,
            ModelDeployment.disabled_at.is_(None),
        )
        .order_by(ModelDeployment.id)
    )
    return list((await session.execute(stmt)).scalars())


async def insert_route(
    session: AsyncSession, org_id: UUID, route_values: dict[str, Any], targets: list[dict[str, Any]]
) -> ModelRoute:
    stmt = insert(ModelRoute).values(org_id=org_id, **route_values).returning(ModelRoute)
    route = (await session.execute(stmt)).scalar_one()
    for target in targets:
        await session.execute(
            insert(ModelRouteTarget).values(
                org_id=org_id,
                project_id=route.project_id,
                route_id=route.id,
                **target,
            )
        )
    await session.flush()
    return route


async def list_route_targets(
    session: AsyncSession, org_id: UUID, route_id: UUID
) -> list[ModelRouteTarget]:
    stmt = (
        select(ModelRouteTarget)
        .where(
            ModelRouteTarget.org_id == org_id,
            ModelRouteTarget.route_id == route_id,
        )
        .order_by(ModelRouteTarget.position, ModelRouteTarget.id)
    )
    return list((await session.execute(stmt)).scalars())


async def get_route(
    session: AsyncSession, org_id: UUID, project_id: UUID, route_id: UUID
) -> ModelRoute | None:
    stmt = select(ModelRoute).where(
        ModelRoute.org_id == org_id,
        ModelRoute.project_id == project_id,
        ModelRoute.id == route_id,
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def list_routes(
    session: AsyncSession,
    org_id: UUID,
    project_id: UUID,
    *,
    include_disabled: bool,
    limit: int,
    offset: int,
) -> tuple[list[ModelRoute], int]:
    base = select(ModelRoute).where(
        ModelRoute.org_id == org_id,
        ModelRoute.project_id == project_id,
    )
    if not include_disabled:
        base = base.where(ModelRoute.disabled_at.is_(None))
    total = await session.scalar(select(func.count()).select_from(base.subquery()))
    rows = await session.execute(
        base.order_by(ModelRoute.alias, ModelRoute.id).limit(limit).offset(offset)
    )
    return list(rows.scalars()), int(total or 0)


async def list_enabled_routes(
    session: AsyncSession, org_id: UUID, project_id: UUID
) -> list[ModelRoute]:
    stmt = (
        select(ModelRoute)
        .where(
            ModelRoute.org_id == org_id,
            ModelRoute.project_id == project_id,
            ModelRoute.disabled_at.is_(None),
        )
        .order_by(ModelRoute.id)
    )
    return list((await session.execute(stmt)).scalars())


async def replace_route_targets(
    session: AsyncSession,
    org_id: UUID,
    project_id: UUID,
    route_id: UUID,
    targets: list[dict[str, Any]],
) -> None:
    await session.execute(
        delete(ModelRouteTarget).where(
            ModelRouteTarget.org_id == org_id,
            ModelRouteTarget.route_id == route_id,
        )
    )
    for target in targets:
        await session.execute(
            insert(ModelRouteTarget).values(
                org_id=org_id,
                project_id=project_id,
                route_id=route_id,
                **target,
            )
        )


async def update_route(
    session: AsyncSession,
    org_id: UUID,
    project_id: UUID,
    route_id: UUID,
    values: dict[str, Any],
) -> ModelRoute | None:
    stmt = (
        update(ModelRoute)
        .where(
            ModelRoute.org_id == org_id,
            ModelRoute.project_id == project_id,
            ModelRoute.id == route_id,
            ModelRoute.disabled_at.is_(None),
        )
        .values(**values)
        .returning(ModelRoute)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def disable_route(
    session: AsyncSession,
    org_id: UUID,
    project_id: UUID,
    route_id: UUID,
    disabled_at: datetime,
) -> ModelRoute | None:
    stmt = (
        update(ModelRoute)
        .where(
            ModelRoute.org_id == org_id,
            ModelRoute.project_id == project_id,
            ModelRoute.id == route_id,
            ModelRoute.disabled_at.is_(None),
        )
        .values(disabled_at=disabled_at)
        .returning(ModelRoute)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def insert_snapshot(
    session: AsyncSession, org_id: UUID, values: dict[str, Any]
) -> RouterConfigSnapshot:
    stmt = (
        insert(RouterConfigSnapshot).values(org_id=org_id, **values).returning(RouterConfigSnapshot)
    )
    return (await session.execute(stmt)).scalar_one()


async def register_signing_key(
    session: AsyncSession,
    org_id: UUID,
    *,
    key_id: str,
    public_key_pem: str,
    used_at: datetime,
) -> RouterSigningKey | None:
    stmt = (
        pg_insert(RouterSigningKey)
        .values(
            org_id=org_id,
            key_id=key_id,
            algorithm="ES256",
            public_key_pem=public_key_pem,
            first_seen_at=used_at,
            last_used_at=used_at,
        )
        .on_conflict_do_update(
            index_elements=[RouterSigningKey.org_id, RouterSigningKey.key_id],
            set_={"last_used_at": used_at},
            where=RouterSigningKey.public_key_pem == public_key_pem,
        )
        .returning(RouterSigningKey)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def get_signing_key(
    session: AsyncSession, org_id: UUID, key_id: str
) -> RouterSigningKey | None:
    stmt = select(RouterSigningKey).where(
        RouterSigningKey.org_id == org_id,
        RouterSigningKey.key_id == key_id,
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def supersede_active_snapshots(session: AsyncSession, org_id: UUID, project_id: UUID) -> None:
    await session.execute(
        update(RouterConfigSnapshot)
        .where(
            RouterConfigSnapshot.org_id == org_id,
            RouterConfigSnapshot.project_id == project_id,
            RouterConfigSnapshot.status == "active",
        )
        .values(status="superseded")
    )


async def get_snapshot(
    session: AsyncSession, org_id: UUID, project_id: UUID, snapshot_id: UUID
) -> RouterConfigSnapshot | None:
    stmt = select(RouterConfigSnapshot).where(
        RouterConfigSnapshot.org_id == org_id,
        RouterConfigSnapshot.project_id == project_id,
        RouterConfigSnapshot.id == snapshot_id,
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def get_latest_active_snapshot(
    session: AsyncSession, org_id: UUID, project_id: UUID, *, now: datetime
) -> RouterConfigSnapshot | None:
    stmt = (
        select(RouterConfigSnapshot)
        .where(
            RouterConfigSnapshot.org_id == org_id,
            RouterConfigSnapshot.project_id == project_id,
            RouterConfigSnapshot.status == "active",
            RouterConfigSnapshot.expires_at > now,
        )
        .order_by(RouterConfigSnapshot.issued_at.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def list_router_workload_bindings(
    session: AsyncSession, org_id: UUID, project_id: UUID, *, now: datetime
) -> list[tuple[WorkloadCredential, WorkloadCredentialGeneration]]:
    stmt = (
        select(WorkloadCredential, WorkloadCredentialGeneration)
        .join(
            WorkloadCredentialGeneration,
            WorkloadCredentialGeneration.id == WorkloadCredential.active_generation_id,
        )
        .where(
            WorkloadCredential.org_id == org_id,
            WorkloadCredential.project_id == project_id,
            WorkloadCredential.revoked_at.is_(None),
            WorkloadCredentialGeneration.revoked_at.is_(None),
            text("'router' = ANY(workload_credentials.modules)"),
            or_(
                WorkloadCredential.expires_at.is_(None),
                WorkloadCredential.expires_at > now,
            ),
        )
        .order_by(WorkloadCredentialGeneration.id)
    )
    rows = (await session.execute(stmt)).all()
    return [(credential, generation) for credential, generation in rows]
