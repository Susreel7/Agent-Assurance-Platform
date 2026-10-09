"""CLI configuration from flags and AAP_* environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class CliConfig:
    base_url: str
    org_id: str | None
    token: str | None
    json_output: bool

    def redacted_repr(self) -> str:
        """For debug lines — never include the bearer token."""
        return (
            f"base_url={self.base_url!r} org_id={self.org_id!r} "
            f"token={'***' if self.token else None}"
        )


def config_from_env(
    *,
    base_url: str | None,
    org_id: str | None,
    token: str | None,
    json_output: bool,
) -> CliConfig:
    resolved_base = (base_url or os.environ.get("AAP_BASE_URL") or "http://localhost:8000").rstrip(
        "/"
    )
    resolved_org = org_id if org_id is not None else os.environ.get("AAP_ORG_ID")
    resolved_token = token if token is not None else os.environ.get("AAP_TOKEN")
    return CliConfig(
        base_url=resolved_base,
        org_id=resolved_org,
        token=resolved_token,
        json_output=json_output,
    )
