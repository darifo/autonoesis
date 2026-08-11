# Tenant Isolation and Break-glass Runbook

## Provision a tenant worker boundary

1. Derive names from `TenantNamespaces`; do not hand-build prefixes.
2. Provision the derived Temporal Namespace and assign its tenant/risk Worker identity.
3. Configure `AUTONOESIS_WORKER_TENANT_ID`, `AUTONOESIS_WORKER_RISK_POOL`, and the tenant-scoped
   application database URL. A tenant Worker must not use the relay login.
4. Register Cache, Search, Vector, topic, Workflow, Telemetry, Evaluation Dataset, Object, and
   Audit Export mappings in `tenant_resource_namespaces`.
5. Run the two-tenant attack matrix before enabling traffic.

## Investigate a denied lookup

Query the requesting tenant's audit chain for `security.tenant_scope_lookup_denied` using its
correlation ID. The object ID is a path hash by design. Do not reveal whether the target exists in
another tenant; the public response must remain the common `record_not_found` 404 envelope.

## Platform emergency stop

Use only the Break-glass API and database identity. Supply a reviewed incident ticket and a reason
of at least 20 characters. Activation and deactivation must each appear in
`platform_audit_events`. Tenant Admin, Operator, API, Worker, Relay, and Auditor identities must
not have write permission on `platform_kill_switches` or `platform_audit_events`.

After deactivation, verify both tenant and platform audit trails, confirm the Gateway no longer
observes the global stop, and complete the incident review. Never repurpose the Break-glass login
for tenant provisioning, migrations, troubleshooting queries, or normal operations.
