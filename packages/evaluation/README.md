# Evaluation

保存 Suite、Case、Trial、Harness 和 Grader 语义。Harness 必须通过注入的 Subject Executor
执行请求中的固定 Subject Version；没有执行器、执行失败、返回其他版本或 Grader 给出
`unknown/invalid` 时，Trial 均为 `invalid`，不得计入绿色通过率。

Trial 的权威 JSON 记录每个 Case 的输入、Subject 输出、环境、模型、工具、随机种子、成本、
失败原因、评分结果和 Evidence 引用。当前达到 `unit-tested`；独立多类 Grader、隐藏数据隔离、
统计重复 Trial 以及 Candidate/Evidence 真实组件集成仍属于 P1-04 后续工作。
