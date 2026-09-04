"""/api/public était recalculé à chaque appel, plusieurs fois par seconde.

Les journaux de production montraient des rafales de ``GET /api/public`` et
``GET /api/me``. La page d'accueil sonde /api/public en boucle tant que le bot
n'est pas « online » — et pendant un redéploiement il ne l'est justement pas, donc
la condition d'arrêt n'était jamais atteinte : 90 requêtes par chargement de page,
sur chaque onglet ouvert, chacune recalculant la somme des membres de tous les
serveurs.

/api/public est une route PUBLIQUE, non authentifiée : on ne peut pas compter sur
le client pour se limiter. Le cache court côté serveur protège donc l'API quoi que
fasse le navigateur, tout en gardant un uptime toujours juste.
"""
from __future__ import annotations

import asyncio
import os
import time
from unittest.mock import Mock, patch

os.environ.setdefault("DISCORD_TOKEN", "x")

from web import dashboard  # noqa: E402


def _bot(guilds: int = 3, membres: int = 100) -> Mock:
    bot = Mock()
    bot.user = Mock()
    bot.user.name = "SentriX"
    bot.user.display_avatar.url = "https://exemple.test/a.png"
    bot.is_ready.return_value = True
    bot.latency = 0.05
    bot.guilds = [Mock(member_count=membres) for _ in range(guilds)]
    return bot


def _requete(bot) -> Mock:
    requete = Mock()
    requete.app = {"bot": bot}
    return requete


def _reinitialiser_cache() -> None:
    dashboard._public_cache["payload"] = None
    dashboard._public_cache["expire"] = 0.0


async def _corps(reponse) -> dict:
    import json

    return json.loads(reponse.body.decode())


async def _le_calcul_n_est_fait_qu_une_fois():
    _reinitialiser_cache()
    bot = _bot()
    requete = _requete(bot)

    with patch.object(dashboard, "_public_payload", wraps=dashboard._public_payload) as calcul:
        for _ in range(25):
            await dashboard.handle_public(requete)
        assert calcul.call_count == 1, (
            f"25 appels rapprochés doivent tenir sur un seul calcul, pas {calcul.call_count}"
        )


def test_les_appels_rapproches_ne_recalculent_pas():
    asyncio.run(_le_calcul_n_est_fait_qu_une_fois())


async def _le_contenu_reste_correct():
    _reinitialiser_cache()
    bot = _bot(guilds=4, membres=50)
    donnees = await _corps(await dashboard.handle_public(_requete(bot)))
    assert donnees["guilds"] == 4
    assert donnees["members"] == 200
    assert donnees["online"] is True
    assert donnees["bot_name"] == "SentriX"


def test_le_cache_ne_deforme_pas_les_donnees():
    asyncio.run(_le_contenu_reste_correct())


async def _uptime_toujours_frais():
    _reinitialiser_cache()
    bot = _bot()
    requete = _requete(bot)
    premier = await _corps(await dashboard.handle_public(requete))

    # Sert depuis le cache, mais l'uptime doit avoir avancé.
    with patch.object(dashboard, "START_TIME", dashboard.START_TIME - 60):
        second = await _corps(await dashboard.handle_public(requete))
    assert second["uptime_seconds"] > premier["uptime_seconds"], (
        "l'uptime doit rester juste même servi depuis le cache"
    )


def test_l_uptime_reste_juste_meme_en_cache():
    asyncio.run(_uptime_toujours_frais())


async def _le_cache_expire():
    _reinitialiser_cache()
    bot = _bot()
    requete = _requete(bot)

    with patch.object(dashboard, "_public_payload", wraps=dashboard._public_payload) as calcul:
        await dashboard.handle_public(requete)
        # Simule la fin de la fenêtre de cache.
        dashboard._public_cache["expire"] = time.monotonic() - 1
        await dashboard.handle_public(requete)
        assert calcul.call_count == 2, "après expiration, l'état doit être recalculé"


def test_le_cache_expire_bien():
    asyncio.run(_le_cache_expire())


async def _passage_hors_ligne_visible_apres_expiration():
    _reinitialiser_cache()
    bot = _bot()
    requete = _requete(bot)
    assert (await _corps(await dashboard.handle_public(requete)))["online"] is True

    bot.is_ready.return_value = False
    dashboard._public_cache["expire"] = time.monotonic() - 1
    assert (await _corps(await dashboard.handle_public(requete)))["online"] is False


def test_une_perte_de_connexion_reste_visible():
    asyncio.run(_passage_hors_ligne_visible_apres_expiration())
