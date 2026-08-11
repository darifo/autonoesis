# 数据库迁移

Alembic 管理 PostgreSQL 权威 Schema、Tenant RLS、数据库约束和角色授权。历史 Revision
必须自包含，不得导入当前应用 metadata 执行 `create_all()`。

## P0-03/P0-04 升级顺序

1. 停止 API、Worker、Outbox Relay 等写入进程，并确认没有长事务；
2. 使用 PostgreSQL 原生工具创建可恢复备份，并记录数据库版本、Alembic head 和备份摘要；
3. 以集群管理员执行 `infra/postgres/roles.sql`；
4. 设置独立的 Migration Owner 连接和角色：

   ```sh
   export AUTONOESIS_MIGRATION_DATABASE_URL='postgresql+psycopg://<migration-login>@<host>/autonoesis'
   export AUTONOESIS_MIGRATION_ROLE='autonoesis_migration'
   alembic upgrade head
   ```

5. 使用 `tools/admin/provision_tenant.py` 显式登记由身份目录确认的 Tenant；
6. 用 Application Role 启动一个 API 副本，验证 RLS、Capability、Goal/Run、Approval、Release
   和 Audit 读取；再逐步恢复 Worker 与其余副本；
7. 保留升级备份，直到兼容性观察窗口结束。

Revision `0002_authoritative_state` 会为旧数据补齐 Tenant Authority 记录并使用 `legacy-`
名称标识待对账 Tenant。旧 Evidence 若无法关联同 Tenant/Run 的 Action，迁移会明确失败，操作员
必须先完成对账，不能静默降级完整性。

Revision `0003_application_use_cases` 强制一个 Run 只有一个不可变 Context Snapshot，并新增
受租户 RLS、复合外键、合法状态和幂等唯一约束保护的 `action_attempts`。若旧数据中一个 Run
已有多个 Context，迁移会失败并要求先对账。

## 回滚

`0002` 增加了 Deployment、完整 Approval/Evidence/Outcome 契约、复合外键与 Active Stable
Pointer；`0003` 增加了不可丢弃的执行尝试事实。旧 Schema 无法无损表达这些事实，因此禁止
原地 `alembic downgrade`。回滚步骤是：

1. 再次停止所有写入进程；
2. 保存失败升级库用于取证；
3. 恢复升级前备份到新的数据库实例；
4. 将应用连接切回恢复实例并执行读验证；
5. 若升级后产生了外部副作用，按 Audit/Outbox 和 Evidence 记录执行前向对账，不把数据库恢复
   当作外部系统回滚。
