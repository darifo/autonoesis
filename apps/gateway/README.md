# Gateway

Reserved independent deployment boundary for model, tool, MCP, A2A, channel, secret-broker, and egress-policy data planes.

During the initial phase, gateway logic is implemented in `packages/gateways` and assembled into API or Worker. Activate this process only through an ADR demonstrating a distinct security domain, scaling curve, shared-product need, or language/runtime requirement.
