"""Prompt internal and runtime API client."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import httpx
from httpx import AsyncBaseTransport

from evaluate.config import Settings
from evaluate.errors import UpstreamError


class PromptClient:
    def __init__(self, settings: Settings, *, transport: AsyncBaseTransport | None = None) -> None:
        self._settings = settings
        self._transport = transport

    def _internal_headers(self, org_id: UUID, project_id: UUID) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._settings.internal_service_token}",
            "X-Organization-Id": str(org_id),
            "X-Project-Id": str(project_id),
            "X-Actor": "evaluate-worker",
        }

    async def fetch_revision_internal(
        self,
        *,
        org_id: UUID,
        project_id: UUID,
        artifact_key: str,
        revision_id: UUID,
    ) -> dict[str, Any]:
        url = (
            f"{self._settings.prompt_base_url.rstrip('/')}"
            f"/v1/orgs/{org_id}/projects/{project_id}/artifacts/{artifact_key}/revisions/{revision_id}"
        )
        async with httpx.AsyncClient(
            timeout=self._settings.upstream_timeout_seconds,
            transport=self._transport,
        ) as client:
            resp = await client.get(url, headers=self._internal_headers(org_id, project_id))
        if resp.status_code >= 400:
            raise UpstreamError(f"prompt internal fetch failed: {resp.status_code}")
        data = resp.json()
        if not isinstance(data, dict):
            raise UpstreamError("prompt internal fetch returned non-object")
        return data

    async def fetch_runtime_artifact(
        self,
        *,
        org_id: UUID,
        project_id: UUID,
        artifact_key: str,
        revision_id: UUID,
    ) -> dict[str, Any]:
        bearer = self._settings.prompt_workload_bearer or self._settings.internal_service_token
        url = (
            f"{self._settings.prompt_base_url.rstrip('/')}"
            f"/v1/orgs/{org_id}/projects/{project_id}/runtime/artifacts/{artifact_key}"
        )
        async with httpx.AsyncClient(
            timeout=self._settings.upstream_timeout_seconds,
            transport=self._transport,
        ) as client:
            resp = await client.get(
                url,
                params={"revision_id": str(revision_id)},
                headers={"Authorization": f"Bearer {bearer}"},
            )
        if resp.status_code >= 400:
            raise UpstreamError(f"prompt runtime fetch failed: {resp.status_code}")
        data = resp.json()
        if not isinstance(data, dict):
            raise UpstreamError("prompt runtime fetch returned non-object")
        return data
