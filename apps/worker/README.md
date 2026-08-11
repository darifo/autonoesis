# Worker 应用

注册 `GoalRunWorkflow` 和 `CandidateLifecycleWorkflow` 原型，建模长任务、审批 Signal、取消、评估和候选晋升流程。

Worker 运行时要求 PostgreSQL URL，并在进程内共享一个 Engine/Store；退出时释放连接池。权威写入、乐观冲突和跨进程可见性已有 PostgreSQL 组件证据，但 Temporal Replay、崩溃恢复和副作用不重复仍未证明。Workflow 不把自身历史当作业务权威，所有状态变更应通过 Application Use Case 事务写入 PostgreSQL。
