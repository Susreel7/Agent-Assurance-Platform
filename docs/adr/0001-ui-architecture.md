# ADR 0001 — UI architecture: web application plus CLI, no desktop application

**Status:** accepted · 2026-09-13 · decision D-008

## Question

Should the product surface be a React web application, or a cloud-connected desktop
application in the style of Cursor or the ChatGPT desktop client?

## Decision

**A React web application for the console and the trust portal, plus an `aap` command-line
tool for the developer surface. No desktop application.**

## Why the trust portal settles it on its own

The trust portal is shown to people who do not work for the customer of record: the client's
security reviewers, their internal audit function, and in regulated sectors their external
auditors and sometimes a regulator.

None of those people will install a binary from a vendor they are in the middle of
evaluating. Asking them to is not a friction problem, it is a dead end — the install itself
would require its own security review, which is the exact cost this product exists to remove.

That single constraint decides the question. Everything below is corroboration.

## Why a desktop application would be actively worse here

**It breaks BYOC and airgap.** The web console ships inside the Helm chart that already
deploys the API. One artifact, one upgrade path, one version to support. A desktop client
means signed binaries per platform, an update channel that must work without egress in
airgap, and a version matrix of client against server across every install. In airgap, an
auto-updater cannot phone home at all, so upgrades become a manual distribution problem for
every customer.

**It adds an approval gate to a product that sells the removal of approval gates.** Endpoint
software at a bank goes through software asset management, endpoint security review and a
deployment ring. Shipping that to sell agent governance is a contradiction a buyer will
notice.

**It multiplies the auth work.** Enterprise SSO over SAML or OIDC, short-lived sessions, and
session audit are browser-native and solved. In a desktop client you rebuild the flow with a
loopback redirect and a token store, and you own the refresh and revocation edge cases.

**One person maintains this.** A web app is one build target.

## What desktop applications are actually for

They earn their considerable cost through capabilities a browser cannot reach: local
filesystem access, local compute, offline-first operation, or deep OS integration.

Cursor needs to be a desktop application because it edits files on your disk and runs your
toolchain. The ChatGPT desktop client is a convenience shell over a web application, shipped
by a company with a platform team.

This console reads and writes rows in a database over HTTP. It needs none of those
capabilities. The qualities that make a modern application feel good — fast navigation,
keyboard control, dense information design, optimistic updates, no full-page reloads — are
properties of how an interface is built, not of how it is distributed. A browser is not the
reason an application feels slow.

## The developer surface is a CLI, not a web page

There is one audience the web console genuinely serves badly: engineers publishing agent
versions. They want the release preview in a terminal and in a CI pipeline, not in a browser
tab. This is also the adoption wedge — engineering teams adopt the differ because it is
useful to them before compliance mandates anything.

```
aap validate descriptor.yaml     # schema-check an AAP descriptor
aap diff v2.1.0 v2.2.0           # semantic changes, human-readable
aap preview descriptor.yaml      # materiality verdict and accreditation impact
aap pack --customer acme         # generate an accreditation pack
```

`aap preview` calls the same `POST /v1/releases/preview` endpoint the console uses and writes
no state, so it is safe as a CI gate. **The CLI holds no logic the API does not have.** It is
a client, so it cannot drift from the console's answers.

## Consequences

- `services/web` stays React, TypeScript, Vite, TanStack Query and Tailwind. Confirmed, not changed.
- The console and the trust portal are two route trees in one application, separated by
  authorisation scope, not two applications. The portal renders a customer-scoped subset.
- A new `services/cli` package is added when the `releases` module gets its API, distributed as
  a single binary via PyInstaller so engineers need no Python.
- The portal must degrade to static signed packs served from object storage, so it survives a
  control-plane outage. This follows from D-004.
- Every screen must be reachable and legible without a mouse. That is where the "feels like a
  native application" quality actually comes from.

## Reconsider if

- A customer requires a genuinely offline reviewer experience with no server at all. The
  answer then is a signed self-contained HTML pack, not a desktop application.
- Engineers ask for materiality feedback inline while editing a descriptor. The answer then is
  a VS Code and Cursor extension, which is a small wrapper over the CLI — still not a desktop
  application.
