"""CrewAI task/step hooks."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from aap_trace.integrations._optional import require_package
from aap_trace.spans import agent_span, tool_span

require_package("crewai", "crewai")


def wrap_crew_task(task_name: str, fn: Callable[..., Any]) -> Callable[..., Any]:
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        with agent_span(name=task_name, **{"crewai.task": task_name}):
            return fn(*args, **kwargs)

    return wrapper


def wrap_crew_tool(tool_name: str, fn: Callable[..., Any]) -> Callable[..., Any]:
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        with tool_span(name=tool_name, **{"crewai.tool": tool_name}):
            return fn(*args, **kwargs)

    return wrapper
