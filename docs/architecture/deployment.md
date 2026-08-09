# Deployment Architecture

> Status: baseline · Last reviewed: 2026-08-09 · Applicable version: 0.1.0

## 1. Initial Deployment (Current)

```text
Users / Systems → Ingress / API Gateway → Agent Platform API
Users → Cockpit → API
API → PostgreSQL
API → Durable Workflow Service
API → Policy Engine (OPA)
Durable Workflow Service → Worker / Runtime / Harness
Worker → PostgreSQL
Worker → Object Store (MinIO)
Worker → Model Gateway Module
Worker → Tool Gateway Module
Model Gateway → Model Providers
Tool Gateway → Enterprise Systems
API → Event Bus
Worker → OTel Collector
API → OTel Collector
```

### Component Selection (Phase 0–1)

| Component | Technology | Role |
|---|---|---|
| API | Python/FastAPI | HTTP/SSE/Webhook control plane; domain layer must not depend on web framework |
| Durable Workflow | Temporal | Long-task state, Timers, Signals, Retries, Recovery |
| Core DB | PostgreSQL | Transactional, optimistic locking, RLS, Outbox/Inbox |
| Object Store | MinIO (S3-compatible) | Immutable Evidence/Artifact payloads |
| Policy Engine | OPA | Policy decisions coexisting with application-level hard invariants |
| Event Bus | NATS JetStream / Kafka | Persistent event delivery (introduced when actual subscribers exist) |
| Telemetry | OpenTelemetry | Vendor-neutral collection standard |
| Cockpit | TypeScript/React | Goal, Run, Approval, Evidence, Policy, Budget, Evaluation, Release, Audit |

### Local Development

```bash
docker compose --file infra/compose/docker-compose.yml up --build
```

Services: PostgreSQL (17-alpine), Temporal (auto-setup), Temporal UI, OPA, MinIO, Jaeger, OTel Collector, API, Worker, Cockpit.

## 2. Production Evolution

As requirements mature, introduce:

| Capability | When |
|---|---|
| Kubernetes with risk-tiered Runtime Pools | Production deployment |
| Independent Gateway egress security domain | When Model/Tool credential isolation required |
| mTLS/SPIFFE and short-lived credential broker | Enterprise security compliance |
| Per-tenant/region Workflow Namespace, Queue, Object Store, keys | Multi-tenant production |
| WORM Audit, SIEM export, DLP, data deletion orchestration | Compliance requirements |
| Shadow/Canary runtime environments, evaluation-dedicated Worker Pool | Governed evolution (Phase 4) |
| High-cardinality analytics store | Advanced AI FinOps, but must not replace Core DB |

## 3. Service Split Conditions

A module is only split into an independent service when **multiple** of these conditions hold simultaneously:

1. Independent team and lifecycle
2. Stable remote contract already exists
3. Requires independent security domain, credential domain, or data region
4. Scaling curve significantly differs from the main application
5. Fault isolation or multi-platform reuse benefit exceeds the cost of network hops and operational complexity

Logical planes do not equal microservice count. The initial three-process deployment (API, Worker, Cockpit) is intentional.

## 4. Security Boundaries

### Network Segmentation

- Public ingress: API and Cockpit only.
- Worker has no public ingress—pulls work from Temporal.
- Model/Tool Gateway outbound is through controlled egress network.
- High-risk enterprise environments should deploy Gateway data plane in a controlled outbound network, isolated from public ingress and the console.

### Credential Management

- Model provider credentials are injected only into the Gateway process.
- Short-lived credentials are brokered at Action execution time.
- Credentials must never enter Prompts, Logs, or Artifacts.

## 5. Storage Layout

| Store | Contents | Not For |
|---|---|---|
| PostgreSQL | Core objects, versions, indices, approvals, budgets, Outbox/Inbox, Audit metadata | Large Artifact bodies |
| Durable Workflow Store | Workflow events, Timers, Signals, Retries, Replay history | Business authoritative state |
| Object Store | Immutable Evidence/Artifact payloads, reports, transcripts | Queryable state machines |
| Event Bus | Event delivery and subscriptions | Long-term authoritative state |
| Search/Vector | Rebuildable retrieval projections | Authoritative Knowledge/Memory/State |
| Telemetry Backend | Metrics, Logs, Traces, and analytical projections | Final business judgment of Goal/Outcome |

## 6. Disaster Recovery

- PostgreSQL must have PITR, backup verification, regular recovery drills, and tenant-level data recovery.
- Workflow Engine must verify Worker loss, redeployment, Replay, and cross-region recovery.
- Object Store requires versioning, optional object locks, integrity digests, and lifecycle policies.
- Event Bus is not an authority source; pending events must be rebuildable from the Outbox.
- Credentials, keys, policies, and Stable Pointers need independent backup and emergency rotation procedures.
- Runbooks must cover: Provider failure, large-scale Tool Unknown, approval backlog, Memory poisoning, suspected tenant leakage, Candidate rollback, and Kill Switch.

## 7. Observability & AI FinOps

Telemetry must correlate by Goal/Run as the top-level dimension, not just by model call.

### Key Metrics

| Category | Examples |
|---|---|
| **Outcome** | Goal satisfaction rate, Outcome verified rate, Evidence completeness |
| **Reliability** | Run success/block/cancel rate, Action unknown rate, recovery time |
| **Quality** | Evaluation pass rate, regression rate, human correction rate |
| **Security** | Policy deny rate, approval bypass attempts, prompt injection, cross-tenant violations |
| **Cost** | Cost per verified Goal, token/tool/sandbox cost, wasted retry cost |
| **Efficiency** | Time-to-first-plan, time-to-outcome, approval wait, critical path duration |
| **Evolution** | Candidate win rate, canary rollback rate, time-to-stable, capability drift |

The optimization target is **total cost per verified successful Goal**—not single token price or single model latency.
