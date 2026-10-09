"""Domain service import graph must match ``app/domains/layer_order.py`` (AGENTS.md rule 3).

Parallel agents added ``composition`` and ``model_routing`` without placing them in the
documented chain, which produced a fragile module-level cycle between ``composition`` and
``assurance``. Routers may compose several services — that is their job — but
``service.py`` files must not import each other against the declared order.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.domains.layer_order import (
    DOMAIN_LAYER_ORDER,
    DOMAINS_OUTSIDE_LAYER,
    may_import_domain,
)

_DOMAINS_ROOT = Path(__file__).resolve().parents[2] / "app" / "domains"
_IMPORT_PREFIX = "app.domains."


def _agents_md_path() -> Path:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "AGENTS.md"
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("AGENTS.md not found above tests/unit")


def _domain_from_service_path(path: Path) -> str | None:
    if path.name != "service.py":
        return None
    try:
        rel = path.relative_to(_DOMAINS_ROOT)
    except ValueError:
        return None
    domain = rel.parts[0]
    if domain in DOMAINS_OUTSIDE_LAYER:
        return None
    return domain


def _service_import_target(module: str) -> str | None:
    """Return the domain whose ``service`` module is imported, if any."""
    if not module.startswith(_IMPORT_PREFIX):
        return None
    rest = module[len(_IMPORT_PREFIX) :]
    parts = rest.split(".")
    if not parts:
        return None
    domain = parts[0]
    if domain in DOMAINS_OUTSIDE_LAYER:
        return None
    if len(parts) == 1:
        return domain
    if parts[1] == "service" and len(parts) == 2:
        return domain
    return None


class _ImportCollector(ast.NodeVisitor):
    def __init__(self) -> None:
        self.modules: list[str] = []

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.modules.append(alias.name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module:
            self.modules.append(node.module)
        self.generic_visit(node)


def _collect_service_layer_edges() -> dict[str, set[str]]:
    edges: dict[str, set[str]] = {name: set() for name in DOMAIN_LAYER_ORDER}
    for path in _DOMAINS_ROOT.rglob("service.py"):
        source_domain = _domain_from_service_path(path)
        if source_domain is None:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        collector = _ImportCollector()
        collector.visit(tree)
        for module in collector.modules:
            target = _service_import_target(module)
            if target is None or target == source_domain:
                continue
            edges.setdefault(source_domain, set()).add(target)
    return edges


def _find_cycles(edges: dict[str, set[str]]) -> list[list[str]]:
    cycles: list[list[str]] = []
    visiting: set[str] = set()
    visited: set[str] = set()
    stack: list[str] = []

    def dfs(node: str) -> None:
        if node in visiting:
            start = stack.index(node)
            cycles.append([*stack[start:], node])
            return
        if node in visited:
            return
        visiting.add(node)
        stack.append(node)
        for nxt in sorted(edges.get(node, ())):
            dfs(nxt)
        stack.pop()
        visiting.remove(node)
        visited.add(node)

    for domain in DOMAIN_LAYER_ORDER:
        if domain not in visited:
            dfs(domain)
    return cycles


def test_layer_order_matches_agents_md_chain() -> None:
    """The prose chain in AGENTS.md must not drift from the code source of truth."""
    try:
        agents_md = _agents_md_path()
    except FileNotFoundError:
        pytest.skip("AGENTS.md not mounted in this runtime")
    text = agents_md.read_text(encoding="utf-8")
    start = text.index("`customers ->")
    end = text.index("`", start + 1)
    chain = text[start + 1 : end]
    declared = tuple(part.strip() for part in chain.split("->"))
    assert declared == DOMAIN_LAYER_ORDER


def test_service_import_graph_is_acyclic() -> None:
    edges = _collect_service_layer_edges()
    cycles = _find_cycles(edges)
    assert not cycles, f"service import cycle(s): {cycles}"


def test_service_imports_respect_declared_layer_order() -> None:
    edges = _collect_service_layer_edges()
    violations: list[str] = []
    for source, targets in sorted(edges.items()):
        for target in sorted(targets):
            if not may_import_domain(source, target):
                violations.append(f"{source} -> {target} (rightward service import)")
    assert not violations, "layer violations:\n" + "\n".join(violations)


def test_no_cross_domain_repository_imports_in_services() -> None:
    violations: list[str] = []
    for path in _DOMAINS_ROOT.rglob("service.py"):
        source_domain = _domain_from_service_path(path)
        if source_domain is None:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        collector = _ImportCollector()
        collector.visit(tree)
        for module in collector.modules:
            if not module.startswith(_IMPORT_PREFIX):
                continue
            rest = module[len(_IMPORT_PREFIX) :]
            parts = rest.split(".")
            if len(parts) >= 2 and parts[1] == "repository" and parts[0] != source_domain:
                violations.append(f"{path.relative_to(_DOMAINS_ROOT)} imports {module}")
    assert not violations, "cross-domain repository imports:\n" + "\n".join(violations)
