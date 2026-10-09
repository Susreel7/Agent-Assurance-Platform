"""Registry pure-function tests — descriptor validation, digest stability, drift."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from app.domains.registry.schemas import DriftStatus
from app.domains.registry.service import (
    InvalidDescriptorError,
    canonical_descriptor_digest,
    compute_drift_status,
    validate_aap_descriptor,
)


def _minimal_descriptor(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "aap_version": "0.1",
        "agent": {
            "urn": "urn:aap:acme:insurance:claims-processor",
            "version": "1.0.0",
        },
        "accountability": {
            "owning_team": "Insurance Automation",
            "accountable_person": "person:j.doe@acme.com",
        },
        "runtime": {"framework": "langgraph"},
        "future_field": {"ignored": True},
    }
    base.update(overrides)
    return base


def test_validate_accepts_forward_compatible_siblings() -> None:
    validate_aap_descriptor(_minimal_descriptor())


def test_validate_rejects_bad_urn() -> None:
    desc = _minimal_descriptor()
    desc["agent"]["urn"] = "urn:wrong:shape"
    with pytest.raises(InvalidDescriptorError, match=r"agent\.urn"):
        validate_aap_descriptor(desc)


def test_validate_rejects_wrong_aap_version() -> None:
    with pytest.raises(InvalidDescriptorError, match="aap_version"):
        validate_aap_descriptor(_minimal_descriptor(aap_version="0.2"))


def test_digest_is_stable_and_canonical() -> None:
    a = _minimal_descriptor()
    d1 = canonical_descriptor_digest(a)
    shuffled = {
        "runtime": a["runtime"],
        "agent": a["agent"],
        "aap_version": a["aap_version"],
        "accountability": a["accountability"],
        "future_field": a["future_field"],
    }
    d2 = canonical_descriptor_digest(shuffled)
    assert d1 == d2
    assert d1.startswith("sha256:")
    assert len(d1) == len("sha256:") + 64


def test_drift_status_cases() -> None:
    vid = uuid4()
    other = uuid4()
    assert compute_drift_status(vid, vid) is DriftStatus.ALIGNED
    assert compute_drift_status(vid, other) is DriftStatus.DRIFTED
    assert compute_drift_status(None, vid) is DriftStatus.UNKNOWN
