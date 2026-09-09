"""`/unmute` était absent du menu slash malgré son statut « commande directe normale »
(cogs/command_catalog_cleanup.py). Cause racine confirmée par exécution réelle :
cogs/v17_moderation_security.py::install_moderation_guards remplace le callback de
unmute/mute/warn/ban/... par un wrapper générique `(*args, **kwargs)` pour la
déduplication de sanctions. Pour ban/mute/warn (with_app_command=True), l'objet slash
existait déjà AVANT ce remplacement, donc ça ne se voyait pas. Mais unmute avait
with_app_command=False : sa version slash est reconstruite PLUS TARD par
cogs/command_hybrid_slash_restore_v3.py, qui inspecte alors le wrapper au lieu de la
vraie signature — `HybridAppCommand(...)` échouait avec `TypeError: unsupported type
annotation` sur `*args`/`**kwargs`. Corrigé en ajoutant `functools.wraps(original)` sur
le wrapper, ce qui restaure une signature introspectable via `inspect.signature`
(discord.py s'appuie dessus pour construire les options slash) sans changer le
comportement runtime (toujours `*args, **kwargs`).

En parallèle, clearwarnings et slowmode ont été ajoutées à NORMAL_DIRECT_COMMANDS (à la
place de quarantine/unquarantine, retirées : le budget slash est plafonné à 100 racines
globales et était déjà à saturation — voir cogs/slash_command_budget.py). lock/unlock
étaient déjà correctement couverts par ce même mécanisme, non touchés ici.
"""
from __future__ import annotations

import os
import unittest

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import discord
from discord import app_commands
from discord.ext import commands
from discord.ext.commands.hybrid import HybridAppCommand

from cogs import v17_moderation_security
from cogs.command_catalog_cleanup import NORMAL_DIRECT_COMMANDS


class _FakeModerationCog(commands.Cog, name="Moderation"):
    """Reproduit uniquement ce dont install_moderation_guards a besoin : une classe
    portant check_targetable, et les commandes réellement wrappées enregistrées sur un
    vrai bot discord.py (pas un mock — le bug est dans la vraie machinerie
    inspect/app_commands de discord.py, un mock le masquerait)."""

    async def check_targetable(self, ctx: commands.Context, membre: discord.Member) -> bool:
        return True

    @commands.hybrid_command(name="mute", description="Rendre muet un membre.")
    @app_commands.describe(membre="Le membre à rendre muet", raison="La raison")
    async def mute(self, ctx: commands.Context, membre: discord.Member, *, raison: str = "Aucune raison"):
        pass

    @commands.hybrid_command(name="unmute", description="Retirer le mute.", with_app_command=False)
    @app_commands.describe(membre="Le membre à démuter", raison="La raison")
    async def unmute(self, ctx: commands.Context, membre: discord.Member, *, raison: str = "Aucune raison"):
        pass


class ModerationSlashRestorationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        intents = discord.Intents.none()
        self.bot = commands.Bot(command_prefix="+", intents=intents)
        await self.bot.add_cog(_FakeModerationCog())

    async def test_unmute_callback_reste_introspectable_apres_le_wrapping_v17(self):
        """Reproduit précisément le bug : sans functools.wraps sur dedupe_callback, cette
        assertion échoue (inspect.signature ne verrait que *args/**kwargs)."""
        import inspect

        v17_moderation_security.install_moderation_guards(self.bot)

        unmute = self.bot.get_command("unmute")
        signature = inspect.signature(unmute.callback)
        self.assertIn("membre", signature.parameters)
        self.assertIn("raison", signature.parameters)

    async def test_unmute_peut_etre_reconstruite_en_vraie_commande_slash_apres_v17(self):
        """C'est EXACTEMENT ce que cogs/command_hybrid_slash_restore_v3.py fait au
        démarrage. Avant le correctif, cette ligne levait TypeError: unsupported type
        annotation — /unmute n'existait alors jamais, seul +unmute fonctionnait."""
        v17_moderation_security.install_moderation_guards(self.bot)

        unmute = self.bot.get_command("unmute")
        app_command = HybridAppCommand(unmute)  # ne doit lever aucune exception

        param_names = {param.name for param in app_command.parameters}
        self.assertEqual(param_names, {"membre", "raison"})

    async def test_wrapping_ne_change_pas_le_comportement_runtime(self):
        """Le correctif est purement introspectif : le wrapper doit toujours passer par
        dedupe_callback (déduplication de sanctions), pas contourner la logique métier."""
        v17_moderation_security.install_moderation_guards(self.bot)

        unmute = self.bot.get_command("unmute")
        self.assertTrue(getattr(unmute.callback, "_sentrix_v17_dedupe", False))
        self.assertEqual(unmute.callback.__wrapped__, unmute.callback._sentrix_original)

    async def test_mute_deja_slash_n_est_pas_casse_par_le_wrapping(self):
        """Non-régression : mute avait déjà son app_command construit avant le wrapping
        (with_app_command=True par défaut) ; ça doit continuer à fonctionner à l'identique."""
        mute_before = self.bot.tree.get_command("mute")
        self.assertIsNotNone(mute_before)

        v17_moderation_security.install_moderation_guards(self.bot)

        mute_after = self.bot.tree.get_command("mute")
        self.assertIsNotNone(mute_after)


class ModerationSlashPrefixDivergenceTests(unittest.IsolatedAsyncioTestCase):
    """Bug distinct trouvé le 2026-09-08, plus grave que le premier : /mute (déjà
    slash-active dès la décoration, contrairement à /unmute) n'a jamais été touchée
    par le TypeError de restauration — mais install_moderation_guards() fait
    `command.callback = dedupe_callback` APRÈS que mute.app_command existait déjà.
    discord.py fige une copie de la référence de fonction dans
    HybridAppCommand._callback à la construction (voir cogs/hybrid_callback_resync.py
    pour la preuve complète) : /mute a donc continué à exécuter l'ANCIEN callback,
    SANS dédoublonnage de sanctions, pour toujours — alors que +mute était protégée.
    Confirmé en production sur ban/kick/mute/warn/unban/clear (entre autres)."""

    async def asyncSetUp(self):
        intents = discord.Intents.none()
        self.bot = commands.Bot(command_prefix="+", intents=intents)
        await self.bot.add_cog(_FakeModerationCog())

    async def test_mute_divergeait_reellement_avant_le_correctif_general(self):
        mute = self.bot.get_command("mute")
        original_callback = mute.callback

        v17_moderation_security.install_moderation_guards(self.bot)

        self.assertIsNot(mute.callback, original_callback)  # + est bien protégée
        self.assertIs(
            mute.app_command._callback, original_callback,
            "/mute exécutait encore l'ancien callback, sans dédoublonnage — c'est le bug.",
        )

    async def test_hybrid_callback_resync_repare_mute_avec_le_vrai_wrapper_de_production(self):
        from cogs.hybrid_callback_resync import resync

        mute = self.bot.get_command("mute")
        v17_moderation_security.install_moderation_guards(self.bot)
        self.assertIsNot(mute.callback, mute.app_command._callback)  # bug présent

        fixed = resync(self.bot)

        self.assertIn("mute", fixed)
        self.assertIs(mute.callback, mute.app_command._callback)
        self.assertTrue(getattr(mute.app_command._callback, "_sentrix_v17_dedupe", False))


class ModerationCatalogSurfaceTests(unittest.TestCase):
    def test_unmute_lock_unlock_clearwarnings_slowmode_sont_dans_la_surface_directe(self):
        for name in ("unmute", "lock", "unlock", "clearwarnings", "slowmode"):
            with self.subTest(name=name):
                self.assertIn(name, NORMAL_DIRECT_COMMANDS)

    def test_normal_direct_commands_reste_exactement_a_100(self):
        """Contrat déjà imposé par tools/command_runtime_audit.py : le budget slash
        (cogs/slash_command_budget.py) est plafonné à 100 racines globales."""
        self.assertEqual(len(NORMAL_DIRECT_COMMANDS), 100)


if __name__ == "__main__":
    unittest.main()
