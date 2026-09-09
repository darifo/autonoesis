#!/usr/bin/env bash
# Render and lint the Autonoesis Helm chart (P2-01 CI gate).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CHART="$ROOT/infra/helm/autonoesis"
if ! command -v helm >/dev/null 2>&1; then
  # Fetch a pinned helm binary for validation when none is installed.
  HELM_BIN="$(mktemp -d)/helm"
  case "$(uname -s)-$(uname -m)" in
    Darwin-arm64) HELM_OS=darwin; HELM_ARCH=arm64 ;;
    Darwin-*) HELM_OS=darwin; HELM_ARCH=amd64 ;;
    Linux-arm64) HELM_OS=linux; HELM_ARCH=arm64 ;;
    Linux-*) HELM_OS=linux; HELM_ARCH=amd64 ;;
    *) echo "unsupported platform for helm download" >&2; exit 1 ;;
  esac
  curl -sSL "https://get.helm.sh/helm-v3.16.4-${HELM_OS}-${HELM_ARCH}.tar.gz" \
    | tar -xz -C "$(dirname "$HELM_BIN")" --strip-components=1
  chmod +x "$HELM_BIN"
  HELM="$HELM_BIN"
else
  HELM="helm"
fi

"$HELM" lint "$CHART"
"$HELM" template autonoesis "$CHART" > /tmp/autonoesis-rendered.yaml
# Every rendered manifest must be non-empty YAML documents.
python3 - <<'PY'
import yaml

docs = [doc for doc in yaml.safe_load_all(open("/tmp/autonoesis-rendered.yaml")) if doc]
assert docs, "chart rendered no manifests"
kinds = sorted({doc["kind"] for doc in docs})
required = {"Deployment", "ServiceAccount", "NetworkPolicy", "PodDisruptionBudget"}
missing = required - set(kinds)
assert not missing, f"chart is missing required kinds: {missing}"
service_accounts = {doc["metadata"]["name"] for doc in docs if doc["kind"] == "ServiceAccount"}
expected_pools = {
    "autonoesis-api",
    "autonoesis-cockpit",
    "autonoesis-worker-general",
    "autonoesis-worker-high-risk",
    "autonoesis-worker-evaluator",
    "autonoesis-worker-release-executor",
}
assert expected_pools <= service_accounts, (
    f"dedicated service accounts missing: {expected_pools - service_accounts}"
)
for doc in docs:
    if doc["kind"] == "Deployment":
        spec = doc["spec"]["template"]["spec"]
        assert spec["serviceAccountName"], f"{doc['metadata']['name']} lacks a service account"
print(f"chart validated: {len(docs)} manifests, kinds={kinds}")
PY
