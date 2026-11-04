"""04/11/2026 : un seul module restaure après un nuke (plus de salons recréés en double).

L'ancien rollback (cogs/antinuke_rollback) recréait les salons AVANT la sanction,
puis l'anti-nuke V55 les recréait une seconde fois (il ne retrouve pas l'ancien
identifiant d'un salon déjà recréé). Quand V55 est chargé, il restaure seul :
sanction d'abord, puis rôles, catégories, salons, positions et permissions.
"""
from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from cogs import antinuke_rollback as rb  # noqa: E402


def _bot(avec_v55: bool):
    appels = []

    class Rollback:
        async def rollback_actor(self, guild, actor_id, reason):
            appels.append("ancien-rollback")

    class Automod:
        async def punish_nuker(self, guild, actor_id, reason):
            appels.append("sanction")

    automod = Automod()
    cogs = {"Automod": automod, rb._COG_NAME: Rollback()}
    if avec_v55:
        cogs["AntiNukeEmergencyV55"] = object()
    bot = SimpleNamespace(get_cog=cogs.get)
    rb._patch_punishment(bot)
    return automod, appels


def test_avec_v55_l_ancien_rollback_ne_restaure_plus():
    automod, appels = _bot(avec_v55=True)
    asyncio.run(automod.punish_nuker(SimpleNamespace(id=1), 42, "nuke"))
    assert appels == ["sanction"]


def test_sans_v55_l_ancien_rollback_reste_le_filet():
    automod, appels = _bot(avec_v55=False)
    asyncio.run(automod.punish_nuker(SimpleNamespace(id=1), 42, "nuke"))
    assert appels == ["ancien-rollback", "sanction"]
