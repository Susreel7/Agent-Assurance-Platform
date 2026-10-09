# Console

The console is one React application. A ledger install and an assurance install share the route table and differ in the navigation the server sends. `AAP_PRODUCT_MODE` selects the manifest. The default is `ledger`.

Sign-in and the callback sit outside the shell. Everything else is behind it.

Local base URL after `make up`: `http://localhost:5173`.

## Sign-in

| Path | What it is |
|---|---|
| [`/login`](console.md#sign-in) | Provider list from `GET /v1/auth/config`. Nothing is baked in at build time. |
| `/login/callback` | OIDC code exchange. A failed exchange stays on this screen. |

With no issuer configured, development offers a localhost session. With an issuer configured, the button is that issuer. The Microsoft mark is drawn only for an OIDC provider, because that is the common enterprise button. Okta, Auth0, and Keycloak use the same code path. The issuer URL is deployment configuration, not a value in this repository.

## Ledger

These are the screens a fresh ledger install is built around.

| Path | Screen |
|---|---|
| `/` | [Home](console.md#ledger). Coverage by grade, recent high-risk actions, unregistered collectors, credential exposures, and the harness strip. Empty slots say which slice will fill them. A zero is not shown for a measurement that has not been taken. |
| `/observe` | Trace overview |
| `/observe/executions` | Action ledger |
| `/observe/sessions` | Sessions |
| `/observe/live` | Live tail |
| `/observe/traces` | Trace list |
| `/observe/analytics` | Analytics |
| `/agents` | Registered agents |
| `/discovery` | Discovery. Names the harnesses it can attribute. Does not invent a count. |
| `/admin/mcp` | MCP registry |
| `/platform-keys` | Platform keys issued to workloads |
| `/admin/connections` | Provider connections. Secrets stay in the vault. |
| `/model-routing` | Model routes, when the router module is enabled |
| `/admin/people` | Members and teams |
| `/admin/access` | Roles and grants |
| `/admin/audit` | Security audit, cursor-paginated |
| `/profile` | The signed-in member |

## Assurance

These routes exist in both modes. A ledger install hides the ones its capability flags do not enable. The URL still resolves, so a bookmark does not bounce to Home.

| Path | Screen |
|---|---|
| `/assurance` | Assurance center |
| `/customers` | Clients an accreditation is produced for |
| `/engagements` | Engagements |
| `/accreditations` | Accreditation packs |
| `/releases` | Release intelligence |
| `/findings` | Findings |
| `/evidence` | Evidence explorer. Digests and decisions, not prompts |
| `/graph` | Agent graph, recursive SQL, no graph database |
| `/sla` | Service levels |
| `/prompt` | Prompt workspace |
| `/evaluate` | Evaluation workspace |
| `/router` | Gateway deployments, routes, simulate, compile |
| `/control` | Control center |

Deep links of the form `/traces/:id`, `/sessions/:id`, and `/executions/:id` redirect into the Observe routes above.
