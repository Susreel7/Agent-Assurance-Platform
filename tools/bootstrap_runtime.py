"""Create the local runtime project and machine credential, then update ``.env``."""

from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = REPO_ROOT / ".env"
SCOPES = [
    "observe:ingest",
    "ingest:runs",
    "prompt:read",
    "evaluate:score",
    "router:models",
    "router:chat",
    "router:responses",
    "router:embeddings",
    "mcp:invoke",
    "mcp:usage",
    "audit:write",
]


def request(
    method: str,
    url: str,
    *,
    headers: dict[str, str],
    body: dict[str, Any] | None = None,
) -> Any:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {url} failed ({exc.code}): {detail}") from exc


def read_env() -> dict[str, str]:
    if not ENV_PATH.exists():
        return {}
    values: dict[str, str] = {}
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        if line and not line.lstrip().startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def write_env(updates: dict[str, str]) -> None:
    lines = ENV_PATH.read_text(encoding="utf-8").splitlines() if ENV_PATH.exists() else []
    remaining = dict(updates)
    output: list[str] = []
    for line in lines:
        if line and not line.lstrip().startswith("#") and "=" in line:
            key = line.split("=", 1)[0].strip()
            if key in remaining:
                output.append(f"{key}={remaining.pop(key)}")
                continue
        output.append(line)
    if output and output[-1]:
        output.append("")
    output.extend(f"{key}={value}" for key, value in remaining.items())
    ENV_PATH.write_text("\n".join(output) + "\n", encoding="utf-8")


def inspect_token(api_url: str, token: str) -> dict[str, Any] | None:
    if not token:
        return None
    try:
        return request(
            "POST",
            f"{api_url}/v1/workload-credentials/-/introspect",
            headers={"Authorization": f"Bearer {token}"},
        )
    except RuntimeError:
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--org-id", required=True)
    parser.add_argument("--api-url", default="http://localhost:8000")
    parser.add_argument("--project-slug", default="runtime")
    args = parser.parse_args()

    api_url = args.api_url.rstrip("/")
    headers = {"Content-Type": "application/json", "X-Org-Id": args.org_id}
    page = request(
        "GET",
        f"{api_url}/v1/workload-credentials/projects?limit=200",
        headers=headers,
    )
    project = next((item for item in page["items"] if item["slug"] == args.project_slug), None)
    if project is None:
        project = request(
            "POST",
            f"{api_url}/v1/workload-credentials/projects",
            headers=headers,
            body={"slug": args.project_slug, "name": "Agent Runtime"},
        )

    env = read_env()
    token = env.get("RUNTIME_WORKLOAD_BEARER", "")
    current = inspect_token(api_url, token)
    current_is_sufficient = bool(
        current
        and current.get("active")
        and current.get("project_id") == project["id"]
        and set(SCOPES).issubset(set(current.get("scopes") or []))
    )
    if not current_is_sufficient:
        if current and current.get("active") and current.get("credential_id"):
            request(
                "POST",
                f"{api_url}/v1/workload-credentials/{current['credential_id']}/revoke",
                headers=headers,
            )
        credential = request(
            "POST",
            f"{api_url}/v1/workload-credentials",
            headers=headers,
            body={
                "project_id": project["id"],
                "name": "local-runtime-services",
                "environment": "production",
                "modules": ["router", "observe", "prompt", "evaluate"],
                "scopes": SCOPES,
                "allowed_model_patterns": ["*"],
            },
        )
        token = credential["secret"]

    write_env(
        {
            "RUNTIME_ORG_ID": args.org_id,
            "RUNTIME_PROJECT_ID": project["id"],
            "RUNTIME_WORKLOAD_BEARER": token,
        }
    )
    print(f"runtime bootstrap ready: project={project['id']} (credential secret stored in .env)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
