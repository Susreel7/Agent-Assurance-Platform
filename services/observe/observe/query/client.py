"""Typed HTTP client for the Observe query service (internal callers)."""

from __future__ import annotations

from typing import Any, TypeVar
from uuid import UUID

import httpx
from pydantic import BaseModel

from observe.query.schemas import (
    ExecutionDetailResponse,
    ExecutionListResponse,
    ObservedUserListResponse,
    PayloadContentResponse,
)

T = TypeVar("T", bound=BaseModel)


class ObserveQueryClient:
    def __init__(self, base_url: str, token: str, *, timeout: float = 30.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._timeout = timeout

    async def _get(
        self,
        path: str,
        *,
        org_id: UUID,
        project_id: UUID,
        model: type[T],
        params: dict[str, Any] | None = None,
    ) -> T:
        query: dict[str, Any] = {"organization_id": str(org_id), "project_id": str(project_id)}
        if params:
            query.update({k: v for k, v in params.items() if v is not None})
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.get(
                f"{self._base_url}{path}",
                params=query,
                headers={"Authorization": f"Bearer {self._token}"},
            )
        response.raise_for_status()
        return model.model_validate(response.json())

    async def list_executions(
        self, org_id: UUID, project_id: UUID, *, limit: int = 50, offset: int = 0
    ) -> ExecutionListResponse:
        return await self._get(
            "/v1/executions",
            org_id=org_id,
            project_id=project_id,
            model=ExecutionListResponse,
            params={"limit": limit, "offset": offset},
        )

    async def get_execution(
        self, org_id: UUID, project_id: UUID, execution_id: str
    ) -> ExecutionDetailResponse:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.get(
                f"{self._base_url}/v1/executions/{execution_id}",
                params={"organization_id": str(org_id), "project_id": str(project_id)},
                headers={"Authorization": f"Bearer {self._token}"},
            )
        response.raise_for_status()
        return ExecutionDetailResponse.model_validate(response.json())

    async def list_users(
        self, org_id: UUID, project_id: UUID, *, limit: int = 50, offset: int = 0
    ) -> ObservedUserListResponse:
        return await self._get(
            "/v1/users",
            org_id=org_id,
            project_id=project_id,
            model=ObservedUserListResponse,
            params={"limit": limit, "offset": offset},
        )

    async def get_payload(
        self,
        org_id: UUID,
        project_id: UUID,
        payload_id: UUID,
        *,
        actor_subject: str = "internal-service",
    ) -> PayloadContentResponse:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.get(
                f"{self._base_url}/v1/payloads/{payload_id}",
                params={"organization_id": str(org_id), "project_id": str(project_id)},
                headers={
                    "Authorization": f"Bearer {self._token}",
                    "X-Actor-Subject": actor_subject,
                },
            )
        response.raise_for_status()
        return PayloadContentResponse.model_validate(response.json())
