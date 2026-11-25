"""25/11/2026 : « la lenteur pour mute ou warn ou faire une action, ça saoule ».

Après l'action Discord, le rôle mute, le MP (deux allers-retours) et le
dossier en base s'enchaînaient alors qu'ils ne dépendent pas les uns des
autres. Ils partent maintenant ensemble : avec trois étapes de 0,3 s, la
sanction prend ~0,3 s au lieu de ~0,9 s.
"""
from __future__ import annotations

import asyncio
import os
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from services import moderation as svc  # noqa: E402

LENT = 0.3


def _lents(monkeypatch):
    async def lent(*_a, **_k):
        await asyncio.sleep(LENT)

    async def dossier(*_a, **_k):
        await asyncio.sleep(LENT)
        return 7, None

    monkeypatch.setattr(svc, "_hierarchy_error", AsyncMock(return_value=None))
    monkeypatch.setattr(svc, "_apply_mute_role", lent)
    monkeypatch.setattr(svc, "_send_dm_card", lent)
    monkeypatch.setattr(svc, "persist_sanction", dossier)
    monkeypatch.setattr(svc, "_lien_retour", AsyncMock(return_value=None))


def _chrono(coro):
    debut = time.perf_counter()
    resultat = asyncio.run(coro)
    return resultat, time.perf_counter() - debut


def test_mute_lance_role_mp_et_dossier_ensemble(monkeypatch):
    _lents(monkeypatch)
    cible = SimpleNamespace(id=2, timeout=AsyncMock())
    guild = SimpleNamespace(id=1)
    issue, duree = _chrono(svc.mute(
        SimpleNamespace(), guild=guild, actor=SimpleNamespace(id=3), target=cible,
        reason="spam", duree="10m", render_dm_text=lambda s: "Vous êtes muet.",
    ))
    assert issue.executed and issue.dm_sent and issue.case_number == 7
    cible.timeout.assert_awaited_once()
    assert duree < 2 * LENT, f"{duree:.2f} s : les étapes s'enchaînent encore"


def test_unmute_lance_mp_et_dossier_ensemble(monkeypatch):
    _lents(monkeypatch)
    cible = SimpleNamespace(id=2, timeout=AsyncMock())
    issue, duree = _chrono(svc.unmute(
        SimpleNamespace(), guild=SimpleNamespace(id=1), actor=SimpleNamespace(id=3), target=cible,
        reason="ok", dm_text="Vous pouvez parler.",
    ))
    assert issue.executed and issue.dm_sent and issue.case_number == 7
    # timeout instantané, puis rôle (0,3) ; MP et dossier ensemble (0,3).
    assert duree < 3 * LENT, f"{duree:.2f} s"
