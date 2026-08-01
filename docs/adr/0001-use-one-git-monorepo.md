# ADR-0001: Use one Git monorepo

- Status: accepted
- Date: 2026-08-01

## Context

The platform has several logical planes and deployable applications, but its contracts and domain vocabulary are still evolving together. Splitting repositories now would make atomic contract changes, end-to-end testing, and architecture governance harder.

## Decision

Use one Git repository containing independently deployable applications under `apps/` and non-deployable modules under `packages/`.

Use package boundaries, dependency checks, CODEOWNERS, separate images, and separate deployment manifests to preserve ownership and runtime isolation.

## Consequences

- Contract and consumer changes can be reviewed atomically.
- Local and CI end-to-end tests remain practical.
- The repository requires strict dependency direction and affected-path CI as it grows.
- A module can move to another repository only through a superseding ADR and the documented split criteria.

## Alternatives considered

- One large application package: rejected because it hides domain and deployment boundaries.
- Polyrepo from day one: rejected because contracts and ownership are not yet stable.

## Verification

CI must run workspace tests and prevent domain packages from importing application frameworks or provider SDKs.
