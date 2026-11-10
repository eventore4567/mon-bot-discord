"""Anti-fake : tests unitaires déterministes, sans accès à Discord ou à la production."""
from __future__ import annotations

import os
import time
from datetime import timedelta
from unittest.mock import AsyncMock, Mock

import pytest
import discord

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from database.db import Database
from cogs.invites import Invites


def row(index=1, member=20, age=60, *, joined=1000, left=None, flags=None,
        role=0, verified=False, pending=0, quick=0):
    return {
        "id": index, "member_id": member, "joined_at": joined, "left_at": left,
        "account_age_days": age, "fake_flags": flags, "required_role_id": role,
        "role_confirmed": int(verified), "pending_until": pending,
        "quick_leave_seconds": quick,
    }


def settings(**overrides):
    return {
        "enabled": 1, "min_account_age_days": 7, "block_self_invite": 1,
        "require_avatar": 0, "block_rejoins": 1, "required_role_id": 0,
        "credit_delay_hours": 0, "quick_leave_seconds": 3600,
        **overrides,
    }


async def stats(rows, *, options=None, bonus=0):
    db = Database(":memory:")
    db.fetchall = AsyncMock(return_value=rows)
    db.fetchone = AsyncMock(side_effect=[options, {"s": bonus}])
    return await db.get_invite_breakdown(1, 10)


@pytest.mark.asyncio
async def test_ancien_historique_age_3_jours_avant_activation():
    result = await stats([row(age=4)], options=None)
    assert (result["real"], result["fake"], result["credited"]) == (1, 0, 1)


@pytest.mark.asyncio
async def test_age_7_jours_classe_sur_l_arrivee():
    result = await stats([row(age=4, flags=1)], options=settings())
    assert (result["real"], result["fake"], result["credited"]) == (0, 1, 0)


@pytest.mark.asyncio
async def test_auto_invite_est_fake():
    result = await stats([row(flags=2)], options=settings())
    assert (result["real"], result["fake"]) == (0, 1)


@pytest.mark.asyncio
async def test_avatar_manquant_est_fake_si_regle_active_a_l_arrivee():
    result = await stats([row(flags=4)], options=settings(require_avatar=0))
    assert result["fake"] == 1  # critère figé au join, pas recalculé au changement


@pytest.mark.asyncio
async def test_retour_est_fake_sans_perdre_historique():
    result = await stats([row(index=2, member=20, flags=8, joined=9000), row(index=1, member=20, left=4000)], options=settings())
    assert (result["total"], result["fake"], result["left"], result["credited"]) == (1, 1, 0, 0)


@pytest.mark.asyncio
async def test_depart_rapide_est_fake_et_depart_mais_pas_double_soustrait():
    result = await stats([row(flags=0, left=1300, quick=3600)], options=settings())
    assert (result["left"], result["fake"], result["credited"]) == (1, 1, 0)


@pytest.mark.asyncio
async def test_depart_normal_n_est_pas_fake():
    result = await stats([row(flags=0, left=8200, quick=3600)], options=settings())
    assert (result["left"], result["fake"], result["credited"]) == (1, 0, 0)


@pytest.mark.asyncio
async def test_role_non_obtenu_bloque_credit_puis_confirme():
    pending = await stats([row(flags=0, role=999, verified=False)], options=settings())
    done = await stats([row(flags=0, role=999, verified=True)], options=settings())
    assert (pending["fake"], pending["credited"]) == (1, 0)
    assert (done["fake"], done["credited"]) == (0, 1)


@pytest.mark.asyncio
async def test_validation_differee_pas_confondue_avec_fake():
    later = int(time.time()) + 86400
    result = await stats([row(flags=0, pending=later)], options=settings())
    assert (result["pending"], result["fake"], result["real"], result["credited"]) == (1, 0, 0, 0)


@pytest.mark.asyncio
async def test_validation_apres_delai_automatique():
    past = int(time.time()) - 10
    result = await stats([row(flags=0, pending=past)], options=settings())
    assert (result["pending"], result["real"], result["credited"]) == (0, 1, 1)


