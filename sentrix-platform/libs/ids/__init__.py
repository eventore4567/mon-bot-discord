"""UUIDv7 genere cote application (RFC 9562).

Triable temporellement (bon pour les index B-tree), sans fuite d'information
sequentielle, et portable entre versions de PostgreSQL - contrairement a
uuidv7() natif qui n'existe qu'a partir de PostgreSQL 18.

Disposition (128 bits) :
    48 bits  unix_ts_ms
     4 bits  version (0b0111)
    12 bits  rand_a
     2 bits  variant (0b10)
    62 bits  rand_b
"""

from __future__ import annotations

import os
import time
import uuid

__all__ = ["uuid7", "uuid7_at"]


def uuid7_at(ts_ms: int) -> uuid.UUID:
    """UUIDv7 pour un horodatage donne (millisecondes Unix). Utile aux tests."""
    if ts_ms < 0 or ts_ms >= 1 << 48:
        raise ValueError("ts_ms hors des 48 bits disponibles")

    rand = os.urandom(10)
    b = bytearray(16)

    b[0:6] = ts_ms.to_bytes(6, "big")

    # Octet 6 : version 7 sur les 4 bits hauts, rand_a sur les 4 bits bas.
    b[6] = 0x70 | (rand[0] & 0x0F)
    b[7] = rand[1]

    # Octet 8 : variant RFC 4122 (0b10) sur les 2 bits hauts.
    b[8] = 0x80 | (rand[2] & 0x3F)
    b[9:16] = rand[3:10]

    return uuid.UUID(bytes=bytes(b))


def uuid7() -> uuid.UUID:
    """UUIDv7 a l'instant present."""
    return uuid7_at(time.time_ns() // 1_000_000)
