# Field Service 能力包示例

该目录演示如何在不修改 Autonoesis 核心的情况下，为工业设备售后场景定义 Goal Type、Agent、Skill、Tool、策略与评估套件。

核心系统只看见 `field-service.restore-equipment` Goal 和外部 `SubjectRef`。客户、设备、遥测和维修工单始终属于场景能力包及其外部权威系统。

示例包含 10 个正常、输入缺失、事实过期、跨租户、注入、审批、幂等、超时未知和 Outcome 不一致评估案例。
