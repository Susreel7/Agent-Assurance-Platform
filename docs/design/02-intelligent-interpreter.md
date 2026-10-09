# Design 2 — Intelligent interpreter (semantic diff review)

## Problem

Non-technical reviewers must approve agent changes without reading code. The platform already computes a **semantic changeset** (`releases/differ.py`) and **materiality verdicts** (`materiality/rules.py` + D-013 gate/console parity). What is missing is a **review experience** that pairs:

1. Raw source change (VCS diff) for engineers,
2. Plain-language **interpretation** of material consequences for approvers,
3. A recorded **decision** that ties to evidence and accreditation.

A governance tool whose summary hallucinates changes is worse than none.

## Decision (with rationale)

1. **Deterministic narrative is the system of record.** Every sentence in the approval UI must be renderable from `(SemanticChange, rule_id → describe_rule())` templates without an LLM.

2. **Optional LLM prose is a separate, labelled layer** — never used for `ReleaseGateVerdict.allowed`, accreditation impact, or evidence events.

3. **Semantic pipeline unchanged in separation of concerns:** differ describes → materiality judges → **interpreter formats** (new thin module).

4. **Capability-level plain language** comes from descriptor `capabilities[].description` and obligation statements — not inferred from tool names alone.

## Pipeline: raw change → semantic changeset

Already implemented for descriptor pairs:

```
before_descriptor, after_descriptor
        │
        ▼
  releases.service.diff_descriptors()  →  ReleaseDiff
        │
        ▼
  materiality.service.assess(diff, MaterialityContext)  →  verdict per SemanticChange
        │
        ▼
  releases.service.create_release / preview_release  →  persist release_changes (append-only)
```

**Extension for Design 1:** new `ChangeCategory` values (`RULE_OBLIGATION`, `MODEL_POLICY`, `SKILL`, `CONFIG`, `SUB_AGENT`) gain entries in `differ.py` and materiality rules mirroring existing tool/model patterns.

**Extension for VCS code diff (not stored):**

- Release carries `vcs_repo`, `vcs_ref`, `vcs_pr_ref` (already on `ReleaseCreate`).
- Console fetches unified diff from provider API **in browser** or via customer-configured proxy — **not** persisted in Postgres (content risk + size).

Optional future: store `vcs_diff_digest` sha256 only in `releases` table for audit.

### Reconciliation-augmented changes (Design 1 integration)

When reconciliation finds `observed_only` or `conflict` without descriptor change, emit **synthetic `SemanticChange`** rows:

| Field | Value |
|-------|-------|
| `category` | TOOL / MCP_SERVER / MODEL |
| `operation` | ADDED (observed) |
| `path` | `observed.tools[name=x]` |
| `detected_by` | `runtime_reconciliation` |
| `severity` | HIGH if production lifecycle else MEDIUM |
| `verdict` | MATERIAL or NEEDS_REVIEW via new rules e.g. `MAT-050-undeclared-runtime-tool` |

These appear on release **or** on a standing “drift release” pseudo-version — **recommendation:** standalone **Drift review** queue under `engagements` drift API, not mixed into semver releases, to avoid confusing “version 1.2.0” with “nothing was published but runtime drifted”. PO decision in open question.

## Materiality ladder by element class

Maps to existing `Materiality` enum: `immaterial`, `needs_review`, `material` and `AccreditationImpact`: none / requires_revalidation / suspends (from `ReleaseDiff.accreditation_impact`).

