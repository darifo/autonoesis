# Autonoesis

**企业级受控自进化智能体操作系统**

Autonoesis 不是一个堆叠了 Prompt、工具和长期记忆的"大 Agent"，而是一套对智能运行事实负责的企业平台：

- **Goal-first**：每一项工作都是可验证的 `GoalContract`，包含成功标准、约束、预算和截止时间。
- **持久执行**：Goal 跨时间、暂停、审批、取消和进程重启持续推进，通过持久工作流引擎保障。
- **受控行动**：每个外部副作用在执行时必须通过身份、委托、策略、风险、预算、审批和幂等检查。
- **证据驱动结果**：工具返回成功只是回执——不是证明。结果通过对权威系统的回读来验证。
- **受控进化**：改进先成为 Candidate，经独立评估门禁后，通过 Shadow → Canary → Stable 晋升，且可回滚。

```
Intent → GoalContract → ContextSnapshot → Plan → Durable Run → Task
→ Governed Action → Evidence → Outcome → Evaluation
→ ImprovementProposal → Candidate → Shadow/Canary/Stable/Rollback
```

[English](README.md) · [架构总览](docs/architecture/overview.md) · [架构决策记录](docs/adr/README.md) · [路线图](docs/roadmap/mvp.md)

---

## 核心承诺

| 承诺 | 工程含义 |
|---|---|
| 持久智能体 | 任务不依赖一次 HTTP、对话或 Worker 进程存活 |
| 显式授权 | 身份、委托、权限、预算和审批均为显式对象，而非 Prompt 指令 |
| 证据驱动结果 | 工具回执不是证明；通过权威系统回读验证真实世界结果 |
| 受控进化 | 改进先成为 Candidate，通过独立评估和发布门禁后才可 Stable |
| 可替换智能 | 模型、Harness、Memory Provider、MCP/A2A 实现均为可替换适配器 |
| 企业级隔离 | 租户在身份、数据、凭证、运行时、网络、预算和发布维度全面隔离 |

---

## 快速开始

```bash
# 创建并激活 Conda 环境
conda env create -f environment.yml
conda activate autonoesis

# 安装 Python 工作空间
task bootstrap

# 安装 TypeScript 工作空间
pnpm install

# 运行质量检查
task check
```

启动完整本地平台：

```bash
docker compose --file infra/compose/docker-compose.yml up --build
```

- API 文档：http://localhost:8000/docs
- 控制台：http://localhost:4173
- Temporal UI：http://localhost:8088

单进程开发：

```bash
task api                               # FastAPI 热重载
pnpm --filter @autonoesis/cockpit dev  # React 开发服务器
```

---

## 架构一览

Autonoesis 将责任组织为**八个逻辑平面**——不是八个微服务：

| 平面 | 回答的核心问题 | 当前实现 |
|---|---|---|
| Interaction | 请求从哪来，是谁，通过什么渠道 | FastAPI、Cockpit、SDK |
| Intelligence | 目标是什么，应如何规划和决策 | Goal Manager、Planner、Decision、能力选择器 |
| Runtime | 计划如何跨时间可靠推进 | 持久工作流、Harness、检查点、工作空间 |
| Environment | 此刻外部世界的可验证状态是什么 | 事实注册、投影、时效、仿真 |
| Context | 这次运行应该看到什么 | 检索、ACL 过滤、排序、冲突、压缩、快照 |
| Integration | 如何安全连接模型、工具和其他 Agent | Model Gateway、Tool Gateway、MCP Host、A2A Gateway |
| Data & Evidence | 如何保存状态、历史、证据和可观测数据 | PostgreSQL、对象存储、事件总线、审计、遥测 |
| Governance | Agent 凭什么行动，谁能审批和接管 | 身份、委托、策略、审批、预算、Kill Switch |

当前部署为三个进程：**API**、**Worker** 和 **Cockpit**。

---

## 仓库结构

