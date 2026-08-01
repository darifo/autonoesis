# Autonoesis

> Enterprise Governed Self-Evolving Agent Operating System
>
> 企业级受治理自进化智能体操作系统

Autonoesis is a greenfield platform for building enterprise agents that operate across time, learn from real outcomes, and evolve through governed, auditable, and reversible releases.

It is not a single “large agent.” The platform separates goals, durable execution, context, memory, tools, evidence, evaluation, and release governance so that every important action has an owner, a policy boundary, and verifiable outcome evidence.

## Core principles

- **Goal is not prompt.** Goals carry scope, constraints, success criteria, and risk boundaries.
- **State is authoritative.** PostgreSQL owns accepted business state; durable workflow history does not replace it.
- **Runtime is not harness.** Runtime controls order, isolation, recovery, and resources; harnesses execute bounded tasks.
- **Tools do not grant authority.** Every side effect is re-authorized at execution time.
- **Output is not outcome.** Real-world completion requires evidence.
- **Evolution is a release process.** Improvements become candidates and pass evaluation, approval, shadow/canary, and rollback gates.

## Repository shape

```text
autonoesis/
├── apps/                 # independently deployable processes
│   ├── api/
│   ├── worker/
│   ├── cockpit/
│   └── gateway/          # reserved deployment boundary
├── packages/             # internal domain and platform modules
├── infra/                # delivery, policy, observability, migrations
├── examples/             # reference agents and evaluation suites
├── docs/                 # architecture, ADRs, contracts, threats, runbooks
└── tools/                # code generation, development, release utilities
```

The initial deployment has three processes: API, Worker, and Cockpit. Gateway logic starts as shared packages and becomes an independent process only when security, scale, or reuse justifies the operational cost.

## Current status

The repository is in **Phase 0 — architecture baseline and contracts**. The initial code is intentionally small: it establishes dependency direction, stable vocabulary, a health endpoint, a worker entry point, and contract/domain/runtime seams without prematurely implementing provider integrations.

## Quick start

Prerequisites:

- [Conda](https://docs.conda.io/) (Python and `uv` are installed through `environment.yml`)
- Node.js 22+ and pnpm (Cockpit work begins after its UI ADR)
- Docker or another OCI-compatible local runtime for infrastructure work
- [Task](https://taskfile.dev/) for the unified commands below

```bash
conda env create --file environment.yml
conda activate autonoesis
task bootstrap
task check
task test
task api
```

Without Task:

```bash
conda env create --file environment.yml
conda activate autonoesis
UV_PROJECT_ENVIRONMENT="$CONDA_PREFIX" uv sync --inexact --all-packages --dev
pytest
uvicorn autonoesis_api.main:app --reload --app-dir apps/api/src
```

## Documentation

- [Architecture overview](docs/architecture/overview.md)
- [Repository boundaries](docs/architecture/repository-layout.md)
- [Architecture decisions](docs/adr/README.md)
- [Contract rules](docs/contracts/README.md)
- [Threat model](docs/threat-models/README.md)
- [Local development runbook](docs/runbooks/local-development.md)
- [MVP roadmap](docs/roadmap/mvp.md)
- [Contributing](CONTRIBUTING.md)
- [Security policy](SECURITY.md)

## License

[MIT](LICENSE)
