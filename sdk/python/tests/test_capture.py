from __future__ import annotations

from aap_trace.capture import CaptureMode, apply_capture, digest_value, redact_text


def test_digest_mode() -> None:
    out = apply_capture(CaptureMode.DIGEST, "gen_ai.input.messages", [{"content": "secret"}])
    assert out is not None
    assert "gen_ai.input.messages.digest" in out
    assert "secret" not in str(out)


def test_redacted_mode() -> None:
    text = "Contact me at user@example.com please"
    out = apply_capture(CaptureMode.REDACTED, "gen_ai.input.messages", text)
    assert out is not None
    assert "[email]" in out["gen_ai.input.messages.preview"]
    assert "user@example.com" not in out["gen_ai.input.messages.preview"]


def test_full_includes_digest() -> None:
    out = apply_capture(CaptureMode.FULL, "gen_ai.input.messages", "hello")
    assert out is not None
    assert out["gen_ai.input.messages"] == "hello"
    assert out["gen_ai.input.messages.digest"] == digest_value("hello")


def test_none_omits_content() -> None:
    assert apply_capture(CaptureMode.NONE, "gen_ai.input.messages", "x") is None


def test_redact_helper() -> None:
    assert "555" not in redact_text("call 555-123-4567")
