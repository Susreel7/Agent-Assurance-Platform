"""Static verification with no external dependencies: syntax and structure only."""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
errors: list[str] = []
checked = {"py": 0, "yaml": 0, "json": 0}

# ---- Python syntax ----
for path in ROOT.rglob("*.py"):
    if "node_modules" in path.parts or ".venv" in path.parts:
        continue
    try:
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        checked["py"] += 1
    except SyntaxError as exc:
        errors.append(f"PY  {path.relative_to(ROOT)}:{exc.lineno} {exc.msg}")

# ---- JSON ----
for path in ROOT.rglob("*.json"):
    if "node_modules" in path.parts:
        continue
    try:
        json.loads(path.read_text(encoding="utf-8"))
        checked["json"] += 1
    except json.JSONDecodeError as exc:
        errors.append(f"JSON {path.relative_to(ROOT)}:{exc.lineno} {exc.msg}")

# ---- YAML: structural checks without PyYAML ----
for path in list(ROOT.rglob("*.yml")) + list(ROOT.rglob("*.yaml")):
    if "node_modules" in path.parts:
        continue
    text = path.read_text(encoding="utf-8")
    checked["yaml"] += 1
    for i, line in enumerate(text.splitlines(), 1):
        if "\t" in line:
            errors.append(f"YAML {path.relative_to(ROOT)}:{i} contains a tab character")

# ---- expected structure ----
required = [
    "AGENTS.md",
    "Makefile",
    "docker-compose.yml",
    "docker-compose.byoc.yml",
    ".env.example",
    "services/api/Dockerfile",
    "services/api/pyproject.toml",
    "services/api/alembic.ini",
    "services/api/alembic/env.py",
    "services/api/alembic/versions/0001_baseline.py",
    "services/api/app/main.py",
    "services/api/app/config.py",
    "services/api/app/licensing.py",
    "services/api/app/db/session.py",
    "services/api/app/db/base.py",
    "services/api/app/providers/secrets.py",
    "services/api/app/providers/objectstore.py",
    "services/api/app/providers/signing.py",
    "services/api/app/workers/runner.py",
    "services/api/app/domains/releases/schemas.py",
    "services/api/app/domains/releases/differ.py",
    "services/collector/Dockerfile",
    "services/collector/collector/main.py",
    "deploy/helm/agent-assurance/values.yaml",
    "deploy/helm/agent-assurance/values-byoc-aws.yaml",
    "tools/issue_license.py",
]
for rel in required:
    if not (ROOT / rel).exists():
        errors.append(f"MISSING {rel}")

# ---- balance check on the SQL blocks in the baseline migration ----
migration = ROOT / "services/api/alembic/versions/0001_baseline.py"
if migration.exists():
    src = migration.read_text(encoding="utf-8")
    for name, opener, closer in (("paren", "(", ")"), ("bracket", "[", "]")):
        if src.count(opener) != src.count(closer):
            errors.append(
                f"SQL  0001_baseline.py unbalanced {name}: "
                f"{src.count(opener)} vs {src.count(closer)}"
            )
    # every CREATE TABLE should have a matching entry in downgrade
    import re

    created = set(re.findall(r"CREATE TABLE (\w+)", src))
    dropped = set(re.findall(r"DROP TABLE IF EXISTS (\w+)", src))
    missing_drops = created - dropped
    if missing_drops:
        errors.append(f"SQL  tables created but never dropped in downgrade: {sorted(missing_drops)}")

print(f"checked: {checked['py']} python, {checked['json']} json, {checked['yaml']} yaml")
if errors:
    print(f"\n{len(errors)} problem(s):")
    for e in errors:
        print("  " + e)
    sys.exit(1)
print("all checks passed")
