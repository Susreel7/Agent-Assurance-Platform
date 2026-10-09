from __future__ import annotations

from prompt.app import create_app
from prompt.config import reset_settings_cache


def test_openapi_includes_runtime_read_and_compare_schemas(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setenv("PROMPT_RUN_MIGRATIONS_ON_STARTUP", "false")
    reset_settings_cache()
    schema = create_app().openapi()
    paths = schema.get("paths", {})
    internal_path = next(
        (p for p in paths if "/runtime/read/artifacts/" in p),
        None,
    )
    assert internal_path is not None
    get_op = paths[internal_path]["get"]
    assert get_op.get("summary")
    assert "RuntimeArtifactResponse" in schema["components"]["schemas"]
    compare_out = schema["components"]["schemas"].get("PlaygroundCompareOutput")
    assert compare_out is not None
    assert "variants" in compare_out.get("properties", {})
