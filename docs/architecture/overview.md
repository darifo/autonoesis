# Autonoesis Architecture Overview

> Status: target architecture · Last reviewed: 2026-08-16 · Applicable version: 0.1.x
> Implementation evidence: [capability maturity matrix](../roadmap/capability-maturity.md)

## 1. System Responsibility

Autonoesis targets an industry-agnostic, AI-native agent runtime base. It does not own external business system state—customers, orders, devices, medical records, contracts, or projects. Instead, the target platform references these authoritative objects via `SubjectRef` and takes responsibility for the facts of intelligent execution: Goal, Run, Plan, Decision, Action, Evidence, Outcome, and governed evolution.

Core closed loop:

```text
Intent → GoalContract → ContextSnapshot → Plan → Decision
→ Durable Run → Task → Governed Action → Evidence → Outcome
→ Evaluation → ImprovementProposal → Candidate → Stable / Rollback
```

## 2. Eight Logical Planes

Planes are logical responsibility boundaries, not mandatory physical deployment units. The prototype defines API, Worker, and Cockpit process entry points; it is not a production deployment.

| Plane | Core Question | Target Components |
|---|---|---|
| Interaction | Where do requests come from, who is the caller, how are they normalized? | FastAPI, Cockpit, Python/TS SDK |
| Intelligence | What is the goal, and how should we plan and decide? | Goal Manager, Planner, Decision, Capability Selector |
| Runtime | How does the plan advance reliably across time? | Durable Workflow, Harness, Checkpoint, Workspace |
| Environment | What is the verifiable state of the outside world right now? | Fact Registry, Projection, Freshness, Simulation |
| Context | What should this run see? | Retrieval, ACL Filter, Rank, Conflict, Compression, Snapshot |
| Integration | How do we safely connect models, tools, and other agents? | Model Gateway, Tool Gateway, MCP Host, A2A Gateway |
| Data & Evidence | How do we persist state, history, evidence, and telemetry? | PostgreSQL, Object Store, Event Bus, Audit, Telemetry |
| Governance | On what authority does an agent act, and who can approve or take over? | Identity, Delegation, Policy, Approval, Budget, Kill Switch |

## 3. Three Flows That Must Not Be Confused

| Flow | Primary Path | Inviolable Boundary |
|---|---|---|
| Control | Request → Goal → Plan → Decision → Run Command → State Transition | Model output cannot directly become authoritative state |
| Execution | Task → Harness → Model/Skill → Tool Proposal → Action → Result | Tool calls must pass execution-time governance |
| Evidence | Snapshot/Decision/Invocation/Artifact/Fact → Evidence → Outcome → Evaluation | The generator cannot independently prove its own success |

## 4. Goal-First Business Model

The core provides no generic `Case`. `GoalContract` is the single business driver, containing:

- Goal Type and versioned input payload
- One or more external `SubjectRef` references
- Desired Outcome, success criteria, and required Evidence
- Owner, risk tier, constraints, budget limit, and deadline
- Current status with optimistic lock versioning

External systems map their business entities to Goals as they see fit. A CRM might map a complaint to multiple Goals; an ERP might map an order to fulfillment, exception-handling, and review Goals. How business entities are aggregated is the external system's concern—not the platform's.

## 5. Capability Pack

Industry capabilities are installed through versioned Capability Packs (`capability-pack.yaml`). A manifest declares:

- Goal Types with JSON Schema
- Agent, Skill, and Tool definitions
- Policies, default budgets, and risk requirements
- Evaluation Suites with test cases
- Python Entry Point for complex behavior

The target installation path validates: API version, SemVer, strict field and JSON Schema checks, manifest/entry point version matching, identifier uniqueness, dependency integrity, tenant authorization, and audit recording. Current validation is limited to the evidence listed in the maturity matrix.

## 6. Authoritative State & Durable Workflows

| Store | Authoritative For | Not Authoritative For |
|---|---|---|
| PostgreSQL | Goal, Run, Action, Approval, Outcome, Evaluation, Release metadata | Large Artifact bodies |
| Durable Workflow Engine | Workflow events, Timers, Signals, Retries, Replay history | Business authoritative state |
| Object Store | Immutable Evidence/Artifact payloads, reports, transcripts | Queryable state machines |
| Event Bus | Event delivery and subscriptions | Long-term authoritative state |
| Search/Vector | Rebuildable retrieval projections | Authoritative Knowledge/Memory/State |

Temporal Activities that modify business state must call Application transactions. External writes use stable idempotency keys. After timeout, Actions enter `Unknown`—query real state first, then decide success, failure, compensation, or human takeover.

## 7. Workflow vs. Agent Loop

Default to deterministic Workflow. Agent Loop is only used when the next Task step depends on open-ended observation and cannot be pre-enumerated. Each Agent Loop must fix:

- Agent Version, Context Snapshot ID
- Visible Tool set and operable resource scope
- Maximum turns, tokens, cost, time, concurrency, and sub-agent depth
- Success, failure, blockage, escalation, and emergency termination conditions
- Observable transcript to preserve vs. hidden reasoning to discard

Model output is always a structured proposal. It cannot directly mutate authoritative state or acquire permissions.

## 8. Model & Tool Gateway

**Model Gateway**: Hard-filter by capability, data region, and risk first. Then select by quality, latency, cost, quota, and historical success rate. Fallback in explicit, auditable order.

**Tool Gateway** enforces a fixed execution pipeline:

```text
Identity → Delegation → Policy Decision → Schema Validation → Risk Classification
→ Budget/Quota Check → Exact-Parameter Approval → Credential Brokering
→ Idempotency Reservation → Execute in Egress/Sandbox → Normalize Result
→ Verify Effect → Record Evidence and Audit
```

Approval binds to Action parameter digest. Any parameter change requires re-approval. Tool returns `accepted` before `verify` reads the authoritative system.

## 9. Governed Evolution

Post-run Analysis proposes an `ImprovementProposal`. Allowed targets: Agent Instruction, Skill, Prompt Asset, Model Route. Forbidden: identity, policy, tenant isolation, security classification, audit retention, production code, and infrastructure.

Candidate generator, grader, and approver must be separate. The pipeline is:

```text
Draft → Evaluating → Awaiting Approval → Approved → Shadow → Canary → Stable
Stable → Rolled Back
```

Each Stable retains a pointer to the previous Stable for rollback.

## 10. Deployment

Local Compose starts PostgreSQL, Temporal, OPA, MinIO, OpenTelemetry/Jaeger, API, Worker, and Cockpit as a development prototype. API/Worker production paths use PostgreSQL authority when configured, but default local credentials, controlled external-authority simulators, incomplete production failure evidence and static Cockpit data make this stack unsuitable for production. Kubernetes, real Evaluation/Shadow/Canary execution, and production hardening remain planned work.

See [deployment.md](deployment.md) for detailed deployment architecture.

## Further Reading

| Document | Content |
|----------|---------|
| [platform-positioning.md](platform-positioning.md) | Platform positioning, competitive differentiation, enterprise deployment model |
| [integration-guide.md](integration-guide.md) | SOP/SPI architecture, how to connect business systems step-by-step |
| [application-scenarios.md](application-scenarios.md) | Industry use cases with full architectural walkthrough (maintenance, compliance, procurement) |
| [domain-model.md](domain-model.md) | Core domain objects, state machines, and entity relationships |
| [runtime-and-flows.md](runtime-and-flows.md) | Workflow vs. Agent Loop, failure recovery, execution flows |
| [deployment.md](deployment.md) | Infrastructure layout, Docker Compose, production evolution |
