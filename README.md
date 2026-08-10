<p align="center">
  <img src="docs/assets/autonoesis-logo.svg" alt="Autonoesis Logo" width="200"/>
</p>

<p align="center">
  <strong>Enterprise Governed Self-Evolving Agent Operating System</strong>
</p>

<p align="center">
  <a href="https://github.com/darifo/autonoesis/actions/workflows/ci.yml">
    <img src="https://github.com/darifo/autonoesis/actions/workflows/ci.yml/badge.svg" alt="CI"/>
  </a>
  <a href="LICENSE">
    <img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License"/>
  </a>
  <a href="https://www.python.org/downloads/">
    <img src="https://img.shields.io/badge/python-3.12+-blue.svg" alt="Python"/>
  </a>
  <a href="https://nodejs.org/">
    <img src="https://img.shields.io/badge/node-%3E%3D22-green.svg" alt="Node"/>
  </a>
  <img src="https://img.shields.io/badge/tests-122%20passed-brightgreen.svg" alt="Tests"/>
  <img src="https://img.shields.io/badge/mypy-strict%20clean-brightgreen.svg" alt="MyPy"/>
</p>

---

**Autonoesis** is not a "big agent" stacked with prompts and tools. It is an
enterprise platform that takes **responsibility for the facts of intelligent
execution** — governing every action, verifying every outcome, and safely
evolving agent behavior over time.

```text
Intent → GoalContract → ContextSnapshot → Plan → Durable Run → Task
→ Governed Action → Evidence → Outcome → Evaluation
→ ImprovementProposal → Candidate → Shadow/Canary/Stable/Rollback
```

[中文说明](README.zh-CN.md) ·
[Architecture](docs/architecture/overview.md) ·
[ADR](docs/adr/README.md) ·
[Roadmap](docs/roadmap/mvp.md) ·
[Integration Guide](docs/architecture/integration-guide.md)

---

## Why Autonoesis

| Capability | What It Means |
|---|---|
| **Goal-First** | Work is a verifiable `GoalContract` — not a chat message. Success criteria, budget, and deadline are explicit. |
| **Durable Execution** | Goals survive disconnections, crashes, and restarts via Temporal durable workflows. |
| **Governed Action** | Every external side effect passes identity, policy, budget, approval, and idempotency checks at runtime. |
| **Evidence-Based Outcomes** | A tool saying "done" is not proof. Outcomes are verified by reading authoritative state from external systems. |
| **Governed Evolution** | Improvements become Candidates, pass independent evaluation gates, and promote Shadow → Canary → Stable with automatic rollback. |
| **Multi-Tenant Isolation** | Tenants are isolated across identity, data, credentials, runtime, network, budget, and release dimensions. |

### How It Compares

Autonoesis is **not** a LangChain, CrewAI, or AutoGPT alternative. Those are
rapid-prototyping frameworks where the LLM directly drives state. Autonoesis
enforces a governance layer between "the model wants to do X" and "X actually
happens." See [Platform Positioning](docs/architecture/platform-positioning.md)
for the full comparison.

---

## Quick Start

```bash
# Create and activate environment
conda env create -f environment.yml
conda activate autonoesis

# Install Python workspace
UV_PROJECT_ENVIRONMENT="$CONDA_PREFIX" uv sync --inexact --all-packages --dev

# Install TypeScript workspace
pnpm install

# Run all quality checks
ruff format --check . && ruff check . && mypy apps packages --ignore-missing-imports && pytest
```

### Full Platform (Docker Compose)

```bash
docker compose -f infra/compose/docker-compose.yml up --build
```

| Service | URL |
|---|---|
| API (Swagger) | http://localhost:8000/docs |
| Cockpit | http://localhost:4173 |
| Temporal UI | http://localhost:8088 |
| MinIO Console | http://localhost:9001 |
| Jaeger | http://localhost:16686 |

### Single-Process Development

```bash
python -m uvicorn autonoesis_api.main:app --reload   # API
pnpm --filter @autonoesis/cockpit dev                 # Cockpit
python -m autonoesis_worker.main                       # Worker
```

---

## Architecture

