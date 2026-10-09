"""Probe execution target — synthetic rollout until machine auth exists (Q-012).

Live HTTP against a customer agent endpoint is intentionally unimplemented: there is no
agreed credential the collector can present. The interface stays stable so a future
adapter plugs in without rewriting judgement.
"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domains.assurance.probe_oracle import ProbeObservation, StepObservation


class ProbeRolloutRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    probe_id: str = Field(max_length=64)
    agent_id: UUID
    agent_version_id: UUID
    fixture_profile: str = Field(default="compliant", max_length=64)
    attempt: int = Field(default=1, ge=1, le=3)


class ProbeRolloutReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    probe_id: str
    valid: bool
    observation: ProbeObservation
    run_id: UUID | None = None


class AgentProbeTarget(Protocol):
    async def execute_rollout(self, request: ProbeRolloutRequest) -> ProbeRolloutReceipt:
        """Run one probe attempt and return observable effects only."""


_PROFILES: dict[str, ProbeObservation] = {
    "compliant_refuse": ProbeObservation(
        run_outcome="refused",
        steps=[StepObservation(kind="guardrail", name="policy"), StepObservation(kind="llm")],
        agent_acknowledged_constraint=False,
    ),
    "policy_deny": ProbeObservation(
        run_outcome="failed",
        steps=[StepObservation(kind="mcp_tool", name="stripe", denied=True)],
        policy_outcomes=["deny"],
        agent_acknowledged_constraint=True,
    ),
    "exfil_blocked": ProbeObservation(
        run_outcome="refused",
        steps=[StepObservation(kind="guardrail"), StepObservation(kind="llm")],
        capabilities_invoked=[],
        agent_acknowledged_constraint=False,
    ),
    "violate_while_acknowledging": ProbeObservation(
        run_outcome="succeeded",
        steps=[
            StepObservation(kind="llm"),
            StepObservation(kind="mcp_tool", name="undeclared_export", denied=False),
        ],
        capabilities_invoked=["undeclared_export"],
        agent_acknowledged_constraint=True,
    ),
    "residency_reroute": ProbeObservation(
        run_outcome="succeeded",
        policy_outcomes=["reroute"],
        steps=[StepObservation(kind="llm")],
    ),
    "multi_turn_drift": ProbeObservation(
        run_outcome="succeeded",
        steps=[StepObservation(kind="llm"), StepObservation(kind="mcp_tool", name="write_db")],
        capabilities_invoked=["write_db"],
        agent_acknowledged_constraint=True,
    ),
}


class SyntheticProbeTarget:
    """Deterministic stand-in for staging execution — fixtures are synthetic only."""

    async def execute_rollout(self, request: ProbeRolloutRequest) -> ProbeRolloutReceipt:
        obs = _PROFILES.get(request.fixture_profile, _PROFILES["compliant_refuse"])
        return ProbeRolloutReceipt(
            probe_id=request.probe_id,
            valid=True,
            observation=obs.model_copy(deep=True),
            run_id=None,
        )


def default_probe_target() -> AgentProbeTarget:
    return SyntheticProbeTarget()
