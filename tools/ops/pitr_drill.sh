#!/usr/bin/env bash
# Point-in-time recovery drill (P2-02): enable WAL archiving on the platform
# database, capture a base backup plus archived WAL, then restore a fresh
# instance to a chosen point in time and verify rows present/absent.
#
# Usage: pitr_drill.sh <container> <workdir>
set -euo pipefail

CONTAINER="${1:?usage: pitr_drill.sh <postgres-container> <workdir>}"
WORK="${2:?workdir required}"
PG="docker exec $CONTAINER"

rm -rf "$WORK"; mkdir -p "$WORK/archive" "$WORK/basebackup"

echo "== 1. enable WAL archiving =="
$PG sh -c 'mkdir -p /archive && chmod 777 /archive'
$PG psql -U autonoesis -d postgres -c "ALTER SYSTEM SET wal_level = replica" >/dev/null
$PG psql -U autonoesis -d postgres -c "ALTER SYSTEM SET archive_mode = on" >/dev/null
$PG psql -U autonoesis -d postgres -c \
  "ALTER SYSTEM SET archive_command = 'test ! -f /archive/%f && cp %p /archive/%f'" >/dev/null
docker restart "$CONTAINER" >/dev/null
until $PG pg_isready -U autonoesis >/dev/null 2>&1; do sleep 1; done
echo "wal archiving enabled"

echo "== 2. base backup (baseline BEFORE the markers) =="
$PG sh -c 'rm -rf /tmp/base && mkdir -p /tmp/base && chmod 700 /tmp/base'
$PG pg_basebackup -U autonoesis -D /tmp/base -Fp -Xs -P >/dev/null
mkdir -p "$WORK/basebackup"
docker exec "$CONTAINER" tar -C /tmp/base -cf - . | tar -C "$WORK/basebackup" -xf -
$PG rm -rf /tmp/base

echo "== 3. seed pre-pit marker =="
BEFORE_ID="$(uuidgen | tr 'A-F' 'a-f')"
AFTER_ID="$(uuidgen | tr 'A-F' 'a-f')"
$PG psql -U autonoesis -d autonoesis -c \
  "INSERT INTO tenants (id, name, created_at) VALUES ('$BEFORE_ID', 'pitr-before', CURRENT_TIMESTAMP)" >/dev/null
sleep 1
TARGET_TIME="$($PG psql -U autonoesis -d autonoesis -tAc 'SELECT clock_timestamp()' | sed 's/^ *//;s/ *$//')"
echo "recovery target time: $TARGET_TIME"
sleep 1

echo "== 4. seed post-pit marker (must NOT appear after recovery), then archive WAL =="
$PG psql -U autonoesis -d autonoesis -c \
  "INSERT INTO tenants (id, name, created_at) VALUES ('$AFTER_ID', 'pitr-after', CURRENT_TIMESTAMP)" >/dev/null
$PG psql -U autonoesis -d postgres -c "SELECT pg_switch_wal()" >/dev/null
sleep 3
$PG psql -U autonoesis -d postgres -c "SELECT pg_switch_wal()" >/dev/null
sleep 3
$PG psql -U autonoesis -d postgres -c "SELECT pg_switch_wal()" >/dev/null
sleep 3

mkdir -p "$WORK/archive"
for wal in $($PG sh -c 'ls /archive'); do
  docker cp "$CONTAINER:/archive/$wal" "$WORK/archive/$wal" >/dev/null
done
echo "archived WAL segments: $(ls "$WORK/archive" | wc -l | tr -d '[:space:]')"

echo "== 5. restore to target time in a fresh instance =="
RECOVERY_DIR="$WORK/recovery"
mkdir -p "$RECOVERY_DIR"
cp -r "$WORK/basebackup/." "$RECOVERY_DIR/"
rm -f "$RECOVERY_DIR/postmaster.pid" "$RECOVERY_DIR/postmaster.opts" \
      "$RECOVERY_DIR/standby.signal" 2>/dev/null || true
# Keep the base backup's streamed WAL (-Xs): it carries the backup through
# its own end; the archive supplies anything later.
mkdir -p "$RECOVERY_DIR/pg_wal"
cp -n "$WORK/archive/"* "$RECOVERY_DIR/pg_wal/" 2>/dev/null || true
rm -f "$RECOVERY_DIR/postgresql.auto.conf"
cat >> "$RECOVERY_DIR/postgresql.conf" <<CONF
archive_mode = off
wal_level = replica
restore_command = 'cp /wal-archive/%f %p'
recovery_target_time = '$TARGET_TIME'
recovery_target_action = 'promote'
CONF
touch "$RECOVERY_DIR/recovery.signal"

test -f "$RECOVERY_DIR/PG_VERSION" || { echo "FAIL: base backup layout broken (no PG_VERSION)"; exit 1; }
docker rm -f autonoesis-pitr-verify >/dev/null 2>&1 || true
docker run -d --name autonoesis-pitr-verify \
  -v "$RECOVERY_DIR:/var/lib/postgresql/data" \
  -v "$WORK/archive:/wal-archive:ro" \
  -e POSTGRES_HOST_AUTH_METHOD=trust postgres:17-alpine >/dev/null
until docker exec autonoesis-pitr-verify pg_isready -U autonoesis >/dev/null 2>&1; do sleep 1; done
sleep 2

BEFORE_COUNT=$(docker exec autonoesis-pitr-verify psql -U autonoesis -d autonoesis -tAc \
  "SELECT count(*) FROM tenants WHERE id = '$BEFORE_ID'" | tr -d '[:space:]')
AFTER_COUNT=$(docker exec autonoesis-pitr-verify psql -U autonoesis -d autonoesis -tAc \
  "SELECT count(*) FROM tenants WHERE id = '$AFTER_ID'" | tr -d '[:space:]')

[ "$BEFORE_COUNT" = "1" ] || { echo "FAIL: pre-target row missing after PITR"; docker rm -f autonoesis-pitr-verify >/dev/null; exit 1; }
[ "$AFTER_COUNT" = "0" ] || { echo "FAIL: post-target row leaked into PITR restore"; docker rm -f autonoesis-pitr-verify >/dev/null; exit 1; }
echo "ok: point-in-time recovery verified (pre-target present, post-target absent)"
docker rm -f autonoesis-pitr-verify >/dev/null
echo "PITR drill complete; artifacts in $WORK"
