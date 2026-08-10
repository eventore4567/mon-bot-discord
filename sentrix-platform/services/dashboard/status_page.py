from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True, slots=True)
class ComponentStatus:
    name: str
    state: str
    message: str = ""


def public_status(components: list[ComponentStatus]) -> dict[str, object]:
    states = {c.state for c in components}
    overall = "operational" if states <= {"operational"} else "degraded"
    return {
        "status": overall,
        "components": [asdict(c) for c in components],
    }
