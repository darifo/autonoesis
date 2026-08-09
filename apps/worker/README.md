# Worker 应用

注册 `GoalRunWorkflow` 和 `CandidateLifecycleWorkflow`，负责长任务、审批 Signal、恢复、取消、评估和候选晋升。Workflow 不把自身历史当作业务权威，所有状态变更通过应用事务写入 PostgreSQL。
