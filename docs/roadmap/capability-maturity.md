# 能力成熟度矩阵

> 基线日期：2026-08-11
> 产品状态：架构原型 / 工程预览
> 状态定义：以[企业级生产就绪整改路线](enterprise-production-readiness-remediation.md#36-以运行证据定义完成)为准

## 声明规则

1. 成熟度声明描述真实运行证据，不以类、表、路由或测试文件数量替代；
2. `unit-tested` 只引用无真实基础设施依赖的自动化测试；
3. `integrated` 必须引用在 CI 中运行的真实组件任务或已归档演练报告；
4. `production-proven` 必须同时具备故障、并发、安全、运维验收和可定位的证据；
5. 证据失效、CI 门禁移除或实现路径改变时，必须在同一个变更中降级声明；
6. 文档、README、API 元数据和 Cockpit 不得给出高于本矩阵的声明。

当前没有任何能力达到 `integrated` 或 `production-proven`。

## 当前矩阵

| 能力 | 当前成熟度 | 已有证据 | 达到下一等级仍缺少 |
|---|---|---|---|
| 领域语言与基础状态机 | `unit-tested` | `packages/domain/tests/`；CI `python` job | P0-02 完整不变量、非法迁移和冻结契约 |
| Capability Pack Manifest | `unit-tested` | `packages/capability/tests/`；CI `python` job | 签名、SBOM、隔离安装和真实供应链测试 |
| Goal/Run Application 用例 | `unit-tested` | `packages/application/tests/`（InMemory） | 完整纵向用例、事务 Outbox、PostgreSQL 组件测试 |
| HTTP API/SDK | `unit-tested` | `apps/api/tests/`（InMemory）；CI `python` job | Consumer Contract、生产 Repository 装配和多副本一致性 |
| PostgreSQL 权威存储 | `modeled` | SQLAlchemy metadata、Alembic revision `0001` | P0-03 Repository、显式迁移、角色/约束、真实 PostgreSQL CI |
| Temporal 耐久编排 | `modeled` | 两个 Workflow 类型和 Activity 单元测试 | Dispatcher、Reconciler、Replay、Signal 权威复核和崩溃恢复 |
| Governed Tool Gateway | `unit-tested` | 内存 Policy/Budget/Idempotency 测试 | 完整 Envelope、原子 Reservation、执行时授权和受控出口 |
| Identity/Policy/Approval | `unit-tested` | OIDC Validator 和审批逻辑单元测试 | 进程级 JWKS、委托撤销、OPA 组件测试、职责分离 |
| Evidence/Outcome/Audit | `unit-tested` | 内存 Object Store 摘要测试 | MinIO、可信 Readback、Evidence Saga、真实 Audit Ref |
| Context/Environment/Memory | `unit-tested` | 对应包的隔离测试 | 持久化、ACL/来源权威、冲突处理和删除传播集成 |
| Evaluation | `unit-tested` | 试验与统计纯逻辑测试 | 固定 Subject 的真实 Harness、独立 Grader 和证据持久化 |
| Shadow/Canary/Rollback | `unit-tested` | 晋升和 Guardrail 判断算法测试 | 持久化 Deployment、真实双跑/分流、Stable CAS、Release Executor |
| Cockpit | `unit-tested` | CI `cockpit` job：typecheck/build/Playwright；静态样例页面 | 真实 API 数据、权限操作和 Consumer Contract |
| 可观测性/FinOps/SLO | `modeled` / 部分 `unit-tested` | 配置骨架和纯计算测试 | 真实 Trace/Metric/Ledger、告警和运行演练 |
| 多租户隔离 | `modeled` | tenant 字段、RLS 生成逻辑、API 隐藏行为单元测试 | 最小权限角色和跨 DB/Object/Workflow/Telemetry 攻击矩阵 |
| 生产部署/HA/DR/供应链 | `specified` | 架构、威胁模型和 Runbook 草案 | P2 全部实现与演练证据 |

## 证据入口

- 自动化门禁：[`.github/workflows/ci.yml`](../../.github/workflows/ci.yml)
- 可重复基线检查：`task baseline`
- 生成的版本清单：[生产基线报告](generated/production-baseline-report.md)
- 当前限制：[生产就绪基线](production-readiness-baseline.md)
- 后续验收场景：[整改路线第 9 节](enterprise-production-readiness-remediation.md#9-必须持续执行的验收场景)
