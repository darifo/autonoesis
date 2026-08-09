from pathlib import Path


def test_core_source_contains_no_field_service_business_vocabulary() -> None:
    root = Path(__file__).resolve().parents[3]
    source_roots = [
        root / "packages/domain/src",
        root / "packages/application/src",
        root / "packages/runtime-kernel/src",
    ]
    forbidden = ("servicecase", "equipment_id", "customer_id", "repair_order")
    for source_root in source_roots:
        for path in source_root.rglob("*.py"):
            content = path.read_text(encoding="utf-8").lower()
            assert not any(term in content for term in forbidden), path


def test_domain_has_no_framework_or_provider_imports() -> None:
    """packages/domain must not depend on any framework or provider SDK."""
    root = Path(__file__).resolve().parents[3]
    source_root = root / "packages/domain/src"
    forbidden = (
        "fastapi",
        "temporalio",
        "openai",
        "anthropic",
        "sqlalchemy",
        "httpx",
        "psycopg",
        "alembic",
        "pydantic",
        "celery",
        "redis",
        "kafka",
        "nats",
    )
    for path in source_root.rglob("*.py"):
        content = path.read_text(encoding="utf-8").lower()
        for term in forbidden:
            assert term not in content, f"{path} imports forbidden '{term}'"


def test_application_has_no_provider_sdk_imports() -> None:
    """packages/application must not depend on provider SDKs."""
    root = Path(__file__).resolve().parents[3]
    source_root = root / "packages/application/src"
    forbidden = ("openai", "anthropic", "temporalio", "sqlalchemy", "psycopg", "alembic")
    for path in source_root.rglob("*.py"):
        content = path.read_text(encoding="utf-8").lower()
        for term in forbidden:
            assert term not in content, f"{path} imports forbidden '{term}'"
