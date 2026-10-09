"""HTTP client for the Agent Assurance Platform API."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import httpx

from aap_cli.config import CliConfig


class CliError(Exception):
    """Base for failures the pipeline should treat as exit code 1."""


class NetworkError(CliError):
    pass


class AuthError(CliError):
    """401 or 403 — credentials or tenancy, not a release verdict."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code


class ApiResponseError(CliError):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code


class AapClient:
    def __init__(
        self,
        config: CliConfig,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        headers: dict[str, str] = {"Accept": "application/json"}
        if config.org_id:
            headers["X-Org-Id"] = config.org_id
        if config.token:
            headers["Authorization"] = f"Bearer {config.token}"
        self._client = httpx.Client(
            base_url=config.base_url,
            headers=headers,
            timeout=httpx.Timeout(30.0),
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> AapClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            response = self._client.request(method, path, **kwargs)
        except httpx.RequestError as exc:
            raise NetworkError(
                f"could not reach platform at {self._client.base_url}: {exc}"
            ) from exc
        return response

    @staticmethod
    def _detail(response: httpx.Response) -> str:
        try:
            body = response.json()
            if isinstance(body, dict) and "detail" in body:
                detail = body["detail"]
                if isinstance(detail, str):
                    return detail
                return str(detail)
        except Exception:
            pass
        text = response.text.strip()
        return text[:500] if text else f"HTTP {response.status_code}"

    def _check(self, response: httpx.Response) -> None:
        if response.status_code in (401, 403):
            raise AuthError(
                response.status_code,
                f"authentication failed ({response.status_code}): {self._detail(response)}",
            )
        if response.status_code >= 400:
            raise ApiResponseError(
                response.status_code,
                f"platform returned {response.status_code}: {self._detail(response)}",
            )

    def preview_release(
        self,
        before_descriptor: dict[str, Any] | None,
        after_descriptor: dict[str, Any],
    ) -> dict[str, Any]:
        response = self._request(
            "POST",
            "/v1/releases/preview",
            json={
                "before_descriptor": before_descriptor,
                "after_descriptor": after_descriptor,
            },
        )
        self._check(response)
        data = response.json()
        if not isinstance(data, dict):
            raise ApiResponseError(response.status_code, "unexpected preview response shape")
        return data

    def list_packs(self, accreditation_id: UUID | str) -> list[dict[str, Any]]:
        response = self._request("GET", f"/v1/accreditations/{accreditation_id}/packs")
        self._check(response)
        data = response.json()
        if not isinstance(data, list):
            raise ApiResponseError(response.status_code, "unexpected packs list response shape")
        return [item for item in data if isinstance(item, dict)]

    def download_bytes(self, url: str) -> bytes:
        """Fetch pack bytes. Uses a one-off client so pack URIs may leave the API host."""
        try:
            if url.startswith("/"):
                response = self._client.get(url)
            else:
                response = httpx.get(
                    url,
                    headers=dict(self._client.headers),
                    timeout=httpx.Timeout(60.0),
                )
        except httpx.RequestError as exc:
            raise NetworkError(f"could not download pack from {url}: {exc}") from exc
        if response.status_code in (401, 403):
            raise AuthError(
                response.status_code,
                f"authentication failed downloading pack ({response.status_code})",
            )
        if response.status_code >= 400:
            raise ApiResponseError(
                response.status_code,
                f"pack download failed with {response.status_code}",
            )
        return response.content
