from __future__ import annotations

import hashlib
import json
from typing import Any


def command_schema_hash(commands: list[dict[str, Any]]) -> str:
    canonical = json.dumps(commands, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return hashlib.sha256(canonical).hexdigest()


def needs_sync(previous_hash: str | None, commands: list[dict[str, Any]]) -> tuple[bool, str]:
    current = command_schema_hash(commands)
    return previous_hash != current, current
