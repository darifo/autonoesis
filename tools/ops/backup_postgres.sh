#!/usr/bin/env bash
# Consistent backup of the Autonoesis authoritative PostgreSQL databases
# (P2-02). Produces custom-format archives for the platform, Temporal's
# durable workflow history, and independent per-concern sets (stable pointer,
# policies + capability packs), plus a manifest with the alembic head and a
# sha256 digest per archive for immutability.
#
# Usage: backup_postgres.sh <container> <output-dir> [label]
set -euo pipefail

CONTAINER="${1:?usage: backup_postgres.sh <postgres-container> <output-dir> [label]}"
OUT_DIR="${2:?output directory required}"
LABEL="${3:-drill-$(date -u +%Y%m%dT%H%M%SZ)}"

mkdir -p "$OUT_DIR"
STARTED="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

dump_to_host() {
  local db="$1" tables="${2:-}" target="$3" tmp
  tmp="/tmp/$(basename "$target")"
  if [ -n "$tables" ]; then
    # shellcheck disable=SC2086  # tables expands to distinct -t arguments
    docker exec "$CONTAINER" pg_dump -U autonoesis -d "$db" -Fc $tables -f "$tmp"
  else
    docker exec "$CONTAINER" pg_dump -U autonoesis -d "$db" -Fc -f "$tmp"
  fi
  docker cp "$CONTAINER:$tmp" "$target" >/dev/null
  docker exec "$CONTAINER" rm "$tmp"
}

# Full authoritative set: platform + Temporal workflow history + visibility.
dump_to_host autonoesis "" "$OUT_DIR/autonoesis-$LABEL.dump"
dump_to_host temporal "" "$OUT_DIR/temporal-$LABEL.dump"
dump_to_host temporal_visibility "" "$OUT_DIR/temporal-visibility-$LABEL.dump"

# Independent per-concern archives (restorable without the full set):
dump_to_host autonoesis "-t releases -t deployments" "$OUT_DIR/stable-pointer-$LABEL.dump"
dump_to_host autonoesis \
  "-t policy_versions -t capability_packs -t capability_pack_channels" \
  "$OUT_DIR/policy-packs-$LABEL.dump"

HEAD_REVISION="$(docker exec "$CONTAINER" psql -U autonoesis -d autonoesis -tAc \
  'SELECT version_num FROM alembic_version' | tr -d '[:space:]')"

digest() { shasum -a 256 "$1" | cut -d' ' -f1; }

cat > "$OUT_DIR/autonoesis-$LABEL.manifest.json" <<JSON
{
  "label": "$LABEL",
  "database": "autonoesis",
  "started_utc": "$STARTED",
  "alembic_head": "$HEAD_REVISION",
  "format": "postgresql-custom",
  "archives": {
    "platform": {"file": "autonoesis-$LABEL.dump", "sha256": "$(digest "$OUT_DIR/autonoesis-$LABEL.dump")"},
    "temporal": {"file": "temporal-$LABEL.dump", "sha256": "$(digest "$OUT_DIR/temporal-$LABEL.dump")"},
    "temporal_visibility": {"file": "temporal-visibility-$LABEL.dump", "sha256": "$(digest "$OUT_DIR/temporal-visibility-$LABEL.dump")"},
    "stable_pointer": {"file": "stable-pointer-$LABEL.dump", "sha256": "$(digest "$OUT_DIR/stable-pointer-$LABEL.dump")"},
    "policy_and_packs": {"file": "policy-packs-$LABEL.dump", "sha256": "$(digest "$OUT_DIR/policy-packs-$LABEL.dump")"}
  }
}
JSON
echo "backup complete in $OUT_DIR:"
ls -1 "$OUT_DIR"/*-"$LABEL".dump
