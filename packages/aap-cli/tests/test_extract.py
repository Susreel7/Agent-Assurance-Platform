"""Static composition extraction."""

from __future__ import annotations

from pathlib import Path

import yaml

from aap_cli.commands.extract import extract_repo


FIXTURE = Path(__file__).parent / "fixtures" / "langgraph_repo"


def test_extract_finds_langgraph_tools_and_mcp(tmp_path: Path, minimal_descriptor: dict) -> None:
    descriptor_path = tmp_path / "agent.aap.yaml"
    descriptor_path.write_text(yaml.dump(minimal_descriptor), encoding="utf-8")

    patched, report = extract_repo(FIXTURE, minimal_descriptor)

    assert report.confident.get("mcp_servers") == 1
    tool_names = {t["name"] for t in patched.get("tools", []) if isinstance(t, dict)}
    assert "search_claims" in tool_names
    assert "build_graph" not in tool_names
    assert patched["references"]["mcp_servers"][0]["name"] == "stripe"
    sources = patched["composition"]["rule_sources"]
    assert any(s["name"] == "agents_md" for s in sources)
    assert isinstance(report.uncertain, list)
