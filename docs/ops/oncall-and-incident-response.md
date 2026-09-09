# 值班、告警分级与事件响应（P2-05）

## 1. 值班轮替

- 值班角色：**一线值班**（操作员，可执行 Runbook 的止损动作）与 **二线负责人**
  （平台工程，架构级故障）。租户侧审批人独立于值班线（职责分离）。
- 交接：交接单记录进行中事件、未处置告警、临时的 Kill Switch/降级状态。
- 高风险操作的 authority：值班执行止损（HALT/回滚/接管）用自身身份 + 幂等键 +
  二次确认；解除（RESUME）需二线批准并在审计链留理由。

## 2. 告警分级

| 级别 | 定义 | 触发源（现役信号） | 响应 SLA |
|---|---|---|---|
| SEV-1 | 平台不可用 / 多租户隔离疑似破坏 / 数据丢失风险 | 健康探测失败、`security.tenant_scope_lookup_denied` 异常激增、审计链校验失败 | 立即，15 分钟止损 |
| SEV-2 | 单租户不可用 / Kill Switch 激活 / 错误预算耗尽 | `/v1/slos` exhausted=true、`platform.kill_switch.activated` | 1 小时 |
| SEV-3 | 退化（延迟/重试浪费升高、Provider 故障） | `retry_waste` 增长、SLO 消耗加速 | 当日 |

告警通道与升级链在部署环境配置（OTel Collector → 值班系统）；本仓库提供信号：
审计事件、SLO 端点、FinOps 阶段账本、OTel 追踪。

## 3. 事件响应流程

1. **止损优先**：按对应 Runbook 执行（tenant-leakage / provider-failure /
   approval-backlog / memory-poisoning / action-unknown / kill-switch）。
2. **证据保全**：导出审计链（哈希摘要）、相关 Trace ID、SLO 快照——在任何
   恢复动作之前。
3. **恢复**：经演练过的工具（restore/pitr/rollback）而非即兴操作；所有动作走
   运营操作中心（角色+幂等+确认）。
4. **客户通知**：SEV-1/SEV2 影响租户的，按租户合同约定的通道在 SLA 内通知，
   内容以审计链事实为准（时间窗、影响面、已采取动作），不含未证实猜测。
5. **复盘**：无责复盘，产出：时间线、根因、防回归测试/演练用例（必须入库）、
   文档修订。复盘记录归档于 `docs/runbooks/drills/` 或事件系统。

## 4. 演练制度

每个 Runbook 至少每季度演练一次并留记录（`docs/runbooks/drills/`）；已建立记录：
- PostgreSQL 备份/恢复 + PITR（2026-09-09）
- Guardrail 越界自动回滚（CI 组件测试，持续）
- Worker Crash → Replay 不重复副作用（CI 组件测试，持续）
