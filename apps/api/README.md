# API 应用

FastAPI 控制面原型，提供 Capability Pack、Agent/Skill/Tool、Goal/Run、治理、评估、Candidate、Release 和审计接口骨架。

租户、Actor 和 Principal 来自 OIDC 或明确的本地开发身份 Header。当前默认装配使用进程内 Store，错误响应中的 `audit://` 也不是已持久化证据；因此这些接口只适合开发和隔离测试。目标边界要求 API 不直接执行 Action，持久执行由 Temporal Worker 通过 Application Use Case 推进。