Autonoesis organizes responsibility into **eight logical planes** (not eight
microservices). The current deployment uses three processes: **API**, **Worker**,
and **Cockpit**.

| Plane | Responsibility | Implementation |
|---|---|---|
| **Interaction** | Who is calling? | FastAPI, Cockpit, SDKs |
| **Intelligence** | What should we do? | Goal Clarifier, Planner, Capability Selector |
| **Runtime** | How does the plan advance? | Temporal Workflows, Harness, Checkpoint |
| **Environment** | What's the state of the world? | Fact Registry, Projection, Refresh |
| **Context** | What should this run see? | Retrieval, ACL, Freshness, Compression, Snapshot |
| **Integration** | How to safely connect tools? | Model Gateway, Tool Gateway, MCP/A2A |
| **Data & Evidence** | How to persist and prove? | PostgreSQL, MinIO, Audit, Telemetry |
| **Governance** | On what authority? | Identity, Policy, Budget, Approval, Kill Switch |

**Read more**: [Architecture Overview](docs/architecture/overview.md) ·
[Integration Guide](docs/architecture/integration-guide.md) ·
[Application Scenarios](docs/architecture/application-scenarios.md)

---

## Project Structure

```
autonoesis/
├── apps/
│   ├── api/              # FastAPI control plane (HTTP/SSE)
│   ├── worker/           # Temporal Worker (workflows + activities)
│   ├── cockpit/          # React operations console
│   └── gateway/          # Reserved: independent Tool/Model data plane
├── packages/
│   ├── domain/           # Pure domain objects, state machines, invariants
│   ├── contracts/        # Cross-process schemas & envelopes
│   ├── application/      # Command/Query handlers, transaction boundaries
│   ├── runtime-kernel/   # Harness SPI, Gateway protocols, Kill Switch
│   ├── capability/       # Capability Pack manifest & validation
│   ├── intelligence/     # Goal clarification, planning, decisions
│   ├── context/          # Retrieval, ACL, freshness, compression
│   ├── environment/      # Facts, projections, refresh, simulation
│   ├── memory/           # Memory SPI, ledger, write gate, deletion
│   ├── gateways/         # Model/Tool/MCP/A2A boundaries
│   ├── governance/       # Identity, policy, budget, kill switch
│   ├── evaluation/       # Cases, suites, trials, graders
│   ├── improvement/      # Analysis, proposals, releases
│   ├── evolution/        # Replay, Shadow/Canary, FinOps, SLO
│   ├── adapters/         # Provider/Protocol/Persistence adapters
│   ├── testkit/          # Fakes, attack suites, contract tests
│   ├── py-sdk/           # Python client SDK
│   └── ts-sdk/           # TypeScript client SDK
├── docs/                 # Architecture, ADR, Contracts, Runbooks
├── infra/                # Compose, Migrations, Policies, Helm, Terraform
├── examples/             # Reference Capability Packs
└── tools/                # Codegen, dev CLI, release tooling
```

**Dependency rule**: `apps → application → domain`. Domain depends on nothing.
Adapters implement ports defined by domain/application/runtime-kernel.

---

## Phases

| Phase | Status | Focus |
|---|---|---|
| **Phase 0** | ✅ Complete | Domain language, core objects, state machines, monorepo skeleton |
| **Phase 1** | ✅ Complete | API, PostgreSQL, Temporal, Cockpit, Model/Tool adapters, reference Pack |
| **Phase 2** | ✅ Complete | Outbox/Inbox, Kill Switch, MinIO Evidence, real Temporal Activities, Tool reconciliation, MCP adapter |
| **Phase 3** | ✅ Complete | Replay/Simulation, Shadow/Canary, Auto-Rollback, AI FinOps, SLO, Repeat Trials, stub packages filled |
| **Phase 4** | 📋 Planned | Kubernetes, backup/restore, Grafana dashboards, SAST, production hardening |

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development process and definition
of done. See [AGENTS.md](AGENTS.md) for architecture rules and immutable
constraints — domain purity, dependency direction, and greenfield boundaries.

## License

Released under the [MIT License](LICENSE).
