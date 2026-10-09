"""Output must survive a console that cannot encode it.

The gate's job is to return a verdict and an exit code. A cp1252 Windows runner made it
raise UnicodeEncodeError instead, which reads as a broken tool and gets the gate deleted
from the pipeline. These tests pin the degradation.
"""

from __future__ import annotations

import io
from typing import Any

from aap_cli.render import SafeWriter, render_verdict


class Cp1252Stream(io.StringIO):
    """A StringIO that reports a legacy Windows console encoding.

    Writing is still permitted so a regression shows up as mangled text in an assertion
    rather than an exception raised by the test double itself.
    """

    encoding = "cp1252"


class Utf8Stream(io.StringIO):
    encoding = "utf-8"


def _verdict(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "allowed": False,
        # The separator here comes from the API, not from render.py, which is why
        # auditing our own format strings was never sufficient.
        "headline": "12 changes \u00b7 9 material \u00b7 2 needing review",
        "material_count": 9,
        "review_count": 2,
        "accreditation_impact": "suspends",
        "blocking_changes": [
            {
                "summary": "Autonomy level changed from supervised to autonomous.",
                "path": "runtime.autonomy",
                "rules_fired": ["MAT-016-autonomy-raised"],
            }
        ],
        "advisory": [],
    }
    base.update(over)
    return base


def test_a_legacy_console_gets_ascii_instead_of_an_exception() -> None:
    stream = Cp1252Stream()
    render_verdict(_verdict(), as_json=False, stream=stream)
    text = stream.getvalue()

    assert "\u00b7" not in text
    assert "\u2014" not in text
    # The verdict itself must survive the substitution intact.
    assert "BLOCKED" in text
    assert "9 material" in text
    assert "MAT-016-autonomy-raised" in text
    text.encode("cp1252")  # would raise if anything unencodable slipped through


def test_a_utf8_console_keeps_the_real_glyphs() -> None:
    stream = Utf8Stream()
    render_verdict(_verdict(), as_json=False, stream=stream, local_unratified=True)
    text = stream.getvalue()

    assert "\u00b7" in text
    assert "\u2014" in text


def test_unmapped_characters_degrade_rather_than_raise() -> None:
    """A fallback table cannot enumerate every glyph an API might return."""
    stream = Cp1252Stream()
    render_verdict(
        _verdict(headline="cjk \u4e2d\u6587 and emoji \U0001f600"), as_json=False, stream=stream
    )
    text = stream.getvalue()

    assert "BLOCKED" in text
    text.encode("cp1252")


def test_an_unknown_encoding_name_is_treated_as_opaque() -> None:
    class WeirdStream(io.StringIO):
        encoding = "not-a-real-codec"

    stream = WeirdStream()
    SafeWriter(stream).write("arrow \u2192\n")
    assert "\u2192" in stream.getvalue()


def test_an_in_memory_sink_needs_no_degradation() -> None:
    stream = io.StringIO()  # no .encoding attribute
    SafeWriter(stream).write("arrow \u2192\n")
    assert "\u2192" in stream.getvalue()


def test_rule_ids_and_paths_reach_the_engineer() -> None:
    """An exit code says somebody is blocked. A rule id says what to do about it."""
    stream = Utf8Stream()
    render_verdict(_verdict(), as_json=False, stream=stream)
    text = stream.getvalue()

    assert "rules: MAT-016-autonomy-raised" in text
    assert "path:  runtime.autonomy" in text


def test_advisory_lines_do_not_restate_blocking_changes() -> None:
    """The blocking block already printed the summary and the rule id."""
    stream = Utf8Stream()
    render_verdict(
        _verdict(
            advisory=[
                "MAT-016-autonomy-raised: Autonomy level changed from supervised to autonomous.",
                "Reviewers: the platform accreditation board.",
            ]
        ),
        as_json=False,
        stream=stream,
    )
    text = stream.getvalue()

    assert text.count("MAT-016-autonomy-raised") == 1
    assert "Reviewers: the platform accreditation board." in text


def test_json_output_stays_encodable_on_a_legacy_console() -> None:
    """`--json` is what a pipeline parses; it must never be the thing that breaks."""
    stream = Cp1252Stream()
    render_verdict(_verdict(headline="cjk \u4e2d\u6587"), as_json=True, stream=stream)
    text = stream.getvalue()

    text.encode("cp1252")
    import json

    assert json.loads(text)["material_count"] == 9
