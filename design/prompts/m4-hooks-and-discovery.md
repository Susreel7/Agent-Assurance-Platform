# M4 — Hook collector, shadow agents, credential exposure

> Paste this whole file as the only prompt of a fresh session.
> Prerequisite: M3 ingest. Read-only: hooks **observe**, they do not deny. Deny is V1b.

## Objective

Instrument the path the reference incident actually took: `fs.read` → `shell.exec` →
`net.http`. Plus two discovery lists that create urgency: agents we did not register, and
credential-shaped files an agent read.

## Read first

- `design/13-threat-model.md` AP-1, bypass table, session taint §7
- `design/15-capability-governance.md` §3 kinds `shell.exec` `net.http` `fs.read`
- `design/05-model-gateway.md` Claude Code hooks `[B-31]`, Cursor hooks `[B-33]`
- M3 ingest contract

## Scope

**In:**

1. **Collectors (read-only):**
   - Claude Code `PreToolUse` / `PostToolUse` mapper: `Bash`, `Read`, anything that is
     HTTP. Exit 0 always. Record `enforcement_grade=B` (we *could* have vetoed; we did
     not). Set `failClosed` documentation for V1; do not enable deny.
   - Cursor `beforeShellExecution` / file-read hooks analogously.
   - Ship as a small installable config snippet (managed settings / hooks.json) **plus**
     a local collector if the hook cannot POST directly. Customer endpoint team deploys
     it (D-F). We generate; we do not build an MDM.
2. **Session taint (record only):** classify credential-shaped paths locally
   (`.env`, `*.pem`, `credentials`, `.ssh`, `.aws`, `id_rsa`, `token`) set
   `agent_sessions.taint` to `tainted_with_secrets`. Send only path class/prefix plus a
   salted digest, never the full absolute path. Do not block.
3. **Shadow agents:** instances or harness processes that emitted evidence without a
   registered `agent_id`. List at `GET /v1/discovery/agents`. UI placeholder from F2
   becomes a real table.
4. **Credential exposure:** `GET /v1/discovery/exposures` — sessions where a
   credential-shaped `fs.read` was followed by `net.http` or `shell.exec` with `curl` /
   `Invoke-WebRequest` within a window (default 15 minutes). This is the PocketOS-shaped
   query. It is **detection**, labelled as such.
5. Collector identity and health: every event carries collector ID/version and monotonic
   sequence. Installation documents how to remove it. Missing heartbeat lowers estimated
   coverage and creates a discovery finding; it does not silently preserve Grade B.

**Out:** `exit 2` denies, MCP gateway, broker, Cedar, DLP regex on file contents (you
never have the contents — path facets only).

## UI

- `/discovery` — two panels: Unregistered agents · Credential-shaped reads.
- Link a row into Observe/session detail.
- Empty states explain what install is missing.
- Every count has a grade (these findings are D/B evidence, not A prevention). Copy must
  not say "blocked".

## Invariants

| Name | Assertion |
|---|---|
| `inv_hooks_never_deny` | Collector returns success to the harness even when we record risk |
| `inv_taint_from_cred_path` | Read of `/.env` marks session tainted_with_secrets |
| `inv_exposure_query` | Read `.env` then `curl` within window appears on exposures |
| `inv_shadow_agent` | Event with unknown agent_id appears on discovery/agents |
| `inv_no_file_body` | Path class/digest stored; no file bytes or full absolute path |
| `inv_collector_gap_visible` | Missing heartbeat reduces the coverage denominator and produces a finding |

## Gate

- [ ] Documented hook snippet for Claude Code and Cursor in-repo (`collectors/` or
      `design/collectors/` — pick one and use it).
- [ ] One integration test per exposure query.
- [ ] Discovery screens: four states via `DataBoundary`.
- [ ] `PROJECT_STATE.md` updated.

## Do not

- Do not enable deny "just for dangerous curl". That is V1b and needs policy simulation.
- Do not scan disk yourself. You only see paths the harness reported.
