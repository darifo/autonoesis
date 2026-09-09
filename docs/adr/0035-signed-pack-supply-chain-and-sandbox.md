# ADR 0035: Signed Capability Pack Supply Chain and Sandboxed Execution

- Status: Accepted
- Date: 2026-09-09

## Context

Capability Packs were installed from a structurally validated manifest alone (ADR-0009
anticipated signing, SBOM, and dependency review that never landed). Nothing proved a pack's
content, publisher, or source; nothing prevented same-version content swaps; pack subject code
executed by direct in-process import inside the worker; and packs had no tenant lifecycle —
versions could not be enabled, disabled, revoked, or pinned, leaving goal-type resolution
nondeterministic.

## Decision

1. **Content addressing and signatures.** Manifests may carry `artifact_uri`,
   `artifact_digest`, `signature`, `sbom_ref`, `sbom_digest`, and `dependencies` (compound
   semver ranges). The content digest is SHA-256 over the canonical JSON of the declarative
   payload with all supply-chain metadata excluded, so attaching metadata never changes the
   address. The signature is ed25519 over the canonical unsigned payload (metadata included)
   verified against allowlisted publisher public keys.
2. **Install verification fails closed.** `CapabilityPackService.install_pack` consults a
   `PackArtifactVerifier` before persisting. `StrictSupplyChainVerifier` enforces source
   allowlisting, digest match, signature verification, and SBOM attachment; without a
   configured verifier the API returns 503 and PostgreSQL bootstraps refuse to start.
   Re-installing the same `(tenant, pack, version)` with different signed content is a
   conflict, not an idempotent write; identical content remains idempotent.
3. **The control plane never executes pack code.** An architecture boundary test forbids the
   API source from referencing plugin loaders, subject runtimes, or dynamic imports. The API
   parses and persists manifests only.
4. **Sandboxed subject execution.** `SandboxedPackSubjectRuntime` executes pack subjects in a
   disposable subprocess (`python -m autonoesis_adapters.pack_subject_worker`) with JSON-only
   IPC and a hard timeout; the child holds no credentials, repository access, or Tool Gateway
   reach. The worker uses it by default (`AUTONOESIS_PACK_SANDBOX=process`); in-process
   execution is an explicit development escape hatch.
5. **Tenant-scoped lifecycle and channels.** Packs can be disabled, re-enabled, revoked
   (terminal — a revoked version can never be re-enabled or pinned), and pinned to a
   `capability_pack_channels` stable version per tenant. Goal-type resolution prefers the
   channel pin and otherwise the newest enabled version; a pin to a disabled or revoked
   version fails closed with no silent fallback. Every lifecycle transition is one
   transaction with a hashed audit event and outbox fact carrying the real actor identity.
6. **Dependency reconciliation.** Installs and channel changes check declared dependencies
   resolve against enabled tenant packs, and reject channel changes that would break other
   installed packs' declared ranges (upgrade/downgrade conflicts).

## Consequences

- Tampering with pack content while keeping the version (or signature) fails installation;
  the reference e2e now installs the signed `examples/field-service` pack through this path
  with a committed development key (`infra/supply-chain`, test-only, rotatable).
- The committed development signing key is convenience, not trust: production allowlists and
  keys must come from the release pipeline; vulnerability scanning beyond structural SBOM
  checks and OS-level sandboxing (containers, seccomp) remain future work.
- `PackSubjectRuntime`'s in-process import remains for development only; evaluation of packs
  not distributed with worker images must package code for the sandbox worker to import.
