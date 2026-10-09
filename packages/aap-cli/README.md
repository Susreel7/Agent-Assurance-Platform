# aap-cli

Engineering CLI for Agent Assurance Platform release gates. Runs in CI before deploy to
report whether a descriptor change invalidates customer approval.

## Install

```bash
pip install -e "packages/aap-cli[dev]"
```

Semantic diff and offline preview need the control-plane differ:

```bash
pip install -e "packages/aap-cli[offline]"
```

## Commands

| Command | Purpose |
|---------|---------|
| `aap validate <file>` | Validate against AAP 0.1 schema |
| `aap diff <before> <after>` | Semantic diff (requires `[offline]`) |
| `aap preview <before> <after>` | CI gate via platform API |
| `aap pack <accreditation-id>` | Download current accreditation pack |

Configuration: `AAP_BASE_URL`, `AAP_ORG_ID`, `AAP_TOKEN`, or `--base-url`, `--org-id`, `--token`.
Use `--json` in CI for machine-readable output.

### Exit codes (`preview`)

| Code | Meaning |
|------|---------|
| 0 | Allowed to deploy |
| 1 | CLI or platform connectivity/auth failure |
| 2 | Blocked by material changes |

## GitHub Actions

```yaml
- name: Install aap CLI
  run: pip install -e "./packages/aap-cli"

- name: Validate descriptor
  run: aap validate agent/descriptor.yaml

- name: Release gate
  env:
    AAP_BASE_URL: https://assurance.example.com
    AAP_ORG_ID: ${{ vars.AAP_ORG_ID }}
    AAP_TOKEN: ${{ secrets.AAP_TOKEN }}
  run: |
    aap preview baseline/descriptor.yaml agent/descriptor.yaml --json > gate.json
    echo "Verdict: $(jq -r .headline gate.json)"
  # Fails the job on exit 2 (blocked); exit 1 fails on auth/outage — not conflated with blocked.

- name: Block deploy on material change
  if: failure()
  run: echo "Release gate blocked or errored — inspect gate.json"
```

For air-gapped pipelines, add `--offline` to `preview` (install `aap-cli[offline]`). The
verdict is computed locally and is not ratified by the platform.
