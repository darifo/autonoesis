# 生产就绪基线与限制

> 评审日期：2026-09-09
> 适用版本：0.1.x
> 判定：架构原型 / 工程预览，不可用于生产或高风险真实写操作

## 当前可信范围

仓库已经提供领域模型、应用服务骨架、HTTP 路由、SQLAlchemy Schema、Temporal Workflow
定义、基础设施 Compose 文件以及若干适配器。现有 CI 能重复验证 Python 格式、Lint、
严格类型和隔离单元测试，执行冻结 OpenAPI Consumer Contract、PostgreSQL 17 迁移、Temporal、
OPA、KMS MinIO、参考纵向 E2E、依赖/Secret 扫描，以及 Cockpit 单元、类型、构建和浏览器测试；
测试结果生成哈希清单并由 CI 保留 30 天。

这些证据支持 P0 参考纵向切片、PostgreSQL 权威存储、HTTP/Application 用例、Governed Tool
Gateway、Temporal 耐久编排、Evidence/Outcome/Audit 可信链，以及 P1-01 多维租户隔离、
P1-02 企业身份治理、P1-03 可信 Context/Memory 的 `integrated` 声明。P1-04 Evaluation 九个
实施项全部完成（含重复 Trial 置信门禁、Candidate 固定引用、禁止目标双层禁止和评估证据
持久化门禁），仍为 `unit-tested`；没有任何能力达到 `production-proven`。

## 生产限制

- PostgreSQL 已有冻结迁移、租户复合外键、全租户表强制 RLS、非 BYPASSRLS 应用角色和双租户攻击矩阵，但尚无生产备份恢复、容量、故障和滚动升级演练；
- Temporal 已有 Outbox Dispatcher、固定 Workflow ID、DB/Workflow Reconciler、Replay、Worker
  重启、租户化 Workflow ID/Queue/Worker Pool 和故障注入组件测试；尚无生产 Namespace 预配、HA/备份、积压容量和滚动升级演练；
- Tool Gateway 已使用 PostgreSQL 原子协调预算与幂等 Reservation，并以真实 OPA 验证策略；
  但生产 Credential Broker、网络层出口策略及第三方系统端到端写入仍未演练；
- Evidence 已通过真实 MinIO 的 SSE-S3、版本、Tenant 前缀、COMPLIANCE Object Lock、Saga、
  删除墓碑/证明和 PostgreSQL 审计链组件测试；尚无生产 KMS、Bucket Policy、跨区复制、
  WORM 导出和长期保留/删除演练；
- OPA Policy 组件测试已进入 CI，但尚未完成策略发布、回滚和不可用故障演练；
- API 未持久化错误返回空 Audit Ref；已提交事件返回带摘要的真实 Ref，但错误审计全面覆盖
  和外部 WORM 导出尚未完成；
- P1-01 使用真实 PostgreSQL、MinIO 和 Temporal 验证 API、DB、Object、Workflow、Telemetry、
  Memory、Evaluation 和 Release 的双租户隔离，并建立独立 Break-glass 路径；外部
  Search/Vector/Telemetry 后端、生产 Bucket Policy 与长期攻防演练仍未完成；
- Evaluation Harness 已在单元层执行固定 Subject Version、记录完整 Trial 条件并对缺失执行、
  基础设施错误和不确定评分失败关闭；五级 Grader 按治理顺序、独立身份和短路门禁执行，
  隐藏/生产回放 Case 不向 Generator 暴露；重复 Trial 以 Wilson 双侧置信区间门禁——下界达标即
  MET，上界低于阈值才 NOT_MET，跨阈值区间保持采样而非误判拒绝（ADR-0024 修正），Invalid
  Trial 不计入绿色率也不折抵最小样本；Candidate 必须携带不可变 Artifact Digest、固定 Suite
  与 Generator 身份，禁止改进目标在 Application 与 OPA 策略层双重拒绝；Candidate 晋升只能
  由持久化 Trial 的置信评估记录（candidate_evaluations）驱动，caller 决策路径已移除，
  审批必须携带理由；Suite Catalog 已持久化，Pack 声明式 Subject（进程内执行）与独立规则 Grader 后端经真实
  Temporal 工作流和 PostgreSQL 组件测试驱动重复 Trial 至置信晋升，生产 Worker 已装配评估器，
  Grader 与 Release Executor 使用 per-tenant 确定性分离身份；Pack 代码沙箱隔离与
  Outcome/LLM/Human Grader 后端仍未完成；
