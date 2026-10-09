# Deployment

The same images are meant to run in three modes. `services/api/app/config.py` refuses to start on a combination that would phone home from an air-gapped install, or that would treat a customer-hosted install as multi-tenant SaaS.

| Mode | Who operates | Tenancy | Data leaves the estate | Egress back to the operator |
|---|---|---|---|---|
| `saas` | The operator | Multi | Yes, into the operator's cloud | Not applicable |
| `byoc` | Customer's cloud, operator manages | Single | No | Opt-in metadata only |
| `airgap` | Customer, isolated network | Single | No | None |

Set the mode with `AAP_DEPLOYMENT_MODE` and `AAP_TENANCY`. The full list of switches is in [`.env.example`](../.env.example). Copy that file to `.env` for a local run. `.env` is gitignored.

## Local SaaS-shaped stack

Requires Docker Compose v2.

```sh
make up
```

On Windows, after the development secrets exist:

```text
.\scripts\dev-up.ps1
```

| Surface | URL |
|---|---|
| Console | http://localhost:5173 |
| API docs | http://localhost:8000/docs |
| Readiness | http://localhost:8000/readyz |
| MCP adapter | http://localhost:8097/healthz |

`make up` builds images, runs migrations, seeds a synthetic fleet, and starts Postgres, Redis, ClickHouse, the API, the worker, Observe, Prompt, Evaluate, the Go gateway, the MCP adapter, the collector, and the console.

```sh
make reset    # destroy and rebuild
make test     # unit, integration, and golden-file tests
make check    # the CI set
make shell    # psql
```

Integration tests that need Postgres are skipped when Docker is not available. A skipped integration test is not a pass.

## Customer-hosted shape

```sh
make byoc-up
```

`docker-compose.byoc.yml` runs the same images with MinIO standing in for S3, so the object-store and offline-license paths can be exercised on a laptop.

The Helm values in `deploy/helm/agent-assurance/` are the review surface for a real customer account:

- `values.yaml` — the shared defaults
- `values-byoc-aws.yaml` — the AWS shape, including a customer KMS for signing

In BYOC the signing key is the customer's. The process cannot sign an accreditation pack with a key it does not hold. Entitlement is a signed file checked offline, so a network outage on the operator side does not stop the install.

## Air-gapped shape

`AAP_DEPLOYMENT_MODE=airgap` requires tenancy `single`, telemetry off, and update checks off. The validator rejects anything else. There is no phone-home on the request path. Licensing stays an offline file.

Identity in this mode is a local account, not a public OIDC issuer. See [Console](console.md#sign-in).

## Identity

Sign-in is generic OIDC. Entra, Okta, Auth0, and Keycloak are an issuer URL plus an audience. The audience is mandatory once an issuer is set, so a token minted for a different application is rejected. HMAC algorithms are rejected, because they would turn the verification key into a signing secret.

Development, and only development, can sign in as `developer@localhost` without an issuer. That address is local on purpose: a development session that looks like a production directory identity pollutes the audit trail.

No tenant id, client secret, or directory hostname is stored in this repository. Those belong in the secret manager of the install, not in git.