| Element class | Immaterial (examples) | Needs review | Material (blocks / suspends) |
|---------------|----------------------|--------------|------------------------------|
| **Metadata** | display_name typo, team rename | — | — |
| **Inference params** | top_p ±≤0.05 | temperature change >0.1 | — |
| **Models** | patch version within same family+region+hosting | new family, hosting change | region outside approved set; `selection_mode` → `auto`; fallback model change |
| **Model policy** | allowlist expands within approved catalogue | new allowlist pattern | `pinned` → `auto`; denylist shrink |
| **Prompts / rule sources** | digest unchanged | digest changed, obligations unchanged | digest changed + binding obligation changed/removed |
| **Rule obligations** | advisory wording tweak | new advisory obligation | new forbid/limit binding; forbid→require weakened polarity |
| **Tools** | read endpoint path change same host | new read tool | new write/execute; irreversible; auth downgrade on path |
| **MCP servers** | digest unchanged (tool list) | new server URL | new external vendor; digest change (tool surface change) |
| **Capabilities** | description only | new read capability | new write/irreversible; human_approval removed |
| **Sub-agents / delegation** | internal accredited version bump | new internal delegate | external/partner trust; new delegate URN |
| **Data classes** | reorder | new non-special class | special category added; class removed while engaged |
| **Residency** | — | basis text | cross_border ladder **down** (any rung); permitted_regions shrink |
| **Guardrails** | defence reorder | defence removed | injection defence removed entirely |
| **Autonomy** | — | — | any rung up (`_AUTONOMY_LADDER`) |
| **Security auth** | — | synonym normalisation | ladder down (`_AUTH_LADDER`) |
| **Runtime observed drift** | — | first seen in staging | production + undeclared tool/model/MCP |

Rules should be added as explicit ids in `materiality/rules.py` (pattern `MAT-*`, `IMM-*`, `REV-*`), not ad hoc in interpreter.

**Cross-border:** reuse `_CROSS_BORDER_LADDER` and engagement `CrossBorderTransfer` — engagement terms feed `MaterialityContext.approved_regions` and approved cross-border rung; descriptor `data.residency.cross_border` compared to engagement minimum strictness.

## Plain-language generation (deterministic backbone)

New module: `app/domains/releases/interpreter.py` (pure functions, unit tested).

```python
class ReviewSentence(BaseModel):
    change_path: str
    rule_ids: tuple[str, ...]
    template_id: str           # e.g. "tool.added.write"
    text: str                  # rendered sentence, ≤512 chars
    severity: Severity
    materiality: Materiality

class ReleaseReviewBrief(BaseModel):
    release_id: UUID | None
    from_semver: str | None
    to_semver: str
    headline: str              # from ReleaseDiff.headline()
    sentences: list[ReviewSentence]
    accreditation_impact: AccreditationImpact
    blocking_rule_ids: list[str]
    generated_at: datetime
    generator_version: str = "deterministic-v1"
```

### Template catalogue (examples — implement exhaustively from ChangeCategory × Operation)

| template_id | Condition | Text pattern |
|-------------|-----------|--------------|
| `tool.added.write` | TOOL ADDED effect=write | "This agent gained a tool «{name}» that can modify data ({effect})." |
| `tool.added.execute` | effect=execute | "This agent gained the ability to run «{name}» (execute)." |
| `mcp.added` | MCP ADDED | "A new MCP server «{url}» was attached, expanding tools available to the agent." |
| `obligation.weakened` | RULE obligation polarity forbid→require inverted | "A rule forbidding {category} was weakened or removed (obligation {id})." |
| `model.auto` | model_policy selection_mode→auto | "Model selection changed to automatic routing; production data may reach models not listed in the descriptor." |
| `residency.cross_border_down` | ladder move | "Cross-border data transfer stance moved from {before} to {after} (more permissive)." |
| `capability.irreversible` | CAPABILITY ADDED reversible=false | "This agent gained an irreversible capability: «{name}»." |

Templates pull **subjects** from `SemanticChange.subject` and **detail** from `SemanticChange.detail` when present.

**Rule description enrichment:**

```python
text = template.format(**fields) + " " + rule_rationale_snippet(rule_ids[0])  # max 1 sentence from describe_rule
```

### Optional LLM layer

| Field | Policy |
|-------|--------|
| Storage | None in DB; returned ephemerally from `?prose=1` query param |
| UI | Collapsible "Plain English summary (AI-assisted)" banner — **must** show `generator_version != deterministic` |
| Gate | LLM output **ignored** by `ReleaseGateVerdict` |
| Safety | Input is structured `ReviewSentence[]` only — no raw prompts |

If LLM unavailable, omit section — never fallback to fake deterministic text.

### Preventing hallucinated governance

| Mechanism | Purpose |
|-----------|---------|
| Every sentence cites `change_path` + `rule_ids` | Click links to structured change row |
| `template_id` logged in evidence on approval | Auditor verifies template version |
| Invariant test: brief sentences ⊆ diff paths | No orphan claims |
| No LLM on `allowed` boolean | D-013 extended to interpreter |

