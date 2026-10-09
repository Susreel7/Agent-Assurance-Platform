# Worked example: a claims triage agent

Two AAP 0.1 descriptors for the same agent, and the release the gate refuses.

| File | What it is |
|---|---|
| `v1.0.0.aap.yaml` | The accredited baseline. Supervised, EU-only, no write tools. |
| `v1.1.0.aap.yaml` | A proposed change that would need re-accreditation. |

Run these from this directory. `python -m aap_cli` works anywhere the package is
importable; `aap` is the same thing when the console script is on PATH.

## 1. Is the descriptor well formed?

```
python -m aap_cli validate v1.0.0.aap.yaml
```

Exit `0` and `Descriptor is valid.` Every enum here comes from the published schema, so
these files are a safe starting point for a real agent — but run `validate` before you
run anything else, because the error messages are the fastest way to learn the
vocabulary.

## 2. What changed between the two versions?

```
python -m aap_cli diff v1.0.0.aap.yaml v1.1.0.aap.yaml
```

Twelve governed changes across nine categories. This is a description, not a judgement:
the differ says *what* changed and says nothing about whether it matters.

## 3. Would the gate let it through?

```
python -m aap_cli preview v1.0.0.aap.yaml v1.1.0.aap.yaml --offline
```

```
BLOCKED: 12 changes | 9 material | 2 needing review - data residency, human oversight, guardrails
Material: 9 | Review: 2 | Accreditation impact: suspends

Blocking changes:
  - Autonomy level changed from supervised to autonomous.
      rules: MAT-016-autonomy-raised
      path:  runtime.autonomy
  ...
```

Exit code `2`. Every blocking change names the rule that produced it, because an exit
code only tells an engineer they are blocked — the rule id is what they read the docs
for, quote in an override request, or cite when they think the rule is wrong.

### Exit codes

| Code | Meaning | In CI |
|---|---|---|
| `0` | Allowed | Proceed. |
| `2` | Blocked, or needs review | Stop. A human decision is required. |
| `1` | The gate could not run | A bad path, an unreachable API, a malformed file. Not a verdict. |

`1` is kept distinct from `2` on purpose: a broken gate and a blocked release call for
different responses, and conflating them teaches people to ignore both.

## 4. In a pipeline

```
python -m aap_cli preview "$BASELINE" aap.yaml --json > verdict.json
```

`--json` works before or after the subcommand. For a brand new agent with no baseline,
pass `-` as the before path.

Offline mode prints `local offline verdict - not ratified by the platform`. It runs the
same differ and the same rule set as the server, but the result is not recorded as
evidence and no accreditation moves. Use it for fast pre-commit feedback; run online for
the verdict of record.

## What the edits are meant to demonstrate

| Edit | Verdict | Why |
|---|---|---|
| `autonomy: supervised` → `autonomous` | material | Removes the point where a person could intervene. |
| `cross_border: prohibited` → `permitted_with_consent` | material | Relaxes the jurisdictional constraint that was approved. |
| New `settlement_writer` tool, `effect: write`, `reversible: false` | material | A new irreversible side effect on customer money. |
| `authentication: oauth2_client_credentials` → `api_key` | material | Weaker inbound authentication than accredited. |
| `human_approval: required` → `none` on an existing capability | material | Removes an approved control. |
| `owning_team` renamed | immaterial | No assurance consequence. Renaming a team must not cost a re-accreditation. |

The last row matters as much as the others. A gate that blocks on cosmetic edits gets
switched off, and then it protects nothing.

## A note on `permitted_with_consent`

The descriptor vocabulary is `prohibited` / `permitted` / `permitted_with_consent`. The
engagement record and the materiality ladder use `permitted_with_safeguards` for the
middle rung, and the engine normalises between them, so no verdict depends on which you
write. The mismatch is tracked as an open question (Q-007) rather than left as folklore:
consent and Article 46 safeguards are different legal bases, so collapsing them onto one
rung may itself be wrong.
