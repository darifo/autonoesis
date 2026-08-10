<p align="center">
  <img src="docs/assets/autonoesis-logo.svg" alt="Autonoesis Logo" width="200"/>
</p>

<p align="center">
  <strong>企业级受控自进化智能体操作系统</strong>
</p>

<p align="center">
  <a href="https://github.com/darifo/autonoesis/actions/workflows/ci.yml">
    <img src="https://github.com/darifo/autonoesis/actions/workflows/ci.yml/badge.svg" alt="CI"/>
  </a>
  <a href="LICENSE">
    <img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License"/>
  </a>
  <a href="https://www.python.org/downloads/">
    <img src="https://img.shields.io/badge/python-3.12+-blue.svg" alt="Python"/>
  </a>
  <a href="https://nodejs.org/">
    <img src="https://img.shields.io/badge/node-%3E%3D22-green.svg" alt="Node"/>
  </a>
  <img src="https://img.shields.io/badge/tests-122%20passed-brightgreen.svg" alt="Tests"/>
  <img src="https://img.shields.io/badge/mypy-strict%20clean-brightgreen.svg" alt="MyPy"/>
</p>

---

**Autonoesis** 不是一个堆叠了 Prompt 和工具的"大 Agent"。它是一套对智能运行**事实负责**的企业平台——每次行动都受治理、每个结果都被验证、每次进化都经过安全检查。

```text
意图 → GoalContract → ContextSnapshot → Plan → 持久 Run → Task
→ 受控 Action → Evidence → Outcome → Evaluation
→ ImprovementProposal → Candidate → Shadow/Canary/Stable/Rollback
```

[English](README.md) ·
[架构总览](docs/architecture/overview.md) ·
[ADR](docs/adr/README.md) ·
[路线图](docs/roadmap/mvp.md) ·
[集成指南](docs/architecture/integration-guide.md)

---

## 核心理念

| 能力 | 含义 |
|---|---|
| **目标驱动** | 工作是可验证的 `GoalContract`——成功标准、预算和截止时间都是显式的，不是嵌在 prompt 里 |
| **持久执行** | Goal 跨断线、崩溃和重启持续推进，通过 Temporal 持久工作流引擎保障 |
| **受控行动** | 每个外部副作用在执行时必经身份、策略、预算、审批和幂等五重检查 |
| **证据优先** | 工具说"完成了"不算——Outcome 必须通过外部系统的权威回读来验证 |
| **受控进化** | 改进先成为 Candidate，经独立评估后通过 Shadow → Canary → Stable 渐进发布，自动回滚 |
| **多租户隔离** | 租户在身份、数据、凭证、运行时、网络、预算和发布维度上完全隔离 |

### 与通用框架的区别

Autonoesis **不是** LangChain、CrewAI 或 AutoGPT 的替代品。那些是快速原型框架——LLM 直接驱动状态变更。
Autonoesis 在"模型想做什么"和"实际发生了什么"之间强制执行一层治理。详见[平台定位](docs/architecture/platform-positioning.md)。

---

## 快速开始

```bash
# 创建并激活 Conda 环境
conda env create -f environment.yml
conda activate autonoesis

# 安装 Python 工作区
UV_PROJECT_ENVIRONMENT="$CONDA_PREFIX" uv sync --inexact --all-packages --dev

# 安装 TypeScript 工作区
pnpm install

# 运行全部质量检查
ruff format --check . && ruff check . && mypy apps packages --ignore-missing-imports && pytest
```

### 全栈启动 (Docker Compose)

```bash
docker compose -f infra/compose/docker-compose.yml up --build
```

| 服务 | 地址 |
|---|---|
| API (Swagger 文档) | http://localhost:8000/docs |
| 运营控制台 (Cockpit) | http://localhost:4173 |
| Temporal UI | http://localhost:8088 |
| MinIO 控制台 | http://localhost:9001 |
| Jaeger 链路追踪 | http://localhost:16686 |

---

## 架构概览

Autonoesis 将职责划分为**八个逻辑平面**（八个逻辑层，非八个微服务）。当前部署为三个进程：**API**、**Worker** 和 **Cockpit**。

