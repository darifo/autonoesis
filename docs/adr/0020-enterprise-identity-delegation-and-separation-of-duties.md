# ADR-0020: Enterprise Identity, Delegation, and Separation of Duties

- Status: accepted
- Date: 2026-08-13
- Extends: ADR-0010, ADR-0013, ADR-0019

## Context

The API reconstructed an OIDC validator for every request and accepted candidate generator and
grader identifiers from request bodies. Delegations were process-local tuples without Tenant,
Principal, purpose, expiry, or durable revocation. Approval recorded an Actor but could not
distinguish two sessions owned by one Principal. Break-glass had a distinct database path and
ticket audit, but no prior temporary grant, security alert, or independent post-review record.

## Decision

OIDC validation reuses a process-scoped `PyJWKClient` with a bounded JWKS cache. Tokens must pass
signature, Issuer, Audience, Subject, Tenant, `exp`, `iat`, and accepted access-token type checks.
The resulting trusted context distinguishes Actor and Principal and can carry Service or Agent
identity. Request bodies cannot declare the proposal author, candidate generator, grader, approval
reviewer, or release executor.

`DelegationGrant` is a Tenant-scoped, short-lived capability bound to grantor and delegate
Principals, exact Tool, resource prefix, and purpose. Revision `0007_enterprise_identity` stores
enterprise identities, delegations, temporary authorizations, and Break-glass alerts under forced
RLS. The execution gateway queries PostgreSQL on every invocation; revocation is authoritative on
the next check and is not hidden behind an authorization cache.

L3 and L4 Actions require two affirmative reviews from different Principals. Actor/session IDs do
not satisfy this distinction. Candidate generation, grading, approval, and release execution use
separate roles and the persisted generator, grader, and approver Principal IDs prevent one
Principal from crossing those gates even when it holds multiple roles.

Platform Break-glass operations require a short-lived `platform.kill_switch` authorization issued
by `security_admin` to another Principal, plus the incident ticket and `break_glass` role. Use emits
both an audit event and security alert; `security_auditor` performs an independent post-review.

## Verification

Domain tests cover scoped delegation, immediate revocation, identity-kind invariants, independent
post-review, and two-session/same-Principal rejection. API tests prove body identities are absent,
roles are separate, and the issue/use/alert/review Break-glass flow is complete.
`tests/security/test_enterprise_identity_authority.py` repeats delegation revoke and temporary
authorization review against migrated PostgreSQL.

This is integrated engineering evidence, not proof against a production enterprise IdP. Key
rotation storms, IdP outage behavior, SCIM lifecycle, workload identity federation, and alert
delivery to the production SOC remain deployment acceptance work.
