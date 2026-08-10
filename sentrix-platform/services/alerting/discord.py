"""Discord alert payload construction. Sending is done by a transport adapter."""

from __future__ import annotations

from dataclasses import dataclass

_ALLOWED = {"crash", "deployment_failed", "identify_breaker", "identify_budget_low", "log_quota"}


@dataclass(frozen=True, slots=True)
class Alert:
    kind: str
    title: str
    detail: str
    environment_id: str

    def payload(self) -> dict[str, object]:
        if self.kind not in _ALLOWED:
            raise ValueError("unsupported alert kind")
        return {
            "embeds": [
                {
                    "title": self.title[:256],
                    "description": self.detail[:4000],
                    "fields": [
                        {"name": "Type", "value": self.kind, "inline": True},
                        {
                            "name": "Environment",
                            "value": self.environment_id[:1024],
                            "inline": True,
                        },
                    ],
                }
            ],
            "allowed_mentions": {"parse": []},
        }
