# 本地开发与运行手册

## 初始化

```bash
conda env create --file environment.yml
conda activate autonoesis
UV_PROJECT_ENVIRONMENT="$CONDA_PREFIX" uv sync --inexact --all-packages --dev
pnpm install
```

`--inexact` 保留 Conda 管理的包，不创建仓库内 `.venv`。

## 验证

```bash
ruff format --check .
ruff check .
mypy apps packages examples/field-service
pytest
pnpm typecheck
pnpm build
pnpm --filter @autonoesis/cockpit test
```

## 单进程开发

```bash
task api
task worker
pnpm --filter @autonoesis/cockpit dev
```

API 本地开发模式要求请求携带 `X-Tenant-ID`、`X-Actor-ID`、`X-Roles` 和写请求的 `Idempotency-Key`。这些 Header 不能用于生产身份。

## 完整本地平台

```bash
docker compose --file infra/compose/docker-compose.yml up --build
```

API 启动前执行 Alembic 迁移；PostgreSQL 保存权威状态，Temporal 保存持久工作流历史。停止服务不会清除 Volume；需要清空本地数据时必须明确执行 Compose Volume 删除命令。

## Capability Pack

Field Service Manifest 位于 `examples/field-service/capability-pack.yaml`。新增能力包必须通过 Manifest 测试，并确保核心包不导入示例模块。

## 安全

复制 `.env.example` 为 `.env`。不要提交凭证、生产 Payload、原始客户 Prompt、未脱敏 Trace、私钥或 Evidence 原文。
