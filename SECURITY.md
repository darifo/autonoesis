# Security policy

Autonoesis handles high-agency automation and must assume prompts, retrieved content, tool output, remote agents, and external callbacks are untrusted.

## Reporting a vulnerability

Do not open a public issue for a suspected vulnerability. Use GitHub private vulnerability reporting for this repository. If that feature is unavailable, contact the repository owner through a private channel before disclosing details.

Include the affected component, impact, reproduction steps, required privileges, and any known mitigation. Do not include real customer data or active credentials.

## Baseline guarantees

- Least-privilege credentials with explicit audience and short lifetime
- Tenant isolation and authorization at every data and tool boundary
- Execution-time authorization for side effects
- Immutable audit and evidence references
- Idempotency and unknown-outcome reconciliation for write actions
- Sandboxed harness execution and controlled egress
- Human approval, pause, takeover, rollback, and kill-switch paths
- Candidate-based evolution; no direct production self-modification

Supported-version and disclosure timelines will be published before the first public production release.