@pytest.mark.asyncio
async def test_plusieurs_signaux_ne_creditent_pas():
    result = await stats([row(flags=1 | 2 | 4 | 8)], options=settings(), bonus=2)
    assert (result["total"], result["fake"], result["real"], result["credited"]) == (1, 1, 0, 2)


@pytest.mark.asyncio
async def test_historique_sans_age_reste_neutre():
    result = await stats([row(age=None, flags=None)], options=None)
    assert result["real"] == 1 and result["fake"] == 0


@pytest.mark.asyncio
async def test_un_membre_compte_une_seule_fois():
    result = await stats([row(index=2, joined=9000), row(index=1, joined=1000, left=3000)], options=settings())
    assert (result["total"], result["left"], result["real"], result["credited"]) == (1, 0, 1, 1)


@pytest.mark.asyncio
async def test_activation_par_serveur_enregistree():
    db = Database(":memory:")
    db.execute = AsyncMock()
    await db.set_invite_detection_enabled(42, True)
    sql, values = db.execute.await_args.args
    assert "ON CONFLICT(guild_id)" in sql and values == (42, 1)


@pytest.mark.asyncio
async def test_parametres_sql_non_injectables():
    db = Database(":memory:")
    db.execute = AsyncMock()
    with pytest.raises(ValueError):
        await db.set_invite_detection_rule(1, "required_role_id;DROP TABLE member_invites", 1)
    db.execute.assert_not_awaited()


def test_les_commandes_slash_et_prefix_sont_hybrides():
    assert "i" in Invites.invites_cmd.aliases
    assert "fc" in Invites.fakeconfig.aliases
    assert "get_invite_detection_settings" in Invites.invites_cmd.callback.__code__.co_names


@pytest.mark.asyncio
async def test_nouvelle_arrivee_enregistre_age_auto_avatar_retour():
    bot = Mock()
    bot.db.get_invite_detection_settings = AsyncMock(return_value={
        "enabled": True, "min_account_age_days": 7, "block_self_invite": True,
        "require_avatar": True, "block_rejoins": True, "required_role_id": 0,
        "credit_delay_hours": 24, "quick_leave_seconds": 3600,
    })
    bot.db.has_invite_join_history = AsyncMock(return_value=True)
    bot.db.record_invite_join = AsyncMock()
    cog = Invites(bot)
    invite = Mock()
    invite.inviter.id = 20
    invite.code = "abc"
    cog.find_used_invite = AsyncMock(return_value=invite)
    cog._journaliser_arrivee = AsyncMock()
    member = Mock(spec=discord.Member)
    member.bot = False
    member.id = 20
    member.created_at = discord.utils.utcnow() - timedelta(days=2)
    member.avatar = None
    member.roles = []
    member.guild = Mock(id=42)
    await cog.on_member_join(member)
    bot.db.record_invite_join.assert_awaited_once()
    kwargs = bot.db.record_invite_join.await_args.kwargs
    assert kwargs["fake_flags"] == 1 | 2 | 4 | 8
    assert kwargs["quick_leave_seconds"] == 3600
    assert kwargs["pending_until"] > int(time.time())
    cog._journaliser_arrivee.assert_awaited_once()


@pytest.mark.asyncio
async def test_role_recu_confirme_le_membre_sans_retroactivite():
    bot = Mock()
    bot.db.get_invited_by = AsyncMock(return_value={
        "left_at": None, "required_role_id": 77, "role_confirmed": 0,
    })
    bot.db.mark_invite_role_confirmed = AsyncMock()
    cog = Invites(bot)
    before = Mock(spec=discord.Member)
    before.bot = False
    before.roles = []
    after = Mock(spec=discord.Member)
    after.bot = False
    after.id = 20
    after.guild = Mock(id=42)
    role = Mock()
    role.id = 77
    after.roles = [role]
    await cog.on_member_update(before, after)
    bot.db.mark_invite_role_confirmed.assert_awaited_once_with(42, 20, 77)
