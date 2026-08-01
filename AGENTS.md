# AGENTS.md

This file defines repository-wide instructions for human and AI contributors.

## Mission

Build Autonoesis as an enterprise governed self-evolving agent operating system. Optimize for durable execution, explicit authority, evidence-based outcomes, and reversible improvement—not demo-only autonomy.

## Greenfield constraint

- This repository is a greenfield implementation.
- Do not import, copy, inspect, migrate, or preserve behavior from the previously abandoned local Hermes projects.
- Upstream Hermes, Codex, OpenAI Agents SDK, Honcho, MCP, and A2A are replaceable adapters or protocols. Their internal models must not become Autonoesis domain models.

## Architecture rules

- `packages/domain` contains pure domain behavior and invariants. It must not depend on FastAPI, Temporal, provider SDKs, databases, queues, or ORMs.
- `packages/contracts` contains stable cross-process and cross-language schemas. Do not duplicate domain behavior there.
- `packages/application` owns use-case orchestration and transaction boundaries.
- `apps/*` own process assembly, protocol entry points, configuration, and lifecycle only.
- `packages/adapters/*` implement ports. Provider objects must not leak into domain or application APIs.
- PostgreSQL is the authority for accepted business state. Temporal is the authority for durable workflow history.
- A model may propose a command or action; it may not directly mutate authoritative state.
- Every external side effect must pass execution-time identity, delegation, policy, budget, and argument checks.
- Context, knowledge, memory, session history, and environment facts are different concepts. Do not merge them into a generic vector-store abstraction.
- Evaluation and improvement remain separate. A component must not generate, grade, and release its own candidate without independent gates.

## Engineering workflow

- Use Conda for the Python virtual environment and `uv` for workspace dependency locking.
- Set `UV_PROJECT_ENVIRONMENT="$CONDA_PREFIX"` and pass `--inexact` when running `uv sync` inside the activated `autonoesis` Conda environment; do not replace Conda-managed packages or create a project-local `venv` or `.venv`.
- Use `pnpm` for TypeScript workspaces.
- Prefer `task <command>` as the repository-level interface.
- Add or update an ADR when a change affects a process boundary, authority, protocol, persistence model, security boundary, or release policy.
- Add tests for state transitions, idempotency, authorization, recovery, and negative paths—not only happy-path model outputs.
- Generated files must live under an explicitly named `generated/` directory and must not be hand-edited.
- Never commit secrets, production data, raw customer prompts, or unredacted traces.

## Definition of done

A change is complete when its relevant formatting, lint, type, unit, contract, and security checks pass; architecture or runbook documentation is updated; and the evidence required to validate behavior is recorded.
