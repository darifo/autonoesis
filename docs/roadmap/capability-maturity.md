# 能力成熟度矩阵

> 基线日期：2026-09-09
> 产品状态：架构原型 / 工程预览
> 状态定义：以[企业级生产就绪整改路线](enterprise-production-readiness-remediation.md#36-以运行证据定义完成)为准

## 声明规则

1. 成熟度声明描述真实运行证据，不以类、表、路由或测试文件数量替代；
2. `unit-tested` 只引用无真实基础设施依赖的自动化测试；
3. `integrated` 必须引用在 CI 中运行的真实组件任务或已归档演练报告；
4. `production-proven` 必须同时具备故障、并发、安全、运维验收和可定位的证据；
5. 证据失效、CI 门禁移除或实现路径改变时，必须在同一个变更中降级声明；
6. 文档、README、API 元数据和 Cockpit 不得给出高于本矩阵的声明。

当前 P0 参考纵向切片、PostgreSQL 权威存储、HTTP/Application 用例、Governed Tool Gateway、
Temporal 耐久编排、Evidence/Outcome/Audit 可信链，以及 P1-01～03 的多租户、身份和可信
Context/Memory 达到 `integrated`。P1-01～07 全部 68 项实施与退出门槛完成（退出门槛按 CI 组件/安全套件证据等级，
非 production-proven）（Evaluation 与 Release Executor 组件测试经真实 Temporal + PostgreSQL 验证），
整体仍为 `unit-tested`；没有任何能力达到 `production-proven`。

## 当前矩阵

| 能力 | 当前成熟度 | 已有证据 | 达到下一等级仍缺少 |
|---|---|---|---|
| 领域语言与基础状态机 | `integrated` | P0-02 冻结契约；CI 参考 E2E 真实推进 Goal/Run/Task/Action/Evidence/Outcome | 属性测试、长期兼容与生产异常状态演练 |
| Capability Pack Manifest | `integrated` | Field Service Pack（签名+Digest+SBOM）经真实 API 安装并驱动参考 E2E；来源允许列表/ed25519 签名/内容寻址/同版本内容冲突拒绝/租户 enable-disable-revoke 与 Stable Channel（迁移 0015，事务+审计+Outbox）；API 控制面禁止执行 Pack 代码（架构测试）；Worker 默认子进程沙箱执行 Subject | 生产密钥流水线、漏洞/SBOM 扫描、OS 级沙箱（容器/seccomp）与真实供应链演练 |
| Goal/Run Application 用例 | `integrated` | PostgreSQL 事务/恢复组件测试；真实 Temporal/Tool/OPA/Evidence 参考 E2E | 真实第三方系统、网络故障和多进程容量演练 |
| HTTP API/SDK | `integrated` | 冻结 OpenAPI 3.1、Consumer Contract、统一错误 Envelope；参考 E2E 从真实 ASGI API 发起 | 生成 SDK、多副本 API、OIDC 与外部 Consumer 验证 |
| PostgreSQL 权威存储 | `integrated` | CI PostgreSQL 17；Alembic `0001 → 0009`；全租户表强制 RLS 与双租户攻击矩阵 | 备份恢复、故障注入、容量/升级演练和长期运行证据 |
| Temporal 耐久编排 | `integrated` | CI 真实 Temporal：Outbox/Reconciler、重启/Replay，以及租户化 Workflow ID、Queue、Worker Pool 攻击测试 | Namespace 预配自动化、HA/备份、容量、网络分区和滚动升级演练 |
| Governed Tool Gateway | `integrated` | PostgreSQL 原子预算/幂等 Reservation、真实 OPA、凭证租约、受控出口和故障语义组件测试 | 生产 Credential Broker、网络层出口策略和第三方系统故障演练 |
| Identity/Policy/Approval | `integrated` | P1-02 进程级 JWKS、严格 OIDC Claims、PostgreSQL 即时委托撤销、双 Principal 高风险审批、进化职责分离和 Break-glass 临时授权/告警/复核；真实 OPA Worker 决策 | 生产企业 IdP/SCIM、密钥轮换与故障、工作负载身份联邦和 SOC 告警演练 |
| Evidence/Outcome/Audit | `integrated` | CI PostgreSQL 17 + KMS MinIO：预写入准入、Version/Object Lock、Saga 恢复、权威回读 Outcome、并发摘要审计链、真实 Audit Ref 和删除墓碑/证明 | 生产 KMS/跨区复制、真实业务 Authority、WORM 导出、保留/删除长期演练 |
| Context/Environment/Memory | `integrated` | P1-03 多维 Context ACL、可复现 Snapshot 摘要、冲突/Injection 信号、Memory Write Gate；PostgreSQL Ledger、递归删除传播和向量投影清理 | 生产来源 Connector/DLP、规模化索引重建和数据主体删除演练 |
| Evaluation | `unit-tested` | Harness 执行固定 Subject Version；Trial 完整保存固定条件与结果；五级 Grader 严格顺序/独立身份/短路门禁；隐藏与生产回放 Case Catalog 隔离；权威 JSON 无损持久化；重复 Trial 以 Wilson 双侧置信区间门禁（下界达标=MET，上界低于阈值=NOT_MET，跨阈值区间继续采样，ADR-0024 修正）；Candidate 固定引用与禁止目标双层拒绝；CandidateEvaluation 证据记录持久化并绑定晋升，caller 决策路径已移除；Suite Catalog 持久化，Pack 声明式 Subject（进程内）+ 独立规则 Grader 后端经真实 Temporal 工作流与 PostgreSQL 组件测试驱动重复 Trial 至置信晋升 | Human 决策工作流化；沙箱绝对路径文件读防御（OS 级 gVisor/Kata 职责）；LLM Judge 生产 IdP 密钥与提示词红队测试 |
| Shadow/Canary/Rollback | `unit-tested` | 持久化 Deployment/Release、Active Stable 唯一约束与乐观版本 CAS；每 (租户,部署,阶段,指标) Guardrail 观测计数器；Canary 观察窗口/最小样本/指标缺失拒绝晋升；Guardrail 越界自动回滚目标部署；并发晋升唯一胜出组件测试；Shadow 写抑制（Run 绑定部署 + 执行时拒绝 L2+ 写）；Application Stable/Candidate 并发成对执行端口与逐请求对比证据；Worker 注册 ShadowPair Workflow/Activity；API 使用 Payload-bound 固定 ID Dispatch 到租户 high-risk Pool；Canary 进入绑定确定性可审计 TrafficAllocation（SHA-256 salt+request 分桶，持久化于 Deployment definition，可按 request 重放路由）；独立 ReleaseExecutionWorkflow 以 per-tenant executor/grader 分离身份执行 Canary/Stable/Rollback，API 仅 Dispatch 并在无 Executor 时 503 失败封闭；真实 Temporal + PostgreSQL 组件测试驱动 Shadow→Canary 规则绑定 | 生产 Shadow Runtime、Candidate 沙箱、Shadow/Release Outbox 对账、Goal/Run 创建实时绑定路由和长期攻防演练 |
| Cockpit | `unit-tested` | CI Vitest/typecheck/build/Playwright；12 个数据页直连真实 API（错误/空状态显式呈现，不回退样例）；运营操作中心覆盖审批/Unknown 对账/Kill Switch/回滚/接管，全部经角色+幂等键+输入目标标识的二次确认；客户端支持 OIDC Bearer 令牌（配置后取代开发身份头，经 API 既有 OIDC 验证路径） | 生成 Client 接入与真实权限操作演练（令牌获取流程需部署环境 IdP） |
| 可观测性/FinOps/SLO | `unit-tested` | OTel SDK 接入 API/Worker/Repository/Gateway/模型适配（OTLP/HTTP，无端点时 no-op）；请求 Span 关联租户/Correlation 并回传 X-Trace-ID，Worker 经 Temporal TracingInterceptor 贯穿；JSON 结构化日志递归脱敏（敏感键+凭证形块）；审计事件投影 SLO 测量（无事件不合成）；SLO 按 sample_count 加权并区分 gte/lte；FinOps 四阶段（预估/预留/结算/重试浪费）经权威 budget_ledger 并按 Run/Goal 汇总 | 告警通道接线（规则已定义于 infra/observability/alerts.yaml）和生产运行演练 |
| 多租户隔离 | `integrated` | P1-01 双租户真实 API/PostgreSQL/MinIO/Temporal/Telemetry/Memory/Release 攻击矩阵；独立 Break-glass 审计 | 生产 Bucket Policy、Temporal Namespace 预配、外部 Search/Vector/Telemetry 后端和长期攻防演练 |
| 生产部署/HA/DR/供应链 | `specified` / 部分 `unit-tested`（实施项全部交付） | 锁文件依赖审计、精确 Secret 基线、CI 哈希证据归档；Helm Chart（风险分层 Worker Pool 各配专用 ServiceAccount/默认拒绝 Egress/加固 SecurityContext/ExternalSecret 可选/配额/AZ spread/滚动升级+PDB，CI lint+渲染断言校验）；CI 生成 Python/Node/Capability Pack CycloneDX SBOM 并归档证据；6 个 P2 Runbook 与运营流程文档（值班告警/租户生命周期/版本与变更控制）；已执行的真实演练：备份集恢复（schema/RLS/审计链验证）、PITR 时间点恢复、对象存储复制传播；容量基线与混沌注入实测（docs/ops/capacity-model.md） | 生产集群部署与滚动升级、跨区复制、季度完整 DR 切换、非开发人员 Runbook 执行与告警接线等生产验收 |

## 证据入口

- 自动化门禁：[`.github/workflows/ci.yml`](../../.github/workflows/ci.yml)
- 可重复基线检查：`task baseline`
- 生成的版本清单：[生产基线报告](generated/production-baseline-report.md)
- 当前限制：[生产就绪基线](production-readiness-baseline.md)
- 后续验收场景：[整改路线第 9 节](enterprise-production-readiness-remediation.md#9-必须持续执行的验收场景)
