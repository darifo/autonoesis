import importlib.util
import sys
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[2] / "tools/security/scan_secrets.py"
SPEC = importlib.util.spec_from_file_location("autonoesis_secret_scanner", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
SCANNER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = SCANNER
SPEC.loader.exec_module(SCANNER)
fingerprint = SCANNER.fingerprint
scan = SCANNER.scan


def test_secret_scanner_detects_and_exact_allowlist_cannot_hide_a_changed_value(
    tmp_path: Path,
) -> None:
    candidate = tmp_path / "settings.env"
    original = "SERVICE_PASSWORD=temporary-test-value"
    candidate.write_text(original + "\n", encoding="utf-8")

    findings = scan((candidate,), set())
    assert len(findings) == 1
    allowed = {(str(candidate), fingerprint(str(candidate), original))}
    assert scan((candidate,), allowed) == ()

    candidate.write_text("SERVICE_PASSWORD=changed-test-value\n", encoding="utf-8")
    assert len(scan((candidate,), allowed)) == 1


def test_secret_scanner_ignores_non_credentials(tmp_path: Path) -> None:
    candidate = tmp_path / "settings.py"
    candidate.write_text('timeout_seconds = 30\nmode = "development"\n', encoding="utf-8")
    assert scan((candidate,), set()) == ()
