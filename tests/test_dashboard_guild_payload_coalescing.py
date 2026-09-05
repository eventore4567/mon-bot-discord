"""/api/guilds/<id> enchaîne 10+ requêtes SQL séquentielles (settings, automod,
ai_settings, 5 compteurs de métriques, notifications sociales) sur l'unique
connexion aiosqlite partagée par tout le bot (database/db.py, Database._conn).

Les journaux Railway montrent plusieurs onglets/comptes redemandant le même
serveur à quelques millisecondes d'intervalle : chaque appel relançait sa
propre série de requêtes, la file d'attente sur cette connexion unique
grossissait plus vite qu'elle ne se vidait, et la latence explosait (jusqu'à
plusieurs secondes, puis plus de 10 secondes, en production).

Important : web/dashboard.py importe web.dashboard_pages_v3 à la fin de son
propre fichier, qui appelle patch_dashboard_runtime() au chargement du module
— ce qui remplace immédiatement dashboard.handle_guild par la version
« fail-soft » de dashboard_oxyde_hotfix.py. C'est donc CETTE version qui
tourne réellement en production, jamais celle définie dans dashboard.py. Ces
tests appellent dashboard.handle_guild tel qu'il est réellement câblé après
import, et vérifient le nombre d'appels SQL plutôt qu'une fonction interne
précise, pour rester valables quelle que soit l'implémentation active.
"""
from __future__ import annotations

import asyncio
import json
import os
from unittest.mock import AsyncMock, Mock, patch

os.environ.setdefault("DISCORD_TOKEN", "x")

from web import dashboard  # noqa: E402


def _db() -> Mock:
    db = Mock()
    db.get_guild_config = AsyncMock(return_value=None)
    db.get_automod = AsyncMock(return_value=None)
    db.execute = AsyncMock(return_value=None)
    db.fetchone = AsyncMock(return_value=None)
    db.fetchall = AsyncMock(return_value=[])
    return db


def _guild(guild_id: int) -> Mock:
    guild = Mock()
    guild.id = guild_id
    guild.name = f"Serveur {guild_id}"
    guild.icon = None
    guild.member_count = 10
    guild.roles = []
    guild.channels = []
    return guild


def _requete(bot, guild_id: int) -> Mock:
    requete = Mock()
    requete.app = {"bot": bot}
    requete.match_info = {"guild_id": str(guild_id)}
    return requete


async def _corps(reponse) -> dict:
    return json.loads(reponse.body.decode())


def _reinitialiser() -> None:
    dashboard._guild_payload_inflight.clear()


async def _les_appels_concurrents_ne_font_qu_un_seul_calcul():
    _reinitialiser()
    guild = _guild(1)
    db = _db()

    async def manageable(_request, _guild_id):
        return {"user": {"id": "1"}}, guild, None

    with patch.object(dashboard, "_manageable_guild", side_effect=manageable):
        bot = Mock()
        bot.db = db
        requetes = [_requete(bot, 1) for _ in range(12)]
        reponses = await asyncio.gather(*(dashboard.handle_guild(r) for r in requetes))
        assert db.get_guild_config.call_count == 1, (
            f"12 requêtes concurrentes pour le même serveur doivent tenir sur un seul "
            f"accès SQL, pas {db.get_guild_config.call_count}"
        )
        assert db.fetchall.call_count == 1
        for reponse in reponses:
            corps = await _corps(reponse)
            assert corps["guild"]["id"] == "1"


def test_les_appels_concurrents_pour_le_meme_serveur_ne_relancent_pas_le_sql():
    asyncio.run(_les_appels_concurrents_ne_font_qu_un_seul_calcul())


async def _deux_serveurs_differents_restent_independants():
    _reinitialiser()
    db = _db()
    guilds = {1: _guild(1), 2: _guild(2)}

    async def manageable(request, _guild_id):
        guild_id = int(request.match_info["guild_id"])
        return {"user": {"id": "1"}}, guilds[guild_id], None

    with patch.object(dashboard, "_manageable_guild", side_effect=manageable):
        bot = Mock()
        bot.db = db
        requetes = [_requete(bot, 1), _requete(bot, 2), _requete(bot, 1), _requete(bot, 2)]
        reponses = await asyncio.gather(*(dashboard.handle_guild(r) for r in requetes))
        assert db.get_guild_config.call_count == 2, (
            f"deux serveurs différents doivent chacun déclencher leur propre accès SQL, "
            f"pas se mélanger ({db.get_guild_config.call_count} appels)"
        )
        corps = [await _corps(r) for r in reponses]
        ids = sorted(c["guild"]["id"] for c in corps)
        assert ids == ["1", "1", "2", "2"]


def test_deux_serveurs_differents_ne_sont_pas_fusionnes():
    asyncio.run(_deux_serveurs_differents_restent_independants())


async def _un_appel_ulterieur_recalcule_bien():
    """La coalescence ne doit pas figer les données après la fin du calcul."""
    _reinitialiser()
    guild = _guild(1)
    db = _db()

    async def manageable(_request, _guild_id):
        return {"user": {"id": "1"}}, guild, None

    with patch.object(dashboard, "_manageable_guild", side_effect=manageable):
        bot = Mock()
        bot.db = db
        await dashboard.handle_guild(_requete(bot, 1))
        await dashboard.handle_guild(_requete(bot, 1))
        assert db.get_guild_config.call_count == 2, (
            "un second appel, une fois le premier terminé, doit relire les données "
            "à jour plutôt que de rester bloqué sur l'ancien résultat"
        )
        assert dashboard._guild_payload_inflight == {}, (
            "l'entrée en vol doit être nettoyée une fois le calcul terminé"
        )


def test_un_appel_ulterieur_recalcule_les_donnees():
    asyncio.run(_un_appel_ulterieur_recalcule_bien())


if __name__ == "__main__":
    import unittest

    unittest.main()
