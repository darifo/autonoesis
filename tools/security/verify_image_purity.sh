#!/usr/bin/env bash
# Assert the production image excludes dev dependencies, test material,
# repository history, and development signing keys (P2-03).
set -euo pipefail

IMAGE="${1:-autonoesis-purity-check}"
PACKAGE="${2:-autonoesis-api}"

check() {
  if docker run --rm --entrypoint sh "$IMAGE" -c "$2" >/dev/null 2>&1; then
    echo "FAIL: $1"
    exit 1
  fi
  echo "ok: $1 excluded"
}

check "development signing key" "test -f /workspace/infra/supply-chain/dev-signing-private-key.txt"
check "tests directory" "test -d /workspace/tests"
check "git history" "test -d /workspace/.git"
check "dev dependencies" "/opt/autonoesis/bin/python -c 'import pytest'"

docker run --rm --entrypoint sh "$IMAGE" -c \
  "/opt/autonoesis/bin/python -c 'import ${PACKAGE//-/_}'" \
  || { echo "FAIL: runtime package $PACKAGE missing"; exit 1; }
echo "purity verified for $PACKAGE"
