# API 应用

FastAPI 控制面，提供 Capability Pack、Agent/Skill/Tool、Goal/Run、治理、评估、Candidate、Release 和审计接口。

租户、Actor 和 Principal 来自 OIDC 或明确的本地开发身份 Header。API 不直接执行 Action；持久执行由 Temporal Worker 推进。
