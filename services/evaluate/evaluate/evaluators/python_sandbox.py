"""Sandboxed Python function evaluator via subprocess."""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import textwrap
from typing import Any

from evaluate.config import Settings
from evaluate.errors import ValidationError


def _sanitized_env() -> dict[str, str]:
    allowed_prefixes = ("PATH", "SYSTEMROOT", "HOME", "USER", "LANG", "LC_", "TMP", "TEMP")
    env: dict[str, str] = {}
    for key, val in os.environ.items():
        if key in ("PYTHONNOUSERSITE", "PYTHONHASHSEED"):
            env[key] = val
        elif key.startswith(allowed_prefixes):
            env[key] = val
    env["PYTHONNOUSERSITE"] = "1"
    env["PYTHONHASHSEED"] = "0"
    for blocked in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "NO_PROXY",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
    ):
        env.pop(blocked, None)
    return env


def _linux_preexec(settings: Settings, workdir: str) -> Any:
    import resource

    def _apply() -> None:
        os.chdir(workdir)
        mem_bytes = settings.python_eval_memory_mb * 1024 * 1024
        resource.setrlimit(
            resource.RLIMIT_CPU,
            (
                int(settings.python_eval_timeout_seconds),
                int(settings.python_eval_timeout_seconds) + 1,
            ),
        )
        resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))
        resource.setrlimit(resource.RLIMIT_NOFILE, (32, 32))

    return _apply


def run_python_evaluator(
    settings: Settings,
    *,
    source: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    if settings.python_sandbox_mode == "production" and platform.system().lower() != "linux":
        raise ValidationError(
            "production python sandbox requires Linux resource isolation; refused on this platform"
        )
    if "import socket" in source or "urllib" in source or "httpx" in source or "requests" in source:
        raise ValidationError("network imports are not allowed in python_function evaluators")
    wrapped = textwrap.dedent(
        f"""
        import json
        payload = json.loads({json.dumps(json.dumps(payload))})
        def evaluate(payload):
            {textwrap.indent(source.strip(), "    ")}
        result = evaluate(payload)
        if not isinstance(result, dict):
            raise ValueError("evaluate must return a dict")
        print(json.dumps(result))
        """
    )
    env = _sanitized_env()
    script_path = ""
    workdir = tempfile.mkdtemp(prefix="evaluate-sandbox-")
    completed: subprocess.CompletedProcess[bytes] | None = None
    try:
        script_path = os.path.join(workdir, "evaluator.py")
        with open(script_path, "w", encoding="utf-8") as fh:
            fh.write(wrapped)
        cmd = [sys.executable, "-I", script_path]
        preexec: Any = None
        if settings.python_sandbox_mode == "production" and platform.system().lower() == "linux":
            preexec = _linux_preexec(settings, workdir)
        completed = subprocess.run(
            cmd,
            capture_output=True,
            timeout=settings.python_eval_timeout_seconds,
            check=False,
            env=env,
            cwd=workdir,
            preexec_fn=preexec,
        )
    except subprocess.TimeoutExpired as exc:
        raise ValidationError("python evaluator timed out") from exc
    finally:
        try:
            shutil.rmtree(workdir, ignore_errors=True)
        except OSError:
            pass
    if completed is None:
        raise ValidationError("python evaluator failed to start")
    if completed.returncode != 0:
        err = (completed.stderr or completed.stdout or b"evaluator failed")[:512]
        raise ValidationError(err.decode("utf-8", errors="replace"))
    lines = completed.stdout.decode("utf-8", errors="replace").strip().splitlines()
    try:
        parsed = json.loads(lines[-1] if lines else "{}")
    except json.JSONDecodeError as exc:
        raise ValidationError("python evaluator returned invalid JSON") from exc
    if not isinstance(parsed, dict):
        raise ValidationError("python evaluator must return object")
    return parsed
