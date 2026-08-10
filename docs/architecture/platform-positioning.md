# Platform Positioning & Deployment Model

> Status: baseline · Last reviewed: 2026-08-10

## What Autonoesis Is

Autonoesis is a **general-purpose Enterprise Agent Platform runtime base**. It is
**not** an end-user AI application. It is the infrastructure layer that
enterprises build *on top of* to create governed, auditable, self-improving
intelligent agents for their specific business domains.

**Think of it as**: What Kubernetes is to container orchestration,
Autonoesis aims to be for AI agent execution — a universal runtime base that
handles scheduling, recovery, and governance, while you define the domain logic.

Kubernetes does not know your business application, but it provides scheduling,
self-healing, and resource isolation. Autonoesis does not know your industry,
but it provides Goal execution, tool governance, evidence chains, and
controlled self-evolution.

---

## What Autonoesis Is NOT

- **Not a "big agent"** — It does not ship with a pre-trained LLM or a fixed toolset.
  You bring your models, your tools, and your evaluation criteria.
- **Not an industry solution** — It contains zero industry-specific vocabulary.
  `pump`, `transaction`, `prescription` do not appear in the core codebase.
- **Not a chatbot framework** — It is built for durable, multi-step execution
  over hours or days, not for conversational turn-taking.
- **Not a LangChain/CrewAI/AutoGPT competitor** — Those are rapid-prototyping
  frameworks where the LLM directly drives state changes. Autonoesis enforces
  a governance layer between "the model wants to do X" and "X actually happens".

---

## Core Differentiation

| Dimension | Generic Agent Frameworks | Autonoesis |
|---|---|---|
| **Execution model** | Agent Loop (while True: think → act) | Deterministic Temporal Workflow + bounded Agent Loop |
| **Crash recovery** | Unknown — restart from scratch | Workflow History replays from last checkpoint |
| **State authority** | LLM itself declares "done" | PostgreSQL (ACID) + Evidence verification |
| **Side-effect safety** | Tool called directly | GovernedToolGateway (Kill Switch → Policy → Budget → Approval → Idempotency → Execute → Verify) |
| **Auditability** | Conversation logs | Immutable ContextSnapshot + Evidence content-hash + Audit Events |
| **Self-evaluation** | LLM grades itself | EvaluationHarness (independent grader; grader ≠ generator) |
| **Self-improvement** | Manual prompt tuning | Shadow → Canary → Stable pipeline with automated guardrails |
| **Multi-tenant isolation** | None or basic | Row-Level Security, cross-tenant request rejection |
| **Industry neutrality** | N/A (always coupled to specific tools) | Capability Pack is the sole industry-injection point |

---

## When to Use Autonoesis

Autonoesis is the right choice when your use case requires **at least two** of
the following:

1. **Executing actions, not just generating text** — the agent writes to your
   production systems (ERP, CRM, IoT, payment gateways).
2. **An audit trail that survives a regulatory review** — every decision must
   be traceable to its inputs, policy version, and human approver.
3. **Crash recovery** — the agent task spans minutes to hours; a process crash
   must not lose in-flight state.
4. **Controlled evolution** — agent behavior is updated frequently and must
   pass automated tests before reaching production traffic.
5. **Multi-tenant SaaS deployment** — multiple customers share the platform;
   data isolation is non-negotiable.

If your use case is "chatbot that answers FAQs" or "content summarizer",
generic frameworks are sufficient. Autonoesis is for when the agent **acts on
the world** and must **prove it did the right thing**.

---

## Enterprise Deployment Model

### Architecture

```
┌─────────────────────────────────────────────────┐
│                  Cockpit (React)                 │  ← 运营控制台
├─────────────────────────────────────────────────┤
│                  API (FastAPI)                   │  ← 控制面: CRUD Goal/Run/Approval
├─────────────────────────────────────────────────┤
│               Worker (Temporal)                  │  ← 执行面: Workflow + Activity
├──────────┬──────────┬──────────┬────────────────┤
│ Postgres │ Temporal │   OPA    │  MinIO          │  ← 基础设施
│ (状态)    │ (工作流)  │ (策略)   │  (证据)         │
├──────────┴──────────┴──────────┴────────────────┤
│          Capability Packs (行业插件)              │  ← 企业自定义
│          Tool Adapters (业务系统对接)             │
└─────────────────────────────────────────────────┘
```

### Deployment Sizes *(estimated targets, not yet benchmarked)*

| Scale | Configuration | Typical Use |
|---|---|---|
| **Dev/Test** | Docker Compose, 16 GB | 1-5 Agents, local development |
| **Small Production** | 2× nodes, 64 GB each | 5-20 Agents, <500 Goals/day, single tenant |
| **Medium Production** | PostgreSQL HA + Temporal Cluster | 20-100 Agents, <5 000 Goals/day, multi-tenant |
| **Large Production** | Kubernetes + Helm, auto-scaling | >100 Agents, dedicated DB/Temporal clusters |

### What the Enterprise Brings

Autonoesis provides the **platform**. The enterprise provides:

| Layer | What You Build |
|---|---|
| **Capability Pack** | YAML manifest: Goal Types, Tools, Skills, Policies, Evaluation Suites |
| **Tool Adapters** | Implement `ToolExecutor` Protocol (2 methods: `execute`, `verify`). Connect to your SAP, MES, IoT, payment systems |
| **Evaluation Cases** | Define "what good looks like" in your domain |
| **Policies** | OPA Rego rules: who can approve what, dollar limits, compliance checks |
| **OIDC** | Connect to your corporate IdP (Keycloak, Okta, Azure AD) |
| **Cockpit Customization** | Optional: brand the UI, add domain-specific dashboards |

---

## Platform Boundaries

```
┌── Autonoesis Responsibility ──────────────────────┐
│                                                     │
│  ✓ Goal lifecycle management                       │
│  ✓ Durable execution (Temporal Workflows)           │
│  ✓ Tool governance pipeline (Policy/Budget/Approval)│
│  ✓ Evidence collection & Outcome verification       │
│  ✓ Evaluation suite execution                       │
│  ✓ Shadow/Canary deployment pipeline                │
│  ✓ Multi-tenant isolation                           │
│  ✓ Kill Switch / Reconciler                         │
│                                                     │
├── Enterprise Responsibility ────────────────────────┤
│                                                     │
│  ✓ Define Goal Types & business logic               │
│  ✓ Build Tool Adapters (connect to YOUR systems)     │
│  ✓ Write Evaluation Cases (YOUR definition of good) │
│  ✓ Configure Policies (YOUR compliance rules)        │
│  ✓ Operate (Cockpit usage, approval decisions)      │
│  ✓ Integrate IdP (YOUR authentication)              │
│                                                     │
└─────────────────────────────────────────────────────┘
```

The platform does **not** embed industry-specific schema or business logic,
and does **not** initiate connections to your external systems. It *does* persist
business data as part of the evidence chain (`GoalContract.input_payload`,
`Evidence.observed_state`), but only in a schema-agnostic way — the platform
never interprets the meaning of your data. It guarantees that whatever you
choose to do, the **execution is governed, the evidence is immutable, and
the evolution is safe**.

---

## See Also

- [Integration Guide](integration-guide.md) — SOP/SPI architecture, how to connect business systems
- [Application Scenarios](application-scenarios.md) — industry use cases with full walkthrough
- [Domain Model](domain-model.md) — core entities and state machines