```
autonoesis/
├── apps/
│   ├── api/          # HTTP/SSE/Webhook 控制面
│   ├── worker/       # 持久工作流/Activity/Harness Worker
│   ├── cockpit/      # 运营、审批、证据、评估和发布控制台
│   └── gateway/      # 独立 Model/Tool 数据面（达到拆分条件后）
├── packages/
│   ├── domain/       # 纯领域对象、状态机和不变量
│   ├── contracts/    # 跨进程 Schema、Envelope、错误目录
│   ├── application/  # Command/Query Handler、UoW、事务边界
│   ├── capability/   # Capability Pack Manifest、发现、安装和验证
│   ├── intelligence/ # Goal 澄清、Planning、Decision、能力选择
│   ├── runtime-kernel/ # Orchestrator、Harness SPI、Workspace、Checkpoint
│   ├── context/      # 检索、ACL、时效、冲突、压缩、Snapshot
│   ├── environment/  # Environment Fact、投影、刷新、仿真
│   ├── memory/       # Memory SPI、Ledger、Write Gate、删除传播
│   ├── gateways/     # Model、Tool、MCP、A2A、Channel 统一边界
│   ├── governance/   # Identity、Delegation、Policy、Approval、Budget、Audit
│   ├── evaluation/   # EvaluationCase、Suite、Trial、Harness、Grader
│   ├── improvement/  # Analysis、Proposal、Candidate、Release、Rollback
│   ├── adapters/     # Provider / Protocol / Persistence 适配器
│   └── testkit/      # Fake Provider、攻击套件、契约测试支撑
├── sdk/              # Python / TypeScript 客户端 SDK
├── examples/         # 仅依赖公开接口的参考 Capability Pack
├── infra/            # Compose、Helm、IaC、Policy、OTel、Supply Chain
├── docs/             # Architecture、ADR、Contracts、Threat Models、Runbooks
└── tools/            # Codegen、Schema Check、Release、Dev CLI
```

**依赖方向**：`apps → application → domain` · `domain` 不得依赖框架 · `core` 不得反向依赖 `examples`

---

## 核心领域模型

| 对象 | 语义 |
|---|---|
| `SubjectRef` | 外部权威业务对象的稳定引用 |
| `GoalContract` | 一个可管理、可验证的目标合同，含成功标准、约束、预算和截止时间 |
| `Session` | 交互连续性，不是执行生命周期 |
| `Run` | 一次独立核算、恢复和审计的执行 |
| `Plan` | 版本化 Task DAG 及其前提假设 |
| `Task` | 无外部副作用语义的可调度工作单元 |
| `DecisionRecord` | 为什么执行、拒绝、升级或重规划 |
| `Action` | 最小可治理副作用边界 |
| `Evidence` | 对真实世界状态的可引用观测 |
| `Outcome` | 成功标准是否在现实中成立 |
| `CandidateVersion` | 未经生产发布门禁的能力新版本 |

---

## 实施阶段

| 阶段 | 状态 | 重点 |
|---|---|---|
| **Phase 0** | ✅ 完成 | 领域语言、核心对象、状态机、Monorepo 骨架、ADR 模板 |
| **Phase 1** | ✅ 完成 | API、PostgreSQL、持久工作流、Cockpit、模型/工具适配器、参考 Capability Pack |
| **Phase 2** | 🚧 规划中 | 统一 Model/Tool Gateway、凭证 Broker、证据对账、SLO、Kill Switch |
| **Phase 3** | 📋 规划中 | 上下文装配、Memory Write Gate、Multi-Agent、长任务压缩 |
| **Phase 4** | 📋 规划中 | 受控自进化、Candidate 管线、Shadow/Canary、自动回滚 |

---

## 文档索引

- [架构总览](docs/architecture/overview.md)
- [领域模型](docs/architecture/domain-model.md)
- [运行时与执行流](docs/architecture/runtime-and-flows.md)
- [部署架构](docs/architecture/deployment.md)
- [仓库与依赖边界](docs/architecture/repository-layout.md)
- [架构决策记录](docs/adr/README.md)
- [API 与事件契约](docs/contracts/README.md)
- [威胁模型](docs/threat-models/README.md)
- [运行手册](docs/runbooks/local-development.md)
- [MVP 路线图](docs/roadmap/mvp.md)

## 参与贡献

参见 [CONTRIBUTING.md](CONTRIBUTING.md) 和 [AGENTS.md](AGENTS.md) 了解架构规则、工程流程和完成定义。

## 许可证

基于 [MIT License](LICENSE) 发布。
