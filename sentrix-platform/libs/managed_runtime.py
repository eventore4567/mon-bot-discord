"""Managed Runtime handshake used to gate Gateway connection establishment."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from services.identify_broker.broker import IdentifyBroker


@dataclass
class GatewayIdentifyGate:
    broker: IdentifyBroker

    def identify(
        self,
        application_id: str,
        shard_id: int,
        send_opcode2: Callable[[], None],
        *,
        now: float,
    ) -> str:
        reservation = self.broker.reserve(application_id, shard_id, now=now)
        # MUST happen before send_opcode2().
        self.broker.persist_identify_sent(reservation.id, now=now)
        send_opcode2()
        return reservation.id
