# CI Test Evidence Runbook

## Purpose

Preserve reviewable proof for contracts, real-component tests, UI tests, dependency audits, and
secret scans. CI artifacts are retained for 30 days; production release evidence requires a longer
external retention policy and is not established by this runbook.

## Local verification

```bash
python tools/dev/check_production_baseline.py
python tools/dev/freeze_openapi.py
python tools/security/scan_secrets.py
pytest
pnpm --filter @autonoesis/cockpit test:unit
pnpm --filter @autonoesis/cockpit test:e2e
```

For dependency checks, export locked production requirements and use the official npm audit
endpoint:

```bash
uv export --all-packages --no-dev --no-emit-workspace --frozen --output-file /tmp/autonoesis-requirements.txt
pip-audit --requirement /tmp/autonoesis-requirements.txt --strict
pnpm audit --prod --audit-level high --registry=https://registry.npmjs.org
```

## Artifact sets

- `python-component-evidence`: JUnit, production baseline, frozen OpenAPI, hash manifest;
- `dependency-secret-scan-evidence`: exported requirements, Python/npm audit JSON, hash manifest;
- `cockpit-test-evidence`: Vitest and Playwright JUnit, built entry point, hash manifest.

Every manifest uses `autonoesis.test-evidence.v1`, records the GitHub run and commit identities, and
contains SHA-256 plus byte size for each present artifact. Missing artifacts remain explicit when a
prior CI step fails.

## Secret baseline changes

Do not weaken a rule to make a finding disappear. Verify that the value is a non-production fixture,
then add only the exact `path` and line fingerprint with a reason. Any content change invalidates the
entry and requires a new review.
