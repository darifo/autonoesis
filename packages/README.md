# 内部包说明

`domain` 保存纯业务不变量，`application` 保存用例与端口，`capability` 保存能力包契约，`runtime-kernel` 保存运行边界，`adapters` 保存可替换基础设施，SDK 保存公共客户端。逻辑平面目录不得变成相互任意调用的工具箱。
