"""04/11/2026 : un seul module restaure après un nuke (plus de salons recréés en double).

L'ancien rollback (cogs/antinuke_rollback) recréait les salons AVANT la sanction,
puis l'anti-nuke V55 les recréait une seconde fois (il ne retrouve pas l'ancien
identifiant d'un salon déjà recréé). Quand V55 est chargé, il restaure seul :
sanction d'abord, puis rôles, catégories, salons, positions et permissions.

22/11/2026 : cette règle vivait dans un remplacement de punish_nuker installé
par antinuke_rollback (_patch_punishment). Elle est écrite dans
AutoMod.punish_nuker, l'implémentation unique. Changement assumé : sans V55,
le rollback historique restaure désormais APRÈS la sanction, et non avant —
la règle de V55, « confinement d'abord » : sinon l'auteur continue d'agir
pendant la restauration.
"""
from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from cogs import automod as am  # noqa: E402
from cogs import security_v2_runtime  # noqa: E402


def _scenario(avec_v55: bool):
    appels = []

    class Rollback:
        async def rollback_actor(self, guild, actor_id, reason):
            appels.append("ancien-rollback")

    class V55:
        async def restore_burst(self, guild, actor_id, reason):
            appels.append("restauration-v55")

    cogs = {"AntiNukeRollback": Rollback()}
    if avec_v55:
        cogs["AntiNukeEmergencyV55"] = V55()
    cog = am.AutoMod.__new__(am.AutoMod)
    cog.bot = SimpleNamespace(get_cog=cogs.get)
    cog.is_antinuke_exempt = AsyncMock(return_value=False)
    cog.nuke_tracker = MagicMock()

    async def sanction(guild, actor_id, reason):
        appels.append("sanction")

    cog._sanctionner_nuker = sanction
    original = security_v2_runtime._write_incident
    security_v2_runtime._write_incident = AsyncMock()
    try:
        asyncio.run(cog.punish_nuker(SimpleNamespace(id=1, get_member=lambda uid: None), 42, "nuke"))
    finally:
        security_v2_runtime._write_incident = original
    return appels


def test_avec_v55_l_ancien_rollback_ne_restaure_plus():
    assert _scenario(avec_v55=True) == ["sanction", "restauration-v55"]


def test_sans_v55_l_ancien_rollback_reste_le_filet():
    assert _scenario(avec_v55=False) == ["sanction", "ancien-rollback"]
