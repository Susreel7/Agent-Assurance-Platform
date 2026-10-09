# Design 1 — Agent composition

## Problem

Reviewers must see **what an agent is made of** and what changed between versions, but customer agents are increasingly assembled by AI from LangGraph graphs, Cursor SDK wiring, dozens of MCP servers, skills, and natural-language rules. The AAP 0.1 descriptor already covers models, digest-pinned prompts, tools, MCP URLs, capabilities, delegation, data classes, residency, and guardrail enums — yet it does not fully express **model selection policy**, **skills**, **sub-agents**, **runtime configs**, or **reviewable rules** without carrying forbidden prompt content.

The product thesis: **declared vs observed disagreement** is the highest-value signal (already partially implemented for tools/MCP via D-039 and `operations`).

## Decision (with rationale)

1. **Ship AAP 0.2** with an explicit top-level `composition` object rather than overloading `references` and `additionalProperties`. Rationale: golden-file contract, clear diff categories, and BOM extraction stay maintainable. AAP 0.1 agents remain valid; 0.2 is opt-in via `aap_version: "0.2"`. *(Escalated as open question — recommendation: 0.2 bump.)*

2. **Rules are represented twice, neither copy is raw prompt text in the database:**
   - **In the descriptor (customer repo):** `rule_sources[]` — path, digest, kind; optional customer-local content stays in git.
   - **In the descriptor (governance surface):** `rule_obligations[]` — machine-generated or human-approved **bounded obligations** (≤512 chars each) derived at publish time; these are what diff, materiality, and gap analysis consume.
   - **In evidence / operations:** digests, obligation ids, classifications only (AGENTS.md rule 5).

3. **Capture is dual-path:** static extraction at publish (`aap extract`) plus runtime observation (`run_steps`, existing ingest). Reconciliation produces **findings**, never silent descriptor mutation.

4. **MCP servers gain a stable `name` field** (closes Q-017): `{ "name": "stripe", "url": "...", "digest": "..." }`. Match keys remain for backward compatibility.

## AAP 0.2 field shapes (Pydantic / JSON Schema sketch)

Root still requires `aap_version`, `agent`, `accountability`, `runtime`. New section:

```yaml
aap_version: "0.2"

composition:
  model_policy:
    selection_mode: pinned | allowlist | auto   # auto = router/SDK may pick
    pin:
      provider: anthropic
      id: claude-sonnet-4-5
    allowlist:                                 # used when selection_mode != pinned
      - provider/id pattern, e.g. "anthropic/claude-*"
    denylist: []
    residency_binding: engagement              # enum: descriptor | engagement | custom
    custom_permitted_regions: []               # when residency_binding=custom

  rule_sources:
    - name: agents_md
      kind: agents_md | cursor_rule | skill | system_prompt | guardrail_prompt
      path: .cursor/rules/project-state.mdc    # repo-relative at extract time
      digest: "sha256:..."
      language: en
    - name: refund_policy_skill
      kind: skill
      path: .cursor/skills/refund/SKILL.md
      digest: "sha256:..."

  rule_obligations:
    - id: OBL-001                             # stable within agent; uuid ok
      source_ref: agents_md                   # matches rule_sources.name
      category: data_egress | financial | pii | tool_use | residency | oversight | other
      polarity: require | forbid | limit
      statement: "Must not transmit customer PII to external URLs."  # max 512 chars
      strength: binding | advisory            # binding → probe + materiality
      digest: "sha256:..."                    # hash of normalised statement text

  skills:
    - name: automate
      path: .cursor/skills-cursor/automate/SKILL.md
      digest: "sha256:..."
      invoked_by: [orchestrator]              # optional tags

  sub_agents:
    - name: research_subagent
      kind: langgraph_subgraph | cursor_subagent | a2a_delegate
      ref: graphs/research.py:graph           # or urn for delegates_to link
      digest: "sha256:..."                    # hash of exported tool/skill list
      trust: internal_accredited | internal | partner | external

  configs:
    - name: langgraph_checkpointer
      kind: env | yaml | toml | json
      path: config/checkpointer.yaml
      digest: "sha256:..."
      keys: [postgres_dsn, pool_size]         # key names only, not values

  memory_retrieval:
    - name: claims_vector
      kind: vector_store | bm25 | hybrid
      ref: data.sources[name=claims_primary]  # cross-link to existing data.sources
      classes: [claims_history]
      region: eu-west-1
```

