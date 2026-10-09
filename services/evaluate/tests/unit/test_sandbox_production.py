import platform

import pytest

from evaluate.config import Settings
from evaluate.errors import ValidationError
from evaluate.evaluators.python_sandbox import run_python_evaluator


def test_production_sandbox_refused_off_linux() -> None:
    if platform.system().lower() == "linux":
        pytest.skip("linux hosts use resource limits instead")
    settings = Settings(python_sandbox_mode="production", python_eval_timeout_seconds=60.0)
    with pytest.raises(ValidationError, match="refused"):
        run_python_evaluator(settings, source='return {"score": 1.0}', payload={})
