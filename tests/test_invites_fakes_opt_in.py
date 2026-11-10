"""Régression SentriX : vraies invitations, fakes, départs et opt-in via /invites ou +i."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from database.db import Database
from cogs.invites import Invites


def _join(row_id: int, member_id: int, age: int | None, *, joined: int = 1000, left: int | None = None):
    return {
        "id": row_id,
        "member_id": member_id,
        "joined_at": joined,
        "left_at": left,
        "account_age_days": age,
    }


async def _stats(rows, *, enhanced=False, bonus=0):
    db = Database(":memory:")
    settings = {"enabled": 1, "min_account_age_days": 7} if enhanced else None
    db.fetchall = AsyncMock(return_value=rows)
    db.fetchone = AsyncMock(side_effect=[settings, {"s": bonus}])
    return await db.get_invite_breakdown(1, 10)


@pytest.mark.asyncio
async def test_seuil_legacy_reste_inchange_avant_activation():
    stats = await _stats([_join(1, 20, age=4)], enhanced=False)
    assert (stats["real"], stats["fake"], stats["credited"]) == (1, 0, 1)


@pytest.mark.asyncio
async def test_un_compte_de_quatre_jours_devient_fake_apres_activation():
    stats = await _stats([_join(1, 20, age=4)], enhanced=True)
    assert (stats["real"], stats["fake"], stats["credited"]) == (0, 1, 0)


@pytest.mark.asyncio
async def test_depart_rapide_est_fake_et_leave_mais_ne_credite_rien():
    stats = await _stats([_join(1, 20, age=60, left=1300)], enhanced=True)
    assert (stats["left"], stats["fake"], stats["credited"]) == (1, 1, 0)


@pytest.mark.asyncio
async def test_depart_normal_n_est_pas_un_fake():
    stats = await _stats([_join(1, 20, age=60, left=8200)], enhanced=True)
    assert (stats["left"], stats["fake"], stats["credited"]) == (1, 0, 0)


@pytest.mark.asyncio
async def test_deux_arrivees_du_meme_membre_ne_doublent_pas_le_credit():
    stats = await _stats([
        _join(2, 20, age=60, joined=9000),
        _join(1, 20, age=60, joined=1000, left=3000),
    ], enhanced=True)
    assert (stats["total"], stats["left"], stats["real"], stats["credited"]) == (1, 0, 1, 1)


@pytest.mark.asyncio
async def test_un_compte_sans_age_n_est_pas_qualifie_fake_sans_preuve():
    stats = await _stats([_join(1, 20, age=None)], enhanced=True)
    assert stats["real"] == 1 and stats["fake"] == 0


@pytest.mark.asyncio
async def test_bonus_explicite_s_ajoute_mais_fake_ne_rapporte_rien():
    stats = await _stats([_join(1, 20, age=2)], enhanced=True, bonus=2)
    assert (stats["real"], stats["fake"], stats["credited"]) == (0, 1, 2)


@pytest.mark.asyncio
async def test_activation_enregistree_par_serveur():
    db = Database(":memory:")
    db.execute = AsyncMock()
    await db.set_invite_detection_enabled(42, True)
    sql, values = db.execute.await_args.args
    assert "ON CONFLICT(guild_id)" in sql
    assert values == (42, 1)


def test_le_meme_hybrid_command_sert_slash_et_prefix():
    assert "i" in Invites.invites_cmd.aliases
    callback = Invites.invites_cmd.callback
    assert "get_invite_detection_settings" in callback.__code__.co_names
    assert "set_invite_detection_enabled" in callback.__code__.co_names
