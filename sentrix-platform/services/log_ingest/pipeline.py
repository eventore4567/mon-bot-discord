from __future__ import annotations

from dataclasses import dataclass, field

from services.log_ingest.quota import OrgLogQuota
from services.log_ingest.redaction import SecretRedactor


@dataclass
class MemoryLogSink:
    rows: list[tuple[str, bytes]] = field(default_factory=list)

    def append(self, org_id: str, line: bytes) -> None:
        self.rows.append((org_id, line))


@dataclass
class LogPipeline:
    quota: OrgLogQuota
    sink: MemoryLogSink
    dropped_bytes: dict[str, int] = field(default_factory=dict)

    def ingest(self, org_id: str, line: bytes, *, now: float, redactor: SecretRedactor) -> bool:
        cleaned = redactor.redact(line)
        if not self.quota.allow(org_id, len(cleaned), now):
            self.dropped_bytes[org_id] = self.dropped_bytes.get(org_id, 0) + len(cleaned)
            return False
        self.sink.append(org_id, cleaned)
        return True
