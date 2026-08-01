# Adapters

Replaceable integrations that implement Autonoesis ports. External framework types must not leak into domain or application contracts.

Planned adapters:

- `hermes`, `codex`, `openai-agents`: Harness implementations
- `honcho`: Memory provider
- `mcp`, `a2a`: Protocol boundaries
- `persistence`, `messaging`: Repositories, unit of work, outbox/inbox, event transport
