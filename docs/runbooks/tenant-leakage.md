# Runbook: Tenant Leakage（疑似租户数据泄漏）

> 适用：怀疑一个租户的数据、凭证、遥测或命名空间被另一租户访问或可见。
> 严重级别：最高。目标是**立即止损、保全证据、事后验证边界仍然封闭**。

## 1. 立即止损（0–10 分钟）

1. 对疑似受影响租户激活 Kill Switch（运营操作中心，输入 `HALT`），阻断后续外部副作用。
2. 若怀疑平台级隔离缺陷：走 Break-glass 平台级 Kill Switch（需票据 + 临时授权，
   自动告警并强制事后复核）。
3. **保全证据**：导出审计链（/v1/audit-events，含哈希链摘要）、相关 Trace ID
   （响应头 X-Trace-ID）、审计 `security.tenant_scope_lookup_denied` 记录。

## 2. 边界核查（对照 P1-01 防线）

1. PostgreSQL：确认所有租户表 RLS 策略存在且 FORCE（迁移 0001 起）；用 admin 连接
   抽查 `current_setting('app.tenant_id')` 行可见性。
2. 对象存储：按租户前缀（TenantNamespaces.object_prefix）核对对象归属与策略。
3. Temporal：Workflow ID 必须携带 `tenant-{token}` 前缀；核对无跨租户队列消费。
4. 遥测/评估/发布：确认 `TenantTelemetryRecord.for_export` 的租户校验路径未被绕过。
5. 内存（Memory）：Ledger 写入门禁与递归删除传播是否按租户隔离。

## 3. 验证武器

- 双租户攻击矩阵（tests/security/test_tenant_isolation_matrix.py）在隔离副本上重放：
  同名 Goal/Pack/Release/评估套件互不可见。
- 泄漏样本仅允许以摘要/引用形式进入工单；原始租户数据不得跨租户复制。

## 4. 恢复

1. 修复后先在 CI/隔离环境全量重放攻击矩阵，再解除 Kill Switch（`RESUME` + 理由）。
2. 对泄漏期间所有跨租户访问尝试出具清单（来自审计链），通知受影响租户（按合规义务）。
3. 事后必须新增一个攻击矩阵用例固化该泄漏模式，防止回归。

## 5. 禁止事项

- 禁止用 admin/break-glass 身份"验证一下数据"而不留票据——break-glass 全程告警+复核。
- 禁止在工单/日志中粘贴租户原始数据（结构化日志会脱敏，但人不会）。
