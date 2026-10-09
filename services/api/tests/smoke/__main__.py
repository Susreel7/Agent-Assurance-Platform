"""End-to-end smoke test against a running stack.

Walks the flow the product is sold on, in order, against a real API and a real Postgres:

    register an agent -> publish an accredited baseline -> propose a material change
    -> watch the CI gate refuse it -> record evidence -> seal and verify the chain

Every step asserts on the response rather than just checking the status code, because a
200 carrying the wrong verdict is the failure mode that matters here.

    python -m tests.smoke                       # against http://localhost:8000
    python -m tests.smoke --base-url http://api:8000
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from typing import Any

import httpx
from sqlalchemy import text

from app.config import get_settings
from app.db.session import admin_session

PASS = "ok  "
FAIL = "FAIL"

# Historical default from before tenant resolution checked that the organisation exists.
# Migration 0001 seeds `default` with a generated UUID, so this placeholder is never a row.
_LEGACY_PLACEHOLDER_ORG = "00000000-0000-0000-0000-000000000001"


class SmokeError(Exception):
    pass


class Smoke:
    def __init__(self, base_url: str, org_id: str) -> None:
        self.client = httpx.Client(
            base_url=base_url,
            timeout=30.0,
            headers={"X-Org-Id": org_id, "Content-Type": "application/json"},
        )
        self.org_id = org_id
        self.checks = 0

    def close(self) -> None:
        self.client.close()

    # -- plumbing ------------------------------------------------------
    def call(
        self, method: str, path: str, *, expect: int | tuple[int, ...] = 200, **kw: Any
    ) -> Any:
        response = self.client.request(method, path, **kw)
        wanted = (expect,) if isinstance(expect, int) else expect
        if response.status_code not in wanted:
            hint = ""
            if response.status_code == 403 and "unknown organisation" in response.text:
                hint = (
                    "\n  The X-Org-Id does not match any row in organizations. "
                    "Omit --org-id to use the migration-seeded tenant (slug "
                    f"{get_settings().default_org_slug!r}), or pass a real UUID."
                )
            raise SmokeError(
                f"{method} {path} returned {response.status_code}, wanted {wanted}\n"
                f"  {response.text[:600]}{hint}"
            )
        if response.status_code == 204 or not response.content:
            return None
        return response.json()

    def check(self, label: str, condition: bool, detail: str = "") -> None:
        self.checks += 1
        if not condition:
            raise SmokeError(f"{label}{(' — ' + detail) if detail else ''}")
        print(f"  {PASS} {label}" + (f"  [{detail}]" if detail else ""))

    def step(self, title: str) -> None:
        print(f"\n{title}")


def descriptor(urn: str, semver: str, **over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "aap_version": "0.1",
        "agent": {
            "urn": urn,
            "display_name": "Smoke Claims Triage",
            "version": semver,
            "lifecycle_state": "production",
        },
        "accountability": {
            "owning_team": "Claims Platform",
            "accountable_person": "person:smoke@test.example",
        },
        "runtime": {"framework": "langgraph", "deployment": "kubernetes", "autonomy": "supervised"},
        "models": [
            {
                "role": "primary",
                "provider": "anthropic",
                "family": "claude",
                "id": "claude-sonnet-4-5",
                "endpoint_region": "eu-west-1",
                "hosting": "cloud_managed",
                "data_retention": "zero_retention",
            }
        ],
        "data": {
            "classes": ["customer_pii"],
            "retention_days": 90,
            "residency": {
                "permitted_regions": ["eu-west-1"],
                "cross_border": "prohibited",
            },
        },
        "capabilities": [
            {"name": "classify_claim", "effect": "read", "human_approval": "none"},
        ],
        "tools": [{"name": "policy_lookup", "kind": "http", "effect": "read"}],
        "security": {"authentication": "oauth2_client_credentials", "secrets_source": "vault"},
    }
    base.update(over)
    return base


async def _lookup_default_org_id() -> str:
    slug = get_settings().default_org_slug
    async with admin_session() as session:
        row = await session.execute(
            text("SELECT id FROM organizations WHERE slug = :slug"), {"slug": slug}
        )
        found = row.scalar_one_or_none()
    if found is None:
        raise SystemExit(
            f"No organisation with slug {slug!r}. Run `alembic upgrade head` first, "
            "or pass --org-id with an existing organisations.id."
        )
    return str(found)


def resolve_smoke_org_id(explicit: str) -> str:
    """Map the CLI org id to a tenant that actually exists.

    The placeholder UUID predates ``assert_org_exists``; every real install gets its
    default row from migration 0001 with a server-generated id.
    """
    if explicit != _LEGACY_PLACEHOLDER_ORG:
        return explicit
    return asyncio.run(_lookup_default_org_id())


def run(base_url: str, org_id: str) -> int:
    s = Smoke(base_url, org_id)
    suffix = uuid.uuid4().hex[:8]
    urn = f"urn:aap:smoke:claims-{suffix}:eu"

    try:
        # ---------------------------------------------------------------
        s.step("0. The stack is up and talking to Postgres")
        ready = s.call("GET", "/readyz")
        s.check("readyz reports ok", ready["status"] == "ok")
        s.check("database reachable", ready["checks"]["database"] == "ok")
        s.check(
            "deployment mode is reported",
            bool(ready["deployment"]["mode"]),
            ready["deployment"]["mode"],
        )

        # ---------------------------------------------------------------
        s.step("1. Register an agent")
        agent = s.call(
            "POST",
            "/v1/agents",
            expect=(200, 201),
            json={
                "urn": urn,
                "display_name": "Smoke Claims Triage",
                "lifecycle_state": "production",
                "owning_team": "Claims Platform",
            },
        )
        agent_id = agent["id"]
        s.check("agent created with an id", bool(agent_id), agent_id)
        s.check("urn round-trips", agent["urn"] == urn)

        fetched = s.call("GET", f"/v1/agents/{agent_id}")
        s.check("agent is readable back", fetched["id"] == agent_id)

        # ---------------------------------------------------------------
        s.step("2. Publish the accredited baseline")
        v1 = s.call(
            "POST",
            f"/v1/agents/{agent_id}/versions",
            expect=(200, 201),
            json={
                "semver": "1.0.0",
                "descriptor": descriptor(urn, "1.0.0"),
                "published_by": "person:smoke@test.example",
            },
        )
        s.check("version 1.0.0 accepted", v1["semver"] == "1.0.0")
        s.check(
            "descriptor digest computed",
            str(v1.get("descriptor_digest", "")).startswith("sha256:"),
            str(v1.get("descriptor_digest"))[:24],
        )

        # ---------------------------------------------------------------
        s.step("3. An immaterial change is allowed through")
        benign = descriptor(urn, "1.0.1")
        benign["accountability"]["owning_team"] = "Claims Decisioning"
        verdict = s.call(
            "POST",
            "/v1/releases/preview",
            json={"before_descriptor": descriptor(urn, "1.0.0"), "after_descriptor": benign},
        )
        s.check("renaming a team is allowed", verdict["allowed"] is True)
        s.check("no material changes", verdict["material_count"] == 0)
        s.check(
            "accreditation unaffected",
            verdict["accreditation_impact"] == "none",
            verdict["accreditation_impact"],
        )

        # ---------------------------------------------------------------
        s.step("4. The CI gate refuses a material change")
        risky = descriptor(urn, "1.1.0")
        risky["runtime"]["autonomy"] = "autonomous"
        risky["data"]["residency"]["cross_border"] = "permitted_with_consent"
        risky["tools"].append(
            {"name": "settlement_writer", "kind": "http", "effect": "write", "reversible": False}
        )
        verdict = s.call(
            "POST",
            "/v1/releases/preview",
            json={"before_descriptor": descriptor(urn, "1.0.0"), "after_descriptor": risky},
        )
        s.check("gate blocks the release", verdict["allowed"] is False)
        s.check(
            "accreditation would be suspended",
            verdict["accreditation_impact"] == "suspends",
            verdict["accreditation_impact"],
        )

        fired = {r for c in verdict["blocking_changes"] for r in c.get("rules_fired", [])}
        s.check(
            "raising autonomy is named",
            "MAT-016-autonomy-raised" in fired,
            "MAT-016-autonomy-raised",
        )
        s.check(
            "loosening residency is named",
            "MAT-009-cross-border-loosened" in fired,
            "MAT-009-cross-border-loosened",
        )
        s.check(
            "the new write tool is named",
            "MAT-010-write-tool-added" in fired,
            "MAT-010-write-tool-added",
        )
        s.check(
            "every blocking change carries a rule id",
            all(c.get("rules_fired") for c in verdict["blocking_changes"]),
            f"{len(verdict['blocking_changes'])} blocking changes",
        )

        # ---------------------------------------------------------------
        s.step("5. Record evidence")
        events = [
            {
                "kind": "policy_decision",
                "occurred_at": "2026-09-13T10:00:00Z",
                "agent_id": agent_id,
                "actor": "service:collector",
                "action": "policy.evaluate",
                "outcome": "allow",
                "detected_by": "collector",
                "region": "eu-west-1",
                "decision": "allow",
                "reason_code": "within_envelope",
            },
            {
                "kind": "routing_decision",
                "occurred_at": "2026-09-13T10:00:01Z",
                "agent_id": agent_id,
                "actor": "service:collector",
                "action": "model.route",
                "outcome": "observed",
                "detected_by": "collector",
                "region": "eu-west-1",
            },
            {
                "kind": "oversight_record",
                "occurred_at": "2026-09-13T10:00:02Z",
                "agent_id": agent_id,
                "actor": "person:adjuster@test.example",
                "action": "human.approve",
                "outcome": "observed",
                "detected_by": "collector",
            },
        ]
        ingested = s.call("POST", "/v1/evidence", expect=(200, 201, 202), json={"events": events})
        s.check(
            "three events accepted",
            ingested.get("accepted") == 3,
            f"accepted={ingested.get('accepted')}",
        )

        listed = s.call("GET", "/v1/evidence", params={"agent_id": agent_id, "limit": 50})
        s.check("events are queryable", len(listed["items"]) >= 3, f"{len(listed['items'])} rows")
        s.check(
            "each event carries a content digest",
            all(str(e["content_digest"]).startswith("sha256:") for e in listed["items"]),
        )

        # ---------------------------------------------------------------
        s.step("6. Seal the chain and verify it")
        sealed = s.call("POST", "/v1/evidence/-/seal", expect=(200, 201, 202), json={})
        batch = sealed["batch"]
        s.check("a batch was sealed", bool(batch["id"]), f"seq={batch['seq']}")
        s.check(
            "the batch has a Merkle root",
            str(batch["merkle_root"]).startswith("sha256:"),
            str(batch["merkle_root"])[:24],
        )
        s.check(
            "tree size covers the events",
            int(batch["tree_size"]) >= 3,
            f"tree_size={batch['tree_size']}",
        )

        verification = s.call("GET", "/v1/evidence/-/verify")
        s.check("chain verifies", verification["is_valid"] is True)
        s.check(
            "the whole chain was walked",
            int(verification["batches_checked"]) >= 1,
            f"{verification['batches_checked']} batch(es)",
        )

        # ---------------------------------------------------------------
        # The claim a trust portal actually makes: this specific event is in the log,
        # provable against the published root without trusting the server that served
        # it. Verified here with the same Merkle code path the portal uses.
        s.step("7. Prove one event's inclusion")
        anchored = s.call("GET", "/v1/evidence", params={"agent_id": agent_id, "limit": 1})
        event_id = anchored["items"][0]["id"]

        proof = s.call("GET", f"/v1/evidence/{event_id}/proof")
        s.check("a proof was issued", bool(proof["batch_id"]), f"algorithm={proof['algorithm']}")
        s.check(
            "the proof names the event digest and the root",
            str(proof["content_digest"]).startswith("sha256:")
            and str(proof["merkle_root"]).startswith("sha256:"),
        )
        s.check("the server verified it", proof["is_verified"] is True)

        # Recomputed here from the published values alone — the event digest, its index,
        # the tree size and the sibling digests. This is the calculation an external
        # auditor reimplements, so if it only passes inside the service it is worthless.
        from app.domains.evidence import merkle

        s.check(
            "the audit path recomputes the published root, independently",
            merkle.verify_inclusion(
                leaf=merkle.leaf_hash(proof["content_digest"]),
                index=int(proof["leaf_index"]),
                tree_size=int(proof["tree_size"]),
                path=[merkle.parse_hash(h) for h in proof["audit_path"]],
                expected_root=merkle.parse_hash(proof["merkle_root"]),
            ),
            f"leaf {proof['leaf_index']} of {proof['tree_size']}",
        )

        s.check(
            "a tampered digest does not verify",
            not merkle.verify_inclusion(
                leaf=merkle.leaf_hash("sha256:" + "0" * 64),
                index=int(proof["leaf_index"]),
                tree_size=int(proof["tree_size"]),
                path=[merkle.parse_hash(h) for h in proof["audit_path"]],
                expected_root=merkle.parse_hash(proof["merkle_root"]),
            ),
        )

        print(f"\n{s.checks} checks passed")
        return 0

    except SmokeError as exc:
        print(f"\n  {FAIL} {exc}")
        print(f"\nfailed after {s.checks} passing checks")
        return 1
    finally:
        s.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tests.smoke")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument(
        "--org-id",
        default=_LEGACY_PLACEHOLDER_ORG,
        help=(
            "Tenant UUID for X-Org-Id. NOTE: no longer accepted by the API — this "
            "harness has not been migrated to console sessions and every request it "
            "makes returns 401. See the module docstring in tests/smoke/sweep.py. "
            "The historical placeholder is resolved to the migration-seeded organisation "
            f"(AAP_DEFAULT_ORG_SLUG, default {get_settings().default_org_slug!r})."
        ),
    )
    args = parser.parse_args(argv)
    return run(args.base_url, resolve_smoke_org_id(args.org_id))


if __name__ == "__main__":
    sys.exit(main())
