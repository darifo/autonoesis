# Runtime, Orchestrator & Harness

> Status: baseline · Last reviewed: 2026-08-09 · Applicable version: 0.1.0

## 1. Responsibility Separation

| Component | Responsible For | Not Responsible For |
|---|---|---|
| **Orchestrator** | Task dependencies, state advancement, Timers, Signals, parallelism, retries, and recovery | Free-form reasoning, direct high-risk tool invocation |
| **Runtime** | Run isolation, resources, Workspace, Sandbox, Lease, Heartbeat, Cancellation | Business goal definition |
| **Harness** | Assembling Agent Version, Context Snapshot, Model, Skill, Tool Scope, Loop, and telemetry | Global Run state, enterprise authorization, Stable release |
| **Agent Loop** | Selecting the next step within a Task based on observation | Unbounded autonomy, declaring Goal completion without Evidence |

## 2. Workflow vs. Agent Loop Decision

```text
New Task
  → Can the path be stably enumerated?
    → Yes: Deterministic Workflow / Code
    → No: Does the next step depend on open-ended observation?
      → No: Rules, search, or ordinary program
      → Yes: Constrained Agent Loop
```

## 3. Agent Loop Constraints

Every Agent Loop must fix:

- Agent/Prompt/Skill/Tool/Model Route version
- Context Snapshot ID and allowed Fact types for refresh
- Visible Tool set and operable resource scope
- Maximum turns, tokens, cost, time, concurrency, and sub-agent depth
- Success, failure, blockage, escalation, and emergency termination conditions
- Observable Transcript to preserve vs. hidden reasoning to discard

## 4. Normal Execution Flow

```text
Channel/API → Submit intent / goal request
Application → Identity, tenant, schema, idempotency
Application → Create/activate Goal and Run
Application → Start durable workflow
Workflow → Build immutable ContextSnapshot
Workflow → Create Plan and ready Tasks
Workflow → Execute bounded Task
Harness → Structured result or ActionProposal
Workflow → Governed Action request
Tool Gateway → Delegation, policy, schema, risk, budget, approval
Tool Gateway → Execute with idempotency key
External System → Accepted / result / unknown
Tool Gateway → Normalized ToolResult
Evidence Verifier → Verify expected real-world effect
Evidence Verifier → Read authoritative state
Application → Evidence
Application → Evaluate Outcome and transition Run/Goal
```

## 5. Failure Classification & Handling

| Failure Type | Default Handling |
|---|---|
| Transient no-side-effect failure | Exponential backoff retry with cap |
| Invalid structured output | One repair attempt in the same turn; if still invalid → Blocked/Replan |
| Missing or stale context | Refresh specified Facts or human clarification; generate new Snapshot |
| Policy denial | No retry; record Decision; escalate per policy |
| Budget exhausted | Pause and request new budget or fallback route |
| Pre-side-effect execution failure | Retry within idempotency guarantee |
| Side-effect result unknown | Action enters Unknown; reconcile/read-back first; no blind retry |
| Partial side-effects already occurred | Execute predefined compensation plan or human takeover |
| Environment vs. plan premise conflict | Preserve old Plan; generate new Plan Version and replan |

## 6. Run & Goal Lifecycle

### Run States

```text
Pending → Running
Running → Blocked (awaiting approval/facts)
Running → AwaitingEvidence (actions done, verifying)
Running → Succeeded / Failed / Cancelled
Blocked → Running (approval received / facts refreshed)
Blocked → Failed / Cancelled
AwaitingEvidence → Succeeded / Failed / Cancelled
```

Key invariants:
- Session closure must not implicitly terminate a running Run.
- Worker crash must recover from Durable History without re-executing completed side effects.
- A Run marked Succeeded requires all Outcomes to be Verified with Evidence references.

### Run Cancellation

Cancellation may be requested at any time. The Run enters Cancelled state. In-flight Actions that are idempotent may complete; non-idempotent Actions must be halted or compensated.

## 7. Checkpoint & Recovery

- The Durable Workflow Engine maintains deterministic event history.
- Checkpoints capture Run position in the Task DAG.
- On recovery, the Workflow replays from the last checkpoint.
- Completed Actions are not re-executed (idempotency records prevent this).
- In-flight Actions at crash time enter Unknown → reconciliation.

## 8. Implementation Status

- `GoalRunWorkflow` and `CandidateLifecycleWorkflow` are defined in `apps/worker/src/autonoesis_worker/workflows.py`.
- `Harness`, `TaskRequest`, `TaskResult` protocols are in `packages/runtime-kernel/src/autonoesis_runtime/harness.py`.
- `ModelGateway` and `GovernedToolGateway` are in `packages/runtime-kernel/src/autonoesis_runtime/`.
- Temporal Activities use process-level injected Application dependencies; Goal execution has
  Outbox dispatch, fixed Workflow IDs, reconciliation, cancellation, recovery and Replay evidence.
- Candidate evaluation now fails closed without a real Evaluator. Fixed-Subject Harness and Grader
  logic are unit-tested, but production Worker wiring and the end-to-end release path remain pending.
