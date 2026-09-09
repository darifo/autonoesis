"""Generate a CycloneDX SBOM over signed Capability Pack manifests.

Packs are the platform's own supply-chain unit (ADR-0035): each component
carries the pack identity, version, content digest, signature presence, SBOM
reference, and declared dependencies so downstream tooling can reconcile the
pack graph alongside Python/Node SBOMs.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from autonoesis_capability import load_manifest

ROOT = Path(__file__).resolve().parents[2]
PACK_MANIFESTS = (ROOT / "examples").rglob("capability-pack.yaml")


def build_pack_sbom(manifest_paths=None) -> dict:
    components = []
    dependencies = []
    for path in manifest_paths or sorted(PACK_MANIFESTS):
        manifest = load_manifest(path)
        component = {
            "type": "library",
            "bom-ref": f"pkg:autonoesis/{manifest.pack_id}@{manifest.version}",
            "name": manifest.pack_id,
            "version": manifest.version,
            "purl": f"pkg:autonoesis/{manifest.pack_id}@{manifest.version}",
            "properties": [
                {"name": "autonoesis:pack:entryPoint", "value": manifest.python_entry_point},
                {"name": "autonoesis:pack:signed", "value": str(manifest.signature is not None)},
                {"name": "autonoesis:pack:contentDigest", "value": manifest.artifact_digest or ""},
                {"name": "autonoesis:pack:sbomRef", "value": manifest.sbom_ref or ""},
            ],
        }
        if manifest.artifact_digest:
            component["hashes"] = [{"alg": "SHA-256", "content": manifest.artifact_digest}]
        components.append(component)
        depends_on = [
            f"pkg:autonoesis/{dependency.pack_id}" for dependency in manifest.dependencies
        ]
        dependencies.append(
            {
                "ref": f"pkg:autonoesis/{manifest.pack_id}@{manifest.version}",
                "dependsOn": depends_on,
            }
        )
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "serialNumber": f"urn:uuid:{uuid4()}",
        "version": 1,
        "metadata": {
            "timestamp": datetime.now(UTC).isoformat(),
            "component": {
                "type": "application",
                "name": "autonoesis-capability-packs",
                "version": "0.1.0",
            },
        },
        "components": components,
        "dependencies": dependencies,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, help="output CycloneDX JSON path")
    args = parser.parse_args()
    sbom = build_pack_sbom()
    Path(args.output).write_text(json.dumps(sbom, indent=2, ensure_ascii=False))
    print(f"wrote {args.output} with {len(sbom['components'])} pack components")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
