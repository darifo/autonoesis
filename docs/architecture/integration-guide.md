# Business System Integration Guide

> Status: baseline · Last reviewed: 2026-08-10

How Autonoesis connects to external business systems — the SOP/SPI architecture,
the invocation pipeline, and the step-by-step process for adding a new
integration.

---

## Three-Layer Architecture

```
                         ┌──────────────────────────────┐
  SOP (Static Contract)   │  ToolDefinition              │  ← domain/assets.py:79
  "What is this tool?"    │  SideEffectClass             │  ← 5-level risk
                          │  idempotent / verification    │  ← mandatory for writes
                          │  compensation                │  ← rollback path
                          └──────────────┬───────────────┘
                                         │
  SPI (Runtime Contract)  ┌──────────────┴───────────────┐
  "How to call it?"        │  ToolExecutor Protocol       │  ← runtime-kernel/tools.py:124
                          │  execute(action) → Receipt   │  ← 2 methods
                          │  verify(action, receipt)     │
                          └──────────────┬───────────────┘
                                         │
  Adapter (Implementation)┌──────────────┴───────────────┐
  "What protocol?"         │  REST / MQTT / gRPC / MCP   │  ← adapters/
                          │  SOAP / GraphQL / NATS       │  ← extensible
                          └──────────────────────────────┘
```

- **SOP** (Service Object Profile): `ToolDefinition` — what the platform needs
  to know *statically* to govern a tool. Declared in Capability Pack YAML.
- **SPI** (Service Provider Interface): `ToolExecutor` Protocol — what every
  adapter must implement *at runtime*. Two methods: `execute` and `verify`.
- **Adapter**: The concrete protocol binding — REST, MQTT, gRPC, MCP, or
  any custom protocol.

---

## Step 1: The SOP — Declare the Tool

Every tool integrated into the platform must declare its contract in a
Capability Pack manifest. This is a **static, reviewable declaration** —
no code execution happens at declaration time.

```yaml
# In capability-pack.yaml
tools:
  - tool_id: "sap-create-po"            # Globally unique
    version: "2.1"                      # Semantic version
    input_schema:                       # JSON Schema: what this tool expects
      type: object
      required: [supplier_id, items]
      properties:
        supplier_id: {type: string}
        items: {type: array}
    output_schema:                      # JSON Schema: what this tool returns
      type: object
      properties:
        po_number: {type: string}
    adapter: "rest"                     # Which protocol adapter to use
    side_effect: "high_impact_write"    # L0-L4 risk classification
    idempotent: true                    # MANDATORY for L2-L4 writes
    verification: "read-back"           # How to confirm execution
    compensation: "sap-cancel-po"       # Rollback tool name
```

> **Note on `adapter`**: This field is **declarative metadata** — it documents
> which protocol the tool uses, but does **not** drive routing at runtime. The
> actual routing is done by the `tool_name → ToolExecutor` mapping in the
> Gateway's `executors` dict (see Step 3).

> **Note on `compensation`**: The `compensation` field declares the *name* of
> a compensating tool (e.g., `"sap-cancel-po"`). At present, the
> `GovernedToolGateway` does **not** automatically trigger compensation on
> failure. The `CompensationExecutor` (`packages/gateways/tool_reconciliation.py`)
> provides the execution logic, but the trigger must be implemented by the
> caller (e.g., in the `UnknownReconciler` or in custom error-handling logic
> within the Activity). Full automatic compensation is a planned Phase 3 feature.

### SideEffectClass vs RiskLevel — Two Related Enums

The platform uses **two separate enums** for risk classification, at different
layers:

| Layer | Enum (domain location) | Member naming | Used by |
|---|---|---|---|
| **Tool declaration** | `SideEffectClass` (`assets.py:15`) | `COMPUTE`, `READ`, `REVERSIBLE_WRITE`, `HIGH_IMPACT_WRITE`, `PRIVILEGED` | `ToolDefinition.side_effect` |
| **Runtime action** | `RiskLevel` (`execution.py:21`) | `L0_COMPUTE`, `L1_READ`, `L2_REVERSIBLE_WRITE`, `L3_HIGH_IMPACT_WRITE`, `L4_PRIVILEGED` | `Action.risk_level` |

They are semantically identical — the `L0`–`L4` prefix on `RiskLevel`
exists only for disambiguation in the `Action` context. When building an
adapter that reads `action.risk_level.value`, you will get values like
`"l2_reversible_write"` (with the `l2_` prefix). When declaring a tool in
YAML, use the unprefixed form: `side_effect: "reversible_write"`.

### The 5 Risk Levels

