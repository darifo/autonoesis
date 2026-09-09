"""Architecture boundary: the API control plane never executes pack code.

P1-06 forbids unisolated third-party entry points from executing inside the
API process. The control plane may parse and persist manifests; importing or
invoking pack modules, plugin loaders, or subject runtimes belongs to workers
and sandboxes only.
"""

from pathlib import Path

API_SOURCES = tuple((Path(__file__).resolve().parents[1] / "src").rglob("*.py"))

FORBIDDEN_TOKENS = (
    "autonoesis_capability.plugins",
    "load_plugin",
    "discover_plugins",
    "PackSubjectRuntime",
    "InProcessSubjectRuntime",
    "SandboxedPackSubjectRuntime",
    "pack_subject_worker",
)


def test_control_plane_never_loads_or_executes_capability_pack_code() -> None:
    assert API_SOURCES, "API sources must be discovered"
    for source in API_SOURCES:
        text = source.read_text(encoding="utf-8")
        for token in FORBIDDEN_TOKENS:
            assert token not in text, f"{source.name} must not reference {token}"


def test_control_plane_has_no_dynamic_import_of_pack_modules() -> None:
    for source in API_SOURCES:
        text = source.read_text(encoding="utf-8")
        assert "importlib.import_module" not in text, (
            f"{source.name} must not import modules dynamically"
        )
