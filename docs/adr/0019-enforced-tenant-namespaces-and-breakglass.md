# ADR-0019: Enforced Tenant Namespaces and Break-glass Control

- Status: accepted
- Date: 2026-08-11
- Extends: ADR-0010, ADR-0013, ADR-0016, ADR-0017

## Context

Tenant columns and core RLS were necessary but did not close every boundary. Evidence descriptors
could name an arbitrary S3 URI, Temporal identifiers and queues were shared, Memory and Telemetry
had no RLS-backed projection, cross-tenant 404 responses were not security-audited, and platform
emergency control was not separated from tenant administration.

## Decision

Revision `0006_tenant_isolation` adds forced-RLS `memory_records`, `telemetry_records`, and
`tenant_resource_namespaces`. The migration fails if any public table carrying `tenant_id` lacks
both RLS and FORCE RLS. Application and Break-glass logins are explicitly `NOSUPERUSER
NOBYPASSRLS`; tenant provisioning remains a separate administrative operation and is never used
to prove isolation.

`TenantNamespaces` is the canonical contract for Object, Cache, Search, Vector, message topic,
Workflow Namespace/Task Queue/Worker Pool, Telemetry, Evaluation Dataset, and Audit Export names.
Mappings are frozen in `tenant_resource_namespaces`; a logical mapping cannot be silently changed
and a physical namespace cannot be claimed by another tenant.

Evidence storage now checks the configured Bucket and the exact
`tenants/{tenant}/evidence/{evidence}/{digest}` key on write, read, and deletion. A caller cannot
forge another tenant's URI even when the digest and object version are known.

Workflow IDs include Tenant and Run IDs. Production workers set `AUTONOESIS_WORKER_TENANT_ID` and
`AUTONOESIS_WORKER_RISK_POOL`; their dispatcher uses RLS instead of the cross-tenant relay and the
worker rejects commands for another tenant or risk pool. Temporal Namespaces and Task Queues are
derived from the same contract and must be provisioned before enabling isolated API starts.

Tenant Kill Switch endpoints can only target their authenticated Tenant. Platform-wide stop and
resume use `/v1/platform/break-glass/kill-switch`, an independent `break_glass` role and database
login, a mandatory incident ticket, and append-only `platform_audit_events`. The normal app role
can read the global stop state but cannot modify it.

Unknown and cross-tenant API lookups return the same 404 envelope. Both append a hashed-resource
security event to the requesting tenant's audit chain without disclosing target existence.

## Verification

`tests/security/test_tenant_isolation_matrix.py` runs two real tenants through API, PostgreSQL,
MinIO, Temporal, Telemetry, Memory, Evaluation, Release, and Break-glass attacks. It also checks
all tenant tables for forced RLS and verifies the application and Break-glass logins are neither
superusers nor `BYPASSRLS`.

This is integration evidence, not a `production-proven` claim. Production Bucket Policies,
Temporal Namespace provisioning, external Search/Vector/Telemetry services, capacity isolation,
and long-running adversarial exercises remain required.
