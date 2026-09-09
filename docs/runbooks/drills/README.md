# 演练记录索引（P2-05）

每个 Runbook 至少每季度演练一次；组件级持续演练由 CI 承载并在下表引用。

| 演练 | 频率 | 最新记录 | 承载 |
|---|---|---|---|
| PostgreSQL 备份/恢复 + PITR | 季度 | [2026-09-09](2026-09-09-postgres-backup-restore.md) | `tools/ops/backup_postgres.sh` 等 |
| Guardrail 越界自动回滚 | 每次发布分支 | CI 组件测试 | `test_release_gates_component.py` |
| Worker Crash → Replay | 持续 | CI 组件测试 | `test_temporal_durability.py` |
| 双租户隔离攻击矩阵 | 持续 | CI 安全套件 | `test_tenant_isolation_matrix.py` |
| Provider 故障退化 | 季度 | `tools/perf/load_profile.py --chaos provider-5xx` | 容量基线（docs/ops/capacity-model.md） |
| 网络分区注入 | 季度（生产环境） | **待首次执行** | 生产演练缺口 |