| Level | SideEffectClass | RiskLevel | Examples | Gateway Behavior |
|---|---|---|---|---|
| **L0** | `COMPUTE` | `L0_COMPUTE` | Local calculation | Sandbox only |
| **L1** | `READ` | `L1_READ` | Query APIs, read DBs | ACL + audit |
| **L2** | `REVERSIBLE_WRITE` | `L2_REVERSIBLE_WRITE` | Drafts, config | Policy + idempotency + verification |
| **L3** | `HIGH_IMPACT_WRITE` | `L3_HIGH_IMPACT_WRITE` | Payments, publishing | Approval binding + strong evidence |
| **L4** | `PRIVILEGED` | `L4_PRIVILEGED` | IAM, infra | Default deny; dedicated process |

### Domain-Level Enforcement

The domain model enforces that **write tools must declare idempotency**
(`assets.py:96-105`):

```python
if self.side_effect in {REVERSIBLE_WRITE, HIGH_IMPACT_WRITE, PRIVILEGED} and not self.idempotent:
    raise ValueError("write tools must declare an idempotent execution contract")
```

This is a hard constraint — it is impossible to register a write-capable
tool without idempotency.

> **Schema validation status**: The `input_schema` declared on `ToolDefinition`
> defines the expected parameter shape, but **validation is not yet enforced
> by the Gateway at tool invocation time**. Goal-level `input_schema` is
> validated in `CreateGoalHandler`. Tool-level schema enforcement in the
> Gateway pipeline is planned for a future release. Currently, adapters
> should perform their own parameter validation in `execute()`.

---

## Step 2: The SPI — Implement ToolExecutor Protocol

Every adapter must implement two methods
(`packages/runtime-kernel/src/autonoesis_runtime/tools.py:124-127`):

```python
class ToolExecutor(Protocol):
    async def execute(self, action: Action) -> ToolReceipt: ...
    async def verify(self, action: Action, receipt: ToolReceipt) -> bool: ...
```

### Why Two Methods?

1. **`execute`** — Issues the external call. Returns a `ToolReceipt` with the
   external system's response.
2. **`verify`** — Confirms the side effect actually took effect. Called
   immediately after `execute`. If it returns `False`, the Gateway returns
   `ActionStatus.UNKNOWN`, triggering the reconciliation process.

This "execute-verify separation" is what distinguishes Autonoesis from
frameworks that call an API and assume success.

### ToolReceipt — The Unified Return Format

```python
ToolReceipt(
    external_id="PO-88421",  # ID in the external system
    accepted=True,  # Was the call accepted?
    output=(  # Key-value result pairs
        ("po_number", "PO-88421"),
        ("status", "created"),
    ),
)
```

### Complete Example: SAP Purchase Order Adapter

> **Credential management**: In production, inject credentials via environment
> variables, a secrets manager (HashiCorp Vault, AWS Secrets Manager), or the
> platform's credential brokering layer
> (`docs/contracts/tool-invocation.md`, step 10). The example below uses
> constructor injection for clarity.

> **Tool version**: The `Action` domain model does **not** carry a `tool_version`
> field. Versioning is the adapter's responsibility — either use a separate
> adapter class per version, or maintain an internal version map.

```python
from autonoesis_runtime import ToolExecutor, ToolReceipt
from uuid import uuid4
import httpx, os


class SapPOExecutor:
    """Implements ToolExecutor Protocol for SAP Purchase Order creation."""

    def __init__(self, base_url: str):
        self._url = base_url
        self._token = os.getenv("SAP_API_TOKEN", "")

    async def execute(self, action: Action) -> ToolReceipt:
        params = dict(action.parameters)

        # Build the 19-field Invocation Envelope.
        # tool_version is maintained by the adapter, not passed via Action.
        envelope = {
            "invocation_id": str(uuid4()),
            "action_id": str(action.action_id),
            "tenant_id": str(action.tenant_id),
            "run_id": str(action.run_id),
            "task_id": str(action.task_id),
            "tool": action.tool_name,
            "tool_version": "2.1",  # adapter-maintained, not from Action
            "operation": action.operation,
            "arguments": params,
            "argument_digest": action.parameter_digest,
            "risk_level": action.risk_level.value,
            "idempotency_key": action.idempotency_key,
            "expected_effect": action.expected_effect,
        }

        try:
            resp = await httpx.post(
                f"{self._url}/api/purchase-orders",
                json=envelope,
                headers={
                    "Idempotency-Key": action.idempotency_key,
                    "Authorization": f"Bearer {self._token}",
                },
                timeout=30.0,
            )
            if resp.status_code in (200, 201):
                po = resp.json()
                return ToolReceipt(
                    external_id=po["po_number"],
                    accepted=True,
                    output=(("po_number", po["po_number"]),),
                )
            return ToolReceipt(
                external_id="",
                accepted=False,
                output=(("error", str(resp.status_code)),),
            )
        except httpx.TimeoutException:
            return ToolReceipt(
                external_id="",
                accepted=False,
                output=(("error", "timeout"),),
            )

    async def verify(self, action: Action, receipt: ToolReceipt) -> bool:
        """Read-back: confirm the PO actually exists in SAP."""
        if not receipt.external_id:
            return False
        try:
            resp = await httpx.get(
                f"{self._url}/api/purchase-orders/{receipt.external_id}",
                headers={"Authorization": f"Bearer {self._auth['token']}"},
                timeout=10.0,
            )
            return resp.status_code == 200
        except Exception:
            return False
```

