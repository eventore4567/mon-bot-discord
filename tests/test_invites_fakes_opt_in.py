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
    """11/11/2026 : un compte jugé trop récent est signalé, plus retiré du crédit.

    InviteLogger affichait 18 là où SentriX affichait 17, sur les mêmes arrivées :
    un soupçon suffisait à retirer une invitation réellement faite. Le serveur qui
    veut l'ancien calcul le demande explicitement (``exclude_fakes``).
    """
    result = await stats([row(age=4, flags=1)], options=settings())
    assert (result["real"], result["fake"], result["credited"]) == (0, 1, 1)

    strict = await stats([row(age=4, flags=1)], options=settings(exclude_fakes=1))
    assert (strict["real"], strict["fake"], strict["credited"]) == (0, 1, 0)


@pytest.mark.asyncio
async def test_auto_invite_est_fake():
    result = await stats([row(flags=2)], options=settings())
    assert (result["real"], result["fake"]) == (0, 1)


@pytest.mark.asyncio
async def test_avatar_par_defaut_est_un_indice_pas_un_fake():
    result = await stats([row(flags=4)], options=settings(require_avatar=1))
    assert (result["fake"], result["real"], result["credited"]) == (0, 1, 1)


@pytest.mark.asyncio
async def test_retour_compte_une_seule_fois_et_n_est_pas_un_fake():
    """Revenir n'est pas tricher : une seule invitation, comptée une seule fois."""
    result = await stats([row(index=2, member=20, flags=8, joined=9000), row(index=1, member=20, left=4000)], options=settings())
    assert (result["total"], result["fake"], result["left"], result["credited"]) == (1, 0, 0, 1)


@pytest.mark.asyncio
async def test_depart_rapide_est_seulement_reparti():
    result = await stats([row(flags=0, left=1300, quick=3600)], options=settings())
    assert (result["left"], result["fake"], result["credited"]) == (1, 0, 0)


@pytest.mark.asyncio
async def test_depart_normal_n_est_pas_fake():
    result = await stats([row(flags=0, left=8200, quick=3600)], options=settings())
    assert (result["left"], result["fake"], result["credited"]) == (1, 0, 0)


@pytest.mark.asyncio
async def test_role_non_obtenu_est_en_attente_pas_fake():
    pending = await stats([row(flags=0, role=999, verified=False)], options=settings())
    done = await stats([row(flags=0, role=999, verified=True)], options=settings())
    assert (pending["pending"], pending["fake"], pending["credited"]) == (1, 0, 0)
    assert (done["pending"], done["fake"], done["credited"]) == (0, 0, 1)


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
async def test_plusieurs_signaux_restent_signales_sans_retirer_le_credit():
    result = await stats([row(flags=1 | 2 | 4 | 8)], options=settings(), bonus=2)
    assert (result["total"], result["fake"], result["real"], result["credited"]) == (1, 1, 0, 3)

    # Le serveur qui a demandé d'écarter les suspectes ne garde que le bonus.
    strict = await stats([row(flags=1 | 2 | 4 | 8)], options=settings(exclude_fakes=1), bonus=2)
    assert strict["credited"] == 2


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


def test_la_fiche_invites_reste_simple_en_slash_et_prefix():
    import inspect

    assert "i" in Invites.invites_cmd.aliases
    assert not hasattr(Invites, "fakeconfig")
    assert not hasattr(Invites, "fakeinfo")
    source = inspect.getsource(Invites.invites_cmd.callback)
    # 11/11/2026 : les quatre chiffres isolés ne disaient pas d'où venait le total
    # crédité. Ils tiennent dans une ligne de calcul sous le chiffre, qui part
    # du total des arrivées et retranche ce qui n'est pas crédité.
    assert "detail_du_calcul(b)" in source
    assert "embed.add_field" not in source, "la fiche n'a plus de champs séparés"
    assert "panels.Bouton" not in source
    assert "boutons=" not in source


@pytest.mark.asyncio
async def test_detection_renforcee_active_par_defaut_sans_nouveau_bouton():
    db = Database(":memory:")
    db.fetchone = AsyncMock(return_value=None)
    settings = await db.get_invite_detection_settings(42)
    assert settings["enabled"] is True
    assert settings["min_account_age_days"] == 7


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


