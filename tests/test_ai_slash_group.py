"""`/ai` n'avait aucune vraie sous-commande Discord : c'était une commande à plat, et
"reset"/"memory"/"model"/"help" étaient distingués par une simple comparaison de
chaîne sur le texte tapé. "/ai enable"/"/ai disable"/"/ai search" n'existaient tout
simplement nulle part dans le code — les taper envoyait littéralement ce texte comme
question à l'IA, qui répondait n'importe quoi. `+aisetup`/`+aidiag`/`+image` restent
par ailleurs strictement préfixe (with_app_command=False) et hors du périmètre de ce
correctif (voir le rapport d'audit /ai livré à l'utilisateur).

Corrigé en transformant `/ai` en vrai groupe (`hybrid_group(fallback="ask")`) avec de
vraies sous-commandes ask/search/enable/disable/reset/memory/model/help. Tests
d'exécution réels : vrai bot discord.py, vraie extension chargée, vraie base SQLite
temporaire — pas des assertions sur le texte source.
"""
from __future__ import annotations

import os
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import discord
from discord.ext import commands

import cogs.ai as ai_module
from database.db import Database
from utils import ai_service


class _FakeMessage:
    def __init__(self, content: str, guild=None):
        self.content = content
        self.author = SimpleNamespace(bot=False, id=1, roles=[])
        self.guild = guild
        self.channel = SimpleNamespace(id=1)
        self.id = 1
        self.webhook_id = None
        self.attachments = []
        self._state = None


class AiGroupTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        os.environ["DATABASE_PATH"] = os.path.join(self._tmpdir.name, "sentrix-test.db")
        intents = discord.Intents.none()
        intents.message_content = True
        self.bot = commands.Bot(command_prefix="+", intents=intents)
        self.bot.db = Database(os.environ["DATABASE_PATH"])
        await self.bot.db.connect()
        self.bot._connection.user = SimpleNamespace(id=999999)
        # setup() direct plutôt que bot.load_extension("cogs.ai") : cogs/__init__.py
        # patche Bot.load_extension pour enchaîner ~25 installateurs runtime
        # supplémentaires (ai_reliability, bot_v14_core, stability_runtime...) qui
        # monkeypatchent des fonctions au niveau MODULE (donc partagées par tout le
        # process pytest) — les déclencher ici polluait d'autres fichiers de tests
        # sans rapport (ex: test_visual_brand_v2.py) quand la suite tourne en entier.
        # setup() se contente d'un bot.add_cog() normal, sans cette cascade.
        await ai_module.setup(self.bot)

    async def asyncTearDown(self):
        ai_cog = self.bot.get_cog("Ai")
        if ai_cog is not None:
            for loop in ("_cleanup_memory",):
                task = getattr(ai_cog, loop, None)
                if task is not None:
                    task.cancel()
        await self.bot.db._conn.close()
        self._tmpdir.cleanup()

    async def test_ai_est_un_groupe_avec_les_bonnes_sous_commandes_en_slash(self):
        tree_ai = self.bot.tree.get_command("ai")
        self.assertIsNotNone(tree_ai)
        names = {child.name for child in tree_ai.walk_commands()}
        self.assertEqual(names, {"ask", "search", "enable", "disable", "reset", "memory", "model", "help"})

    async def test_prefixe_plus_ai_question_route_toujours_vers_le_groupe_directement(self):
        """Non-régression : +ai <question> ne doit pas devenir +ai ask <question>. La
        résolution du nom racine par get_context() ne suffit pas à prouver le dispatch
        réel (elle ne regarde que le premier mot) : il faut vraiment invoquer la
        commande, comme Discord le fait, en observant quelle méthode reçoit l'appel.
        `ctx.command.invoke()` fait le vrai routage groupe/sous-commande de discord.py
        sans passer par bot.invoke()/dispatch(), dont les listeners annexes fuient
        entre tests IsolatedAsyncioTestCase (event loop fermée entre-temps)."""
        ai_cog = self.bot.get_cog("Ai")
        ctx = await self.bot.get_context(_FakeMessage("+ai bonjour comment vas tu"))
        with patch.object(ai_cog, "_handle_ai_command", new=AsyncMock()) as handled:
            await ctx.command.invoke(ctx)
        handled.assert_awaited_once()
        self.assertEqual(handled.await_args.args[1], "bonjour comment vas tu")

    async def test_prefixe_plus_ai_enable_route_vers_la_vraie_sous_commande(self):
        """C'est exactement le bug rapporté : avant le correctif, "enable" était
        traité comme une question adressée à l'IA (aucune sous-commande de ce nom
        n'existait), jamais comme une action."""
        ai_cog = self.bot.get_cog("Ai")
        ctx = await self.bot.get_context(_FakeMessage("+ai enable"))
        self.assertEqual(ctx.command.qualified_name, "ai")  # get_context ne résout que la racine
        with patch.object(ai_cog, "_ai_toggle", new=AsyncMock()) as toggled, \
             patch.object(ai_cog, "_handle_ai_command", new=AsyncMock()) as handled, \
             patch("utils.checks.is_verified_bot_owner", new=AsyncMock(return_value=True)):
            await ctx.command.invoke(ctx)
        toggled.assert_awaited_once_with(ctx, True)
        handled.assert_not_awaited()  # "enable" ne doit JAMAIS être envoyé comme question

    async def test_ai_enable_ecrit_reellement_enabled_1_en_base(self):
        """+ai enable / /ai enable doivent écrire directement la colonne `enabled` de
        `ai_settings` — la même que lit _prepare_and_generate avant de générer une
        réponse (cogs/ai.py) — sans passer par un mécanisme parallèle qui n'aurait
        aucun effet réel."""
        guild_id = 4242
        ai_cog = self.bot.get_cog("Ai")
        fake_ctx = SimpleNamespace(guild=SimpleNamespace(id=guild_id))
        with patch("cogs.ai.panels.envoyer", new=AsyncMock()):
            await ai_cog._ai_toggle(fake_ctx, True)

        row = await self.bot.db.fetchone("SELECT enabled FROM ai_settings WHERE guild_id = ?", (guild_id,))
        self.assertEqual(int(row["enabled"]), 1)

    async def test_ai_disable_ecrit_reellement_enabled_0_en_base(self):
        guild_id = 4343
        await self.bot.db.execute(
            "INSERT INTO ai_settings (guild_id, enabled, updated_at) VALUES (?, 1, 0)", (guild_id,)
        )

        ai_cog = self.bot.get_cog("Ai")
        fake_ctx = SimpleNamespace(guild=SimpleNamespace(id=guild_id))
        with patch("cogs.ai.panels.envoyer", new=AsyncMock()):
            await ai_cog._ai_toggle(fake_ctx, False)

        row = await self.bot.db.fetchone("SELECT enabled FROM ai_settings WHERE guild_id = ?", (guild_id,))
        self.assertEqual(int(row["enabled"]), 0)

    async def test_ai_search_force_reellement_la_recherche_web_meme_sans_mot_cle(self):
        """/ai search doit forcer web_search=True même sur une question qui ne
        contiendrait normalement aucun déclencheur de recherche automatique."""
        ai_cog = self.bot.get_cog("Ai")
        guild_id = 44
        await ai_service.update_setting(self.bot, guild_id, "enabled", 1)

        question = "raconte-moi une blague"  # aucun mot-clé de recherche
        self.assertFalse(ai_service.needs_web_search(question))

        captured = {}

        async def fake_generate(prompt, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(ok=True, text="réponse", model_key="luna", response_id=None)

        with patch("cogs.ai.ai_service.generate", new=fake_generate):
            result = await ai_cog._prepare_and_generate(
                guild_id=guild_id, channel_id=1, user_id=1, author_name="test",
                question=question, command="ai search", force_web_search=True,
            )

        self.assertTrue(result["ok"])
        self.assertTrue(captured.get("web_search"))

    async def test_ai_ask_normal_n_active_pas_la_recherche_web_sans_raison(self):
        """Non-régression : le comportement par défaut (heuristique) ne doit pas être
        forcé pour /ai ask, seulement pour /ai search."""
        ai_cog = self.bot.get_cog("Ai")
        guild_id = 45
        await ai_service.update_setting(self.bot, guild_id, "enabled", 1)

        question = "raconte-moi une blague"
        captured = {}

        async def fake_generate(prompt, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(ok=True, text="réponse", model_key="luna", response_id=None)

        with patch("cogs.ai.ai_service.generate", new=fake_generate):
            await ai_cog._prepare_and_generate(
                guild_id=guild_id, channel_id=1, user_id=1, author_name="test",
                question=question, command="ai",
            )

        self.assertFalse(captured.get("web_search"))

    async def test_ai_enable_est_reserve_a_un_administrateur(self):
        """Vérifie la matrice centrale directement (utils/access_matrix.py), pas
        seulement l'ancien décorateur local (retiré comme redondant au runtime)."""
        from utils import access_matrix

        member = SimpleNamespace(id=1, guild_permissions=SimpleNamespace(administrator=False))
        guild = SimpleNamespace(id=1, owner_id=999)
        decision = await access_matrix.evaluate(self.bot, command_name="ai enable", author=member, guild=guild)
        self.assertFalse(decision.allowed)

    async def test_ai_ask_reste_public_pour_tout_le_monde(self):
        from utils import access_matrix

        member = SimpleNamespace(id=1, guild_permissions=SimpleNamespace(administrator=False))
        guild = SimpleNamespace(id=1, owner_id=999)
        decision = await access_matrix.evaluate(self.bot, command_name="ai ask", author=member, guild=guild)
        self.assertTrue(decision.allowed)


if __name__ == "__main__":
    unittest.main()
