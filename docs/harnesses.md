# Tracked harnesses

The ledger stores a closed vocabulary for the client that produced an action. The same list is the check constraint on `agent_instances.harness` and on `agent_actions.source_harness`. Two copies of one fact is how a fleet view and a ledger view start to disagree, so a test fails if they drift.

A client that is not in this list is `custom` or `unknown`. Unknown is not a silent success: an ungraded row is treated as grade E.

The marks below are original drawings for this repository. They identify the client. They are not the vendor's logo.

## Cursor

![Cursor](assets/harnesses/cursor.svg)

`cursor`. IDE agent sessions, editor hooks, and MCP calls made from Cursor. The console's home page and the Discovery page render this mark next to the others.

## Claude Code

![Claude Code](assets/harnesses/claude.svg)

`claude_code`. Claude Code CLI sessions and the tools those sessions invoke.

## GitHub Copilot

![GitHub Copilot](assets/harnesses/copilot.svg)

`copilot`. Copilot agent activity in an editor or on a pull request.

## OpenAI Codex

![OpenAI Codex](assets/harnesses/codex.svg)

`codex`. Codex CLI and cloud-agent runs.

## Gemini CLI

![Gemini CLI](assets/harnesses/gemini.svg)

`gemini_cli`. Gemini CLI sessions.

## LangGraph

![LangGraph](assets/harnesses/langgraph.svg)

`langgraph`. Graph runs reported through the tracing SDK. See `docs/tracing/langgraph.md` and `sdk/python`.

## SDK

![SDK](assets/harnesses/sdk.svg)

`sdk`. A workload using `sdk/python` or `sdk/typescript` directly, rather than one of the clients above.

## CI

![CI](assets/harnesses/ci.svg)

`ci`. An agent that runs inside a pipeline, with no interactive editor.

## What is deliberately not a harness

`custom` and `unknown` are stored values, not products. Adding another product means a migration that extends both check constraints and the `Harness` enum in `services/api/app/domains/agent_actions/schemas.py`, plus the console marks in `services/web/src/components/HarnessMark.tsx`. The unit test that compares the enum to the SQL is the thing that keeps that honest.
