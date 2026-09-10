"""cogs/server_builder.py::ServerBuilder est un cog unique partagé par TOUS les
serveurs. build_server() écrivait sa progression dans un unique attribut
d'instance self._build_step, lu ensuite par ServerBuilderView.confirm() dans
ses gestionnaires d'exception pour dire à l'utilisateur à quelle étape
Discord a échoué. Deux /create-server concurrents (deux serveurs différents,
ou le même serveur relancé pendant qu'une première exécution tourne encore)
partageaient donc le même compteur : si la construction du serveur B avançait
pendant que celle du serveur A était interrompue, le message d'erreur montré
à l'administrateur de A pouvait décrire l'étape de B — c'est un bug
démontrable sur la seule implémentation existante (pas un fork de
comportement), corrigé ici en indexant la progression par guild_id
(self._build_steps: dict[int, str]).

Ce test ne rejoue pas tout build_server() (permissions, rôles, salons,
tickets Discord réels) : il stubbe les étapes internes pour contrôler
précisément l'entrelacement de deux constructions concurrentes et vérifier
que la progression de l'une n'écrase jamais celle de l'autre."""
from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from cogs.server_builder import ServerBuilder


def _make_cog():
    cog = ServerBuilder.__new__(ServerBuilder)
    cog.bot = SimpleNamespace()
    cog._build_steps = {}
    return cog


class ConcurrentBuildStepsTests(unittest.IsolatedAsyncioTestCase):
    async def test_deux_serveurs_concurrents_ne_melangent_jamais_leur_etape(self):
        cog = _make_cog()

        guild_a_can_advance = asyncio.Event()
        guild_b_finished = asyncio.Event()

        async def fake_ensure_roles(guild, data, reason):
            if guild.id == 111:
                # Le serveur A reste bloqué APRÈS la 1ère étape jusqu'à ce que le test
                # l'autorise explicitement à continuer.
                await guild_a_can_advance.wait()
            role_map = {
                data["staff_role_name"]: SimpleNamespace(mention="@Staff"),
                data["member_role_name"]: SimpleNamespace(mention="@Membre"),
            }
            return role_map, 0, 0

        async def fake_ensure_structure(guild, data, role_map, reason):
            return {}, {}, 0, 0, 0, 0

        cog._ensure_roles = fake_ensure_roles
        cog._ensure_structure = fake_ensure_structure
        cog._configure_bot_channels = AsyncMock(return_value=0)
        cog._publish_welcome_content = AsyncMock(return_value=0)
        cog._configure_tickets = AsyncMock(return_value="ok")
        cog._capacity_error = lambda guild, data: None

        guild_a = SimpleNamespace(id=111, name="Serveur A")
        guild_b = SimpleNamespace(id=222, name="Serveur B")
        member = SimpleNamespace()

        async def run_b():
            await cog.build_server(guild_b, "communaute", member)
            guild_b_finished.set()

        task_a = asyncio.create_task(cog.build_server(guild_a, "communaute", member))
        # Laisse A atteindre puis se figer sur "création et mise à jour des rôles".
        await asyncio.sleep(0)
        self.assertEqual(
            cog._build_steps[guild_a.id], "création et mise à jour des rôles"
        )

        # B se déroule intégralement pendant que A est toujours figé.
        await run_b()
        self.assertTrue(guild_b_finished.is_set())
        self.assertEqual(cog._build_steps[guild_b.id], "finalisation")

        # A doit toujours afficher SA PROPRE étape, jamais celle de B.
        self.assertEqual(
            cog._build_steps[guild_a.id], "création et mise à jour des rôles"
        )

        guild_a_can_advance.set()
        await task_a

        self.assertEqual(cog._build_steps[guild_a.id], "finalisation")
        self.assertEqual(cog._build_steps[guild_b.id], "finalisation")

    async def test_erreur_sur_un_serveur_rapporte_sa_propre_etape_pas_celle_dun_autre(self):
        cog = _make_cog()

        async def fake_ensure_roles(guild, data, reason):
            role_map = {
                data["staff_role_name"]: SimpleNamespace(mention="@Staff"),
                data["member_role_name"]: SimpleNamespace(mention="@Membre"),
            }
            return role_map, 0, 0

        async def failing_ensure_structure(guild, data, role_map, reason):
            import discord
            raise discord.Forbidden(SimpleNamespace(status=403, reason="x"), "x")

        cog._ensure_roles = fake_ensure_roles
        cog._ensure_structure = failing_ensure_structure
        cog._capacity_error = lambda guild, data: None

        # Un autre serveur a déjà avancé plus loin dans _build_steps avant cet appel.
        cog._build_steps[999] = "finalisation"

        guild = SimpleNamespace(id=333, name="Serveur C")
        with self.assertRaises(Exception):
            await cog.build_server(guild, "communaute", SimpleNamespace())

        # L'étape enregistrée pour CE serveur est la sienne (celle où _ensure_structure
        # a échoué), pas celle du serveur 999.
        self.assertEqual(
            cog._build_steps[guild.id],
            "création et configuration des catégories et salons",
        )
        self.assertEqual(cog._build_steps[999], "finalisation")


if __name__ == "__main__":
    unittest.main()
