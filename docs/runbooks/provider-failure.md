# Runbook: Provider Failure（模型/工具提供商故障）

> 适用：模型适配器（OpenAI/Anthropic 兼容端点）或外部工具系统不可用、限流或返回持续 5xx。
> 目标：平台降级可控、预算不被浪费消耗、Unknown 不被臆断、恢复后自动续跑。

## 1. 检测

- OTel 追踪中 `autonoesis.model.generate` / `autonoesis.gateway.reserve` Span 错误率升高。
- 审计事件 `action.governed_execution_recorded` 明细中失败状态比例上升；`budget.recorded`
  出现 `retry_waste` 阶段条目。
- /v1/slos 中 `action_success_rate` 错误预算消耗加速。

## 2. 立即动作（0–15 分钟）

1. **不要**将失败 Action 手工标记为成功；执行时 Unknown 只能经权威回读对账
   （见 [action-unknown.md](action-unknown.md)）。
2. 确认故障范围：单租户、单 Pack 还是平台级（查询审计事件按 `object_type=action` 聚合）。
3. 若为持续 5xx：在提供商侧确认事故状态；平台侧依赖 Temporal 的 Activity 重试策略，
   不要手工重放松弛幂等键——重复执行可能重复副作用。
4. 若预算被重试快速消耗：激活租户级 Kill Switch 阻断后续外部副作用
   （运营操作中心 → Kill Switch，输入 `HALT` 确认），原因记录进审计链。

## 3. 降级运行

- 只读/计算类（L0/L1）Goal 可继续；L2+ 写入依赖提供商恢复。
- Candidate 评估若依赖 Pack Subject（进程内/沙箱执行）可继续；依赖外部模型的 Grader 暂停。

## 4. 恢复与验证

1. 提供商恢复后，观察 `retry_waste` 停止增长、`action_success_rate` 预算回收。
2. 对故障期间产生 Unknown 的 Action 逐一经权威凭证对账。
3. 解除 Kill Switch（输入 `RESUME` 确认 + 解除理由）。
4. 在事后报告中记录：故障窗口、受影响 Run 数、浪费成本（FinOps `retry_waste` 总额）、
   对 SLO 错误预算的消耗。

## 5. 禁止事项

- 禁止绕过 Tool Gateway 直连提供商"先跑通再说"。
- 禁止以固定次数盲目重试替代置信判断（与评估门禁同理）。
