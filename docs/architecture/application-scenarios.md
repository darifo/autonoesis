# Application Scenarios & Architectural Walkthrough

> Status: baseline · Last reviewed: 2026-08-10

How Autonoesis's architecture modules map to real-world use cases. Each
scenario traces a complete Goal → Run → Action → Evidence → Outcome →
Evolution path, showing exactly which packages and domain objects are
involved at each step.

---

## Scenario A: Industrial Predictive Maintenance

**Business context**: A factory operates 200+ pumps. Currently, maintenance
is calendar-based — pumps are serviced every 6 months regardless of actual
condition. This results in both unnecessary downtime (servicing healthy pumps)
and unexpected failures (pumps that degrade between service windows).

**Goal**: "Evaluate pump P-42's failure risk over the next 72 hours. If risk
exceeds threshold, create a maintenance work order and order replacement parts."

### Architecture Walkthrough

```
Step 1: Goal Creation (packages/domain/goals.py)
  └── GoalContract created with:
      - goal_type: "field-service.restore-equipment"
      - subject_refs: (SubjectRef("iot-platform", "pump", "P-42"),)
      - success_criteria: risk_assessed + action_taken
      - risk_tier: "medium", budget_limit: 500

Step 2: Capability Pack Resolution (packages/capability/)
  └── Capability Pack "field-service" loaded:
      - Tools: iot-platform-read (L1), cmm-create-workorder (L3),
               erp-create-purchase-order (L3)
      - Skills: vibration-analysis, maintenance-planning
      - Policies: maintenance-sop (L3 requires supervisor approval)
      - Evaluation Suite: field-service-suite

Step 3: GoalRunWorkflow (apps/worker/workflows.py)
  └── Temporal Durable Workflow started
      - Survives worker crashes; replays from Workflow History
      - States: PENDING → RUNNING → AWAITING_EVIDENCE → SUCCEEDED

Step 4: Context Assembly (packages/context/)
  └── ContextAssembler builds ContextSnapshot:
      - EnvironmentFact: vibration (142Hz, amplitude 0.8mm, trend↑)
                         valid_until = now + 5min
      - EnvironmentFact: temperature (78.5°C, threshold 85°C)
      - KnowledgeRef: bearing-life-curve (ISO 281, trust=AUTHORITATIVE)
      - KnowledgeRef: P-42 maintenance history (CMMS, trust=ADVISORY)
      - Freshness: all facts within valid_until ✓
      - ACL: tenant has read permission on P-42 data ✓

Step 5: Planning (packages/intelligence/)
  └── Planner generates Task DAG:
      1. analyze_vibration     (parallel)
      2. analyze_temperature   (parallel)
      3. assess_failure_risk   (depends on 1, 2)
      4. create_work_order     (depends on 3, conditional)
      5. order_parts           (depends on 4, conditional)

Step 6: Execution — Low-Risk Read (packages/runtime-kernel/tools.py)
  └── Action: iot-platform-read, risk=L1_READ
      → Gateway: Kill Switch ✓ → Policy (auto-allow L1) ✓ → Budget ✓
      → MQTT Adapter: query vibration sensor
      → Evidence: (source=mqtt-broker-1, reference=msg-xyz)

Step 7: Execution — High-Risk Write (packages/runtime-kernel/tools.py)
  └── Action: cmm-create-workorder, risk=L3_HIGH_IMPACT_WRITE
      → Gateway: Kill Switch ✓ → Policy (requires_approval=True)
      → ApprovalRequest(action_digest=sha256(params), required_role="supervisor")
      → Supervisor approves in Cockpit
      → Gateway validates: action_digest matches ✓, approval not expired ✓
      → REST Adapter: POST /workorders → WO-8842
      → verify(): GET /workorders/WO-8842 → 200 OK ✓
      → Evidence: WO-8842 created, assigned to Zhang San

Step 8: Outcome Verification (packages/domain/execution.py)
  └── SuccessCriterion "risk_assessed" → Outcome(VERIFIED, evidence=[ev-001])
  └── SuccessCriterion "action_taken"  → Outcome(VERIFIED, evidence=[ev-003])

Step 9: Self-Evolution (packages/improvement/, packages/evaluation/)
  └── If bearing actually failed at 120h (predicted 300h):
      → EvaluationSuite detects regression
      → ImprovementProposal: "Add acceleration features to vibration model"
      → Candidate → Evaluate → Shadow → Canary → Stable
```

### Key Architectural Decisions at Work

