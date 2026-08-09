# 仓库与依赖边界

## 依赖方向

```text
apps → application → domain
apps → adapters → application ports / runtime contracts
application → domain + contracts + capability
runtime-kernel → domain + contracts
capability → Manifest / JSON Schema / plugin discovery
domain ↛ FastAPI / Temporal / provider SDK / ORM / database
core ↛ examples
```

## 目录责任

| 路径 | 责任 | 可独立部署 |
| --- | --- | --- |
| `apps/api` | HTTP、OIDC 上下文、控制面协议入口 | 是 |
| `apps/worker` | Temporal Workflow 与 Activity 装配 | 是 |
| `apps/cockpit` | 运营控制面 | 是 |
| `packages/domain` | 纯领域对象、状态机和不变量 | 否 |
| `packages/application` | 用例、端口和事务边界 | 否 |
| `packages/capability` | Capability Pack Manifest 与插件发现 | 否 |
| `packages/runtime-kernel` | Harness、Model 与 Tool 运行契约 | 否 |
| `packages/adapters` | PostgreSQL、OIDC、OPA、模型等可替换适配器 | 否 |
| `packages/contracts` | 跨进程稳定 Envelope | 否 |
| `packages/py-sdk` / `ts-sdk` | 公共客户端 | 否 |
| `examples/field-service` | 只依赖公开接口的行业示例 | 否 |
| `infra` | Compose、迁移、策略和可观测性 | 否 |

模块只有同时具备独立团队和生命周期、稳定远程契约，以及明显的安全、规模或发布收益时才允许拆为独立服务或仓库。
