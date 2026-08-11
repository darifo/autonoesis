#!/usr/bin/env python3
"""Validate maturity claims and render a deterministic repository baseline report."""

from __future__ import annotations

import argparse
import ast
import hashlib
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "docs/roadmap/generated/production-baseline-report.md"


def read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def digest(relative_path: str) -> str:
    return hashlib.sha256((ROOT / relative_path).read_bytes()).hexdigest()


def assigned_string(tree: ast.AST, name: str) -> str:
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if (
            any(isinstance(target, ast.Name) and target.id == name for target in node.targets)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            return node.value.value
    raise ValueError(f"could not find string assignment for {name}")


def database_inventory() -> tuple[str, list[str]]:
    revisions: dict[str, str | None] = {}
    for migration in (ROOT / "infra/migrations/versions").glob("*.py"):
        tree = ast.parse(migration.read_text(encoding="utf-8"))
        revision = assigned_string(tree, "revision")
        down_revision: str | None = None
        for node in tree.body:
            if (
                isinstance(node, ast.Assign)
                and any(
                    isinstance(target, ast.Name) and target.id == "down_revision"
                    for target in node.targets
                )
                and isinstance(node.value, ast.Constant)
            ):
                down_revision = node.value.value
        revisions[revision] = down_revision
    parents = {value for value in revisions.values() if value is not None}
    heads = sorted(set(revisions) - parents)
    if len(heads) != 1:
        raise ValueError(f"expected one Alembic head, found {heads}")

    persistence_tree = ast.parse(
        read("packages/adapters/src/autonoesis_adapters/persistence_schema.py")
    )
    tables: list[str] = []
    for node in persistence_tree.body:
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
            continue
        call_name = node.value.func.id if isinstance(node.value.func, ast.Name) else ""
        if call_name not in {"Table", "tenant_table"} or not node.value.args:
            continue
        first_arg = node.value.args[0]
        if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
            tables.append(first_arg.value)
    return heads[0], sorted(tables)


def api_inventory() -> tuple[str, list[str]]:
    tree = ast.parse(read("apps/api/src/autonoesis_api/main.py"))
    version = "unknown"
    routes: list[str] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "FastAPI"
        ):
            for keyword in node.keywords:
                if keyword.arg == "version" and isinstance(keyword.value, ast.Constant):
                    version = str(keyword.value.value)
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Attribute):
                continue
            owner = decorator.func.value
            if not isinstance(owner, ast.Name) or owner.id != "app":
                continue
            method = decorator.func.attr.upper()
            if method not in {"GET", "POST", "PUT", "PATCH", "DELETE"} or not decorator.args:
                continue
            path = decorator.args[0]
            if isinstance(path, ast.Constant) and isinstance(path.value, str):
                routes.append(f"{method} {path.value}")
    return version, sorted(routes)


def workflow_inventory() -> list[str]:
    tree = ast.parse(read("apps/worker/src/autonoesis_worker/workflows.py"))
    workflows: list[str] = []
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        for decorator in node.decorator_list:
            if (
                isinstance(decorator, ast.Attribute)
                and isinstance(decorator.value, ast.Name)
                and decorator.value.id == "workflow"
                and decorator.attr == "defn"
            ):
                workflows.append(node.name)
    return sorted(workflows)


def compose_images() -> list[str]:
    pattern = re.compile(r"^\s+image:\s+([^\s#]+)", re.MULTILINE)
    return sorted(pattern.findall(read("infra/compose/docker-compose.yml")))


def validate_claim_boundaries() -> list[str]:
    checks = {
        "README.md engineering-preview warning": (
            "README.md",
            "architecture prototype and engineering preview",
        ),
        "README.zh-CN.md engineering-preview warning": (
            "README.zh-CN.md",
            "架构原型和工程预览",
        ),
        "maturity matrix limits integrated claims": (
            "docs/roadmap/capability-maturity.md",
            "当前 PostgreSQL 权威存储和 Goal/Run Application 用例达到 `integrated`",
        ),
        "Cockpit global prototype banner": (
            "apps/cockpit/src/main.tsx",
            'data-testid="prototype-banner"',
        ),
        "Cockpit static-data disclosure": (
            "apps/cockpit/src/main.tsx",
            "当前页面使用静态样例数据",
        ),
        "API engineering-preview phase": (
            "apps/api/src/autonoesis_api/main.py",
            '"phase": "engineering-preview"',
        ),
    }
    errors = [label for label, (path, marker) in checks.items() if marker not in read(path)]
    forbidden = {
        "README.md": ("✅ Complete", "tests-122%20passed"),
        "README.zh-CN.md": ("✅ 完成", "tests-122%20passed"),
        "docs/roadmap/mvp.md": ("\uff08完成\uff09",),
        "apps/cockpit/src/main.tsx": ("系统运行正常", "Acme / Production"),
    }
    for path, markers in forbidden.items():
        content = read(path)
        for marker in set(markers):
            if marker in content:
                errors.append(f"{path} still contains forbidden maturity claim: {marker}")
    return errors


