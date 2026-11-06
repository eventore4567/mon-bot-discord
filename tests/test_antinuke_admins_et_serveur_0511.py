"""05/11/2026 : l'anti-nuke surveille les admins et l'identité du serveur.

Test réel : un compte admin secondaire a supprimé tous les salons et renommé le
serveur sans aucune réaction.
"""
from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from cogs.automod import AutoMod  # noqa: E402


def _cog(actor_id=77, antinuke=1):
    cog = AutoMod.__new__(AutoMod)
    cog.bot = SimpleNamespace(user=SimpleNamespace(id=2))
    cog.get_automod_cached = AsyncMock(return_value={"antinuke": antinuke})
    cog.get_audit_actor = AsyncMock(return_value=SimpleNamespace(id=actor_id))
    cog.is_antinuke_exempt = AsyncMock(return_value=False)
    compteur = {"n": 0}

    async def record(guild, actor):
        compteur["n"] += 1
        return compteur["n"] >= 3

    cog.record_nuke_action = record
    cog.punish_nuker = AsyncMock()
    return cog


def _serveur(nom):
    return SimpleNamespace(id=1, name=nom, icon=None, banner=None, splash=None, description=None,
                           edit=AsyncMock())


def test_trois_renommages_rapides_sanctionnent_et_remettent_le_nom_d_origine():
    cog = _cog()

    async def scenario():
        noms = ["Mon Serveur", "NUKED 1", "NUKED 2", "NUKED 3"]
        dernier = None
        for avant, apres in zip(noms, noms[1:]):
            dernier = _serveur(apres)
            await cog._garde_identite_serveur(_serveur(avant), dernier)
        return dernier

    dernier = asyncio.run(scenario())
    cog.punish_nuker.assert_awaited_once()
    dernier.edit.assert_awaited_once()
    assert dernier.edit.await_args.kwargs["name"] == "Mon Serveur"


def test_un_seul_renommage_ne_sanctionne_personne():
    cog = _cog()
    asyncio.run(cog._garde_identite_serveur(_serveur("A"), _serveur("B")))
    cog.punish_nuker.assert_not_awaited()


def test_anti_nuke_eteint_ne_fait_rien():
    cog = _cog(antinuke=0)
    for _ in range(4):
        asyncio.run(cog._garde_identite_serveur(_serveur("A"), _serveur("B")))
    cog.punish_nuker.assert_not_awaited()


def test_huit_pings_de_la_meme_personne_dans_un_message_sont_detectes():
    import datetime as dt

    cog = AutoMod.__new__(AutoMod)
    cog.bot = SimpleNamespace(user=SimpleNamespace(id=2))
    cible = SimpleNamespace(id=500, bot=False)
    message = SimpleNamespace(
        author=SimpleNamespace(id=9),
        guild=SimpleNamespace(id=1),
        mentions=[cible],
        role_mentions=[],
        reference=None,
        content=" ".join(["<@500>"] * 8),
        created_at=dt.datetime.now(dt.timezone.utc),
    )
    assert cog._pings_repetes(message) == "Mentions répétées (ping spam)."


# ------------------------------------------------- pings : avertir, puis muter

def test_pings_repetes_avertissent_avant_de_muter_et_suppriment_les_precedents():
    import asyncio as _asyncio
    from types import SimpleNamespace as _NS
    from cogs import automod as _am

    cog = _am.AutoMod.__new__(_am.AutoMod)
    cog.bot = _NS(user=_NS(id=999))
    supprimes = []

    def _msg(numero):
        async def delete():
            supprimes.append(numero)
        cible = _NS(id=77, bot=False)
        return _NS(
            id=numero, author=_NS(id=5), guild=_NS(id=1), mentions=[cible], role_mentions=[],
            reference=None, content="<@77>", created_at=None, delete=delete,
        )

    async def scenario():
        resultats = [cog._pings_repetes(_msg(n)) for n in range(1, 4)]
        await _asyncio.sleep(0)
        await _asyncio.sleep(0)
        return resultats

    resultats = _asyncio.run(scenario())
    assert resultats[:2] == [None, None]
    assert resultats[2] == "Mentions répétées (ping spam)."
    assert sorted(supprimes) == [1, 2]   # les deux premiers pings sont retirés aussi
    assert _am.MOTIF_MENTION_MASSIVE == "Mention massive détectée."


def test_une_rafale_juste_apres_l_avertissement_ne_mute_pas_encore(monkeypatch):
    import asyncio as _asyncio
    from types import SimpleNamespace as _NS
    from unittest.mock import AsyncMock as _AM
    from cogs import automod as _am

    cog = _am.AutoMod.__new__(_am.AutoMod)
    cog.bot = _NS(db=_NS(get_guild_config=_AM(return_value=None)))
    etapes = iter([2, 3])  # 2 = avertissement (palier de départ 1 depuis le 07/11)
    cog._next_spam_stage = _AM(side_effect=lambda *_: next(etapes))
    monkeypatch.setattr(_am.moderation_service, "warn", _AM(return_value=_NS(executed=True)))
    guild = _NS(id=1, me=_NS(id=9), name="Serveur", owner_id=2)
    membre = _NS(id=5)

    premier = _asyncio.run(cog._spam_progressive_action(guild, membre, "spam"))
    juste_apres = _asyncio.run(cog._spam_progressive_action(guild, membre, "spam"))
    assert premier[0] == "warn"
    assert juste_apres[0] == "warning_ping" and "dernier avertissement" in juste_apres[3]
    assert cog._next_spam_stage.await_count == 1   # pas de nouveau palier pendant la grâce
