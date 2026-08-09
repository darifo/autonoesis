# ADR-0003：采用 Goal-first 内核与 Capability Pack 扩展

- 状态：accepted
- 日期：2026-08-02

## 背景

把第一个行业示例直接放入领域、应用和 API，会让平台核心被客户、设备、工单等语义污染，也无法证明其他行业能在不修改核心的情况下接入。

## 决策

- 核心唯一业务驱动对象是 `GoalContract`；
- 外部业务实体通过 `SubjectRef` 引用，核心不拥有通用 Case；
- 行业 Goal Type、Agent、Skill、Tool、Policy 和 Evaluation Suite 通过版本化 Capability Pack 安装；
- Manifest 使用严格 YAML/JSON Schema，复杂行为使用 Python Entry Point；
- 行业示例只能依赖核心公开接口，核心包禁止反向依赖示例。

## 后果

- 平台可以适配不同业务系统而不扩张核心模型；
- Capability Pack 需要稳定的版本、兼容性、权限和供应链治理；
- 核心控制台以通用运行对象为中心，不提供行业专用页面；
- Field Service 仅作为外部示例验证扩展接口。

## 验证

CI 扫描领域、应用和运行时源码，禁止出现 Field Service 行业字段；示例端到端测试只能导入公开包。
