# PostgreSQL 持久化适配器

`persistence_schema.py` 定义当前权威 Schema，`persistence_codec.py` 负责领域聚合无损映射，
`persistence.py` 实现按聚合/Use Case 组织的 Repository。生产 `PostgreSQLPlatformStore` 只做
进程级 Engine 生命周期和 Repository 委托，不继承或复制 `InMemoryPlatformStore` 状态。

关键约束：

- Tenant Authority 与 Tenant 复合外键；
- 合法状态、正版本/预算、Evidence 摘要与有效区间 Check Constraint；
- 资产版本、Action/请求幂等、Trial 固定条件和 Active Stable Pointer 唯一约束；
- mutable aggregate 的乐观锁；
- 业务事实、Audit、Outbox 同事务提交；
- Application Role 强制 RLS，Migration/Relay/Audit 角色职责分离。

SQLite 只用于无基础设施的 Outbox/Inbox 单元测试。权威行为以 CI 中 PostgreSQL 17 组件测试
为准。
