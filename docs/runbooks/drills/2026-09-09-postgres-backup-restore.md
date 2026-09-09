# 演练记录：PostgreSQL 权威库备份与恢复（2026-09-09）

> 范围：本地 Compose 基础设施（真实 PostgreSQL 17 容器，89 个租户、组件测试产生的
> 真实数据），非生产集群演练。本记录同时是 P2-02 演练机制的首次执行样例。

## 目标（RTO/RPO）

| 指标 | 目标（本地演练观测） | 生产目标（待生产环境确认） |
|---|---|---|
| RPO | 最近一次成功备份（定时任务间隔） | ≤ 15 分钟（WAL 归档 + 周期全量） |
| RTO（数据层） | **0.4s**（恢复 89 租户库到独立恢复库，实测） | ≤ 30 分钟含实例切换 |

## 执行步骤与结果

1. **备份**：`bash tools/ops/backup_postgres.sh autonoesis-postgres-1 /tmp/autonoesis-drill p2-drill`
   - 产物：`autonoesis-p2-drill.dump`（custom 格式）+ TOC + manifest
   - manifest：`alembic_head: 0015_pack_supply_chain`，
     `sha256: 4b6814940e258de8afe7bb9c25e4ec79b19dabfefa6310a9633d3d762c7aa6d7`
2. **恢复**：`bash tools/ops/restore_postgres.sh … 0015_pack_supply_chain autonoesis_recovery`
   - `ok: alembic head restored (0015_pack_supply_chain)` —— schema 版本与备份一致
   - `ok: all tenant-scoped tables restored with row-level security forced`
     （平台级表 tenants/platform_kill_switches/platform_audit_events/breakglass_alerts
     按设计走独立 break-glass 角色路径，不在租户 RLS 内）
   - `ok: audit chain verified for tenant …`（对全部 89 个租户逐个验证哈希链）
3. **PITR 时间点恢复**（`tools/ops/pitr_drill.sh`，真实 PostgreSQL 17）：
   - WAL 归档启用（archive_command → /archive，28 段归档）；
   - 基线备份（pg_basebackup -Xs）在标记写入**之前**取得；
   - 写入 pre-target 租户标记 → 记录 `recovery_target_time` → 写入 post-target 标记 →
     pg_switch_wal 归档；
   - 以基线+归档 WAL 在全新容器实例恢复到目标时间：
     `ok: point-in-time recovery verified (pre-target present, post-target absent)`。
4. **备份集完整性**（`tools/ops/backup_postgres.sh` 扩展）：
   - 平台库 + Temporal workflow history/visibility 库共三个全量档案；
   - 独立关注点档案：stable-pointer（releases+deployments）、policy-packs
     （policy_versions+capability_packs+channels），可脱离全量单独恢复；
   - manifest 记录 alembic head 与每个档案的 sha256。
5. **对象存储保留与复制**：
   - `tools/ops/configure_object_store.py`：versioning + noncurrent 90 天生命周期 +
     Object Lock 状态报告（Enabled）；
   - `tools/ops/configure_object_replication.sh`：源桶 → Object-Lock 副本桶的
     MinIO 复制规则 + 探针对象传播验证（`ok: replication verified`）。

## 结论与边界

- 备份可恢复性、schema/RLS/审计链完整性、租户级隔离（每租户仅见自身链）在真实
  PostgreSQL 上验证通过；恢复库与源库并存，未污染源数据。
- 未完成 Run 恢复不重复副作用的证据由 Temporal Replay 组件测试承担
  （`apps/worker/tests/test_temporal_durability.py`，真实 Temporal）。
- 生产差距：跨区/跨站复制、季度完整切换演练（本记录为机制首次执行）、KMS 管理的
  生产备份凭证——这些需要生产环境，本演练不替代。WAL 归档与 PITR 机制本身已在
  本地真实 PostgreSQL 上验证。

## 复现

```bash
docker compose -f infra/compose/docker-compose.yml up -d postgres
# … migrate + seed …
bash tools/ops/backup_postgres.sh autonoesis-postgres-1 /tmp/autonoesis-drill p2-drill
bash tools/ops/restore_postgres.sh autonoesis-postgres-1 \
  /tmp/autonoesis-drill/autonoesis-p2-drill.dump 0015_pack_supply_chain
```
