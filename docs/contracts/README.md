# Contract rules

Contracts define stable messages across processes, languages, and release versions. They do not contain domain behavior.

## Initial object chain

```text
Request → Case → Goal → Plan → Decision → Run → Task → Action
                                              ↓
                              Artifact → Outcome → Evidence
```

## Envelope requirements

Every command and event will eventually include:

- unique message and correlation identifiers;
- tenant, actor, delegation, and causation references;
- schema name and version;
- creation time and trace context;
- idempotency key where side effects are possible;
- data classification and retention metadata where applicable.

## Compatibility

- Adding an optional field may be backward compatible.
- Removing or renaming fields, adding required fields, or changing meaning requires a new major schema version.
- Event meanings are immutable.
- Generated Python and TypeScript models live under `packages/contracts/generated/` and are not hand-edited.

The current Python contract types are bootstrap types, not a frozen public protocol.
