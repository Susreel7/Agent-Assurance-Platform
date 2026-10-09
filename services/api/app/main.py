"""FastAPI application.

One process, all domain modules. The health endpoint deliberately reports the deployment
mode and entitlement state, because in BYOC and air-gapped installs the operator is the
customer and they need to see what the instance thinks it is.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api.deps import CurrentPrincipal
from app.api.errors import REQUEST_ID_HEADER, install_error_handling
from app.config import DeploymentMode, get_settings
from app.db.session import admin_session, dispose_engine, get_engine
from app.licensing import LicenseError, check_entitlement, get_license

log = logging.getLogger("aap")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    s = get_settings()
    logging.basicConfig(level=s.log_level)

    log.info(
        "starting aap api",
        extra={
            "mode": s.deployment_mode,
            "tenancy": s.tenancy,
            "instance": s.instance_name,
            "version": s.version,
        },
    )

    # Fail fast on an unreadable or mismatched license rather than discovering it on
    # the first write.
    if s.customer_operated:
        try:
            lic = get_license()
            log.info(
                "license loaded",
                extra={"licensee": lic.licensee, "expires": lic.expires_at.isoformat()},
            )
        except LicenseError:
            log.exception("license validation failed")
            raise

    # Verify the database is reachable and migrated before accepting traffic.
    async with admin_session() as session:
        revision = await session.scalar(text("SELECT version_num FROM alembic_version"))
        log.info("database connected", extra={"revision": revision})

    yield

    await dispose_engine()


def create_app() -> FastAPI:
    s = get_settings()

    app = FastAPI(
        title="Agent Assurance Platform",
        version=s.version,
        description=(
            "Discovery, release intelligence, accreditation and continuous attestation "
            "for enterprise AI agents."
        ),
        root_path=s.api_root_path,
        lifespan=lifespan,
        docs_url="/docs" if s.environment != "production" else None,
    )

    # Every failure leaves through one envelope carrying a reason code. Installed before
    # the routers so a router that raises during construction is still rendered as one.
    install_error_handling(app)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=s.cors_origins,
        # The console session is an HttpOnly cookie, so a cross-origin console cannot
        # send it without this. `allow_origins` is an explicit list, never `*` — the two
        # together are what browsers refuse.
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*", REQUEST_ID_HEADER],
        expose_headers=[REQUEST_ID_HEADER],
    )

    @app.get("/healthz", tags=["ops"])
    async def healthz() -> dict[str, Any]:
        """Liveness. Must not touch the database — a database blip should not cause an
        orchestrator to kill an otherwise healthy process."""
        return {"status": "ok", "version": s.version}

    @app.get("/readyz", tags=["ops"])
    async def readyz() -> dict[str, Any]:
        """Readiness. Reports everything an operator of a self-hosted install needs."""
        checks: dict[str, Any] = {}

        try:
            async with get_engine().connect() as conn:
                await conn.execute(text("SELECT 1"))
            checks["database"] = "ok"
        except Exception as exc:
            checks["database"] = f"error: {exc.__class__.__name__}"

        agent_count = 0
        try:
            async with admin_session() as session:
                agent_count = await session.scalar(text("SELECT count(*) FROM agents")) or 0
        except Exception:
            pass

        entitlement = check_entitlement(agent_count)

        return {
            "status": "ok" if checks.get("database") == "ok" else "degraded",
            "version": s.version,
            "deployment": {
                "mode": s.deployment_mode,
                "tenancy": s.tenancy,
                "instance": s.instance_name,
                "egress_permitted": s.egress_permitted,
                "object_store": s.object_store,
                "secrets_provider": s.secrets_provider,
                "signing_provider": s.signing_provider,
            },
            "entitlement": {
                "ok": entitlement.ok,
                "read_only": entitlement.read_only,
                "reasons": list(entitlement.reasons),
                "warnings": list(entitlement.warnings),
            },
            "checks": checks,
            "agents": agent_count,
        }

    @app.get("/v1/deployment", tags=["ops"])
    async def deployment_info(_: CurrentPrincipal) -> dict[str, Any]:
        """Surfaced in the console banner so nobody is ever unsure whether they are
        looking at a shared instance or their own.

        Authenticated, unlike `/readyz`. The licensee name and exact version are not
        things to hand out to anyone who can reach the port, and the console only needs
        this once it has a signed-in user. `/readyz` still reports mode and tenancy
        unauthenticated, which is what an orchestrator probe and the pre-login console
        actually need.
        """
        lic = get_license()
        return {
            "mode": s.deployment_mode,
            "customer_operated": s.customer_operated,
            "instance": s.instance_name,
            "environment": s.environment,
            "version": s.version,
            "licensee": lic.licensee,
            "license_expires": lic.expires_at.isoformat()
            if s.deployment_mode is not DeploymentMode.SAAS
            else None,
            "data_leaves_estate": s.deployment_mode is DeploymentMode.SAAS,
        }

    # Domain routers are registered here as each milestone lands.
    from app.api.v1 import router as v1

    app.include_router(v1.router, prefix="/v1")

    return app


app = create_app()
