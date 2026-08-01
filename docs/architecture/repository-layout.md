# Repository boundaries

Autonoesis uses one Git monorepo with multiple deployable applications and internal packages.

## Dependency direction

```text
apps → application → domain
apps → runtime-kernel / intelligence / context / evaluation
application → domain + contracts
adapters → ports + external SDKs
packages/* → contracts
domain ↛ framework / workflow / provider / persistence
```

## Directories

| Path | Responsibility | Independently deployable |
|---|---|---|
| `apps/api` | API process assembly | Yes |
| `apps/worker` | Durable execution process assembly | Yes |
| `apps/cockpit` | Operator web application | Yes |
| `apps/gateway` | Reserved gateway process | Later |
| `packages/contracts` | Stable transport contracts | No |
| `packages/domain` | Entities, value objects, invariants | No |
| `packages/application` | Commands, queries, use cases, transactions | No |
| `packages/runtime-kernel` | Harness and durable-runtime ports | No |
| `packages/governance` | Identity, delegation, policy, approval, budget | No |
| `packages/context` | Context assembly and snapshots | No |
| `packages/environment` | External facts and freshness | No |
| `packages/memory` | Memory ports and write gates | No |
| `packages/gateways` | Model, tool, MCP, A2A, and channel boundaries | No |
| `packages/evaluation` | Datasets, trials, graders, trajectory analysis | No |
| `packages/improvement` | Candidates, release gates, rollback | No |
| `packages/adapters` | Replaceable framework and infrastructure adapters | No |

## Split criteria

A module may leave the monorepo only after an ADR demonstrates all three:

1. an independent owning team and lifecycle;
2. a stable remote contract;
3. material security, compliance, scale, or release benefits that exceed added operational cost.

Directory neatness alone is not a split criterion.
