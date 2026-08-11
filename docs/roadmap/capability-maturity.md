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

当前仅 PostgreSQL 权威存储达到 `integrated`；没有任何能力达到 `production-proven`。

## 当前矩阵

| 能力 | 当前成熟度 | 已有证据 | 达到下一等级仍缺少 |
|---|---|---|---|
| 领域语言与基础状态机 | `unit-tested` | P0-02 冻结契约；`packages/domain/tests/`；CI `python` job | P0-04 纵向集成 |
| Capability Pack Manifest | `unit-tested` | `packages/capability/tests/`；CI `python` job | 签名、SBOM、隔离安装和真实供应链测试 |
| Goal/Run Application 用例 | `unit-tested` | `packages/application/tests/`（InMemory）；Repository 事务组件测试 | P0-04 完整纵向用例与统一事务边界 |
| HTTP API/SDK | `unit-tested` | `apps/api/tests/`；生产 PostgreSQL Store 装配 | Consumer Contract 与真实多副本 API 测试 |
| PostgreSQL 权威存储 | `integrated` | CI PostgreSQL 17；Alembic `0001 → 0002`；`test_postgres_authority.py` | 备份恢复、故障注入、容量/升级演练和长期运行证据 |
| Temporal 耐久编排 | `modeled` | 两个 Workflow 类型和 Activity 单元测试 | Dispatcher、Reconciler、Replay、Signal 权威复核和崩溃恢复 |
| Governed Tool Gateway | `unit-tested` | 完整 Envelope 与 Approval 绑定、内存 Policy/Budget/Idempotency 测试 | 原子 Reservation、执行时授权和受控出口 |
| Identity/Policy/Approval | `unit-tested` | OIDC Validator、完整审批持久化、数据库角色职责分离 | 进程级 JWKS、委托撤销、OPA 组件测试、业务职责分离 |
| Evidence/Outcome/Audit | `unit-tested` | 完整 Evidence/Outcome 持久化与 Audit/Outbox 原子回滚组件测试 | MinIO、可信 Readback、Evidence Saga、真实 Audit Ref |
| Context/Environment/Memory | `unit-tested` | 对应包的隔离测试 | 持久化、ACL/来源权威、冲突处理和删除传播集成 |
| Evaluation | `unit-tested` | 试验与统计纯逻辑、Trial 持久化 | 固定 Subject 的真实 Harness、独立 Grader 和证据链集成 |
| Shadow/Canary/Rollback | `unit-tested` | 持久化 Deployment/Release 与 Active Stable 唯一约束；晋升算法测试 | 真实双跑/分流、观察窗口和 Release Executor |
| Cockpit | `unit-tested` | CI `cockpit` job：typecheck/build/Playwright；静态样例页面 | 真实 API 数据、权限操作和 Consumer Contract |
| 可观测性/FinOps/SLO | `modeled` / 部分 `unit-tested` | 配置骨架和纯计算测试 | 真实 Trace/Metric/Ledger、告警和运行演练 |
| 多租户隔离 | `unit-tested` | PostgreSQL 最小权限角色、Tenant Authority、复合外键、RLS 跨租户攻击组件测试 | Object/Workflow/Telemetry 隔离和完整攻击矩阵 |
| 生产部署/HA/DR/供应链 | `specified` | 架构、威胁模型和 Runbook 草案 | P2 全部实现与演练证据 |

## 证据入口

- 自动化门禁：[`.github/workflows/ci.yml`](../../.github/workflows/ci.yml)
- 可重复基线检查：`task baseline`
- 生成的版本清单：[生产基线报告](generated/production-baseline-report.md)
- 当前限制：[生产就绪基线](production-readiness-baseline.md)
- 后续验收场景：[整改路线第 9 节](enterprise-production-readiness-remediation.md#9-必须持续执行的验收场景)
