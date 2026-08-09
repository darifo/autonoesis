# MVP 路线图

## Phase 0：行业无关内核（完成）

- [x] GoalContract、SubjectRef、Session、Run 和执行对象
- [x] Agent/Skill/Tool、Context、Evaluation 和 Improvement 版本对象
- [x] Capability Pack Manifest、Schema 校验和 Entry Point
- [x] 核心行业词汇隔离测试

## Phase 1：通用运行平台（完成）

- [x] PostgreSQL Schema、Alembic、RLS、Outbox/Inbox 和幂等记录
- [x] Temporal Goal 与 Candidate Workflow
- [x] OIDC、OPA、预算、审批和 Tool Gateway 边界
- [x] OpenAI、Anthropic、OpenAI-compatible 和 Fake 模型适配器
- [x] 通用 API、Python/TypeScript SDK 和 Cockpit
- [x] Field Service 外部能力包和 10 个评估案例

## Phase 2：生产级活动与证据

- [ ] 将示例执行器注册为真实 Temporal Activity
- [ ] MinIO Evidence 内容摘要、分类和删除传播
- [ ] PostgreSQL Outbox Publisher 与 Inbox Consumer
- [ ] Tool 超时未知对账、补偿和 Kill Switch
- [ ] OIDC 企业身份提供方集成测试
- [ ] MCP Tool Server 与远程资源隔离

## Phase 3：高级进化发布

- [ ] 可复现 Replay 和 Simulation 环境
- [ ] Shadow、Canary、观察窗口和自动回滚
- [ ] 重复 Trial、分位数和不确定性报告
- [ ] 单位成功 Goal 的完整 AI FinOps
- [ ] Kubernetes、备份恢复、SLO 和容量规划

## 当前退出证据

基础框架必须持续满足：核心无行业字段；跨租户隐藏；写入审批绑定精确参数；重复执行不重复副作用；Tool 回执不能直接证明 Outcome；Candidate 生成者不能自评或自批；Cockpit 配置、运行、治理、评估和进化主导航通过浏览器测试。
