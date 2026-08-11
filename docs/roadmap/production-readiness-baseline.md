# 生产就绪基线与限制

> 评审日期：2026-08-11
> 适用版本：0.1.x
> 判定：架构原型 / 工程预览，不可用于生产或高风险真实写操作

## 当前可信范围

仓库已经提供领域模型、应用服务骨架、HTTP 路由、SQLAlchemy Schema、Temporal Workflow
定义、基础设施 Compose 文件以及若干适配器。现有 CI 能重复验证 Python 格式、Lint、
严格类型和隔离单元测试，执行冻结 OpenAPI Consumer Contract、PostgreSQL 17 迁移、Temporal、
OPA、KMS MinIO、参考纵向 E2E、依赖/Secret 扫描，以及 Cockpit 单元、类型、构建和浏览器测试；
测试结果生成哈希清单并由 CI 保留 30 天。

这些证据支持 P0 参考纵向切片、PostgreSQL 权威存储、HTTP/Application 用例、Governed Tool
Gateway、Temporal 耐久编排、Evidence/Outcome/Audit 可信链和 P1-01 多维租户隔离的
`integrated` 声明；其余能力最高仍为 `unit-tested`，没有任何能力达到 `production-proven`。

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
- Candidate/Shadow/Canary 已持久化 Deployment/Release，但没有真实流量双跑、分流、观察窗口和独立 Release Executor；
- Cockpit 使用静态演示数据，不从公共 API 获取运营指标；
- Compose 含本地默认凭证和公开测试 KMS key；MinIO 镜像已固定摘要，但配置不满足生产
  Secret/KMS 与供应链要求；
- 完整 Goal → Plan → Task → Action → Evidence → Verified Outcome → Satisfied Goal 已在
  Field Service 参考 E2E 中连接真实 API、PostgreSQL、Temporal、OPA、Tool Gateway 和 MinIO；
  外部业务系统仍是确定性受控模拟器，不能替代真实第三方、网络分区和生产凭证演练；
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
