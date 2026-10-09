# Later — optional modules (do not start during MVP)

> Not a development session unless the owner explicitly names one module after the MVP
> gate. Paste a **single section** if so, never the whole file.

These were phases 3, 4, 6, 7, 8 in the superseded plan. They are real products and also
the commodity layers the research told us not to lead with.

## Model gateway (old P3–P4)

`design/05`, `design/01` D-11. Honest Cursor: grade D for model traffic; do not sell
prompt DLP. Claude Code / Codex / Gemini CLI base URL is grade A. p95 add < 12 ms.
Catalogue and alias routing are V2+. **Do not build this to "make Cursor safe".**

## Data protection (old P6)

`design/07` D-16. One pluggable interface, small high-precision rules, measured FP rate
before block. Not a prompt-injection product. Facets enter policy, not raw content.

## ClickHouse + cost (old P7–P8)

`design/08` D-16. Postgres partitions until a real customer volume requires ClickHouse.
Cost accounting is V2. Do not size for 3 000 events/s with no customer.

## Declared vs observed (V2)

The strongest original idea in this repo (`docs/design/01-agent-composition.md`). Load it
once the ledger has versions **and** observed capabilities for the same agent. Do not
block MVP on `aap extract`.

If you are tempted to start any of this because the ledger feels "too small", re-read
`design/17` §7 and §11 (non-goals).
