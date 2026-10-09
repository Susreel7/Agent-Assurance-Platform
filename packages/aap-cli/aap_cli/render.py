"""Human and JSON output for CLI commands.

Everything user-facing goes through :class:`SafeWriter`. The gate runs on CI runners
whose console encoding we do not choose, and some of the text it prints comes from the
API rather than from this file, so no format string here can be audited into safety. A
release must never appear to fail because a separator character could not be encoded.
"""

from __future__ import annotations

import json
import sys
from typing import Any, TextIO, cast

from aap_cli.loader import ValidationResult

#: ASCII stand-ins for the glyphs that show up in verdict text, ours and the API's.
#: Applied only when the destination cannot encode them.
_FALLBACKS = str.maketrans(
    {
        "\u2192": "->",  # rightwards arrow
        "\u2190": "<-",
        "\u00b7": "|",  # middle dot, the verdict separator
        "\u2014": "-",  # em dash
        "\u2013": "-",  # en dash
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2026": "...",
        "\u2713": "OK",
        "\u2717": "x",
        "\u00a0": " ",
    }
)

#: Probe string: if the destination encodes these, it can encode our output.
_PROBE = "\u2192\u00b7\u2014"


class SafeWriter:
    """A text sink that degrades characters the destination cannot encode.

    A Windows console is cp1252 by default and has no U+2192. Writing one raises
    UnicodeEncodeError, so the gate exits with a traceback instead of a verdict and
    reads as a broken tool rather than a blocked release. Degrade the glyph, never the
    exit code.
    """

    def __init__(self, stream: TextIO) -> None:
        self._stream = stream
        encoding = getattr(stream, "encoding", None)
        if not encoding:
            # StringIO and other in-memory sinks accept any str.
            self._encoding: str | None = None
            self._degrade = False
            return
        self._encoding = encoding
        try:
            _PROBE.encode(encoding)
        except UnicodeEncodeError:
            self._degrade = True
        except LookupError:
            # An encoding name Python does not know. Treat the sink as opaque.
            self._encoding = None
            self._degrade = False
        else:
            self._degrade = False

    def write(self, text: str) -> None:
        if not self._degrade or self._encoding is None:
            self._stream.write(text)
            return
        safe = text.translate(_FALLBACKS)
        try:
            safe.encode(self._encoding)
        except UnicodeEncodeError:
            # Text from the API may hold anything; '?' beats a traceback.
            safe = safe.encode(self._encoding, errors="replace").decode(
                self._encoding, errors="replace"
            )
        self._stream.write(safe)


def _write_json(payload: Any, stream: TextIO) -> None:
    # ensure_ascii keeps JSON output encodable on any console, and consumers decode it.
    json.dump(payload, stream, indent=2, sort_keys=True, ensure_ascii=True)
    stream.write("\n")


def render_validation(result: ValidationResult, *, as_json: bool, stream: TextIO) -> None:
    if as_json:
        _write_json(
            {
                "valid": result.valid,
                "issues": [{"path": i.path, "message": i.message} for i in result.issues],
            },
            stream,
        )
        return
    out = SafeWriter(stream)
    if result.valid:
        out.write("Descriptor is valid.\n")
        return
    out.write(f"Descriptor is invalid ({len(result.issues)} issue(s)):\n")
    for issue in result.issues:
        out.write(f"  {issue.path}: {issue.message}\n")


def _change_to_dict(change: Any) -> dict[str, Any]:
    if hasattr(change, "model_dump"):
        return cast(dict[str, Any], change.model_dump(mode="json"))
    return cast(dict[str, Any], dict(change))


def render_diff(
    diff: Any,
    *,
    as_json: bool,
    stream: TextIO,
) -> None:
    changes = diff.changes
    if as_json:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for category, items in diff.grouped().items():
            grouped[category.value if hasattr(category, "value") else str(category)] = [
                _change_to_dict(c) for c in items
            ]
        _write_json(
            {
                "from_semver": diff.from_semver,
                "to_semver": diff.to_semver,
                "change_count": len(changes),
                "by_category": grouped,
            },
            stream,
        )
        return

    out = SafeWriter(stream)
    out.write(f"Release diff {diff.from_semver or '(none)'} \u2192 {diff.to_semver}\n")
    if not changes:
        out.write("No governed changes.\n")
        return
    for category, items in diff.grouped().items():
        label = category.value.replace("_", " ").title() if hasattr(category, "value") else category
        out.write(f"\n[{label}]\n")
        for change in items:
            severity = (
                change.severity.value if hasattr(change.severity, "value") else change.severity
            )
            out.write(f"  ({severity}) {change.summary}\n")


def render_verdict(
    verdict: dict[str, Any],
    *,
    as_json: bool,
    stream: TextIO,
    local_unratified: bool = False,
) -> None:
    if as_json:
        payload = dict(verdict)
        if local_unratified:
            payload["local_unratified"] = True
        _write_json(payload, stream)
        return

    out = SafeWriter(stream)

    if local_unratified:
        out.write(
            "Notice: local offline verdict \u2014 not ratified by the platform. "
            "Re-run online when the API is reachable.\n\n"
        )

    allowed = verdict.get("allowed", False)
    headline = verdict.get("headline", "")
    out.write(f"{'ALLOWED' if allowed else 'BLOCKED'}: {headline}\n")
    material_count = verdict.get("material_count", 0)
    review_count = verdict.get("review_count", 0)
    impact = verdict.get("accreditation_impact", "none")
    out.write(
        f"Material: {material_count} \u00b7 Review: {review_count} "
        f"\u00b7 Accreditation impact: {impact}\n"
    )

    blocking = verdict.get("blocking_changes") or []
    if blocking:
        out.write("\nBlocking changes:\n")
        for change in blocking:
            if not isinstance(change, dict):
                out.write(f"  - {change}\n")
                continue
            out.write(f"  - {change.get('summary', change)}\n")
            # The rule id is what makes a block actionable: it is the handle for the
            # docs, for an override request, and for arguing the rule is wrong.
            rules = change.get("rules_fired") or []
            if rules:
                out.write(f"      rules: {', '.join(str(r) for r in rules)}\n")
            path = change.get("path")
            if path:
                out.write(f"      path:  {path}\n")

    # Advisory lines that merely restate a blocking change are noise; the blocking
    # block already printed the summary and its rule ids.
    advisory = [line for line in verdict.get("advisory") or [] if line]
    if blocking:
        seen = {
            f"{rule}: {change.get('summary', '')}"
            for change in blocking
            if isinstance(change, dict)
            for rule in change.get("rules_fired") or []
        }
        advisory = [line for line in advisory if line not in seen]
    if advisory:
        out.write("\n")
        for line in advisory:
            out.write(f"Advisory: {line}\n")


def render_pack_result(path: str, digest: str, *, as_json: bool, stream: TextIO) -> None:
    if as_json:
        _write_json({"path": path, "digest": digest}, stream)
        return
    out = SafeWriter(stream)
    out.write(f"Pack written to {path}\n")
    out.write(f"Digest: {digest}\n")


def render_error(message: str, *, as_json: bool, stream: TextIO) -> None:
    if as_json:
        _write_json({"error": message}, stream)
    else:
        SafeWriter(sys.stderr).write(f"Error: {message}\n")
