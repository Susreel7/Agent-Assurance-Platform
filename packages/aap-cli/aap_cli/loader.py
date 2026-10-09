"""Load AAP descriptors from disk and validate against the bundled 0.1 schema."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import jsonschema
import yaml
from jsonschema import Draft202012Validator

_SCHEMA_REL = Path("schema") / "aap-0.1.schema.json"


class DescriptorLoadError(Exception):
    """The file could not be read or parsed as YAML/JSON."""


@dataclass(frozen=True)
class ValidationIssue:
    path: str
    message: str


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    issues: tuple[ValidationIssue, ...]


def schema_path() -> Path:
    bundled = Path(__file__).resolve().parent / _SCHEMA_REL
    if bundled.is_file():
        return bundled
    monorepo = Path(__file__).resolve().parents[2] / "aap-spec" / "schema" / "aap-0.1.schema.json"
    return monorepo


def _load_schema() -> dict[str, Any]:
    with schema_path().open(encoding="utf-8") as fh:
        return cast(dict[str, Any], json.load(fh))


def load_descriptor(path: Path) -> dict[str, Any]:
    """Parse a descriptor file. Raises ``DescriptorLoadError`` on failure."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise DescriptorLoadError(f"cannot read {path}: {exc}") from exc

    suffix = path.suffix.lower()
    try:
        if suffix in {".yaml", ".yml"}:
            data = yaml.safe_load(text)
        elif suffix == ".json":
            data = json.loads(text)
        else:
            # Extensionless or unknown — try JSON first, then YAML.
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                data = yaml.safe_load(text)
    except (yaml.YAMLError, json.JSONDecodeError) as exc:
        raise DescriptorLoadError(f"malformed descriptor in {path}: {exc}") from exc

    if not isinstance(data, dict):
        raise DescriptorLoadError(f"descriptor root must be an object, got {type(data).__name__}")
    return data


def save_descriptor(path: Path, document: dict[str, Any]) -> None:
    """Write a descriptor back to disk in the same format as the path extension."""
    suffix = path.suffix.lower()
    if suffix in {".yaml", ".yml"}:
        text = yaml.dump(document, sort_keys=False, allow_unicode=True)
    elif suffix == ".json":
        text = json.dumps(document, indent=2, sort_keys=True)
        text += "\n"
    else:
        text = yaml.dump(document, sort_keys=False, allow_unicode=True)
    path.write_text(text, encoding="utf-8")


def _json_pointer(error: jsonschema.exceptions.ValidationError) -> str:
    if not error.absolute_path:
        return "/"
    segments = [str(p) for p in error.absolute_path]
    return "/" + "/".join(segments)


def _human_message(error: jsonschema.exceptions.ValidationError) -> str:
    # jsonschema messages are often usable; shorten the noisier ones for CI logs.
    if error.validator == "required":
        missing = error.message.split("'")[1] if "'" in error.message else "field"
        return f"Missing required property '{missing}'."
    schema_obj = cast(dict[str, Any], error.schema)
    if error.validator == "const":
        return f"Must be {schema_obj.get('const')!r}."
    if error.validator == "enum":
        allowed = ", ".join(repr(v) for v in schema_obj.get("enum", ()))
        return f"Value is not one of: {allowed}."
    if error.validator == "pattern":
        return "Value does not match the required pattern."
    return error.message


def validate_descriptor(document: dict[str, Any]) -> ValidationResult:
    schema = _load_schema()
    validator = Draft202012Validator(schema)
    issues: list[ValidationIssue] = []
    for error in sorted(validator.iter_errors(document), key=lambda e: list(e.absolute_path)):
        issues.append(ValidationIssue(path=_json_pointer(error), message=_human_message(error)))
    return ValidationResult(valid=not issues, issues=tuple(issues))
