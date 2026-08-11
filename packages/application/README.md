# Application

Application 是受治理业务状态的唯一生产写入入口。`GoalExecutionApplication` 实现 Goal
创建/激活、Run/Context/Plan、Task/Action、Approval、Action Attempt、Evidence/Outcome、
Unknown 对账和 Run/Goal 完成判定；`CandidateLifecycleService` 负责候选评估与发布。

每个纵向命令使用 `CommandContext` 携带 Identity/Tenant、Correlation、Causation、
Idempotency Key 和请求摘要。Application 打开事务，Repository 在该事务中写入业务状态、
Audit、Outbox 与幂等结果。Provider、HTTP、Temporal 和 ORM 对象不进入用例契约。
