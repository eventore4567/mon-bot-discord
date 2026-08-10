"""Pre-build source scanner for credentials that must never enter an image."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# Discord bot tokens have changed shape over time. The scanner intentionally
# favors false positives: a rejected build is safer than shipping a live token.
_TOKEN_PATTERNS = (
    re.compile(
        rb"(?<![A-Za-z0-9_-])[MN][A-Za-z0-9_-]{20,30}\.[A-Za-z0-9_-]{5,8}\.[A-Za-z0-9_-]{25,80}(?![A-Za-z0-9_-])"
    ),
    re.compile(
        rb"(?i)(?:discord[_-]?token|bot[_-]?token|DISCORD_TOKEN)\s*[:=]\s*['\"]?[A-Za-z0-9_.-]{40,}"
    ),
)


@dataclass(frozen=True, slots=True)
class SecretFinding:
    path: str
    kind: str


def scan_bytes(data: bytes, *, path: str = "<memory>") -> list[SecretFinding]:
    findings: list[SecretFinding] = []
    for pattern in _TOKEN_PATTERNS:
        if pattern.search(data):
            findings.append(SecretFinding(path=path, kind="discord_token"))
            break
    return findings


def scan_tree(root: Path) -> list[SecretFinding]:
    findings: list[SecretFinding] = []
    for path in root.rglob("*"):
        if not path.is_file() or ".git" in path.parts:
            continue
        try:
            data = path.read_bytes()
        except OSError:
            continue
        if len(data) > 2_000_000:
            continue
        findings.extend(scan_bytes(data, path=str(path.relative_to(root))))
    return findings
