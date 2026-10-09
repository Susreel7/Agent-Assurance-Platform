"""Unit tests for attestation check aggregation."""

from __future__ import annotations

from app.domains.attestation.schemas import AttestationResult
from app.domains.attestation.service import aggregate_attestation_result, evaluate_check


def test_all_pass_yields_pass() -> None:
    checks = [
        evaluate_check("chain_integrity", True),
        evaluate_check("accreditation_drift", True),
    ]
    assert aggregate_attestation_result(checks) is AttestationResult.PASS


def test_one_fail_yields_fail() -> None:
    checks = [
        evaluate_check("chain_integrity", True),
        evaluate_check("open_critical_findings", False),
    ]
    assert aggregate_attestation_result(checks) is AttestationResult.FAIL


def test_degraded_without_fail() -> None:
    checks = [
        evaluate_check("chain_integrity", True, degraded=True),
        evaluate_check("control_coverage", True),
    ]
    assert aggregate_attestation_result(checks) is AttestationResult.DEGRADED
