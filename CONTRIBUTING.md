# Contributing to Autonoesis

Autonoesis is early-stage and architecture-first. Small, reviewable changes that preserve domain and authority boundaries are preferred over broad framework additions.

## Development flow

1. Read [AGENTS.md](AGENTS.md) and the relevant ADRs.
2. Open or reference an issue describing the outcome and acceptance evidence.
3. Create a focused branch.
4. Add tests before or with implementation.
5. Run `task check` and `task test`.
6. Update contracts, ADRs, threat models, or runbooks when their behavior changes.
7. Submit a pull request using the repository template.

## Commit guidance

Use clear, imperative subjects. Conventional Commit prefixes are recommended:

```text
feat(domain): add explicit run cancellation transition
fix(runtime): preserve idempotency key across activity retry
docs(adr): record tool gateway authorization boundary
```

## Compatibility

- Additive optional contract fields may be backward compatible.
- Renaming, deletion, required-field additions, or semantic changes require a new major contract version.
- Published events are immutable facts. Never change the meaning of an existing event type in place.

## Security-sensitive changes

Changes to identity, delegation, policy, approval, secrets, sandboxing, egress, audit, tenancy, release gates, or data retention require an explicit threat-model update and independent review.
