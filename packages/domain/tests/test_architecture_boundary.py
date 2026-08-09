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
