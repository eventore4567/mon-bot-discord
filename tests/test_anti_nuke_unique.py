"""Anti-nuke : une seule implémentation de punish_nuker, et sa protection s'exécute.

22/11/2026. Observé sur le bot booté, la chaîne réelle était :

    security_v2 (journal) → rollback → v55 (verrou, ban par identifiant,
    restauration) → AutoMod.punish_nuker   ← l'ORIGINAL

La protection d'owner_sanction_immunity (propriétaire du bot, liste blanche
revérifiée, refus de sanctionner si elle est illisible) enveloppait la CLASSE
après que les couches d'instance avaient capturé la méthode : elle ne
s'exécutait jamais. Ces tests vérifient le comportement de la méthode unique.
"""
from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import discord  # noqa: E402
import pytest  # noqa: E402

from cogs import automod  # noqa: E402

ACTEUR = 4242


def _cog(*, exempte=False, exempte_erreur=False, v55=True, rollback=True, membre=True):
    cog = automod.AutoMod.__new__(automod.AutoMod)
    restaurateur = SimpleNamespace(restore_burst=AsyncMock())
    ancien = SimpleNamespace(rollback_actor=AsyncMock())
    cogs = {}
    if v55:
        cogs["AntiNukeEmergencyV55"] = restaurateur
    if rollback:
        cogs["AntiNukeRollback"] = ancien
    cog.bot = SimpleNamespace(get_cog=cogs.get)
    if exempte_erreur:
        cog.is_antinuke_exempt = AsyncMock(side_effect=RuntimeError("base indisponible"))
    else:
        cog.is_antinuke_exempt = AsyncMock(return_value=exempte)
    cog._sanctionner_nuker = AsyncMock()
    cog.nuke_tracker = MagicMock()
    guild = SimpleNamespace(id=1, get_member=lambda uid: (SimpleNamespace(id=uid) if membre else None))
    return cog, guild, restaurateur, ancien


def _punir(cog, guild, fois=1):
    from cogs import security_v2_runtime

    journal = AsyncMock()
    original = security_v2_runtime._write_incident
    security_v2_runtime._write_incident = journal
    try:
        for _ in range(fois):
            asyncio.run(cog.punish_nuker(guild, ACTEUR, "Suppression massive de salons"))
    finally:
        security_v2_runtime._write_incident = original
    return journal


def test_un_nuke_est_sanctionne_restaure_et_journalise():
    cog, guild, restaurateur, ancien = _cog()
    journal = _punir(cog, guild)
    cog._sanctionner_nuker.assert_awaited_once()
    restaurateur.restore_burst.assert_awaited_once()
    ancien.rollback_actor.assert_not_awaited(), "les deux restaurateurs ensemble recréaient chaque salon deux fois"
    journal.assert_awaited_once()


def test_sans_v55_le_rollback_historique_restaure():
    cog, guild, _restaurateur, ancien = _cog(v55=False)
    _punir(cog, guild)
    ancien.rollback_actor.assert_awaited_once()


def test_une_rafale_ne_sanctionne_qu_une_fois():
    cog, guild, restaurateur, _ = _cog()
    _punir(cog, guild, fois=3)
    cog._sanctionner_nuker.assert_awaited_once()
    restaurateur.restore_burst.assert_awaited_once()


def test_le_proprietaire_du_bot_n_est_jamais_sanctionne(monkeypatch):
    from utils import owner_access

    monkeypatch.setattr(owner_access, "is_bot_owner_id", lambda uid: int(uid or 0) == ACTEUR)
    cog, guild, restaurateur, _ = _cog()
    _punir(cog, guild)
    cog._sanctionner_nuker.assert_not_awaited()
    restaurateur.restore_burst.assert_not_awaited()


def test_un_compte_de_la_liste_blanche_n_est_pas_sanctionne():
    cog, guild, _, _ = _cog(exempte=True)
    _punir(cog, guild)
    cog._sanctionner_nuker.assert_not_awaited()


def test_une_liste_blanche_illisible_bloque_la_sanction():
    """Un ban est irréversible : dans le doute, on ne bannit pas."""
    cog, guild, _, _ = _cog(exempte_erreur=True)
    _punir(cog, guild)
    cog._sanctionner_nuker.assert_not_awaited()


def test_l_incident_est_journalise_meme_si_la_sanction_echoue():
    cog, guild, _, _ = _cog()
    cog._sanctionner_nuker = AsyncMock(side_effect=RuntimeError("Discord indisponible"))
    with pytest.raises(RuntimeError):
        asyncio.run(_avec_journal(cog, guild))


async def _avec_journal(cog, guild):
    from cogs import security_v2_runtime

    journal = AsyncMock()
    original = security_v2_runtime._write_incident
    security_v2_runtime._write_incident = journal
    try:
        await cog.punish_nuker(guild, ACTEUR, "nuke")
    finally:
        security_v2_runtime._write_incident = original
        journal.assert_awaited_once()


def test_un_auteur_deja_parti_est_banni_par_identifiant():
    cog = automod.AutoMod.__new__(automod.AutoMod)
    cog._journal_securite = AsyncMock()
    guild = SimpleNamespace(
        id=1, name="S", get_member=lambda uid: None, ban=AsyncMock(),
        owner=None, owner_id=9, fetch_member=AsyncMock(side_effect=discord.NotFound(MagicMock(status=404), "x")),
    )
    asyncio.run(cog._sanctionner_nuker(guild, ACTEUR, "nuke"))
    guild.ban.assert_awaited_once()
    assert guild.ban.await_args.args[0].id == ACTEUR


def test_plus_aucun_module_ne_remplace_punish_nuker():
    """Un remplacement rendrait de nouveau la protection ou la restauration mortes."""
    import re
    from pathlib import Path

    racine = Path(__file__).resolve().parents[1]
    coupables = []
    for fichier in (racine / "cogs").rglob("*.py"):
        source = fichier.read_text(encoding="utf-8")
        if re.search(r"\.punish_nuker\s*=(?!=)|\"punish_nuker\"\s*,\s*original", source):
            coupables.append(fichier.name)
    assert coupables == []
