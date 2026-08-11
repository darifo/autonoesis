# 本地 Compose

`docker-compose.yml` 启动 PostgreSQL、Temporal、OPA、MinIO、Jaeger、API、Worker 和 Cockpit，用于完整本地开发与恢复测试。

PostgreSQL 首次初始化会创建独立的 Migration、Application、Relay 和 Audit 角色。Compose
密码仅限本机；生产环境必须由 Secret Manager 创建 Login Role，并只继承
`infra/postgres/roles.sql` 中的 NOLOGIN 权限角色。API 启动时先以 Migration Role 执行迁移和
显式 Tenant provisioning，再以 Application Role 运行服务。删除已有 `postgres-data` 会丢失
本地数据库，Compose 不会自动执行该操作。