@pytest.mark.asyncio
async def test_sqlite_persistant_role_validation_et_depart(tmp_path, monkeypatch):
    monkeypatch.setenv("SENTRIX_DB_BACKEND", "sqlite")
    db = Database(str(tmp_path / "invite_tracking.db"))
    await db.connect()
    try:
        await db.set_invite_detection_enabled(55, True)
        await db.set_invite_detection_rule(55, "required_role_id", 88)
        cfg = await db.get_invite_detection_settings(55)
        assert cfg["enabled"] is True and cfg["required_role_id"] == 88

        await db.record_invite_join(
            55, 101, 202, "abc", 20,
            fake_flags=0, required_role_id=88, role_confirmed=False,
        )
        await db.record_invite_join(55, 101, 202, "abc", 20, fake_flags=0)
        before = await db.get_invite_breakdown(55, 202)
        assert (before["total"], before["pending"], before["fake"], before["credited"]) == (1, 1, 0, 0)

        await db.mark_invite_role_confirmed(55, 101, 88)
        after = await db.get_invite_breakdown(55, 202)
        assert (after["real"], after["fake"], after["credited"]) == (1, 0, 1)

        await db.mark_invite_left(55, 101)
        left = await db.get_invite_breakdown(55, 202)
        assert (left["left"], left["credited"]) == (1, 0)
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_sans_role_obligatoire_compte_age_7_jours():
    result = await stats([row(age=7, flags=0, role=0)], options=settings())
    assert (result["real"], result["fake"], result["pending"], result["credited"]) == (1, 0, 0, 1)


@pytest.mark.asyncio
async def test_six_jours_sont_fakes_et_sept_jours_valides():
    bot = Mock()
    bot.db.get_invite_detection_settings = AsyncMock(return_value={
        "enabled": True, "min_account_age_days": 7, "block_self_invite": True,
        "require_avatar": False, "block_rejoins": False, "required_role_id": 0,
        "credit_delay_hours": 0, "quick_leave_seconds": 3600,
    })
    bot.db.record_invite_join = AsyncMock()
    cog = Invites(bot)
    cog.find_used_invite = AsyncMock(return_value=None)
    cog._journaliser_arrivee = AsyncMock()

    async def simulate(days):
        member = Mock(spec=discord.Member)
        member.bot = False
        member.id = 42 + days
        member.guild = Mock(id=1)
        member.created_at = discord.utils.utcnow() - timedelta(days=days, minutes=2)
        member.avatar = None
        member.roles = []
        await cog.on_member_join(member)
        return bot.db.record_invite_join.await_args.kwargs["fake_flags"]

    assert await simulate(6) & 1 == 1
    assert await simulate(7) & 1 == 0


@pytest.mark.asyncio
async def test_regles_default_n_necessitent_pas_role_ni_avatar():
    db = Database(":memory:")
    db.fetchone = AsyncMock(return_value=None)
    cfg = await db.get_invite_detection_settings(44)
    assert cfg["enabled"] is True
    assert cfg["min_account_age_days"] == 7
    assert cfg["required_role_id"] == 0
    assert cfg["require_avatar"] is False


@pytest.mark.asyncio
async def test_compte_recent_parti_ne_double_compte_pas_fake():
    """Un départ doit apparaître uniquement dans Reparties, jamais aussi dans Fakes."""
    result = await stats([row(age=2, flags=1, left=2000)], options=settings())
    assert (result["total"], result["real"], result["left"], result["fake"], result["credited"]) == (1, 0, 1, 0, 0)


@pytest.mark.asyncio
async def test_ancien_fake_parti_ne_double_compte_pas_historique():
    """Les invitations enregistrées avant le nouveau suivi ne doivent pas doubler."""
    result = await stats([row(age=1, flags=None, left=2000)], options=None)
    assert (result["total"], result["left"], result["fake"]) == (1, 1, 0)


@pytest.mark.asyncio
async def test_huit_arrivees_trois_departs_cinq_valides_zero_fake():
    """Régression du cas réel : 8 joins, 3 leaves dont 1 ancien fake, 5 crédits."""
    invites = [
        row(index=i, member=100 + i, age=30, joined=1000 + i * 10,
            left=(1500 + i) if i <= 3 else None,
            flags=1 if i == 1 else 0)
        for i in range(1, 9)
    ]
    result = await stats(invites, options=settings())
    assert result == {
        "total": 8, "left": 3, "fake": 0, "real": 5,
        "pending": 0, "rejoined": 0, "bonus": 0, "fakes_deduits": False, "credited": 5,
    }
    # Les compteurs couvrent exactement le total : aucune arrivée ne disparaît.
    assert sum(result[c] for c in ("left", "fake", "pending", "rejoined", "real")) == result["total"]
