#!/usr/bin/env python3
"""Fail on credential-shaped repository content unless an exact line is reviewed."""

from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASELINE = ROOT / ".secret-baseline.toml"
SELF = Path("tools/security/scan_secrets.py")
MAX_FILE_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class Finding:
    path: str
    line: int
    rule: str
    fingerprint: str


RULES = (
    (
        "private-key",
        re.compile("-----BEGIN " + "(?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    ),
    (
        "provider-token",
        re.compile(r"(?:gh[pousr]_[A-Za-z0-9]{30,}|sk-[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16})"),
    ),
    (
        "environment-credential",
        re.compile(
            r"([A-Z0-9_]*(?:API_KEY|SECRET|PASSWORD|TOKEN|CREDENTIAL)[A-Z0-9_]*)"
            r"\s*[:=]\s*[\"']?([A-Za-z0-9+/=_:.-]{8,})"
        ),
    ),
    (
        "literal-credential",
        re.compile(
            r"(?i)\b(?:api[_-]?key|secret|password|token|credential)[A-Za-z0-9_.-]*"
            r"\s*=\s*[\"']([^\"']{8,})[\"']"
        ),
    ),
    (
        "mapping-credential",
        re.compile(
            r"(?i)[\"'](?:api[_-]?key|secret|password|token|credential)[A-Za-z0-9_.-]*"
            r"[\"']\s*:\s*[\"']([^\"']{8,})[\"']"
        ),
    ),
    (
        "credential-url",
        re.compile(r"(?i)[a-z][a-z0-9+.-]*://[^\s:/]+:([^\s@/]{8,})@"),
    ),
)


def fingerprint(path: str, line: str) -> str:
    return hashlib.sha256(f"{path}\0{line.strip()}".encode()).hexdigest()


def repository_files() -> tuple[Path, ...]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return tuple(
        ROOT / item.decode()
        for item in result.stdout.split(b"\0")
        if item and Path(item.decode()) != SELF
    )


def load_allowlist(path: Path = BASELINE) -> set[tuple[str, str]]:
    if not path.exists():
        return set()
    payload = tomllib.loads(path.read_text(encoding="utf-8"))
    return {(str(item["path"]), str(item["line_sha256"])) for item in payload.get("allow", ())}


def scan(paths: tuple[Path, ...], allowlist: set[tuple[str, str]]) -> tuple[Finding, ...]:
    findings: list[Finding] = []
    for path in paths:
        if not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
            continue
        raw = path.read_bytes()
        if b"\0" in raw:
            continue
        relative = str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)
        for line_number, line in enumerate(raw.decode("utf-8", errors="replace").splitlines(), 1):
            if "<secret>" in line:
                continue
            digest = fingerprint(relative, line)
            if (relative, digest) in allowlist:
                continue
            for rule, pattern in RULES:
                match = pattern.search(line)
                if match is not None:
                    if (
                        rule == "environment-credential"
                        and match.group(1).lower() == match.group(2).lower()
                    ):
                        continue
                    findings.append(Finding(relative, line_number, rule, digest))
    return tuple(findings)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, default=BASELINE)
    args = parser.parse_args()
    findings = scan(repository_files(), load_allowlist(args.baseline))
    if findings:
        for item in findings:
            print(f"{item.path}:{item.line}: {item.rule} [{item.fingerprint}]")
        print(f"secret scan failed with {len(findings)} unreviewed finding(s)")
        return 1
    print("secret scan passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
