# MVP 路线图（历史实现范围，已重新校准）

> 状态：历史记录，不作为生产就绪声明
> 当前执行计划：[企业级生产就绪整改路线](enterprise-production-readiness-remediation.md)
> 成熟度证据：[能力成熟度矩阵](capability-maturity.md)

本文件原先以“代码对象或接口存在”作为完成标志。自 2026-08-11 起，所有条目按
`specified / modeled / unit-tested / integrated / production-proven` 重新表述。这里的
`unit-tested` 仅说明隔离测试覆盖，不能推导出真实基础设施、故障恢复或生产安全已经成立。

## Phase 0：行业无关内核（`unit-tested`）

- `unit-tested`：GoalContract、SubjectRef、Session、Run 和完整受治理执行契约；
- `unit-tested`：Agent/Skill/Tool、Context、Evaluation 和 Improvement 版本对象；
- `unit-tested`：Capability Pack Manifest、Schema 校验和 Entry Point；
- `unit-tested`：核心行业词汇隔离检查。

已完成：P0-04 纵向 Application 用例、统一事务边界和参考验证链。未完成：连接真实第三方
Tool、业务 Authority 与完整基础设施的外部纵向端到端。

## Phase 1：通用运行平台（`modeled` / 部分 `unit-tested`）

- `integrated`：PostgreSQL 权威 Schema、冻结 Alembic、RLS、角色、Repository、Outbox/Inbox 和幂等表；
- `integrated`：Temporal Goal Workflow、Run Outbox Dispatcher、固定 Workflow ID、Reconciler、Signal、Continue-as-New 和 Replay；
- `unit-tested`：OIDC、预算、审批和 Tool Gateway 的部分隔离逻辑；
- `unit-tested`：模型适配器边界；
- `unit-tested`：通用 API、SDK 和 Cockpit 构建；
- `unit-tested`：Field Service 示例能力包与评估案例解析。

未完成：Candidate Workflow 的生产发布接入、Cockpit 真实 API 数据源和 Consumer Contract。
PostgreSQL/Temporal 的备份恢复、容量和长期运行证据仍未达到生产验证等级。

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
- `unit-tested`：重复 Trial、分位数和不确定性计算；
- `unit-tested`：AI FinOps 和 SLO 计算；
- `modeled`：intelligence/context/memory/environment/improvement/evaluation 包。

未完成：持久化 Deployment Aggregate、独立 Evaluation Harness、真实 Shadow 双跑、
可审计 Canary 分流、Stable Pointer 原子更新和 Release Executor。

## 当前证据边界

现有 CI 执行 Python lint/type/unit test、PostgreSQL 17、Temporal、OPA、KMS MinIO 组件测试和 Cockpit
typecheck/build/静态页面 Playwright。以下项目尚未成为 CI 门禁，因此不得标记为
`integrated` 或 `production-proven`：

- API Consumer Contract Test；
- 真实第三方系统纵向 E2E、生产级故障演练、依赖扫描和 Secret 扫描。

详细限制见[生产就绪基线](production-readiness-baseline.md)，整改优先级以
[企业级生产就绪整改路线](enterprise-production-readiness-remediation.md)为准。
