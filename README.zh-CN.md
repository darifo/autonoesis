<p align="center">
  <img src="docs/assets/autonoesis-logo.svg" alt="Autonoesis Logo" width="200"/>
</p>

<p align="center">
  <strong>企业级受控自进化智能体操作系统 — 工程预览</strong>
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
  <img src="https://img.shields.io/badge/readiness-engineering%20preview-orange.svg" alt="工程预览"/>
</p>

---

> [!WARNING]
> Autonoesis 当前是架构原型和工程预览。生产权威存储、耐久执行、多租户隔离、
> 证据链和发布链路尚未完成端到端验证，请勿用于生产环境或高风险真实写操作。

**Autonoesis** 正在建设一套对智能运行**事实负责**的企业平台——目标是让每次行动受治理、每个结果被验证、每次进化经过安全检查。

```text
意图 → GoalContract → ContextSnapshot → Plan → 持久 Run → Task
→ 受控 Action → Evidence → Outcome → Evaluation
→ ImprovementProposal → Candidate → Shadow/Canary/Stable/Rollback
```

[English](README.md) ·
[架构总览](docs/architecture/overview.md) ·
[ADR](docs/adr/README.md) ·
[生产就绪整改计划](docs/roadmap/enterprise-production-readiness-remediation.md) ·
[能力成熟度](docs/roadmap/capability-maturity.md) ·
[集成指南](docs/architecture/integration-guide.md)

---

## 核心理念

下表描述的是**目标架构**，不代表当前已经生产验证。实际实现证据见[能力成熟度矩阵](docs/roadmap/capability-maturity.md)。

| 目标能力 | 含义 |
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

### 本地原型栈 (Docker Compose)

```bash
docker compose -f infra/compose/docker-compose.yml up --build
```

该栈仅用于本地开发；默认凭证、公开测试 KMS key 和未完成加固的基础设施配置均不满足生产安全要求。MinIO 镜像已固定摘要，API/Worker 已使用 PostgreSQL 权威状态，但这不等于整套系统生产就绪。

| 服务 | 地址 |
|---|---|
| API (Swagger 文档) | http://localhost:8000/docs |
| 运营控制台 (Cockpit) | http://localhost:4173 |
| Temporal UI | http://localhost:8088 |
| MinIO 控制台 | http://localhost:9001 |
| Jaeger 链路追踪 | http://localhost:16686 |

---

## 架构概览

目标架构将职责划分为**八个逻辑平面**（非八个微服务）。原型当前定义了 **API**、**Worker** 和 **Cockpit** 三个进程入口；这不代表生产部署拓扑已经成立。

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

## 交付状态

旧 MVP 阶段记录的是实现广度，不代表生产就绪。现按实际证据重新校准如下：P0 参考基线已完成，P1/P2 企业治理与生产运维仍在进行。

| 旧阶段 | 当前成熟度 | 生产就绪缺口 |
|---|---|---|
| **Phase 0** | 参考执行切片 `integrated` | 冻结契约和 Field Service 参考 Pack 通过真实 PostgreSQL、Temporal、OPA、MinIO 与受控 Authority 模拟器完成 Verified Goal。 |
| **Phase 1** | PostgreSQL、Temporal 与 HTTP/Application 切片 `integrated` | OpenAPI 已冻结并有 Consumer Contract；多副本 API、企业 OIDC 和生产容量证据仍缺失。 |
| **Phase 2** | Tool Gateway 与 Evidence 可信链 `integrated`，其余为部分 `unit-tested` | 参考 E2E 证据进入 CI；真实第三方系统、生产 Credential/KMS 和网络故障演练仍未完成。 |
| **Phase 3** | `unit-tested` | Deployment/Release 已持久化，仍缺真实 Shadow 流量、Canary 分流和 Release Executor。 |
| **Phase 4** | `specified` | 生产运维和加固仅处于计划状态。 |

当前生产限制和可重复基线证据见[生产就绪基线](docs/roadmap/production-readiness-baseline.md)。

---

## 参与贡献

详见 [CONTRIBUTING.md](CONTRIBUTING.md) 了解开发流程和完成定义。详见 [AGENTS.md](AGENTS.md) 了解架构规则和不可变约束——领域纯净度、依赖方向和 Greenfield 边界。

## 许可证

基于 [MIT License](LICENSE) 发布。
