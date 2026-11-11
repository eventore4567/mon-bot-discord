"""11/11/2026 : les arrivées pendant que SentriX est éteint ne doivent plus disparaître.

Question de l'utilisateur, en comparant avec InviteLogger : « comment ils font quand leur
bot est off ? ». Réponse : le compteur d'utilisations d'un lien appartient à Discord, il
monte même bot éteint. SentriX gardait ce compteur en mémoire vive seulement, et le
redémarrage le réécrivait sur les valeurs du moment — l'écart accumulé pendant la coupure
était avalé dans la nouvelle référence, donc perdu définitivement.
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from cogs.invites import Invites  # noqa: E402
from database.db import Database  # noqa: E402


def _invite(code: str, uses: int, inviter_id: int | None = 7):
    return SimpleNamespace(
        code=code, uses=uses,
        inviter=SimpleNamespace(id=inviter_id) if inviter_id else None,
    )


def _membre(member_id: int, *, arrive_il_y_a: int, compte_cree_il_y_a: int = 400):
    maintenant = datetime.now(timezone.utc)
    return SimpleNamespace(
        id=member_id, bot=False,
        joined_at=maintenant - timedelta(seconds=arrive_il_y_a),
        created_at=maintenant - timedelta(days=compte_cree_il_y_a),
    )


async def _bot_avec_base(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    await db.connect()
    return SimpleNamespace(db=db)


def _guild(membres):
    return SimpleNamespace(id=1, members=membres, me=None)


async def _reference_posee_il_y_a(db, secondes: int):
    """La référence date du démarrage PRÉCÉDENT : les arrivées viennent après elle."""
    await db.execute(
        "UPDATE invite_code_meta SET last_seen_at=? WHERE guild_id=1",
        (int(time.time()) - secondes,),
    )


@pytest.mark.asyncio
async def test_une_arrivee_pendant_la_coupure_est_retrouvee(tmp_path):
    bot = await _bot_avec_base(tmp_path)
    cog = Invites.__new__(Invites)
    cog.bot = bot
    cog.invite_cache = {}

    # Avant la coupure : le lien a servi 10 fois, SentriX l'enregistre.
    await bot.db.save_invite_code_counters(1, {"abc": 10})
    await _reference_posee_il_y_a(bot.db, 600)

    # Pendant la coupure, deux personnes arrivent : l'une est encore là, l'autre repartie.
    reste = _membre(99, arrive_il_y_a=300)
    guild = _guild([reste])

    retrouvees = await cog._rattraper_les_absences(guild, [_invite("abc", 12)])
    assert retrouvees == 2

    b = await bot.db.get_invite_breakdown(1, 7)
    assert b["total"] == 2
    # Celle qui est restée crédite ; celle qui est repartie ne crédite rien.
    assert (b["real"], b["left"], b["credited"]) == (1, 1, 1)
    # Et le membre retrouvé est nommément attribué, pas une ligne anonyme.
    assert (await bot.db.get_invited_by(1, 99))["inviter_id"] == 7
    await bot.db.close()


@pytest.mark.asyncio
async def test_rien_a_rattraper_au_tout_premier_demarrage(tmp_path):
    """Sans référence enregistrée, l'écart n'existe pas : on n'invente aucun passé."""
    bot = await _bot_avec_base(tmp_path)
    cog = Invites.__new__(Invites)
    cog.bot = bot
    cog.invite_cache = {}

    assert await cog._rattraper_les_absences(_guild([]), [_invite("abc", 250)]) == 0
    assert (await bot.db.get_invite_breakdown(1, 7))["total"] == 0
    await bot.db.close()


@pytest.mark.asyncio
async def test_une_reference_trop_vieille_ne_rattrape_rien(tmp_path):
    """Bot retiré puis réinvité, base restaurée : l'écart ne veut plus rien dire."""
    bot = await _bot_avec_base(tmp_path)
    cog = Invites.__new__(Invites)
    cog.bot = bot
    cog.invite_cache = {}

    await bot.db.save_invite_code_counters(1, {"abc": 10})
    await bot.db.execute(
        "UPDATE invite_code_meta SET last_seen_at=? WHERE guild_id=1",
        (int(time.time()) - 365 * 86400,),
    )
    assert await cog._rattraper_les_absences(_guild([]), [_invite("abc", 40)]) == 0
    await bot.db.close()


@pytest.mark.asyncio
async def test_un_lien_cree_pendant_la_coupure_n_est_pas_attribue(tmp_path):
    """Sans compteur de référence, on ne sait pas si ces utilisations sont nouvelles."""
    bot = await _bot_avec_base(tmp_path)
    cog = Invites.__new__(Invites)
    cog.bot = bot
    cog.invite_cache = {}

    await bot.db.save_invite_code_counters(1, {"abc": 10})
    await _reference_posee_il_y_a(bot.db, 600)
    retrouvees = await cog._rattraper_les_absences(
        _guild([]), [_invite("abc", 10), _invite("nouveau", 5)]
    )
    assert retrouvees == 0
    await bot.db.close()


@pytest.mark.asyncio
async def test_un_membre_deja_connu_n_est_pas_compte_deux_fois(tmp_path):
    bot = await _bot_avec_base(tmp_path)
    cog = Invites.__new__(Invites)
    cog.bot = bot
    cog.invite_cache = {}

    await bot.db.save_invite_code_counters(1, {"abc": 10})
    await _reference_posee_il_y_a(bot.db, 600)
    # SentriX a bien vu arriver ce membre avant de s'éteindre.
    await bot.db.record_invite_join(1, 99, 7, "abc", 400, fake_flags=0)

    retrouvees = await cog._rattraper_les_absences(
        _guild([_membre(99, arrive_il_y_a=300)]), [_invite("abc", 11)]
    )
    # L'écart d'une utilisation reste, mais il ne peut pas être ce membre-là :
    # il est enregistré comme une arrivée repartie, pas comme un doublon de sa ligne.
    b = await bot.db.get_invite_breakdown(1, 7)
    assert retrouvees == 1
    assert (b["total"], b["real"], b["left"], b["credited"]) == (2, 1, 1, 1)
    await bot.db.close()


@pytest.mark.asyncio
async def test_le_compteur_est_bien_memorise_pour_la_prochaine_fois(tmp_path):
    bot = await _bot_avec_base(tmp_path)
    cog = Invites.__new__(Invites)
    cog.bot = bot
    cog.invite_cache = {}

    guild = _guild([])
    guild.invites = AsyncMock(return_value=[_invite("abc", 12)])
    await cog.cache_guild_invites(guild)

    assert cog.invite_cache[1] == {"abc": 12}
    assert (await bot.db.get_invite_code_counters(1))["abc"]["uses"] == 12
    await bot.db.close()
