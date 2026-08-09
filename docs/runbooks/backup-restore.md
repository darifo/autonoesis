# Runbook: Backup & Restore

> Status: baseline · Last reviewed: 2026-08-09

## Scope

This runbook covers backup and restore procedures for Autonoesis platform data. External business systems (CRM, ERP, etc.) have their own backup procedures.

## What to Back Up

| Component | Backup Method | Frequency | Retention |
|---|---|---|---|
| PostgreSQL | `pg_dump` + WAL archiving (PITR) | Continuous WAL; daily full | 30 days minimum |
| Durable Workflow Store | Temporal backup tooling | Daily | Aligned with PostgreSQL |
| Object Store (MinIO/S3) | Bucket replication or `mc mirror` | Daily | 30 days minimum |
| Policies (OPA) | Git repository (infra-as-code) | On change | Permanent |
| Capability Pack artifacts | Object Store (already versioned) | On install | Permanent |
| Secrets/Credentials | Vault backup or secure export | Daily | 30 days |
| Telemetry (Metrics/Logs/Traces) | Backend-specific backup | Per backend policy | Per observability policy |

## Backup Verification

- Weekly: Restore latest backup to a sandbox environment.
- Verify: Database integrity, Workflow replay capability, Object Store checksums.
- Document: Any failures and remediation steps.

## Restore Scenarios

### Scenario 1: PostgreSQL Corruption or Data Loss

1. Stop API and Worker processes.
2. Restore PostgreSQL from latest backup + WAL to desired point-in-time.
3. Verify database integrity: `pg_isready`, row counts for key tables.
4. Replay Temporal Workflows from Workflow Store (which has its own backup).
5. Restart API and Worker.
6. Verify: Create a test Goal and Run; confirm existing Runs are recoverable.

### Scenario 2: Object Store Data Loss

1. Restore Object Store from backup/replication.
2. Verify integrity: spot-check Evidence and Artifact digests against PostgreSQL metadata.
3. Any Evidence with missing payloads must be flagged; affected Outcomes may need re-verification.

### Scenario 3: Full Disaster Recovery

1. Provision new infrastructure (Kubernetes cluster, database, object store).
2. Restore PostgreSQL from backup.
3. Restore Durable Workflow Store.
4. Restore Object Store.
5. Restore secrets and credentials.
6. Deploy platform components (API, Worker, Cockpit, Gateway).
7. Replay Workflows from last checkpoint.
8. Verify end-to-end: Goal creation → Run → Action → Evidence → Outcome.

### Scenario 4: Tenant-Level Data Recovery

1. Identify tenant-specific data in PostgreSQL (tenant_id filter), Object Store (tenant prefix), and Workflow Store (namespace).
2. Restore tenant data to a sandbox environment first.
3. Verify tenant isolation before merging into production.
4. Notify tenant of recovery completion and any data loss window.

## Recovery Time Objectives (RTO) and Recovery Point Objectives (RPO)

RTO and RPO values will be defined per environment and per tenant tier after production capacity baselines are established. Initial targets:

| Environment | RTO | RPO |
|---|---|---|
| Development | 24 hours | 24 hours |
| Staging | 4 hours | 1 hour |
| Production | 1 hour | 5 minutes |

## Regular Drills

- Quarterly: Full disaster recovery drill.
- Monthly: Partial restore verification (database only).
- On major release: Backup/restore validation as part of release checklist.
