"""Export or verify the API's OpenAPI document.

The frontend contract is generated from this document.  Checking paths against a stale
snapshot only proves that two stale artifacts agree, so CI imports the running
application definition and compares the complete document before building the console.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from app.main import app


def _schema() -> dict[str, Any]:
    return app.openapi()


def _describe_difference(expected: dict[str, Any], actual: dict[str, Any]) -> str:
    expected_paths = set(expected.get("paths", {}))
    actual_paths = set(actual.get("paths", {}))
    expected_schemas = set(expected.get("components", {}).get("schemas", {}))
    actual_schemas = set(actual.get("components", {}).get("schemas", {}))

    parts: list[str] = []
    for label, values in (
        ("added paths", actual_paths - expected_paths),
        ("removed paths", expected_paths - actual_paths),
        ("added schemas", actual_schemas - expected_schemas),
        ("removed schemas", expected_schemas - actual_schemas),
    ):
        if values:
            parts.append(f"{label}: {', '.join(sorted(values))}")
    if not parts:
        parts.append("an existing operation or schema changed")
    return "; ".join(parts)


def _check(path: Path) -> int:
    try:
        expected = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(f"OpenAPI snapshot does not exist: {path}", file=sys.stderr)
        return 1
    except json.JSONDecodeError as exc:
        print(f"OpenAPI snapshot is invalid JSON: {exc}", file=sys.stderr)
        return 1

    actual = _schema()
    if expected != actual:
        print(
            "OpenAPI snapshot is stale: " + _describe_difference(expected, actual),
            file=sys.stderr,
        )
        print(
            "Run `make client` (or `scripts\\aap client`) and commit both artifacts.",
            file=sys.stderr,
        )
        return 1

    print(
        f"OpenAPI snapshot is current: {len(actual.get('paths', {}))} paths, "
        f"{len(actual.get('components', {}).get('schemas', {}))} schemas"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check",
        type=Path,
        help="compare the generated document with this snapshot instead of writing JSON",
    )
    args = parser.parse_args()

    if args.check is not None:
        return _check(args.check)

    json.dump(_schema(), sys.stdout, sort_keys=True, separators=(",", ":"))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
