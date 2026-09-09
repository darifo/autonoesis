# 版本策略与变更审批（P2-05）

## 支持版本与升级窗口
- 预发布阶段（0.1.x）：仅最新 minor 受支持；API 契约为冻结的 OpenAPI 3.1
  （`docs/contracts/generated/openapi-v1.json`），任何破坏性变更都是主版本事件。
- 升级窗口：由部署环境公告；数据库迁移不可跳版本（Alembic 线性链）。
- 弃用：API 字段/事件 schema 弃用提前两个 minor 公告（CHANGELOG + 契约 diff）。

## 安全响应承诺
- SEV-1 安全事件（隔离破坏/凭证泄漏）：立即响应，补丁走紧急回滚通道。
- 提交渠道：SECURITY.md；密钥/凭证泄漏即轮换（开发签名密钥轮换 = 替换
  infra/supply-chain 两个文件并在同一变更更新所有签名清单）。

## 变更审批
- 常规变更：PR + 全部 CI 门禁（含真实组件/安全矩阵）+ 证据归档；涉及权威边界/
  协议/发布策略的变更必须有 ADR。
- 生产变更分级：L0 文档；L1 配置（Helm values，走 GitOps 审计）；L2 数据库迁移
  与平台版本（变更单 + 回滚方案=备份集/PITR 演练过的路径 + 二线批准）；
  L3 紧急（SEV-1 止损）：值班先执行、事后 24 小时内补审。
- 紧急回滚机制：Release 回滚经独立 Release Executor（ADR-0034）；数据层回滚经
  PITR/恢复 Runbook；两者均为演练过的操作而非即兴决定。
