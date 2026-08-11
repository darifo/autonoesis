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

当前 P0 参考纵向切片、PostgreSQL 权威存储、HTTP/Application 用例、Governed Tool Gateway、
Temporal 耐久编排和 Evidence/Outcome/Audit 可信链达到 `integrated`；没有任何能力达到
`production-proven`。

## 当前矩阵

| 能力 | 当前成熟度 | 已有证据 | 达到下一等级仍缺少 |
|---|---|---|---|
| 领域语言与基础状态机 | `integrated` | P0-02 冻结契约；CI 参考 E2E 真实推进 Goal/Run/Task/Action/Evidence/Outcome | 属性测试、长期兼容与生产异常状态演练 |
| Capability Pack Manifest | `integrated` | Field Service Pack 经真实 API 安装、Schema 验证、Agent 绑定并驱动参考 E2E | 签名、SBOM、隔离安装和真实供应链测试 |
| Goal/Run Application 用例 | `integrated` | PostgreSQL 事务/恢复组件测试；真实 Temporal/Tool/OPA/Evidence 参考 E2E | 真实第三方系统、网络故障和多进程容量演练 |
| HTTP API/SDK | `integrated` | 冻结 OpenAPI 3.1、Consumer Contract、统一错误 Envelope；参考 E2E 从真实 ASGI API 发起 | 生成 SDK、多副本 API、OIDC 与外部 Consumer 验证 |
| PostgreSQL 权威存储 | `integrated` | CI PostgreSQL 17；Alembic `0001 → 0005`；`test_postgres_authority.py` | 备份恢复、故障注入、容量/升级演练和长期运行证据 |
| Temporal 耐久编排 | `integrated` | CI 真实 Temporal：Outbox Dispatcher、固定 ID、Reconciler、Worker 重启、Continue-as-New、Signal 和 Replay 测试 | Namespace/队列隔离、HA/备份、容量、网络分区和滚动升级演练 |
| Governed Tool Gateway | `integrated` | PostgreSQL 原子预算/幂等 Reservation、真实 OPA、凭证租约、受控出口和故障语义组件测试 | 生产 Credential Broker、网络层出口策略和第三方系统故障演练 |
| Identity/Policy/Approval | `unit-tested` | OIDC Validator、真实 OPA Worker 决策、参考 E2E 独立审批、数据库角色职责分离 | 进程级 JWKS、委托撤销和企业 IdP/职责分离集成 |
| Evidence/Outcome/Audit | `integrated` | CI PostgreSQL 17 + KMS MinIO：预写入准入、Version/Object Lock、Saga 恢复、权威回读 Outcome、并发摘要审计链、真实 Audit Ref 和删除墓碑/证明 | 生产 KMS/跨区复制、真实业务 Authority、WORM 导出、保留/删除长期演练 |
| Context/Environment/Memory | `unit-tested` | Context 持久化及跨 Store 读取；对应包隔离测试 | 来源 ACL、冲突处理和删除传播集成 |
| Evaluation | `unit-tested` | 试验与统计纯逻辑、Trial 持久化 | 固定 Subject 的真实 Harness、独立 Grader 和证据链集成 |
| Shadow/Canary/Rollback | `unit-tested` | 持久化 Deployment/Release 与 Active Stable 唯一约束；晋升算法测试 | 真实双跑/分流、观察窗口和 Release Executor |
| Cockpit | `unit-tested` | CI Vitest/typecheck/build/Playwright；静态样例和成熟度防误报测试 | 真实 API 数据、权限操作和生成 Client 接入 |
| 可观测性/FinOps/SLO | `modeled` / 部分 `unit-tested` | 配置骨架和纯计算测试 | 真实 Trace/Metric/Ledger、告警和运行演练 |
| 多租户隔离 | `unit-tested` | PostgreSQL 最小权限角色、Tenant Authority、复合外键、RLS 跨租户攻击组件测试 | Object/Workflow/Telemetry 隔离和完整攻击矩阵 |
| 生产部署/HA/DR/供应链 | `specified` / 部分 `unit-tested` | 锁文件依赖审计、精确 Secret 基线、CI 哈希证据归档 | P2 部署、签名/SBOM、HA/DR 与长期演练证据 |

## 证据入口

- 自动化门禁：[`.github/workflows/ci.yml`](../../.github/workflows/ci.yml)
- 可重复基线检查：`task baseline`
- 生成的版本清单：[生产基线报告](generated/production-baseline-report.md)
- 当前限制：[生产就绪基线](production-readiness-baseline.md)
- 后续验收场景：[整改路线第 9 节](enterprise-production-readiness-remediation.md#9-必须持续执行的验收场景)
