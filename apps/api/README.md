# API 应用

FastAPI 控制面原型，提供 Capability Pack、Agent/Skill/Tool、Goal/Run、治理、评估、Candidate、Release 和审计接口骨架。

租户、Actor 和 Principal 来自 OIDC 或明确的本地开发身份 Header。配置数据库 URL 时，生产路径使用进程级 PostgreSQL Store，Capability、Goal/Run、Approval、Evidence、改进发布、Kill Switch、Audit 和幂等状态不保存在 API 进程内；Store 在 FastAPI lifespan 结束时关闭。未配置数据库的 InMemory 路径只用于测试和显式离线开发。

错误响应中的 `audit://` 仍不是已持久化证据，且 P0-04 纵向 Application 用例尚未收敛，因此这些接口仍属于工程预览。API 不直接执行 Action，持久执行由 Temporal Worker 通过 Application Use Case 推进。