| Decision | Why It Matters Here |
|----------|-------------------|
| **ContextSnapshot (not raw prompt)** | Vibration data valid for 5 min; if Worker restarts at minute 6, stale data is excluded |
| **Temporal Workflow (not Agent Loop)** | Maintenance task spans hours; Worker crash must not lose "work order already created" state |
| **L3 Approval** | Creating a work order triggers parts ordering and technician dispatch — not safe to auto-execute |
| **idempotency_key** | If Worker crashes after cmm-create-workorder but before recording, replay uses the same key → no duplicate |
| **Evidence content-hash** | Auditor asks "why was this pump serviced?" → replay ContextSnapshot + Evidence chain |

---

## Scenario B: Financial Compliance Review

**Business context**: A bank must review 500 flagged transactions daily for
anti-money laundering (AML) compliance. Each transaction requires: customer
profile lookup, transaction history analysis, sanctions list check, and a
final disposition (clear / escalate / freeze).

**Goal**: "Review today's 500 flagged transactions. For each, determine
disposition with full evidence trail."

### Architecture Walkthrough

```
Step 1: GoalContract
  └── 500 SubjectRefs, one per transaction
  └── success_criteria: all_reviewed, high_risk_escalated

Step 2: Plan — Parallel Review Tasks
  └── 10 parallel Tasks, each handling 50 transactions

Step 3: Per-Transaction Pipeline
  └── Task → Harness → Action Proposals:
      Action 1: customer-profile-read      (L1_READ → auto)
      Action 2: transaction-history-query   (L1_READ → auto)
      Action 3: sanctions-list-check        (L1_READ → auto)
      Action 4: compliance-rule-match       (L0_COMPUTE → auto)
      Decision: clear / escalate / freeze

Step 4: Freeze Requires L4 Privileged Gate
  └── Action: account-freeze, risk=L4_PRIVILEGED
      → Policy: default deny autonomous
      → Requires: dedicated controlled process + dual-person approval
      → compliance_officer + branch_manager both approve
      → Evidence: freeze order TXN-FRZ-9921

Step 5: Evidence Chain Per Transaction
  └── For each reviewed transaction:
      Evidence(source="customer-db", reference=CUST-8842, observed_state="...")
      Evidence(source="sanctions-list", reference="OFAC-2026-08-10", ...)
      Evidence(source="compliance-engine", reference="RULE-AML-42", ...)
      Outcome: VERIFIED or NOT_MET

Step 6: Audit Replay
  └── Regulator asks: "Why was TXN-7721 cleared?"
      → ReplayEngine loads ContextSnapshot for that Run
      → Shows: sanctions check passed, customer risk=low, transaction amount < threshold
      → Evidence chain is complete and verifiable
```

### Key Compliance Features

| Feature | Implementation |
|---------|---------------|
| **Immutable audit trail** | `AuditEvent` + `Evidence` content-hash |
| **Policy version binding** | Each `PolicyDecision` records `policy_version` |
| **Reproducible decisions** | `ReplayEngine` replays any past Run with its `ContextSnapshot` |
| **No self-certification** | `Outcome.VERIFIED` requires non-empty `evidence_ids` |
| **Human-in-the-loop** | L4 operations default deny + require dual approval |

---

## Scenario C: Supply Chain Procurement

**Business context**: When inventory drops below safety stock, the system
must: check alternative suppliers, compare prices, create purchase orders,
and track delivery — all while staying within departmental budget.

### The Full Risk Ladder in One Goal

This scenario is the clearest demonstration of Autonoesis's risk escalation
model — a single Goal exercises all five risk levels:

```
L0_COMPUTE:
  Action: "Calculate optimal order quantity using EOQ formula"
  → Pure computation, no external calls
  → Gateway: auto-allow

L1_READ:
  Action: "Query inventory levels for SKU-442 across 3 warehouses"
  Action: "Query supplier price lists for 5 registered vendors"
  → Read-only API calls
  → Gateway: auto-allow with ACL

L2_REVERSIBLE_WRITE:
  Action: "Create draft purchase requisition PR-9921"
  → Reversible: can be cancelled before approval
  → Gateway: policy check + idempotency
  → Compensation: cancel-PR

L3_HIGH_IMPACT_WRITE:
  Action: "Issue Purchase Order PO-8842 for ¥84,000 to Supplier S-442"
  → Gateway: exact-parameter approval required
  → action_digest binds supplier, quantity, amount
  → Manager approves → Gateway validates digest match → Execute
  → Evidence: PO-8842 in ERP, approval timestamp

L4_PRIVILEGED:
  Action: "Wire transfer ¥84,000 to supplier bank account"
  → Gateway: default deny, dual-person approval
  → finance_approver + procurement_director both approve
  → UnknownReconciler ready if bank response is ambiguous
  → Evidence: bank confirmation TXN-77321
```

