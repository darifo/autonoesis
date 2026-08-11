# Worker 应用

注册 `GoalRunWorkflow` 和 `CandidateLifecycleWorkflow` 原型，建模长任务、审批 Signal、取消、评估和候选晋升流程。

当前 Worker 使用进程内 Store，尚未证明 PostgreSQL 权威写入、Replay、崩溃恢复或副作用不重复。目标边界是 Workflow 不把自身历史当作业务权威，所有状态变更通过 Application Use Case 事务写入 PostgreSQL。
