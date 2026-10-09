# Privacy, Security, and Retention

## Capture policy

Project capture policy is authoritative:

- `none`: retain structural metadata and content size only;
- `digest`: retain size and a one-way digest;
- `redacted`: encrypt redacted content in object storage;
- `full`: encrypt policy-permitted content in object storage.

Raw content is never inserted into ClickHouse execution rows. Full capture requires an
encryption-key reference and configured payload cipher.

## Sanitization

Observe parses both JSON and protobuf OTLP into one canonical JSON boundary and
sanitizes it before the first durable write. Secret-key fields and common bearer, API
key, cloud credential, private-key, database credential, GitHub token, and JWT patterns
are always masked. Redacted mode additionally masks email, phone, IP, government-ID,
and payment-card patterns.

Hidden/private model chain-of-thought is not captured or reconstructed. Only
provider-exposed reasoning metadata may be retained.

## Access

Trace metadata requires Observe read entitlement. Decrypted payload content additionally
requires the OIDC permission `observe:content:read` (or an Observe/platform admin role).
Legal-hold mutation requires `observe:retention:manage`. Development auth bypass grants
these only in an explicitly development-mode process.

Every full-content read is written to `payload_access_audit`. Hold/release/deletion
actions are written to `payload_policy_audit`.

## Retention and legal hold

Each payload reference receives the project's retention deadline at ingest. The worker
deletes an encrypted object only when every reference to that tenant object has expired
and none is held. Metadata and digest remain with an `expired` state. A legal hold blocks
deletion and records actor, reason, and timestamp.

## Tenant and deployment isolation

Object keys include organization and project. Every query includes verified tenant
identity. Forced PostgreSQL RLS fails closed without transaction-local tenant context.
The BYOC/air-gap Compose overlay disables external container networking and rejects an
external Operations projection URL when air-gap mode is active.
