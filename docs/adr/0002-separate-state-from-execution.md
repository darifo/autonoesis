# ADR-0002：分离业务权威状态与持久执行

- 状态：accepted
- 日期：2026-08-01

## 背景

长任务必须跨故障、审批、取消和重试继续运行。Workflow History 适合确定性恢复，企业业务状态则需要关系约束、明确所有者、查询、保留和审计语义。

## 决策

- PostgreSQL 是 Goal、Plan、Decision、Run、Task、Action、Approval、Outcome、Evidence 元数据和 Release 的权威；
- Temporal 是 Workflow History、Timer、Retry、Signal 和 Continuation 的权威；
- 状态变更与事件发布使用 Transactional Outbox，消费者使用 Inbox 和 Idempotency Record；
- Workflow 私有历史不能证明外部业务 Outcome 已经发生。

## 后果与验证

需要处理双写协调和对账；Workflow 代码必须确定性。集成测试覆盖进程重启、重复投递、超时未知、取消和授权变化后的恢复。
