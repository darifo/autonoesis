# MVP 路线图（历史实现范围，已重新校准）

> 状态：历史记录，不作为生产就绪声明
> 当前执行计划：[企业级生产就绪整改路线](enterprise-production-readiness-remediation.md)
> 成熟度证据：[能力成熟度矩阵](capability-maturity.md)

本文件原先以“代码对象或接口存在”作为完成标志。自 2026-08-16 起，所有条目按
`specified / modeled / unit-tested / integrated / production-proven` 重新表述。这里的
`unit-tested` 仅说明隔离测试覆盖，不能推导出真实基础设施、故障恢复或生产安全已经成立。

## Phase 0：行业无关内核（参考切片 `integrated`）

- `unit-tested`：GoalContract、SubjectRef、Session、Run 和完整受治理执行契约；
- `unit-tested`：Agent/Skill/Tool、Context、Evaluation 和 Improvement 版本对象；
- `unit-tested`：Capability Pack Manifest、Schema 校验和 Entry Point；
- `unit-tested`：核心行业词汇隔离检查。

已完成：P0 全部退出项；领域契约、Capability Pack、Application 用例和参考验证链通过真实
PostgreSQL、Temporal、OPA、MinIO 与受控 Authority 模拟器集成。未完成：连接真实第三方
Tool、业务 Authority 与生产级故障环境的外部纵向端到端。

## Phase 1：通用运行平台（核心切片 `integrated`）

- `integrated`：PostgreSQL 权威 Schema、冻结 Alembic、RLS、角色、Repository、Outbox/Inbox 和幂等表；
- `integrated`：Temporal Goal Workflow、Run Outbox Dispatcher、固定 Workflow ID、Reconciler、Signal、Continue-as-New 和 Replay；
- `integrated`：Governed Tool Gateway、真实 OPA、原子预算/幂等 Reservation 和执行时授权；
- `integrated`：OIDC、委托撤销、双人审批、职责分离、Break-glass 与双租户攻击矩阵；
- `integrated`：可信 Context/Memory ACL、Snapshot、Write Gate、Ledger 和删除传播；
- `unit-tested`：模型适配器边界；
- `integrated`：通用 HTTP/Application API 与冻结 Consumer Contract；
- `unit-tested`：SDK 和 Cockpit 构建；
- `unit-tested`：Field Service 示例能力包与评估案例解析。

未完成：Candidate Workflow 的真实 Evaluation/发布接入、Cockpit 真实 API 数据源、生产 IdP/
SCIM，以及 PostgreSQL/Temporal 的备份恢复、容量和长期运行证据。

## Phase 2：活动与证据骨架（部分 `integrated`）

- `integrated`：Activity 函数使用进程级注入依赖，并通过真实 PostgreSQL/Temporal 恢复测试；
- `integrated`：Evidence 预写入准入、KMS MinIO 版本/Object Lock、Saga 恢复、权威回读
  Outcome、审计摘要链和删除墓碑/证明；
- `integrated`：Outbox/Inbox 逻辑和 PostgreSQL 权威事务；
- `unit-tested`：Unknown 对账、补偿和 Kill Switch 的隔离逻辑；
- `unit-tested`：OIDC Validator；
- `unit-tested`：MCP 适配器边界。

未完成：生产 KMS/Bucket Policy、生产 Credential Broker、网络层出口控制、真实业务 Authority
及第三方系统纵向端到端。

## Phase 3：进化发布算法骨架（`modeled` / 部分 `unit-tested`）

- `unit-tested`：Replay/Simulation 的纯逻辑；
- `unit-tested`：Shadow/Canary、观察窗口和回滚判断算法；
- `unit-tested`：固定 Subject Harness、完整 Trial、五级独立 Grader、加权/Gating 判定与隐藏 Suite 隔离；
- `modeled`：重复 Trial 批次与分位数骨架，统计置信度门禁尚未实现；
- `unit-tested`：AI FinOps 和 SLO 计算；
- `integrated`：context/memory 的权威存储和租户隔离路径；
- `modeled` / `unit-tested`：intelligence/environment/improvement 的纯逻辑。

已完成：Deployment/Release 持久化和 Active Stable 唯一约束。未完成：真实 Subject/Grader
后端、重复 Trial 置信度、Candidate/Evidence 门禁、真实 Shadow 双跑、可审计 Canary 分流、
Stable Pointer 原子 Compare-and-Swap 和 Release Executor。

## 当前证据边界

现有 CI 执行 Python lint/type/unit/Consumer Contract、PostgreSQL 17、Temporal、OPA、KMS
MinIO、参考纵向 E2E、依赖/Secret 扫描和 Cockpit unit/typecheck/build/Playwright，并归档哈希
证据。以下项目尚未成为 CI 门禁，因此不得标记为
`integrated` 或 `production-proven`：

- 真实第三方系统纵向 E2E、生产级故障演练、长期容量/HA/DR 与发布证据。

详细限制见[生产就绪基线](production-readiness-baseline.md)，整改优先级以
[企业级生产就绪整改路线](enterprise-production-readiness-remediation.md)为准。
