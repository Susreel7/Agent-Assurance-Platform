import pytest

from evaluate.config import Settings
from evaluate.errors import ValidationError
from evaluate.evaluators.deterministic import eval_exact_match, eval_regex
from evaluate.evaluators.python_sandbox import run_python_evaluator


def test_exact_match() -> None:
    out = eval_exact_match({}, output="hello", reference="hello")
    assert out["passed"] is True


def test_regex_evaluator() -> None:
    out = eval_regex({"pattern": r"\d+"}, output="abc 42")
    assert out["passed"] is True


def test_python_sandbox_blocks_network_import() -> None:
    settings = Settings(python_eval_timeout_seconds=60.0)
    with pytest.raises(ValidationError):
        run_python_evaluator(settings, source="import urllib.request", payload={})


def test_python_sandbox_runs() -> None:
    settings = Settings(python_eval_timeout_seconds=60.0)
    out = run_python_evaluator(
        settings,
        source='return {"score": 1.0, "passed": True}',
        payload={"output": "x"},
    )
    assert out["passed"] is True