**Existing 0.1 fields retained:** `models[]`, `prompts[]` (digest-only), `tools[]`, `references.mcp_servers[]`, `capabilities[]`, `delegates_to[]`, `data.*`, `security.*`, `inference`, `resilience`.

**Relationship to A2A:** `references.a2a_agent_card` remains authoritative for advertised skills/endpoints; `composition.skills` is the **governance mirror** of what the repo actually ships (diffable). Mismatch between card digest and extracted skills → finding `a2a-card-drift`.

### Enum additions (Postgres + Python `StrEnum` — new migration area `composition` or extend registry)

| Enum | Values |
|------|--------|
| `rule_source_kind` | `agents_md`, `cursor_rule`, `skill`, `system_prompt`, `guardrail_prompt`, `other` |
| `obligation_category` | `data_egress`, `financial`, `pii`, `tool_use`, `residency`, `oversight`, `human_approval`, `other` |
| `obligation_polarity` | `require`, `forbid`, `limit` |
| `obligation_strength` | `binding`, `advisory` |
| `model_selection_mode` | `pinned`, `allowlist`, `auto` |
| `sub_agent_kind` | `langgraph_subgraph`, `cursor_subagent`, `a2a_delegate`, `other` |
| `config_kind` | `env`, `yaml`, `toml`, `json`, `other` |
| `reconciliation_status` | `aligned`, `declared_only`, `observed_only`, `conflict` |

## Data model (platform tables — beyond `agent_versions.descriptor_json`)

`agent_versions.descriptor_json` holds the full 0.2 document (Q-003 size cap should be enforced — recommend 256 KiB soft warning, 1 MiB hard reject at publish).

New table **`composition_snapshots`** (append-only, optional optimisation):

| Column | Type | Notes |
|--------|------|-------|
| `id` | uuid PK | |
| `org_id` | uuid | RLS |
| `agent_version_id` | uuid FK | unique per version |
| `descriptor_digest` | text | sha256 of canonical JSON |
| `obligation_count` | int | denormalised |
| `extracted_at` | timestamptz | |
| `extractor_version` | text | e.g. `aap-cli 0.4.0` |

New table **`composition_reconciliations`** (append-only findings feed):

| Column | Type | Notes |
|--------|------|-------|
| `id` | uuid PK | |
| `org_id` | uuid | |
| `agent_id` | uuid | |
| `agent_version_id` | uuid | baseline or current |
| `element_kind` | text | `tool`, `mcp_server`, `model`, `skill`, `sub_agent`, `rule_obligation`, … |
| `element_key` | text | normalised identity (tool name, server name, model id) |
| `declared` | boolean | |
| `observed` | boolean | |
| `status` | `reconciliation_status` | |
| `observed_count` | int | calls/runs in window |
| `window_start` | date | |
| `window_end` | date | |
| `computed_at` | timestamptz | |

Unique index: `(org_id, agent_version_id, element_kind, element_key, window_end)`.

**Findings linkage:** reconciliation conflicts create/update rows in `findings` with `category` e.g. `composition_drift`, fingerprint `composition:{agent_id}:{element_kind}:{element_key}`.

Existing **`bom_components`** — extend `ComponentKind`:

```python
class ComponentKind(StrEnum):
    ...
    SKILL = "skill"
    CONFIG = "config"
    RULE_SOURCE = "rule_source"
    RULE_OBLIGATION = "rule_obligation"
    SUB_AGENT = "sub_agent"
    MODEL_POLICY = "model_policy"
```

`bom.service.extract_components()` walks `composition.*` and existing arrays.

## Static vs runtime capture

