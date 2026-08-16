# Evaluation

保存 Suite、Case、Trial、Harness 和 Grader 语义。Harness 必须通过注入的 Subject Executor
执行请求中的固定 Subject Version；没有执行器、执行失败、返回其他版本或 Grader 给出
`unknown/invalid` 时，Trial 均为 `invalid`，不得计入绿色通过率。

Trial 的权威 JSON 记录每个 Case 的输入、Subject 输出、环境、模型、工具、随机种子、成本、
失败原因、评分结果和 Evidence 引用。当前达到 `unit-tested`；真实 Grader 后端、持久化 Catalog
以及 Candidate/Evidence 真实组件集成仍属于 P1-04 后续工作。

重复 Trial 由 `TrialConfidenceGate` 按统计方法验收：对同租户、同 Suite 版本、同 Subject
Version、同 Harness 的终态 Trial 计算 Wilson 置信区间，仅当置信下界在设定置信水平下达到
目标通过率且有效样本不小于最小值时才判定通过；固定次数全过不能替代置信度。Invalid Trial
既不计入绿色通过率也不折抵最小样本，重复 Trial ID 与未终态 Trial 会被直接拒绝。

Grader Pipeline 固定为 Deterministic → Outcome → Trajectory → LLM → Human；阶段顺序错误、
重复身份或结果类型与阶段不一致都会被拒绝，任一阶段非 Pass 会阻止后续低优先级阶段运行。
具体后端通过 `IndependentGrader` 注入，不允许 Subject Executor 复用 Grader 身份。

隐藏和生产回放 Case 由 `EvaluationSuiteCatalog` 控制。Generator View 只包含公开 Case 描述和
受保护 Case 数量，不包含受保护 ID、输入、期望结果或标签；包含 Generator 角色的 Principal
即使同时声明 Harness 角色也无法获取完整 Suite。Harness 直接接收未经 Catalog 授权的受保护
Suite 时会生成 Invalid Trial，且不会执行 Subject。