| 平面 | 职责 | 实现 |
|---|---|---|
| **交互** | 谁在调用？ | FastAPI, Cockpit, SDK |
| **智能** | 应该做什么？ | Goal 澄清器, 规划器, 能力选择器 |
| **运行时** | 计划如何持续推进？ | Temporal 工作流, Harness, 检查点 |
| **环境** | 外部世界状态如何？ | 事实注册, 投影, 刷新 |
| **上下文** | 本次执行应该看到什么？ | 检索, ACL, 新鲜度, 压缩, 快照 |
| **集成** | 如何安全连接工具？ | 模型网关, 工具网关, MCP/A2A |
| **数据与证据** | 如何持久化和证明？ | PostgreSQL, MinIO, 审计, 遥测 |
| **治理** | 凭什么授权？ | 身份, 策略, 预算, 审批, Kill Switch |

**深入阅读**：[架构总览](docs/architecture/overview.md) ·
[集成指南](docs/architecture/integration-guide.md) ·
[应用场景](docs/architecture/application-scenarios.md)

---

## 项目结构

```
autonoesis/
├── apps/
│   ├── api/              # FastAPI 控制面 (HTTP/SSE)
│   ├── worker/           # Temporal Worker (工作流 + 活动)
│   ├── cockpit/          # React 运营控制台
│   └── gateway/          # 预留：独立工具/模型数据面
├── packages/
│   ├── domain/           # 纯领域对象、状态机、不变量
│   ├── contracts/        # 跨进程 schema 和信封
│   ├── application/      # 命令/查询处理器、事务边界
│   ├── runtime-kernel/   # Harness SPI、网关协议、熔断
│   ├── capability/       # 能力包清单与验证
│   ├── intelligence/     # 目标澄清、规划、决策
│   ├── context/          # 检索、ACL、新鲜度、压缩
│   ├── environment/      # 事实、投影、刷新、仿真
│   ├── memory/           # 记忆 SPI、账本、写入门禁
│   ├── gateways/         # 模型/工具/MCP/A2A 边界
│   ├── governance/       # 身份、策略、预算、熔断
│   ├── evaluation/       # 用例、套件、试验、评分器
│   ├── improvement/      # 分析、提案、发布
│   ├── evolution/        # 回放、Shadow/Canary、FinOps、SLO
│   ├── adapters/         # 提供者/协议/持久化适配器
│   ├── testkit/          # 假对象、攻击套件、契约测试
│   ├── py-sdk/           # Python 客户端 SDK
│   └── ts-sdk/           # TypeScript 客户端 SDK
├── docs/                 # 架构、ADR、合约、运维手册
├── infra/                # Compose、迁移、策略、Helm
├── examples/             # 参考能力包
└── tools/                # 代码生成、开发 CLI、发布工具
```

**依赖方向**：`apps → application → domain`。Domain 不依赖任何框架。适配器实现 domain/application/runtime-kernel 定义的端口。

---

## 实施阶段

| 阶段 | 状态 | 重点 |
|---|---|---|
| **Phase 0** | ✅ 完成 | 领域语言、核心对象、状态机、Monorepo 骨架 |
| **Phase 1** | ✅ 完成 | API、PostgreSQL、Temporal、Cockpit、模型/工具适配器、参考能力包 |
| **Phase 2** | ✅ 完成 | Outbox/Inbox、Kill Switch、MinIO Evidence、真实 Temporal Activity、工具对账、MCP 适配器 |
| **Phase 3** | ✅ 完成 | 回放/仿真、Shadow/Canary、自动回滚、AI FinOps、SLO、重复试验、桩包填平 |
| **Phase 4** | 📋 计划中 | Kubernetes、备份恢复、Grafana 仪表板、SAST、生产加固 |

---

## 参与贡献

详见 [CONTRIBUTING.md](CONTRIBUTING.md) 了解开发流程和完成定义。详见 [AGENTS.md](AGENTS.md) 了解架构规则和不可变约束——领域纯净度、依赖方向和 Greenfield 边界。

## 许可证

基于 [MIT License](LICENSE) 发布。
