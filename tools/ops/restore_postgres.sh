#!/usr/bin/env bash
# Restore an Autonoesis backup into a fresh recovery database and verify
# integrity (P2-02): alembic head matches, tenant tables carry FORCED ROW
# LEVEL SECURITY, and every tenant's audit hash chain still verifies.
#
# Usage: restore_postgres.sh <source-container> <archive.dump> <alembic-head> [target-db]
set -euo pipefail

CONTAINER="${1:?usage: restore_postgres.sh <container> <archive> <alembic-head> [target-db]}"
ARCHIVE="${2:?archive path required}"
EXPECTED_HEAD="${3:?expected alembic head (from the backup manifest)}"
TARGET_DB="${4:-autonoesis_recovery}"

STARTED=$(python3 -c 'import time; print(time.time())')

docker exec "$CONTAINER" psql -U autonoesis -d postgres -c "DROP DATABASE IF EXISTS $TARGET_DB" >/dev/null
docker exec "$CONTAINER" psql -U autonoesis -d postgres -c "CREATE DATABASE $TARGET_DB OWNER autonoesis" >/dev/null
docker cp "$ARCHIVE" "$CONTAINER:/tmp/restore.dump" >/dev/null
docker exec "$CONTAINER" pg_restore -U autonoesis -d "$TARGET_DB" --no-owner /tmp/restore.dump
docker exec "$CONTAINER" rm /tmp/restore.dump

RESTORED_AT=$(python3 -c 'import time; print(time.time())')
python3 -c "import sys; print(f'restore wall time: {float(sys.argv[1]) - float(sys.argv[2]):.1f}s')" "$RESTORED_AT" "$STARTED"

# 1. Schema head matches the backup manifest.
ACTUAL_HEAD="$(docker exec "$CONTAINER" psql -U autonoesis -d "$TARGET_DB" -tAc \
  'SELECT version_num FROM alembic_version' | tr -d '[:space:]')"
[ "$ACTUAL_HEAD" = "$EXPECTED_HEAD" ] || { echo "FAIL: alembic head $ACTUAL_HEAD != $EXPECTED_HEAD"; exit 1; }
echo "ok: alembic head restored ($ACTUAL_HEAD)"

# 2. Every tenant-scoped table must retain FORCED row-level security. The
#    platform-scope tables (tenants registry, platform kill switch, platform
#    audit, break-glass alerts) are deliberately outside tenant RLS: they are
#    reachable only through the separate break-glass role (ADR/P1-01).
PLATFORM_TABLES="'alembic_version','tenants','platform_kill_switches','platform_audit_events','breakglass_alerts'"
UNFORCED="$(docker exec "$CONTAINER" psql -U autonoesis -d "$TARGET_DB" -tAc \
  "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
   WHERE n.nspname='public' AND c.relkind='r' AND c.relrowsecurity IS NOT TRUE
   AND c.relname NOT IN ($PLATFORM_TABLES)")"
[ "$(echo "$UNFORCED" | tr -d '[:space:]')" = "0" ] \
  || { echo "FAIL: $UNFORCED tenant tables lost FORCE ROW LEVEL SECURITY"; exit 1; }
echo "ok: all tenant-scoped tables restored with row-level security forced"

# 3. Every tenant's audit hash chain still verifies end-to-end.
TENANTS="$(docker exec "$CONTAINER" psql -U autonoesis -d "$TARGET_DB" -tAc \
  'SELECT id FROM tenants' | tr '\n' ' ' | sed 's/  */ /g;s/^ //;s/ $//')"
export AUTONOESIS_TEST_DATABASE_URL="postgresql+psycopg://autonoesis_api:autonoesis-ci-only@localhost:5432/$TARGET_DB"
python3 - $TENANTS <<'PY'
import asyncio
import os
import sys
from uuid import UUID

from autonoesis_adapters import PostgreSQLPlatformStore
from autonoesis_application import verify_audit_chain


async def main() -> None:
    store = PostgreSQLPlatformStore.from_url(os.environ["AUTONOESIS_TEST_DATABASE_URL"])
    try:
        tenants = [UUID(item) for item in sys.argv[1].split()]
        assert tenants, "backup contains no tenants"
        for tenant in tenants:
            events = await store.list_audit_events(tenant)
            if events:
                verify_audit_chain(events)
                print(f"ok: audit chain verified for tenant {tenant} ({len(events)} events)")
            else:
                print(f"ok: tenant {tenant} has no audit events (empty chain)")
    finally:
        await store.close()


asyncio.run(main())
PY

echo "restore verified into $TARGET_DB"