### Budget Enforcement

```python
# packages/evolution/finops.py - CostTracker
tracker.record(CostEntry(category=CostCategory.MODEL_TOKEN, amount=0.05))
tracker.record(CostEntry(category=CostCategory.TOOL_EXECUTION, amount=0.10))
tracker.record(CostEntry(category=CostCategory.SANDBOX_TIME, amount=0.02))

summary = await tracker.summarize_goal(goal_id)
# summary.total_cost = 0.17
# summary.cost_per_verified_outcome = 0.17 / 1 = $0.17

enforcer = BudgetEnforcer(tracker)
ok, msg = await enforcer.check_action(goal_id, estimated_cost=0.05, budget_limit=1.0)
# ok = True, remaining = 0.83
```

---

## Cross-Cutting Patterns

### Risk Escalation Is Deterministic

The `SideEffectClass` on `ToolDefinition` is the **sole determinant** of
which Gateway path an Action takes. There is no runtime ambiguity — a tool
classified as L3 will always require approval, regardless of the Action's
parameters or the tenant's preferences.

### Evidence Chain Is Immutable

Every `Evidence` record is content-addressed (SHA-256). Every `Outcome`
that claims `VERIFIED` must reference at least one `Evidence`. Every
`ContextSnapshot` has a `history_digest`. The result is a complete,
tamper-evident chain from:

```
Goal → Plan → ContextSnapshot → Action → Evidence → Outcome
```

### Self-Evolution Is Safeguarded

The improvement pipeline enforces separation of concerns:

```
ProposalGenerator ≠ CandidateGenerator ≠ Grader ≠ Approver
```

No single entity can propose, generate, grade, and approve a change to
agent behavior.

### Multi-Tenant Isolation Is Structural

Every table carries `tenant_id`. Every API request carries `X-Tenant-ID`.
Cross-tenant access returns 404 (not 403 — no information leakage about
whether the resource exists).

---

## What Ships vs. What You Build

The scenarios above demonstrate the architecture, but they mix built-in
capabilities with industry-specific custom development:

| Component | Ships with Autonoesis | You Build |
|---|---|---|
| `GoalContract`, `Plan`, `Action`, `Evidence`, `Outcome` | ✅ Domain model | — |
| `GovernedToolGateway` (8-step pipeline) | ✅ Runtime kernel | — |
| `GoalRunWorkflow`, `CandidateLifecycleWorkflow` | ✅ Worker | — |
| `EvaluationHarness`, `DeploymentPipeline` | ✅ Evolution package | — |
| `field-service` example Pack (YAML + 10 eval cases) | ✅ Reference only | Connect to real IoT/CMMS |
| Tool Adapters (SAP, MQTT, REST, SWIFT) | — | ✅ Implement `ToolExecutor` Protocol |
| Evaluation Cases (your definition of "good") | — | ✅ Define in YAML |
| Policies (OPA Rego rules) | — | ✅ Write compliance rules |
| OIDC Integration (Keycloak/Okta) | — | ✅ Configure IdP |

> **Note on Scenario A (maintenance)**: The `field-service.restore-equipment`
> Goal Type, `vibration-analysis` Skill, and `cmm-create-workorder` Tool are
> defined in `examples/field-service/capability-pack.yaml` — a **reference
> implementation** that demonstrates the Capability Pack format. It includes
> 10 evaluation cases but does not connect to real IoT hardware or CMMS
> systems. You would create your own Pack with adapters wired to your actual
> infrastructure.

> **Note on Scenario C (compensation)**: The L2 `compensation` field on
> `ToolDefinition` declares a compensating tool name. At present,
> compensation must be triggered by custom logic in the Activity or by the
> `UnknownReconciler` — the `GovernedToolGateway` does not automatically
> invoke it. Automatic compensation on verification failure is planned.

---

## See Also

- [Integration Guide](integration-guide.md) — step-by-step for connecting business systems
- [Platform Positioning](platform-positioning.md) — when Autonoesis is the right choice
- [Runtime & Flows](runtime-and-flows.md) — Workflow vs. Agent Loop execution model
- [Domain Model](domain-model.md) — core entities and state machines
