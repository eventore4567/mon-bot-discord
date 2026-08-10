"""Cache local atomique de l'etat desire."""

from __future__ import annotations

import json
import os
from pathlib import Path

from libs.runtime_models import AgentDesiredInstance


class DesiredCache:
    def __init__(self, path: Path) -> None:
        self.path = path

    def save(self, desired: list[AgentDesiredInstance]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temp = self.path.with_suffix(self.path.suffix + ".tmp")
        data = [item.model_dump(mode="json") for item in desired]
        temp.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
        os.chmod(temp, 0o600)
        os.replace(temp, self.path)

    def load(self) -> list[AgentDesiredInstance]:
        if not self.path.exists():
            return []
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            raise ValueError("cache desired invalide")
        return [AgentDesiredInstance.model_validate(item) for item in raw]
