# 公众号文章原则与工程实现映射

| 文章主题 | 通用内核能力 | 验收证据 |
| --- | --- | --- |
| 从回答到目标驱动 | GoalContract、SubjectRef、成功标准、约束 | Goal 领域测试和通用 API |
| Session、Run 与长任务 | Session/Run 分离、Temporal Workflow | Session 关闭不影响 Run；Workflow Signal |
| Plan、Task、Action、Outcome | 显式状态机和副作用边界 | 非法跳转、权威验证和幂等测试 |
| 当前世界与 Context | EnvironmentFact、KnowledgeRef、MemoryRecord、ContextSnapshot | 时效、来源、冲突和不可变快照不变量 |
| 八个逻辑平面 | 模块化内核、API/Worker/Cockpit 三进程 | 依赖方向和行业词汇扫描测试 |
| Runtime、Harness、Orchestrator | Workflow + 受限 Loop | Loop 预算、停止条件和无副作用重试策略 |
| Tool、MCP、Model Gateway | 统一模型路由和 Tool 治理流水线 | 多适配器契约、审批摘要和去重测试 |
| Outcome 与 Evaluation | Evidence、Outcome、Suite、Trial、GraderResult | Tool 成功不等于 Outcome；独立评分 |
| 受控自进化 | Proposal、Candidate、Release、Rollback | 生成者不能自评/自批；晋升与回滚状态机 |
| 身份、租户和安全 | OIDC、OPA、RLS、Audit、Budget | 跨租户隐藏、拒绝硬边界和策略版本记录 |

Field Service 只用于验证 Capability Pack 公共接口，不再定义核心架构。文章引入新概念时，必须落为通用契约、不变量或负向测试，不能直接把示例业务字段加入核心。
