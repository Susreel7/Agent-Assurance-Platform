"""Router snapshot compilation unit tests."""

from __future__ import annotations

from uuid import uuid4

from app.domains.model_routing.snapshot_compile import _canonical_json, _load_schema_validator


def test_canonical_json_is_deterministic() -> None:
    first = _canonical_json({"b": 1, "a": {"d": 2, "c": 3}})
    second = _canonical_json({"a": {"c": 3, "d": 2}, "b": 1})
    assert first == second


def test_schema_validator_rejects_empty_route_deployments() -> None:
    dep_id = str(uuid4())
    validator = _load_schema_validator()
    doc = {
        "schema_revision": 1,
        "snapshot_id": str(uuid4()),
        "organization_id": str(uuid4()),
        "project_id": str(uuid4()),
        "issued_at": "2026-01-01T00:00:00Z",
        "expires_at": "2026-01-02T00:00:00Z",
        "rules_digest": "sha256:" + "a" * 64,
        "deployments": [
            {
                "id": dep_id,
                "provider": "openai_compatible",
                "model": "gpt-test",
                "endpoint": "https://example.com/v1",
                "credential_ref": "vault:ref",
                "region": "us-east-1",
                "jurisdiction": "US",
                "capabilities": ["chat"],
                "priority": 1,
                "weight": 1,
            }
        ],
        "routes": [
            {
                "id": str(uuid4()),
                "agent_id": str(uuid4()),
                "environment": "dev",
                "alias": "gpt-test",
                "strategy": "priority",
                "deployment_ids": [dep_id],
                "enforcement": "blocking",
            }
        ],
        # Non-empty because the schema requires it and `compile_snapshot` honours that:
        # `runtime_ops` raises `RouterCompileError("no active router workload
        # credentials")` rather than emitting a snapshot nothing can present a key for.
        # A baseline document that the compiler could never produce would make the
        # rejection assertion below prove nothing.
        "workload_bindings": [
            {
                "generation_id": str(uuid4()),
                "secret_hash": "sha256:" + "b" * 64,
                "organization_id": str(uuid4()),
                "project_id": str(uuid4()),
                "environment": "dev",
                "modules": ["router"],
                "scopes": ["router:invoke"],
                "allowed_model_patterns": ["gpt-*"],
            }
        ],
    }
    assert validator.is_valid(doc) is True
    doc["routes"][0]["deployment_ids"] = []
    assert validator.is_valid(doc) is False
