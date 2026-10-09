from __future__ import annotations

from collector.capture import CONTENT_ATTR_KEYS, apply_capture, digest_value, redact_text
from collector.config import CaptureMode, Settings


def test_content_allowlist_is_strict() -> None:
    assert "gen_ai.input.messages" in CONTENT_ATTR_KEYS
    assert "gen_ai.operation.name" not in CONTENT_ATTR_KEYS


def test_digest_mode_no_leakage() -> None:
    settings = Settings()
    out = apply_capture(
        CaptureMode.DIGEST, "gen_ai.input.messages", [{"content": "secret"}], settings
    )
    assert out is not None
    assert "gen_ai.input.messages.digest" in out
    assert "secret" not in str(out)


def test_redacted_custom_regex() -> None:
    settings = Settings(
        redaction_regex_rules=[{"pattern": "SECRET-\\d+", "replacement": "[token]"}]
    )
    preview = redact_text("value SECRET-999 end", settings)
    assert "[token]" in preview
    assert "SECRET-999" not in preview


def test_full_preserves_with_digest() -> None:
    settings = Settings()
    out = apply_capture(CaptureMode.FULL, "gen_ai.input.messages", "hello", settings)
    assert out is not None
    assert out["gen_ai.input.messages"] == "hello"
    assert out["gen_ai.input.messages.digest"] == digest_value("hello")


def test_none_strips() -> None:
    assert apply_capture(CaptureMode.NONE, "gen_ai.input.messages", "x", Settings()) is None