## Data model additions

**No new tables required for v1** if brief is computed on read.

Optional cache (denormalisation):

| Table | Columns |
|-------|---------|
| `release_review_briefs` | `release_id`, `generator_version`, `brief_json` (JSONB, bounded size), `computed_at` |

Append-only if written; prefer on-read for v1.

**Evidence on human decision:**

When release transitions to `APPROVED` or `ABANDONED`:

```python
EvidenceRecord(
    kind=EvidenceKind.RELEASE_DECISION,  # add to enum if missing — migration
    outcome=EvidenceOutcome.ALLOW / DENY,
    reason_code="release_approved" | "release_rejected",
    content_digest=sha256(canonical brief + actor + timestamp),
    ...
)
```

## API surface

| Method | Path | Response |
|--------|------|----------|
| GET | `/v1/releases/{release_id}/review-brief` | `ReleaseReviewBrief` |
| GET | `/v1/releases/preview/review-brief` | POST body same as `ReleasePreviewRequest` → brief without persist |
| GET | `/v1/releases/{release_id}` | extend `ReleaseDetail` with optional embedded `review_brief` |
| POST | `/v1/releases/{release_id}/transition` | existing; records approver on state `APPROVED` |
| POST | `/v1/releases/{release_id}/changes/{change_id}/adjudicate` | existing per-change override |
| POST | `/v1/materiality/changes/{change_id}/adjudicate` | queue adjudication (D-013 overrides) |

**CI:** `aap preview --json` includes `review_brief.sentences[].text` alongside `blocking_changes`.

## Console surface

**Release detail** (extend existing screen from session 4):

```
┌─────────────────────────────────────────────────────────────┐
│ Headline · Accreditation impact badge                       │
├──────────────────────┬──────────────────────────────────────┤
│ REVIEW BRIEF         │ IMPACT RAIL (existing)               │
│ (deterministic list) │ material / review counts             │
│ Each row:            │ rules fired                          │
│  • sentence          │                                      │
│  • severity chip     │                                      │
│  • link → change row │                                      │
├──────────────────────┴──────────────────────────────────────┤
│ Tabs: Semantic changes | Grouped by category | Raw descriptor │
│       Source diff (external link) | Evidence                 │
├─────────────────────────────────────────────────────────────┤
│ Actions: Approve release | Reject | Request changes          │
│ Requires: adjudicated_by + reason on material items (policy) │
└─────────────────────────────────────────────────────────────┘
```

**Approve/reject records:**

| Action | Persisted |
|--------|-----------|
| Approve release | `releases.state=approved`, `approved_by`, `approved_at`, evidence event, optional accreditation transition |
| Reject | `state=abandoned`, evidence event |
| Per-change adjudicate | `release_changes.adjudicated_*`, optional `rule-override:` reason (materiality service) |

Open Q-014: approver role separation — UI should disable approve if `Principal` lacks `approver` scope when auth lands.

## Out of scope

- Natural-language Q&A over the codebase.
- Storing unified diffs in Postgres.
- Auto-approval based on LLM summary.
- Replacing materiality engine with LLM classification.

## Failure modes

| Mode | Impact | Mitigation |
|------|--------|------------|
| Template missing for new change shape | Empty sentence | `RULE_UNCLASSIFIED` + `REV-*` rules; test coverage per category |
| Misleading capability text (author error) | Wrong reviewer belief | Show capability `description` quoted; link to author |
| Drift mixed into release | Confusing narrative | Separate drift queue (open question) |
| LLM prose trusted by users | False confidence | UI labelling + hide by default |

---

## Open questions

### Q-D2-01 — Runtime drift in release review vs drift queue

| Option | Recommendation |
|--------|----------------|
| Separate engagement drift workflow | **Recommended** — matches existing `DriftReport` |
| Synthetic release rows | Avoid |

### Q-D2-02 — Minimum adjudication before approve

| Option | Recommendation |
|--------|----------------|
| All `needs_review` must be adjudicated | **Recommended** for production agents |
| Material only | Weaker — acceptable for dev lifecycle |
