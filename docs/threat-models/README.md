# Agentic 威胁模型

## 保护资产

租户数据与隔离、身份与委托、审批、Tool 凭证和网络权限、Run/Action/Outcome 权威状态、Context/Memory/Evidence、Candidate/Stable 版本、审计和 Kill Switch。

## 信任边界

入口用户、检索内容、模型提供商、Harness Sandbox、MCP/A2A、企业 Tool 与回调、Memory/向量服务、CI/CD 和 Capability Pack 供应链。

## 主要风险与控制

| 风险 | 当前控制 | 后续强化 |
| --- | --- | --- |
| Prompt Injection 扩大权限 | 来源与指令分离、模型不拥有权限、OPA/Schema 门禁 | 检索内容标签和攻击套件 |
| 跨租户泄漏 | OIDC Tenant Context、Repository 过滤、PostgreSQL RLS、HTTP 隐藏存在性 | 租户专属凭证和故障隔离演练 |
| 重试产生重复副作用 | Idempotency-Key、持久记录、网关去重 | 外部系统幂等键和对账 Worker |
| Tool 超时后状态未知 | Action `Unknown`、Workflow 禁止自动副作用重试 | 查询真实状态和补偿流程 |
| 模型宣告自己完成 | Evidence/Outcome 独立对象和权威回读 | 签名 Evidence 与不可变存储 |
| 审批后参数变化 | Action 参数摘要、审批有效期、执行时重新检查 | 策略变更后自动失效 |
| Memory 污染 | 来源、置信度、Scope、TTL、人工批准 | 独立 Memory Grader 和删除传播 |
| Candidate 自评自发 | 生成者、Grader、审批人相互独立 | Shadow/Canary 与观察窗口 |
| 恶意能力包 | 严格 Manifest、Entry Point 组、版本和依赖边界 | 签名、SBOM、来源允许列表和 Sandbox |
| 审计被篡改 | 追加式 Audit、关联 ID、数据库权威 | WORM 存储和外部审计导出 |

修改身份、OPA、Sandbox、网络出口、Secret、Memory 写入门禁或 Release Gate 时，必须更新本文件或增加范围更小的威胁模型。