---

## Step 3: Wire into the Gateway

The `GovernedToolGateway` holds a `dict[str, ToolExecutor]` mapping
tool names to their adapters

(`packages/runtime-kernel/src/autonoesis_runtime/tools.py:162`).

```python
gateway = GovernedToolGateway(
    policy=opa_adapter,
    budget=budget_ledger,
    idempotency=idempotency_store,
    executors={
        "sap-create-po": SapPOExecutor(sap_url, sap_creds),
        "sap-cancel-po": SapPOExecutor(sap_url, sap_creds),  # compensation
        "iot-platform-read": MqttExecutor(broker_url),
        "cmm-create-workorder": RestExecutor(cmm_url, cmm_creds),
        "bank-transfer": SwiftExecutor(bank_gw_url),
    },
    kill_switch=kill_switch_store,
)
```

---

## Step 4: The Gateway Pipeline — What Happens at Runtime

When an `Action` reaches the Gateway, it goes through an 8-step gated
pipeline (`tools.py:172-227`):

```
Step 1: State validation    → Is the Action in PROPOSED or AWAITING_APPROVAL?
Step 2: Kill Switch gate    → Is this tenant/tool/operation currently blocked?
Step 3: Policy decision     → OPA: does policy allow this?
Step 4: Approval check      → If L3/L4: is approval present and parameter-digest matches?
Step 5: Budget reserve      → Does the run have remaining budget?
Step 6: Idempotency check   → Has this idempotency_key already executed?
Step 7: Executor lookup     → Is there a ToolExecutor registered for this tool_name?
Step 8: execute() + verify() → Call the SPI, verify the result
```

Possible outcomes:
- `SUCCEEDED`: side effect confirmed via verify()
- `DENIED`: blocked by kill switch or policy
- `UNKNOWN`: execute() ran but verify() failed → trigger UnknownReconciler

---

## The Invocation Envelope

Every external call carries a 19-field envelope
(`docs/contracts/tool-invocation.md:9-34`):

```yaml
invocation_id: "uuid"       # Unique call ID
tenant_id: "uuid"           # Tenant isolation
run_id: "uuid"              # Parent Run
action_id: "uuid"           # Parent Action
tool: "sap-create-po"       # Tool identifier
tool_version: "2.1"         # Tool version
operation: "create"         # Operation name
arguments: {...}            # Parameters
argument_digest: "sha256:"  # Hash for approval binding
risk_level: "l3"            # Risk classification
idempotency_key: "..."      # Deduplication key
expected_effect: "..."      # Human-readable expected outcome
deadline: "rfc3339"         # Timeout
traceparent: "..."          # OTel distributed tracing
data_classification: "..."  # PII/confidential/internal
```

The external system is expected to:
1. Check `idempotency_key` — do not process if already seen
2. Validate `argument_digest` — do not process if parameters don't match
3. Return the `external_id` in the response
4. Support read-back verification on that `external_id`

---

## Currently Implemented Protocols

| Adapter | Location | Status |
|---------|----------|--------|
| **MCP** (Model Context Protocol) | `packages/adapters/src/autonoesis_adapters/mcp/__init__.py` | Baseline |
| **REST/HTTP** | Illustrated above; production adapter pending | Spec complete |
| **MQTT** (IoT) | Spec defined, adapter pending | Spec complete |
| **gRPC** | Spec defined, adapter pending | Planned |

Additional adapter directories are reserved in `packages/adapters/src/autonoesis_adapters/`:
`a2a/` (Agent-to-Agent), `hermes/`, `codex/`, `honcho/`, `openai-agents/`, `messaging/`.

---

## Adding a New Protocol

To add a new protocol adapter (e.g., SOAP, GraphQL, NATS, Kafka):

1. **Create the adapter file** in `packages/adapters/src/autonoesis_adapters/`
2. **Implement `ToolExecutor` Protocol** (2 methods: `execute` + `verify`)
3. **Map `tool_name` → adapter instance** in the Gateway's `executors` dict
4. **Declare the adapter name** in Capability Pack's `adapter` field
5. **Add tests** verifying:
   - Successful execution + verification
   - Idempotent replay (same key → same receipt)
   - Timeout → `ActionStatus.UNKNOWN`
   - Verification failure → `ActionStatus.UNKNOWN`

No changes to domain, application, or runtime-kernel packages are needed.

---

## See Also

- [Application Scenarios](application-scenarios.md) — real-world use cases with full architecture walkthrough
- [Platform Positioning](platform-positioning.md) — when to use Autonoesis vs. generic frameworks
- [Tool Invocation Contract](../contracts/tool-invocation.md) — the full 13-step pipeline specification
- [Domain Model](domain-model.md) — `ToolDefinition`, `Action`, and entity relationships