def render_report() -> str:
    lock_files = [
        "environment.yml",
        "pyproject.toml",
        "uv.lock",
        "package.json",
        "pnpm-lock.yaml",
        "versions.lock",
        "infra/compose/docker-compose.yml",
    ]
    revision, tables = database_inventory()
    api_version, routes = api_inventory()
    workflows = workflow_inventory()
    schema_digest = digest("packages/adapters/src/autonoesis_adapters/persistence_schema.py")
    workflow_digest = digest("apps/worker/src/autonoesis_worker/workflows.py")
    versions = tomllib.loads(read("versions.lock"))
    reviewed_at = versions["reviewed_at"]
    if hasattr(reviewed_at, "isoformat"):
        reviewed_at = reviewed_at.isoformat()

    lines = [
        "# Generated Production Baseline Report",
        "",
        "> Generated by `tools/dev/check_production_baseline.py`; do not edit by hand.",
        f"> Compatibility review date: {reviewed_at}",
        "",
        "## Dependency and Runtime Sources",
        "",
        "| Source | SHA-256 |",
        "|---|---|",
    ]
    lines.extend(f"| `{path}` | `{digest(path)}` |" for path in lock_files)
    lines.extend(
        [
            "",
            "Configured Compose images (configuration inventory only; not integration evidence):",
            "",
        ]
    )
    lines.extend(f"- `{image}`" for image in compose_images())
    lines.extend(
        [
            "",
            "## Database Schema Baseline",
            "",
            f"- Alembic head: `{revision}`",
            f"- SQLAlchemy metadata digest: `sha256:{schema_digest}`",
            f"- Declared tables ({len(tables)}): " + ", ".join(f"`{table}`" for table in tables),
            "- Evidence level: `integrated`; CI migrates PostgreSQL 17 and runs "
            "authority/Application transaction component tests.",
            "",
            "## HTTP API Contract Baseline",
            "",
            f"- Application contract version: `{api_version}`",
            "- OpenAPI dialect: `3.1.x` (FastAPI default; generated contract is not frozen yet)",
            f"- Route source digest: `sha256:{digest('apps/api/src/autonoesis_api/main.py')}`",
            f"- Declared operations ({len(routes)}):",
            "",
        ]
    )
    lines.extend(f"  - `{route}`" for route in routes)
    lines.extend(
        [
            "",
            "## Workflow Type Baseline",
            "",
            f"- Workflow source digest: `sha256:{workflow_digest}`",
            f"- Declared Workflow types ({len(workflows)}): "
            + ", ".join(f"`{workflow}`" for workflow in workflows),
            "- Workflow patch/version marker: not established.",
            "- Replay evidence: not established.",
            "",
            "## Maturity Guard Result",
            "",
            "- README engineering-preview disclosure: present.",
            "- Cockpit Prototype/Demo and static-data disclosure: present.",
            "- Highest allowed current maturity: `integrated` (PostgreSQL authority and "
            "Goal/Run Application use cases).",
            "- Real-component integration evidence: CI PostgreSQL 17 migration and "
            "authority/Application transaction tests.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true", help="refresh the generated report")
    parser.add_argument("--print", action="store_true", dest="print_report")
    args = parser.parse_args()

    errors = validate_claim_boundaries()
    rendered = render_report()
    if args.print_report:
        print(rendered, end="")
    if args.write:
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        REPORT.write_text(rendered, encoding="utf-8")
    elif not REPORT.exists() or REPORT.read_text(encoding="utf-8") != rendered:
        errors.append(
            "generated baseline report is stale; run "
            "`python3 tools/dev/check_production_baseline.py --write`"
        )

    if errors:
        for error in errors:
            print(f"baseline error: {error}", file=sys.stderr)
        return 1
    if not args.print_report:
        print("production baseline claims and generated inventory are current")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
