# API 与事件契约

跨进程、跨语言和跨版本契约只表达数据，不承载领域行为。

## 对象链

```text
Request → Goal → ContextSnapshot → Plan → Decision → Run → Task → Action
                                                        ↓
                                    Artifact → Evidence → Outcome
                                                        ↓
                               Evaluation → Candidate → Release
```

## Envelope

每个命令和事件必须携带：消息 ID、关联 ID、因果 ID、租户、Actor、Principal、Schema 名称与版本、创建时间、Trace Context、数据分类和保留信息。可能产生副作用的命令必须携带稳定幂等键。

## HTTP 规则

- 租户和身份来自 OIDC 上下文，不接受正文声明；
- 写请求要求 `Idempotency-Key`；
- 更新使用乐观锁版本或 `If-Match`；
- 错误 Envelope 包含 code、message、retryable、next_action 和关联 ID；
- 客户端不能直接执行 Action，只能提交 Goal、审批或治理命令。

## 兼容性

新增可选字段可能向后兼容；删除、重命名、增加必填字段或改变语义必须提升主版本。事件含义不可修改。
HTTP 权威源是 FastAPI，冻结的 Consumer Contract 为
[`generated/openapi-v1.json`](generated/openapi-v1.json)，由 `tools/dev/freeze_openapi.py`
生成并在 CI 中校验，不手工编辑。
