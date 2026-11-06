"""07/11/2026 : le mode raid détecte l'afflux, expulse la vague en quelques secondes,
reste actif pour les arrivants suivants, durcit l'anti-nuke et fait son rapport."""
from __future__ import annotations

import asyncio
import os
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import discord  # noqa: E402
import pytest  # noqa: E402

from cogs import raid_mode as rm  # noqa: E402

GUILD = SimpleNamespace(id=42, owner_id=1, name="Serveur test", owner=None)


def _membre(uid, *, jours=1, avatar=None, bot=False):
    return SimpleNamespace(
        id=uid, guild=GUILD, bot=bot, avatar=avatar, kick=AsyncMock(),
        created_at=discord.utils.utcnow() - timedelta(days=jours),
        guild_permissions=discord.Permissions.none(), roles=[],
        __str__=lambda self: f"m{uid}",
    )


def _automod():
    return SimpleNamespace(_bot_is_allowlisted=AsyncMock(return_value=False), log_action=AsyncMock())


@pytest.fixture(autouse=True)
def _propre(monkeypatch):
    rm.oublier(GUILD.id)
    monkeypatch.setattr("cogs.automod.can_bypass_message_filters", lambda m: False)
    yield
    rm.oublier(GUILD.id)


def test_les_comptes_suspects_sont_reconnus():
    assert rm.motif_suspect(_membre(2, jours=3, avatar="a")).startswith("compte créé")
    assert rm.motif_suspect(_membre(3, jours=900, avatar=None)) == "avatar par défaut"
    assert rm.motif_suspect(_membre(4, jours=900, avatar="a", bot=True)) == "bot ajouté pendant le raid"
    assert rm.motif_suspect(_membre(5, jours=900, avatar="a")) is None   # ancien avec avatar : épargné


def test_un_raid_vide_la_vague_et_epargne_les_comptes_anciens():
    automod = _automod()
    raiders = [_membre(100 + i) for i in range(12)]
    habitue = _membre(999, jours=900, avatar="a")
    proprietaire = _membre(1)

    async def scenario():
        for m in [*raiders, habitue, proprietaire]:
            rm.noter_arrivee(m)
        etat = await rm.declencher(automod, GUILD, mesures=["niveau de vérification relevé"])
        etat.rapport_tache.cancel()
        return etat

    etat = asyncio.run(scenario())
    assert all(m.kick.await_count == 1 for m in raiders)
    habitue.kick.assert_not_awaited()
    proprietaire.kick.assert_not_awaited()
    assert len(etat.expulses) == 12 and etat.epargnes == 2
    assert rm.actif(GUILD.id)


def test_pendant_le_raid_chaque_arrivant_suspect_est_expulse_aussitot():
    automod = _automod()

    async def scenario():
        rm.noter_arrivee(_membre(200))
        etat = await rm.declencher(automod, GUILD)
        tardif, bot_autorise = _membre(201), _membre(202, bot=True)
        automod._bot_is_allowlisted = AsyncMock(side_effect=lambda g, uid: uid == 202)
        expulse = await rm.sur_arrivee(automod, tardif)
        garde = await rm.sur_arrivee(automod, bot_autorise)
        etat.rapport_tache.cancel()
        return expulse, garde, tardif, bot_autorise

    expulse, garde, tardif, bot_autorise = asyncio.run(scenario())
    assert expulse and tardif.kick.await_count == 1
    assert not garde and bot_autorise.kick.await_count == 0


def test_hors_raid_rien_n_est_expulse():
    membre = _membre(300)
    assert asyncio.run(rm.sur_arrivee(_automod(), membre)) is False
    membre.kick.assert_not_awaited()


def test_l_anti_nuke_se_durcit_pendant_un_raid():
    assert rm.seuil_nuke(GUILD.id, 3) == 3

    async def scenario():
        etat = await rm.declencher(_automod(), GUILD)
        etat.rapport_tache.cancel()

    asyncio.run(scenario())
    assert rm.seuil_nuke(GUILD.id, 3) == rm.NUKE_SEUIL_EN_RAID == 2


def test_le_rapport_dit_tout(monkeypatch):
    automod = _automod()
    echoue = _membre(401)
    echoue.kick = AsyncMock(side_effect=discord.HTTPException(SimpleNamespace(status=403, reason="x"), "non"))

    async def scenario():
        for m in [_membre(400), echoue]:
            rm.noter_arrivee(m)
        etat = await rm.declencher(automod, GUILD, mesures=["niveau de vérification relevé"])
        etat.rapport_tache.cancel()
        await rm.envoyer_rapport(automod, GUILD, etat)
        return etat

    etat = asyncio.run(scenario())
    champs = rm.champs_rapport(etat)
    assert champs["Expulsés"] == "1" and "Échecs" in champs
    assert "niveau de vérification relevé" in champs["Mesures"] and "anti-nuke durci" in champs["Mesures"]
    assert "<@400>" in champs["Comptes expulsés"]
    automod.log_action.assert_awaited()
    assert automod.log_action.await_args.kwargs["file"].filename == "rapport-raid.txt"


def test_l_automod_branche_le_mode_raid():
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "cogs" / "automod.py").read_text(encoding="utf-8")
    assert "raid_mode.noter_arrivee(member)" in source
    assert "await raid_mode.sur_arrivee(self, member)" in source
    assert "await raid_mode.declencher(self, member.guild" in source
    assert "raid_mode.seuil_nuke(" in source
