#!/usr/bin/env python3
"""Build a hash manifest for CI test and contract evidence artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--artifact", type=Path, action="append", default=[])
    args = parser.parse_args()
    records: list[dict[str, object]] = []
    for artifact in args.artifact:
        path = artifact if artifact.is_absolute() else ROOT / artifact
        records.append(
            {
                "path": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else path.name,
                "present": path.is_file(),
                "size_bytes": path.stat().st_size if path.is_file() else 0,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None,
            }
        )
    manifest = {
        "schema": "autonoesis.test-evidence.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "git_sha": os.getenv("GITHUB_SHA", "local"),
        "run_id": os.getenv("GITHUB_RUN_ID", "local"),
        "artifacts": records,
    }
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"wrote evidence manifest {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
