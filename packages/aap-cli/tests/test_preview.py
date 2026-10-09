"""Release gate preview — exit codes, JSON shape, token redaction."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from aap_cli.commands import preview as preview_cmd
from aap_cli.config import CliConfig
from aap_cli.main import main


def _preview_transport(
    allowed: bool,
    *,
    expect_token: str | None = "secret-token-xyz",
    expect_org: str | None = "org-123",
) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/releases/preview"
        if expect_token is not None:
            assert request.headers["Authorization"] == f"Bearer {expect_token}"
        if expect_org is not None:
            assert request.headers["X-Org-Id"] == expect_org
        return httpx.Response(
            200,
            json={
                "allowed": allowed,
                "headline": "test headline",
                "material_count": 0 if allowed else 1,
                "review_count": 0,
                "accreditation_impact": "none" if allowed else "suspends",
                "affected_accreditations": [],
                "blocking_changes": [] if allowed else [{"summary": "blocked change"}],
                "advisory": [],
            },
        )

    return httpx.MockTransport(handler)


def test_preview_exit_allowed_blocked(
    descriptors_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    before = descriptors_dir / "before.yaml"
    after = descriptors_dir / "after.yaml"
    cfg = CliConfig(
        base_url="http://platform.test",
        org_id="org-123",
        token="secret-token-xyz",
        json_output=False,
    )

    code = preview_cmd.run(
        before,
        after,
        cfg,
        offline=False,
        transport=_preview_transport(allowed=True),
    )
    assert code == 0
    out = capsys.readouterr()
    assert "secret-token-xyz" not in out.out
    assert "secret-token-xyz" not in out.err

    code = preview_cmd.run(
        before,
        after,
        cfg,
        offline=False,
        transport=_preview_transport(allowed=False),
    )
    assert code == 2


def test_preview_network_failure_exit_one(
    descriptors_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    cfg = CliConfig(base_url="http://platform.test", org_id=None, token=None, json_output=True)
    code = preview_cmd.run(
        descriptors_dir / "before.yaml",
        descriptors_dir / "after.yaml",
        cfg,
        offline=False,
        transport=httpx.MockTransport(handler),
    )
    assert code == 1
    payload = json.loads(capsys.readouterr().out)
    assert "error" in payload


def test_preview_auth_failure(
    descriptors_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "invalid token"})

    cfg = CliConfig(base_url="http://platform.test", org_id=None, token="t", json_output=True)
    code = preview_cmd.run(
        descriptors_dir / "before.yaml",
        descriptors_dir / "after.yaml",
        cfg,
        offline=False,
        transport=httpx.MockTransport(handler),
    )
    assert code == 1
    assert "401" in capsys.readouterr().out


def test_preview_json_shape(
    descriptors_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    cfg = CliConfig(base_url="http://platform.test", org_id=None, token=None, json_output=True)
    preview_cmd.run(
        descriptors_dir / "before.yaml",
        descriptors_dir / "after.yaml",
        cfg,
        offline=False,
        transport=_preview_transport(allowed=True, expect_token=None, expect_org=None),
    )
    payload = json.loads(capsys.readouterr().out)
    for key in (
        "allowed",
        "headline",
        "material_count",
        "review_count",
        "accreditation_impact",
        "blocking_changes",
        "advisory",
    ):
        assert key in payload


def test_main_never_prints_token(
    descriptors_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("AAP_TOKEN", "super-secret-bearer-value")
    monkeypatch.setenv("AAP_BASE_URL", "http://platform.test")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "allowed": True,
                "headline": "ok",
                "material_count": 0,
                "review_count": 0,
                "accreditation_impact": "none",
                "affected_accreditations": [],
                "blocking_changes": [],
                "advisory": [],
            },
        )

    # Patch transport by running preview through command module with explicit transport
    # in tests above; here exercise main with monkeypatched client factory.
    from aap_cli.commands import preview as preview_module

    original_run = preview_module.run

    def run_with_mock(*args: Any, **kwargs: Any) -> int:
        kwargs["transport"] = httpx.MockTransport(handler)
        return original_run(*args, **kwargs)

    monkeypatch.setattr(preview_module, "run", run_with_mock)
    exit_code = main(
        [
            "--token",
            "super-secret-bearer-value",
            "preview",
            str(descriptors_dir / "before.yaml"),
            str(descriptors_dir / "after.yaml"),
        ]
    )
    assert exit_code == 0
    combined = capsys.readouterr().out + capsys.readouterr().err
    assert "super-secret-bearer-value" not in combined


@pytest.mark.parametrize("offline", [True])
def test_preview_offline_local_flag(
    descriptors_dir: Path,
    capsys: pytest.CaptureFixture[str],
    offline: bool,
) -> None:
    pytest.importorskip("app.domains.releases.differ")
    cfg = CliConfig(base_url="http://platform.test", org_id=None, token=None, json_output=True)
    code = preview_cmd.run(
        descriptors_dir / "before.yaml",
        descriptors_dir / "after.yaml",
        cfg,
        offline=True,
    )
    assert code in (0, 2)
    payload = json.loads(capsys.readouterr().out)
    assert payload.get("local_unratified") is True
