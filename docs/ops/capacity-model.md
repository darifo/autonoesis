# 容量模型与压测基线（P2-04）

> 首次测量：2026-09-09，单进程 uvicorn（Apple Silicon 本地），InMemory 装配。
> 数字用于建立**方法与相对基线**；绝对值必须在目标生产拓扑上重测。

## 1. 请求放大模型（每租户）

```text
1 Goal 请求 → 1 GoalContract + 1 Run + K Task + A Governed Action + E Evidence
  - Run dispatch：1 outbox 行 + 1 Temporal Workflow
  - 每个 Governed Action：1 幂等/预算预留行（pg_advisory_xact_lock 串行化同键）
    + ≤N 审计/Outbox 事件（action.proposed/authorized/attempt/…/recorded）
  - K/A/E 由 Pack 的 goal_type 声明决定；规划用 K=3, A=K, E=A 估计
```

容量规划变量：`R` = 租户稳态 Goal 到达率；`并发活跃 Run = R × 平均 Run 时长`；
数据库写放大 ≈ `R × (2 + 5A)` 行/秒（含审计/Outbox）；Temporal 任务率 ≈ `R × K`。

## 2. 实测基线（load_profile.py，GET 热路径）

| 并发 | 请求/5-6s | 错误率 | p50 | p95 | p99 |
|---:|---:|---:|---:|---:|---:|
| 10 | 8,355 | 0% | 5.6ms | 8.2ms | 10.9ms |
| 20 | 2,767 | 0% | 24.1ms | 107.5ms | 164.5ms |
| 50 | 8,138 | 0% | 33.7ms | 54.8ms | 66.2ms |

混沌注入（provider-5xx，2s 故障窗）：错误被计入报告（`status_codes[0]`），
恢复窗后回到 0 错误——退化行为可测量、可恢复（`tools/perf/load_profile.py --chaos`）。

## 3. 组件级压力/混沌证据映射

| 负载面 | 证据（CI 组件测试/演练） |
|---|---|
| PostgreSQL RLS + 并发预留 | `packages/adapters/tests/test_governed_tool_gateway.py`、`test_postgres_authority.py`（并发晋升唯一胜出） |
| Outbox/Reconciler | `apps/worker` dispatch 组件测试（重启/Replay、消息重复按幂等键折叠） |
| Temporal 队列 | `test_temporal_durability.py`（Worker Crash → Replay 不重复副作用） |
| DB Failover | `docs/runbooks/drills/2026-09-09-postgres-backup-restore.md`（PITR/恢复演练） |
| 对象存储错误 | Evidence Saga 恢复组件测试（`test_trusted_evidence_component.py`） |
| 预算/Kill Switch 压力 | 原子预算预留 + 双租户 Kill Switch 攻击矩阵（`tests/security/`） |
| 网络分区 | **生产演练缺口**：机制存在（出口白名单/失败封闭），分区注入需生产环境执行 |

## 4. 扩容阈值与成本模型

- API：p95 超过 SLO 目标（见 docs/slo/service-levels.md）→ 增加 API 副本
  （Chart `api.replicas`，maxUnavailable=0 滚动）；每副本独立无状态。
- Worker：按风险池独立扩容（`workerPools.<pool>.replicas`）；积压指标 =
  Temporal 队列深度（high-risk 池优先）。
- 数据库：写放大逼近连接/IO 上限 → 先垂直扩，再按租户分片（租户隔离是
  一等维度，天然支持）。
- 成本：单位成功 Goal 成本由 FinOps 四阶段账本（estimate/reserve/settle/
  retry_waste）驱动；`retry_waste` 是混沌/退化期的成本信号，纳入复盘。

## 5. 复现

```bash
uvicorn autonoesis_api.main:app --port 8931 --app-dir apps/api/src &
python3 tools/perf/load_profile.py --base-url http://localhost:8931 --concurrency 50
python3 tools/perf/load_profile.py --base-url http://localhost:8931 --chaos provider-5xx
```
