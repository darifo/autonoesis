# Application

Application 是受治理业务状态的唯一生产写入入口。`GoalExecutionApplication` 实现 Goal
创建/激活、Run/Context/Plan、Task/Action、Approval、Action Attempt、Evidence/Outcome、
Unknown 对账和 Run/Goal 完成判定；`CandidateLifecycleService` 负责提案、候选注册、评估与发布：候选晋升只能由 `complete_evaluation` 基于持久化 Trial 的 Wilson 置信评估记录驱动，caller 提供的通过决策不再被接受，审批必须携带理由。

每个纵向命令使用 `CommandContext` 携带 Identity/Tenant、Correlation、Causation、
Idempotency Key 和请求摘要。Application 打开事务，Repository 在该事务中写入业务状态、
Audit、Outbox 与幂等结果。Provider、HTTP、Temporal 和 ORM 对象不进入用例契约。
