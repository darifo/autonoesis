# 生产就绪基线与限制

> 评审日期：2026-08-11
> 适用版本：0.1.x
> 判定：架构原型 / 工程预览，不可用于生产或高风险真实写操作

## 当前可信范围

仓库已经提供领域模型、应用服务骨架、HTTP 路由、SQLAlchemy Schema、Temporal Workflow
定义、基础设施 Compose 文件以及若干适配器。现有 CI 能重复验证 Python 格式、Lint、
严格类型和隔离单元测试，执行 PostgreSQL 17 迁移与权威存储组件测试，以及验证 Cockpit
的类型检查、构建和静态页面浏览器测试。

这些证据支持 PostgreSQL 权威存储、Goal/Run Application 用例、Governed Tool Gateway 和
Temporal 耐久编排的 `integrated` 声明；其余能力最高仍为 `unit-tested`，没有任何能力达到
`production-proven`。

## 生产限制

- PostgreSQL 已有冻结迁移、租户复合外键、角色、RLS 和组件测试，但尚无生产备份恢复、容量、故障和滚动升级演练；
- Temporal 已有 Outbox Dispatcher、固定 Workflow ID、DB/Workflow Reconciler、Replay、Worker
  重启和故障注入组件测试；尚无生产 Namespace 隔离、HA/备份、积压容量和滚动升级演练；
- Tool Gateway 已使用 PostgreSQL 原子协调预算与幂等 Reservation，并以真实 OPA 验证策略；
  但生产 Credential Broker、网络层出口策略及第三方系统端到端写入仍未演练；
- Evidence 测试使用内存 Object Store；真实 MinIO 租户策略、加密、版本、对象锁和 Saga 尚未验证；
- OPA Policy 组件测试已进入 CI，但尚未完成策略发布、回滚和不可用故障演练；
- API 错误响应仍会构造未持久化的 `audit://` 引用，不能视为真实审计证据；
- Candidate/Shadow/Canary 已持久化 Deployment/Release，但没有真实流量双跑、分流、观察窗口和独立 Release Executor；
- Cockpit 使用静态演示数据，不从公共 API 获取运营指标；
- Compose 含本地默认凭证和未固定的 MinIO 镜像，不满足生产供应链要求；
- 完整 Goal → Plan → Task → Action → Evidence → Verified Outcome 只在 Application 自动化
  参考链中通过；尚未连接真实 Temporal、Tool、OPA 和 MinIO 形成外部纵向 E2E。

## 版本权威

| 范围 | 当前权威来源 |
|---|---|
| Python 依赖解析 | `uv.lock` |
| TypeScript 依赖解析 | `pnpm-lock.yaml` |
| Conda 运行时 | `environment.yml` |
| 人工评审兼容版本 | `versions.lock` |
| 数据库 Schema | Alembic revision 与 `packages/adapters/.../persistence_schema.py` metadata |
| HTTP API Contract | FastAPI app version 与 `apps/api/src/autonoesis_api/main.py` 路由 |
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
