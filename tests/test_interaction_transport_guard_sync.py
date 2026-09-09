"""L'audit de synchronisation des commandes slash a confirmé (par exécution, avec les
~47 extensions réellement chargées en production) que main.py fait déjà un
`bot.tree.sync()` global systématique au démarrage (main.py:528). Juste après,
`cogs/interaction_transport_guard.py::_enforce_gateway_transport` (installée par
railway_boot.py, donc active en production) refaisait un SECOND `bot.tree.sync()`
global inconditionnel, sans qu'aucune mutation de l'arbre n'intervienne entre les
deux sur le chemin sain (aucun Interactions Endpoint HTTP mal configuré trouvé) — un
appel réseau à Discord strictement dupliqué à chaque démarrage.

Corrigé en ne resynchronisant que lorsque l'endpoint a effectivement été trouvé ET
retiré (le seul cas où reconfirmer le catalogue a un sens). Test d'exécution réel :
vrai bot discord.py, seul `bot.http.request`/`bot.tree.sync` sont simulés (ce sont les
deux seuls points de contact avec l'API Discord elle-même)."""
from __future__ import annotations

import os
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import discord
from discord.ext import commands

from cogs.interaction_transport_guard import _enforce_gateway_transport, _state


class InteractionTransportGuardSyncTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        intents = discord.Intents.none()
        self.bot = commands.Bot(command_prefix="+", intents=intents)
        self.bot._ready = AsyncMock()
        self.bot.wait_until_ready = AsyncMock()

    async def test_chemin_sain_ne_resynchronise_pas_une_seconde_fois(self):
        """C'est exactement le doublon rapporté par l'audit : sans le correctif, ce
        test échoue (bot.tree.sync() est bien appelé alors que rien n'a changé)."""
        with patch.object(
            self.bot.http, "request", new=AsyncMock(return_value={"id": "1", "interactions_endpoint_url": None})
        ), patch.object(self.bot.tree, "sync", new=AsyncMock(return_value=[])) as sync_mock:
            await _enforce_gateway_transport(self.bot)

        sync_mock.assert_not_awaited()
        state = _state(self.bot)
        self.assertTrue(state["gateway_confirmed"])
        self.assertFalse(state["endpoint_was_configured"])

    async def test_endpoint_http_trouve_declenche_bien_le_retrait_et_la_resynchronisation(self):
        """Non-régression : le vrai scénario dangereux (ancien Interactions Endpoint
        HTTP configuré) doit toujours être corrigé ET reconfirmé par un sync."""
        responses = [
            {"id": "1", "interactions_endpoint_url": "https://old-endpoint.example"},  # GET initial
            {"id": "1", "interactions_endpoint_url": None},  # réponse du PATCH de retrait
            {"id": "1", "interactions_endpoint_url": None},  # GET de vérification après retrait
        ]

        async def fake_request(route, **kwargs):
            return responses.pop(0)

        with patch.object(self.bot.http, "request", new=fake_request), \
             patch.object(self.bot.tree, "sync", new=AsyncMock(return_value=[1, 2, 3])) as sync_mock:
            await _enforce_gateway_transport(self.bot)

        sync_mock.assert_awaited_once()
        state = _state(self.bot)
        self.assertTrue(state["endpoint_was_configured"])
        self.assertTrue(state["clear_attempted"])
        self.assertEqual(state["resynced_commands"], 3)
        self.assertTrue(state["gateway_confirmed"])


if __name__ == "__main__":
    unittest.main()