| Element | Static extract (repo push / `aap extract`) | Runtime only (`run_steps`) | On disagreement |
|---------|---------------------------------------------|----------------------------|-----------------|
| Tools (native) | From LangGraph tool registry / `@tool` exports | `kind=tool`, `name` | finding: undeclared tool |
| MCP servers | MCP config files, `.cursor/mcp.json`, SDK settings | `kind=mcp_tool`, `server_name` | finding: undeclared server (D-039) |
| Models | `models[]`, `composition.model_policy` | `kind=llm`, `model` | finding: undeclared or disallowed model |
| Skills | `.cursor/skills/**/SKILL.md` paths | indirect via tool names / node names | finding: skill file changed but digest unchanged (tamper) |
| Sub-agents | graph definitions, `composition.sub_agents` | `kind=sub_agent`, `name` | finding: undeclared delegation |
| Rule sources | file paths + digests | N/A | obligation extraction must re-run on digest change |
| Rule obligations | NLP/structured extractor in CI | partial via guardrail refusals | obligation marked `observed_only` if behaviour violates |
| Configs | named keys + digests | env drift not visible unless reported | optional future: config fingerprint in run report |
| Memory/retrieval | `data.sources`, `composition.memory_retrieval` | `kind=retrieval`, `name` | undeclared retrieval source |
| Guardrails | `security.prompt_injection_defences`, guardrail prompts (digest) | `kind=guardrail` | missing guardrail step in prod |

**Product behaviour on disagreement:** never auto-patch descriptor. Surface in console (Composition tab), increment finding severity if production lifecycle, block release if binding obligation conflict (via materiality rule — Design 2).

### Static extraction pipeline (`aap extract`)

Inputs: repo root, path to `.aap.yaml`, optional `--framework langgraph`.

Steps (deterministic order):

1. Parse LangGraph graph module(s) listed in `composition.sub_agents[].ref` — collect tool names, bound MCP client ids.
2. Parse `.cursor/mcp.json` / SDK config — emit `references.mcp_servers` with `name` + `url`.
3. Hash listed `rule_sources[].path` files → update digests.
4. Run **obligation extractor** (see Rules section) → update `rule_obligations[]` only when `--apply-obligations` or in CI gate.
5. Validate against AAP 0.2 schema; output patched YAML/JSON.

Extraction failures are **actionable errors** (exit 1), not warnings, when run in CI.

## Rules — reviewable and diffable without prompt storage

### Tension

AGENTS.md: evidence and operational stores never hold prompts/completions. Reviewers need to understand rule changes. Storing customer prompts in Postgres is unacceptable for BYOC/airgap and audit scope.

### Resolution (three layers)

| Layer | Location | Content | Size limit |
|-------|----------|---------|------------|
| Source of truth | Customer git | Full NL rules, skills, AGENTS.md | unbounded in git |
| Descriptor | `rule_sources` + `prompts[].digest` | Digests + paths only | schema |
| Review surface | `rule_obligations[]` | Normalised obligation statements | 512 chars/statement |
| Platform DB | `findings`, `release_changes`, `evidence_events` | obligation id, digest, category, polarity | 512 bytes text fields |

**Diff behaviour:**

- Change to `rule_sources[].digest` without obligation change → `SemanticChange` category `RULE` (new) or `PROMPT`, severity HIGH, materiality via `RULE_PROMPT_DRIFT_*` (extend existing prompt rules to obligations).
- Change to `rule_obligations[].statement` or polarity → diff at obligation id; ladder rules for `polarity` forbid→require etc.

**Obligation extraction (who runs it):**

| Option | Pros | Cons |
|--------|------|------|
| A. Customer CI runs bundled extractor (`aap obligations suggest`) | No prompt leaves customer env in SaaS | Model quality varies; airgap needs local model |
| B. Platform runs extractor on upload | Consistent | Requires prompt upload — **violates rule 5** unless ephemeral |
| C. Human authoring only in console | Safest legally | Does not scale |

**Recommendation:** **Option A** for v1 — extractor ships in `aap-cli`, runs in customer CI, writes obligations into descriptor before publish. Platform never sees raw text. Optional **Option C** for editing obligation statements in console with audit trail (still bounded text, not full prompt).

Extractor output contract:

