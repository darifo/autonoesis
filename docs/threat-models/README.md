# Initial threat model

## Protected assets

- Tenant data and isolation boundaries
- Identity, delegation, and approval state
- Tool credentials and outbound network authority
- Authoritative Run/Action/Outcome state
- Context snapshots, memory records, and evidence
- Candidate and stable release artifacts
- Audit history and kill-switch controls

## Trust boundaries

- Users and inbound channels
- Retrieved documents and web content
- Models and model providers
- Agent harness sandboxes
- MCP servers and remote A2A agents
- Enterprise tools and callbacks
- Memory and vector providers
- CI/CD and artifact registries

## Priority threats

1. Prompt injection expands tool scope or exfiltrates secrets.
2. Cross-tenant retrieval or trace leakage.
3. Duplicate retries create duplicate side effects.
4. Timeout is treated as failure even though the external write succeeded.
5. A model writes authoritative state or marks its own outcome successful.
6. Poisoned memory becomes stable context without provenance or review.
7. Candidate improvement reaches production without independent evaluation.
8. Sandbox escape or unrestricted egress reaches internal services.
9. Approval is reused after identity, delegation, arguments, or policy changed.
10. Audit or evidence objects are modified after the fact.

## Required controls

Threat-specific controls and residual risks will be added with each vertical slice. Any change to identity, policy, sandbox, egress, secrets, memory write gates, or release gates must update this document or add a scoped model.
