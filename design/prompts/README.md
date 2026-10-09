# Development prompts — canonical execution sequence

This directory contains one **active** program and one retained historical program.

Paste exactly one active prompt into a fresh session. Never paste multiple prompts together.
Each prompt owns one vertical slice and must update `PROJECT_STATE.md` before it finishes.

## Decisions fixed for this sequence

The research recommendations are now the implementation baseline:

- **MVP posture:** read-only action ledger. Blocking begins only after policy simulation.
- **First integrations:** Claude Code first, then Cursor before the MVP demo. Copilot is a
  Grade-D/E adapter and must not block the demo.
- **Storage:** Postgres partitions for the MVP. Existing Observe/ClickHouse remains a
  separate service and is linked, not rebuilt.
- **Tenant key:** keep `organizations` / `org_id`. Do not introduce a second `accounts`
  tenant root during the MVP.
- **Real migration head:** `0022_auth_sessions_and_providers`. New control-plane revisions
  start at `0023`.
- **Vocabulary:** human browser sessions are `auth_sessions`; agent context windows are
  `agent_sessions`; ledger rows are `agent_actions`.

## Active sequence

| Order | Prompt | Outcome | Hard gate |
|---:|---|---|---|
| 0 | [f0-console-contract.md](f0-console-contract.md) | Trustworthy login, cookie session, bootstrap and errors | Browser never exchanges tokens; every error has a reason |
| 1 | [f1-ledger-schema.md](f1-ledger-schema.md) | Additive identity-chain and ledger schema from real head `0022` | Fresh upgrade, RLS, append-only and privacy invariants pass |
| 2 | [f2-ui-structure.md](f2-ui-structure.md) | One shell, ledger-first information architecture, reuse existing UI | Observe works without a project and nav comes from bootstrap |
| 3 | [m1-identity-chain.md](m1-identity-chain.md) | Human → agent → version → instance → session → task APIs | Every instance resolves to a human root |
| 4 | [m3-action-ingest.md](m3-action-ingest.md) | Claude Code + Cursor map into `aap.action.v1` | Both clients query as content-free graded actions |
| 5 | [m4-hooks-and-discovery.md](m4-hooks-and-discovery.md) | Read-only hook collection, shadow agents and credential exposure | AP-1-shaped activity is detected without blocking |
| 6 | [m2-visibility.md](m2-visibility.md) | Org-unit visibility and server-driven navigation | Sibling units cannot see each other's agents/actions |
| 7 | [m5-ledger-console.md](m5-ledger-console.md) | Investigation UI and coverage denominator | The one-sentence MVP reconstruction gate passes |
| 8 | [v1-policy.md](v1-policy.md) | Cedar authoring and historical simulation | No policy activates without simulation |
| 9 | [v1-enforcement.md](v1-enforcement.md) | Grade-B hook veto on a narrow destructive subset | Real veto, missing-hook alarm, no Grade-A claim |
| 10 | [v1-mcp-and-broker.md](v1-mcp-and-broker.md) | MCP generalized as capability + scoped credential leases | Pinned MCP call and ≤15-minute broker lease |
| 11 | [p-packaging.md](p-packaging.md) | Customer-VPC and self-hosted packaging | Signed rollback-safe bundles; content-free export |
| Later | [later-optional-modules.md](later-optional-modules.md) | Explicitly optional V2/platform modules | Owner names one module after V1 evidence |

Dependencies:

```text
F0 ───────────────┐
F1 → M1 → M3 → M4 ├→ M2 → M5 → V1a → V1b
 └→ F2 ────────────┘             └──→ V1c → Packaging
```

F1 and F2 may run in parallel only if F2 adds no product tables. M3 is the critical
commercial validation: if Claude Code and Cursor cannot map into one content-free action
contract, stop and revise the capability abstraction.

## Attach these diagrams with each prompt

Use the SVG preview for chat/context and keep the `.excalidraw` as the editable source.

| Prompt | Primary diagram(s) |
|---|---|
| F0 | `02-identity-and-onboarding`, `10-dashboards-and-access` |
| F1 | `16-mvp-schema-and-ui`, `14-agent-identity-chain` |
| F2 | `16-mvp-schema-and-ui`, `10-dashboards-and-access` |
| M1 | `14-agent-identity-chain` |
| M3 | `13-capability-model`, `15-threat-paths` |
| M4 | `15-threat-paths`, `12-enforcement-grades` |
| M2 | `03-hierarchy-and-visibility`, `16-mvp-schema-and-ui` |
| M5 | `16-mvp-schema-and-ui`, `12-enforcement-grades` |
| V1a/V1b | `13-capability-model`, `12-enforcement-grades` |
| V1c | `07-mcp-governance`, `13-capability-model`, `14-agent-identity-chain` |
| Packaging | `01-deployment-topology`, `11-phase-roadmap` |

All previews are under `design/diagrams/preview/`.

## Historical prompts — do not execute

`phase-00-*` through `phase-09-*` are retained only to preserve the superseded architecture
decision. Each has a non-executable warning. They would recreate existing gateway, MCP and
Observe systems, use conflicting migration IDs, and contradict decisions D-066–D-072.

## Rules that apply to every phase

1. Read `AGENTS.md` and `PROJECT_STATE.md` first, then the prompt's named design documents,
   then inspect the current code. Design is intent; current code determines the safe
   migration path. Report discrepancies instead of silently resolving them.
2. Schema → service → API/contract → UI → tests, in that order, unless the prompt is
   explicitly schema-only or UI-only.
3. No dummy data, ever. Fixtures stay behind the `demo` profile.
4. Every earlier gate must still pass at the end. If one regressed, fixing it is the first job.
5. Update `PROJECT_STATE.md`: module status, migrations with their real status, a three-line
   session log, the next slice. `OK` means written, reviewed and tested.
6. Invariant tests are added and never removed.
7. A slice that finds the design wrong stops and says so, with a decision ID. It does not
   improvise a different architecture.
8. Never edit an applied migration. Confirm `alembic heads` before assigning a revision.
9. Reuse existing tables and screens named by the prompt. A parallel agent registry,
   tenant root, auth session, action UI or MCP registry is a defect.
10. Evidence stores digests, bounded facets, classifications and decisions—never prompts,
    completions, file bodies or raw tool arguments.