- Candidate/Shadow/Canary 已持久化 Deployment/Release、Active Stable 唯一约束与乐观版本 CAS；
  Canary 晋升受观察窗口、最小样本和指标缺失拒绝门禁约束，Guardrail 越界自动回滚且按
  (租户, 部署, 阶段, 指标) 隔离，并发晋升唯一胜出有组件测试；Shadow 写抑制已落地——Run 可选
  绑定部署，执行时对 L2+ 写操作失败封闭拒绝，读取仍放行；Application 已具备 Stable/Candidate
  并发成对执行端口，并持久化 Outcome、成本、延迟、安全和人工修正的逐请求对比证据；生产
  Worker 已注册逐请求 `ShadowPairWorkflow`/Activity 合约，API 以 Payload-bound 固定 Workflow ID
  Dispatch 到租户 high-risk Pool；Canary 进入绑定确定性 TrafficAllocation 规则（SHA-256
  salt+request 分桶，持久化于 Deployment definition 并可按 request 重放路由）；独立
  `ReleaseExecutionWorkflow` 是 Canary/Stable/Rollback 的唯一执行路径——API 仅做状态预检与
  Dispatch（202 + Workflow ID），未配置 Executor 时 503 失败封闭，真实 Temporal + PostgreSQL
  组件测试验证 Shadow→Canary 规则绑定；生产 Shadow Runtime、Candidate 沙箱、Shadow/Release
  Outbox 对账和 Goal/Run 创建实时路由绑定仍未完成；
- Cockpit 数据页直连真实 API（未配置身份时显式错误状态而非样例回退），运营操作中心
  覆盖审批/Unknown 对账/Kill Switch/回滚/接管（角色+幂等键+输入目标标识二次确认）；
  总览页仍为静态演示；控制台身份仍是浏览器本地 dev 头，未接 OIDC；
- OTel 追踪（API 请求 Span/Worker Temporal 拦截器/权威事实与网关子 Span）、JSON 脱敏
  日志、审计事件投影的加权 SLO 与四阶段 FinOps 账本均已落地并为 CI 组件测试覆盖；
  Collector 指标/日志管线、延迟 SLI 事件配对和生产告警演练仍未完成；
- Compose 含本地默认凭证和公开测试 KMS key；MinIO 镜像已固定摘要，但配置不满足生产
  Secret/KMS 与供应链要求；
- 完整 Goal → Plan → Task → Action → Evidence → Verified Outcome → Satisfied Goal 已在
  Field Service 参考 E2E 中连接真实 API、PostgreSQL、Temporal、OPA、Tool Gateway 和 MinIO；
  外部业务系统仍是确定性受控模拟器，不能替代真实第三方、网络分区和生产凭证演练；
- Capability Pack 安装已要求来源允许列表、内容寻址 Digest、ed25519 签名与 SBOM 附带
  （StrictSupplyChainVerifier，未配置时 503 失败封闭），同版本不同签名内容拒绝安装；
  租户级 enable/disable/revoke（撤销不可逆）与 Stable Channel 指针持久化（迁移 0015，
  每次变更单事务+哈希审计+Outbox），Goal Type 解析按 Channel 指针→最新启用版本确定性
  解析且指向禁用版本时失败封闭；依赖声明以复合 semver 范围在安装与升降级时复核；
  API 控制面以架构测试禁止加载/执行 Pack 代码，Worker 默认以一次性子进程沙箱
  （JSON IPC + 超时 + 无凭证）执行 Pack Subject；参考 e2e 以仓库内开发密钥
  （infra/supply-chain，仅测试）安装签名 Field Service Pack。生产签名流水线、漏洞/SBOM
  扫描、OS 级沙箱（容器隔离/seccomp）与真实供应链演练仍未完成；
- Python/npm 依赖审计和精确 Secret 基线已成为 CI 门禁，但尚无签名制品、SBOM、镜像扫描、
  Provenance 或生产发布供应链证明。

## 版本权威

| 范围 | 当前权威来源 |
|---|---|
| Python 依赖解析 | `uv.lock` |
| TypeScript 依赖解析 | `pnpm-lock.yaml` |
| Conda 运行时 | `environment.yml` |
| 人工评审兼容版本 | `versions.lock` |
| 数据库 Schema | Alembic revision 与 `packages/adapters/.../persistence_schema.py` metadata |
| HTTP API Contract | FastAPI 源与冻结的 `docs/contracts/generated/openapi-v1.json` |
| Workflow 类型 | `apps/worker/src/autonoesis_worker/workflows.py` 中的 `@workflow.defn` 类 |

具体摘要、表、路由和 Workflow 类型由
[生成的生产基线报告](generated/production-baseline-report.md)记录，避免手工清单漂移。

## 可重复检查

```bash
task baseline
```

该命令校验 README/Cockpit 的原型标识、成熟度文档的声明边界，并重新计算依赖 Lock、
数据库 Schema、HTTP 路由和 Workflow 类型的确定性报告。源发生变化但报告未更新时检查失败；
使用下列命令有意刷新报告：

```bash
python3 tools/dev/check_production_baseline.py --write
```

`integrated` 或 `production-proven` 声明只有在矩阵中同时引用 CI 真实组件任务或演练报告时
才允许合入。基线检查进入 CI，但它本身不提高任何运行能力的成熟度。
