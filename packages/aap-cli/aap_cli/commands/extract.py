"""Static composition extraction from a customer repo."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from aap_cli.config import CliConfig
from aap_cli.loader import load_descriptor, save_descriptor

_TOOL_DECORATOR = re.compile(r"@tool\b")
_LANGGRAPH_STATEGRAPH = re.compile(r"StateGraph\s*\(")
_MCP_JSON_NAMES = ("mcp.json", ".cursor/mcp.json")


@dataclass
class ExtractReport:
    confident: dict[str, Any] = field(default_factory=dict)
    uncertain: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return f"sha256:{digest}"


def _find_mcp_config(repo: Path) -> Path | None:
    for name in _MCP_JSON_NAMES:
        candidate = repo / name
        if candidate.is_file():
            return candidate
    cursor = repo / ".cursor" / "mcp.json"
    if cursor.is_file():
        return cursor
    return None


def _parse_mcp_servers(path: Path, report: ExtractReport) -> list[dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        report.warnings.append(f"Could not parse MCP config {path}: {exc}")
        return []
    servers: list[dict[str, Any]] = []
    raw = payload.get("mcpServers") or payload.get("servers") or payload
    if not isinstance(raw, dict):
        report.uncertain.append(f"MCP config at {path} has unexpected shape")
        return servers
    for name, cfg in raw.items():
        if not isinstance(cfg, dict):
            continue
        url = cfg.get("url") or cfg.get("endpoint")
        if not isinstance(url, str):
            report.uncertain.append(f"MCP server {name!r} has no url — skipped")
            continue
        servers.append({"name": str(name), "url": url})
    return servers


def _scan_langgraph_tools(py_file: Path, report: ExtractReport) -> list[str]:
    try:
        text = py_file.read_text(encoding="utf-8")
    except OSError as exc:
        report.warnings.append(f"Could not read {py_file}: {exc}")
        return []
    if not (_TOOL_DECORATOR.search(text) or _LANGGRAPH_STATEGRAPH.search(text)):
        return []
    names: list[str] = []
    for match in re.finditer(r"def\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\(", text):
        fn = match.group(1)
        if fn.startswith("_"):
            continue
        window = text[max(0, match.start() - 120) : match.start() + 80]
        if "@tool" in window:
            names.append(fn)
    if _LANGGRAPH_STATEGRAPH.search(text) and not names:
        report.uncertain.append(
            f"LangGraph graph in {py_file} — tool names could not be inferred statically"
        )
    return names


def _scan_rules(repo: Path, report: ExtractReport) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    agents_md = repo / "AGENTS.md"
    if agents_md.is_file():
        sources.append(
            {
                "name": "agents_md",
                "kind": "agents_md",
                "path": "AGENTS.md",
                "digest": _sha256_file(agents_md),
            }
        )
    rules_dir = repo / ".cursor" / "rules"
    if rules_dir.is_dir():
        for path in sorted(rules_dir.glob("*.mdc")):
            rel = path.relative_to(repo).as_posix()
            key = path.stem.replace("-", "_")
            sources.append(
                {
                    "name": key[:64],
                    "kind": "cursor_rule",
                    "path": rel,
                    "digest": _sha256_file(path),
                }
            )
    skills_root = repo / ".cursor" / "skills"
    if skills_root.is_dir():
        for skill_md in sorted(skills_root.glob("**/SKILL.md")):
            rel = skill_md.relative_to(repo).as_posix()
            name = skill_md.parent.name
            sources.append(
                {
                    "name": name,
                    "kind": "skill",
                    "path": rel,
                    "digest": _sha256_file(skill_md),
                }
            )
    if not sources:
        report.uncertain.append("No AGENTS.md, Cursor rules or skills found")
    return sources


def _scan_skills(repo: Path) -> list[dict[str, Any]]:
    skills: list[dict[str, Any]] = []
    for root in (repo / ".cursor" / "skills", repo / ".cursor" / "skills-cursor"):
        if not root.is_dir():
            continue
        for skill_md in sorted(root.glob("**/SKILL.md")):
            rel = skill_md.relative_to(repo).as_posix()
            skills.append(
                {
                    "name": skill_md.parent.name,
                    "path": rel,
                    "digest": _sha256_file(skill_md),
                }
            )
    return skills


def _scan_subagents(repo: Path, report: ExtractReport) -> list[dict[str, Any]]:
    subagents: list[dict[str, Any]] = []
    for py_file in repo.rglob("*.py"):
        if "node_modules" in py_file.parts or ".venv" in py_file.parts:
            continue
        try:
            text = py_file.read_text(encoding="utf-8")
        except OSError:
            continue
        if "subagent" not in text.lower() and "SubAgent" not in text:
            continue
        if not _LANGGRAPH_STATEGRAPH.search(text):
            continue
        rel = py_file.relative_to(repo).as_posix()
        subagents.append(
            {
                "name": py_file.stem,
                "kind": "langgraph_subgraph",
                "ref": rel,
                "digest": _sha256_file(py_file),
            }
        )
    if not subagents:
        report.uncertain.append(
            "No LangGraph subgraph modules detected — sub_agents left unchanged"
        )
    return subagents


def extract_repo(repo_root: Path, descriptor: dict[str, Any]) -> tuple[dict[str, Any], ExtractReport]:
    """Best-effort harvest. Never guesses tool names without a decorator hint."""
    report = ExtractReport()
    patched = json.loads(json.dumps(descriptor))

    mcp_path = _find_mcp_config(repo_root)
    if mcp_path:
        servers = _parse_mcp_servers(mcp_path, report)
        if servers:
            refs = patched.setdefault("references", {})
            existing = {
                str(s.get("url")): s for s in (refs.get("mcp_servers") or []) if isinstance(s, dict)
            }
            merged: list[dict[str, Any]] = []
            for server in servers:
                row = existing.get(server["url"], {})
                merged.append({**row, **server})
            refs["mcp_servers"] = merged
            report.confident["mcp_servers"] = len(merged)

    tool_names: set[str] = set()
    graph_modules: list[Path] = []
    for py_file in repo_root.rglob("*.py"):
        if any(part in py_file.parts for part in (".venv", "node_modules", ".git")):
            continue
        names = _scan_langgraph_tools(py_file, report)
        tool_names.update(names)
        if _LANGGRAPH_STATEGRAPH.search(py_file.read_text(encoding="utf-8", errors="ignore")):
            graph_modules.append(py_file)

    if tool_names:
        tools = patched.setdefault("tools", [])
        known = {str(t.get("name")) for t in tools if isinstance(t, dict)}
        for name in sorted(tool_names):
            if name not in known:
                tools.append({"name": name, "effect": "unknown"})
        report.confident["tools"] = len(tool_names)
    elif graph_modules:
        report.uncertain.append(
            "LangGraph modules found but no @tool-decorated functions — tools not updated"
        )

    composition = patched.setdefault("composition", {})
    composition["rule_sources"] = _scan_rules(repo_root, report)
    composition["skills"] = _scan_skills(repo_root)
    if composition["skills"]:
        report.confident["skills"] = len(composition["skills"])

    subagents = _scan_subagents(repo_root, report)
    if subagents:
        composition["sub_agents"] = subagents
        report.confident["sub_agents"] = len(subagents)

    return patched, report


def run(
    repo_root: Path,
    descriptor_path: Path,
    config: CliConfig,
    *,
    write: bool = False,
) -> int:
    descriptor = load_descriptor(descriptor_path)
    patched, report = extract_repo(repo_root.resolve(), descriptor)

    if write:
        save_descriptor(descriptor_path, patched)

    if config.json_output:
        print(
            json.dumps(
                {
                    "written": write,
                    "confident": report.confident,
                    "uncertain": report.uncertain,
                    "warnings": report.warnings,
                },
                indent=2,
            )
        )
    else:
        for key, val in report.confident.items():
            print(f"confident: {key} ({val})")
        for line in report.uncertain:
            print(f"uncertain: {line}")
        for line in report.warnings:
            print(f"warning: {line}")
        if write:
            print(f"updated {descriptor_path}")
        else:
            print("(dry run — pass --write to patch the descriptor)")

    return 0 if not report.warnings else 0