```python
class SuggestedObligation(BaseModel):
    source_ref: str
    category: ObligationCategory
    polarity: ObligationPolarity
    statement: str = Field(max_length=512)
    confidence: Literal["high", "medium", "low"]  # low → NEEDS_REVIEW in gate, not stored in evidence
```

Only obligations with `confidence=high` or human-approved are written to descriptor; `medium` surfaced as CI warnings.

**Classification without storing prose:** TF-IDF or embedding of obligation statements is allowed **if** embeddings are not stored in evidence (compute at diff time in CI only). Prefer deterministic keyword/classifier templates for v1 to avoid ML dependency.

### Boundary

- **Inside platform:** obligation ids, digests, categories, polarity, materiality verdicts.
- **Outside platform (git):** full rules; linked via VCS fields on `agent_versions` (`vcs_repo`, `vcs_ref`).
- **Console “view rule”:** deep-link to VCS at commit (`vcs_provider` + ref + path); do not fetch and render prompt body in SaaS without explicit customer opt-in (BYOC policy).

## API surface

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/v1/agents/{agent_id}/versions/{version_id}/composition` | Declared composition summary from descriptor + BOM |
| GET | `/v1/agents/{agent_id}/composition/reconciliation` | Latest reconciliations + link to findings |
| POST | `/v1/agents/{agent_id}/versions/{version_id}/composition/extract` | **Optional** server-side trigger for BYOC agents with repo webhook; runs same logic as CLI in worker |
| GET | `/v1/agents/{agent_id}/versions/{version_id}/bom` | existing; extended kinds |

Publish path unchanged: `POST /v1/agents/{id}/versions` with full descriptor; service validates schema version, calls `bom.rebuild_for_version`.

Events (for dependency direction): after version publish, emit internal job `composition.reconcile` (worker) — do not import `operations` from `registry` directly; use job queue table or existing `jobs` from 0001.

## Console surface

**Agent → Composition tab** (new, beside Activity):

- Sections: Model policy, Rules (obligations table), Tools & MCP, Skills, Sub-agents, Configs, Memory.
- Columns: **Declared** | **Last observed** (7d/90d from top bar window) | **Status** badge.
- Row drill-down: link to finding, link to run trace exemplar, link to VCS path for rule sources.
- No prompt body rendering by default; “Open in repo” button.

## Out of scope

- Storing or embedding full prompt corpora in Postgres.
- Automatic remediation (auto-editing customer repos).
- Neo4j-style live graph of composition (use existing `graph` domain only for accredited blast radius).
- Real-time extraction on every run (batch reconciliation only for v1).

## Failure modes (honest)

| Failure | Consequence | Mitigation |
|---------|-------------|------------|
| Extractor misses dynamically registered tools | False negative undeclared | Runtime reconciliation catches |
| Heuristic MCP URL matching (pre-Q-017) | False positive undeclared | `name` field + exact match |
| Obligation extractor hallucinates obligations | Wrong governance baseline | Human approve in CI; confidence gating; diff shows statement text bounded |
| Customer publishes without re-extract | Stale digests | CI gate: digest mismatch vs git at `vcs_ref` |
| `auto` model policy | Declared model set incomplete | Design 3 enforcement + observed model findings |
| Large descriptor (Q-003) | Index bloat | Size cap; externalise heavy SBOM to `references.sbom` URL only |

---

## Open questions (product owner)

### Q-D1-01 — AAP 0.2 vs incremental 0.1 extensions

| Option | Recommendation |
|--------|----------------|
| 0.2 with `composition` block | **Recommended** — clear golden break, one migration story |
| Cram into `additionalProperties` | Avoid — differ and BOM won't discover fields reliably |

### Q-D1-02 — Obligation extractor ownership

| Option | Recommendation |
|--------|----------------|
| Customer CI only (A) | **Recommended** for rule 5 compliance |
| Platform-side with ephemeral processing | Only BYOC with explicit DPA; not v1 |

### Q-D1-03 — Descriptor size cap (extends Q-003)

Recommend **256 KiB warn / 1 MiB reject** at `VersionPublish` with clear error citing largest section.
