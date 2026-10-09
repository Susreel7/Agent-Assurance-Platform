# V1b — Grade B enforcement (hooks actually deny)

> Paste this whole file as the only prompt of a fresh session.
> Prerequisite: V1a simulation against real ledger data.

## Objective

On the destructive subset, the Claude Code / Cursor hook returns a veto the harness
honours (`PreToolUse` exit 2 / Cursor equivalent). Absence of the hook is an **alert**,
not silent grade E. Still honest: this is Grade B, bypassable by running another client.

## Read first

- `design/13-threat-model.md` bypass table, AP-1
- `design/12-strategic-thesis.md` §5 Grade B
- `design/05-model-gateway.md` Claude Code hooks
- M4 collector (observe-only)

## Scope

**In:**

1. Policy matching on facets for `shell.exec` (destructive binaries, production hosts),
   `net.http` (production audiences), `fs.write` if cheap.
2. Hook responds deny; ingest records `outcome=deny`, `enforcement_grade=B`.
3. Heartbeat / missing collector → finding + Home alert. `failClosed` for the **agent
   session** is a customer setting; default off for IDE, on for CI.
4. Never claim coverage for clients without hooks.
5. Policy response is signed or authenticated, has a short expiry, and includes policy
   version and reason code. A stale response is never reused as a fresh allow.
6. Start with an allow-list of tested destructive patterns and destinations. Unsupported
   syntax annotates or requires approval; it never becomes an accidental allow because a
   parser failed.

**Out:** MCP mediation (V1c), broker, model gateway, killing the user's other IDEs.

## Gate

- [ ] Integration: a fixture hook POST that would have been allow in M4 is now deny for
      `curl` to a listed production host.
- [ ] Missing heartbeat creates a finding within the documented SLA.
- [ ] UI copy says "vetoed by hook (grade B)", not "blocked at gateway".
- [ ] Simulate (V1a) still runs before a deny rule activates.
- [ ] Removing/disabling a hook changes coverage to E and creates an alert.
- [ ] Every denied ledger row names the exact policy version and reason.

## Do not

- Do not fail-closed the developer's entire laptop on collector outage unless the
  customer setting says so.
- Do not deny `fs.read` of source code. That is noise and a revolt.
