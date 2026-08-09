# Autonoesis

**Enterprise Governed Self-Evolving Agent Operating System**

Autonoesis is not a "big agent" stacked with prompts, tools, and long-term memory. It is an enterprise platform that takes responsibility for the facts of intelligent execution:

- **Goal-first**: Every unit of work is a verifiable `GoalContract` with success criteria, constraints, budget, and deadline.
- **Durable execution**: Goals advance across time, pauses, approvals, cancellations, and process restarts via durable workflows.
- **Governed action**: Every external side effect passes identity, delegation, policy, risk, budget, approval, and idempotency checks at execution time.
- **Evidence-based outcomes**: Tool success is a receipt—not proof. Outcomes are verified by reading authoritative state from external systems.
- **Governed evolution**: Improvements become Candidates, pass independent evaluation gates, and promote through Shadow → Canary → Stable with rollback.

```
Intent → GoalContract → ContextSnapshot → Plan → Durable Run → Task
→ Governed Action → Evidence → Outcome → Evaluation
→ ImprovementProposal → Candidate → Shadow/Canary/Stable/Rollback
```

[中文说明](README.zh-CN.md) · [Architecture](docs/architecture/overview.md) · [ADR](docs/adr/README.md) · [Roadmap](docs/roadmap/mvp.md)

---

## Why Autonoesis

| Promise | Engineering meaning |
|---|---|
| Durable Agency | Tasks survive HTTP disconnections, Worker crashes, and Session closures |
| Explicit Authority | Identity, delegation, permissions, budget, and approval are explicit objects—not prompt instructions |
| Evidence-Based Outcome | Tool receipts are not proof; authoritative readback verifies real-world results |
| Governed Evolution | Improvements are Candidates that pass independent evaluation and release gates |
| Replaceable Intelligence | Models, Harnesses, Memory Providers, and MCP/A2A implementations are replaceable adapters |
| Enterprise Isolation | Tenants are isolated across identity, data, credentials, runtime, network, budget, and release dimensions |

---

## Quick Start

```bash
# Create and activate the Conda environment
conda env create -f environment.yml
conda activate autonoesis

# Install Python workspace
task bootstrap

# Install TypeScript workspace
pnpm install

# Run quality checks
task check
```

Start the full local platform:

```bash
docker compose --file infra/compose/docker-compose.yml up --build
```

- API docs: http://localhost:8000/docs
- Cockpit: http://localhost:4173
- Temporal UI: http://localhost:8088

Single-process development:

```bash
task api                           # FastAPI with hot reload
pnpm --filter @autonoesis/cockpit dev  # React dev server
```

---

## Architecture At a Glance

Autonoesis organizes responsibility into **eight logical planes**—not eight microservices:

| Plane | Core question | Implementation |
|---|---|---|
| Interaction | Who is calling, through what channel? | FastAPI, Cockpit, SDKs |
| Intelligence | What is the goal, and how should we plan? | Goal Manager, Planner, Decision, Capability Selector |
| Runtime | How does the plan advance reliably across time? | Durable Workflow, Harness, Checkpoint, Workspace |
| Environment | What is the verifiable state of the outside world? | Fact Registry, Projection, Freshness, Simulation |
| Context | What should this run see? | Retrieval, ACL Filter, Rank, Conflict, Compression, Snapshot |
| Integration | How do we safely connect models, tools, and other agents? | Model Gateway, Tool Gateway, MCP Host, A2A Gateway |
| Data & Evidence | How do we persist state, history, evidence, and telemetry? | PostgreSQL, Object Store, Event Bus, Audit, Telemetry |
| Governance | On what authority does an agent act? | Identity, Delegation, Policy, Approval, Budget, Kill Switch |

The current deployment is three processes: **API**, **Worker**, and **Cockpit**.

---

## Repository Structure

```
autonoesis/
├── apps/
│   ├── api/          # HTTP/SSE/Webhook control plane
│   ├── worker/       # Durable Workflow/Activity/Harness worker
│   ├── cockpit/      # Operations, approval, evidence, evaluation, release console
│   └── gateway/      # Independent Model/Tool data plane (when scaling warrants)
├── packages/
│   ├── domain/       # Pure domain objects, state machines, invariants
│   ├── contracts/    # Cross-process schemas, envelopes, error catalog
│   ├── application/  # Command/Query handlers, unit-of-work, transaction boundaries
│   ├── capability/   # Capability Pack manifest, discovery, installation, validation
│   ├── intelligence/ # Goal clarification, planning, decision, capability selection
│   ├── runtime-kernel/ # Orchestrator, Harness SPI, Workspace, Checkpoint
│   ├── context/      # Retrieval, ACL, freshness, conflict, compression, snapshot
│   ├── environment/  # Environment facts, projections, refresh, simulation
│   ├── memory/       # Memory SPI, ledger, write gate, deletion propagation
│   ├── gateways/     # Model, Tool, MCP, A2A, Channel unified boundaries
│   ├── governance/   # Identity, delegation, policy, approval, budget, audit
│   ├── evaluation/   # EvaluationCase, Suite, Trial, Harness, Grader
│   ├── improvement/  # Analysis, Proposal, Candidate, Release, Rollback
│   ├── adapters/     # Provider/Protocol/Persistence adapters
│   └── testkit/      # Fake providers, attack suites, contract test support
├── sdk/              # Python / TypeScript client SDKs
├── examples/         # Reference Capability Packs (public interfaces only)
├── infra/            # Compose, Helm, IaC, Policy, OTel, Supply Chain
├── docs/             # Architecture, ADR, Contracts, Threat Models, Runbooks
└── tools/            # Codegen, Schema Check, Release, Dev CLI
```

**Dependency direction**: `apps → application → domain` · `domain` must not depend on frameworks · `core` must not depend on `examples`

---

## Core Domain Model

| Object | Semantics |
|---|---|
| `SubjectRef` | Stable reference to an external authoritative business object |
| `GoalContract` | A manageable, verifiable goal with criteria, constraints, budget, and deadline |
| `Session` | Interaction continuity—not execution lifecycle |
| `Run` | An independently auditable, recoverable execution |
| `Plan` | Versioned Task DAG with assumptions |
| `Task` | A schedulable unit of work with no external side-effect semantics |
| `DecisionRecord` | Why something was executed, rejected, escalated, or re-planned |
| `Action` | The smallest governable external side-effect boundary |
| `Evidence` | A citable observation of real-world state |
| `Outcome` | Whether a success criterion was met in reality |
| `CandidateVersion` | A new capability version before production release gates |

---

## Phases

| Phase | Status | Focus |
|---|---|---|
| **Phase 0** | ✅ Complete | Domain language, core objects, state machines, monorepo skeleton, ADR templates |
| **Phase 1** | ✅ Complete | API, PostgreSQL, Durable Workflow, Cockpit, Model/Tool adapters, reference Capability Pack |
| **Phase 2** | 🚧 Planned | Unified Model/Tool Gateway, credential brokering, evidence reconciliation, SLO, Kill Switch |
| **Phase 3** | 📋 Planned | Context assembly, Memory write gate, Multi-Agent, long-task compression |
| **Phase 4** | 📋 Planned | Governed self-evolution, Candidate pipeline, Shadow/Canary, auto-rollback |

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) and [AGENTS.md](AGENTS.md) for architecture rules, engineering workflow, and the definition of done.

## License

Released under the [MIT License](LICENSE).
