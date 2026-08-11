# Adapters

提供核心端口的可替换适配器骨架：进程内测试 Store、部分 SQLAlchemy Repository、OIDC/JWKS、OPA、OpenAI、Anthropic 和 OpenAI-compatible。当前 PostgreSQL Repository 只覆盖 Goal/Run 的部分路径，其余适配器主要达到 `modeled` 或 `unit-tested`；真实组件集成状态见[能力成熟度矩阵](../../docs/roadmap/capability-maturity.md)。任何提供商类型都不能泄漏到领域或应用 API。
