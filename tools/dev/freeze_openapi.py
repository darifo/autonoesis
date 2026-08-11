#!/usr/bin/env python3
"""Freeze and verify the public HTTP consumer contract deterministically."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from autonoesis_adapters import InMemoryPlatformStore
from autonoesis_api.main import build_app

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "docs/contracts/generated/openapi-v1.json"


def render() -> str:
    schema = build_app(InMemoryPlatformStore()).openapi()
    return json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    rendered = render()
    if args.write:
        CONTRACT.parent.mkdir(parents=True, exist_ok=True)
        CONTRACT.write_text(rendered, encoding="utf-8")
        print(f"wrote {CONTRACT.relative_to(ROOT)}")
        return 0
    if not CONTRACT.exists() or CONTRACT.read_text(encoding="utf-8") != rendered:
        print("OpenAPI consumer contract is stale; run tools/dev/freeze_openapi.py --write")
        return 1
    print("OpenAPI consumer contract is current")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
