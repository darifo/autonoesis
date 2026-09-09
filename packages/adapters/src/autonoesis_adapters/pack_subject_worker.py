"""Subprocess entry point for sandboxed Capability Pack subject execution.

Reads one JSON object ({"input_payload": ..., "random_seed": ...}) from stdin,
imports the requested pack-owned module:function, executes it, and writes the
result payload as JSON to stdout. The child process holds no platform
credentials, no database access, and no Tool Gateway reach: it is pure compute.
"""

from __future__ import annotations

import importlib
import json
import sys


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: pack-subject-worker <module> <function>", file=sys.stderr)
        return 2
    module_name, function_name = sys.argv[1], sys.argv[2]
    try:
        command = json.loads(sys.stdin.read())
        input_payload = command["input_payload"]
        random_seed = int(command["random_seed"])
    except (json.JSONDecodeError, KeyError, ValueError) as exc:
        print(f"invalid subject command: {exc}", file=sys.stderr)
        return 2
    try:
        module = importlib.import_module(module_name)
        subject = getattr(module, function_name)
        output = subject(input_payload, random_seed)
    except Exception as exc:
        print(f"subject execution failed: {exc}", file=sys.stderr)
        return 1
    if not isinstance(output, dict):
        print("subject output must be a JSON object", file=sys.stderr)
        return 1
    try:
        sys.stdout.write(json.dumps(output))
    except (TypeError, ValueError) as exc:
        print(f"subject output is not serializable: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
