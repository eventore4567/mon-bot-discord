"""`/unmute` était absent du menu slash malgré son statut « commande directe normale »
(cogs/command_catalog_cleanup.py). Cause racine confirmée par exécution réelle :
cogs/v17_moderation_security.py::install_moderation_guards remplaçait le callback de
unmute/mute/warn/ban/... par un wrapper générique `(*args, **kwargs)` pour la
déduplication de sanctions (déplacée depuis dans cogs/moderation.py — voir
tests/test_moderation_short_replies.py). Pour ban/mute/warn (with_app_command=True), l'objet slash
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


class ModerationGuardsNoLongerWrapCallbacksTests(unittest.IsolatedAsyncioTestCase):
    """install_moderation_guards ne remplace plus aucun callback de sanction : la
    déduplication vit dans cogs/moderation.py. Les deux bugs historiques (signature
    non introspectable pour /unmute, divergence + vs / pour /mute) ne peuvent donc
    plus se produire par ce chemin."""

    async def asyncSetUp(self):
        intents = discord.Intents.none()
        self.bot = commands.Bot(command_prefix="+", intents=intents)
        await self.bot.add_cog(_FakeModerationCog())

    async def test_les_callbacks_de_sanction_ne_sont_plus_remplaces(self):
        mute = self.bot.get_command("mute")
        unmute = self.bot.get_command("unmute")
        mute_before, unmute_before = mute.callback, unmute.callback

        v17_moderation_security.install_moderation_guards(self.bot)

        self.assertIs(mute.callback, mute_before)
        self.assertIs(unmute.callback, unmute_before)
        self.assertIs(mute.app_command._callback, mute.callback)

    async def test_unmute_reste_reconstructible_en_slash(self):
        v17_moderation_security.install_moderation_guards(self.bot)
        unmute = self.bot.get_command("unmute")
        app_command = HybridAppCommand(unmute)
        self.assertEqual({param.name for param in app_command.parameters}, {"membre", "raison"})

    async def test_check_targetable_est_toujours_protege(self):
        v17_moderation_security.install_moderation_guards(self.bot)
        cog = self.bot.get_cog("Moderation")
        self.assertTrue(getattr(type(cog).check_targetable, "_sentrix_v17_protected", False))


class ModerationCatalogSurfaceTests(unittest.TestCase):
    def test_unmute_lock_unlock_clearwarnings_slowmode_sont_dans_la_surface_directe(self):
        for name in ("unmute", "lock", "unlock", "clearwarnings", "slowmode"):
            with self.subTest(name=name):
                self.assertIn(name, NORMAL_DIRECT_COMMANDS)

    def test_normal_direct_commands_reste_exactement_a_122(self):
        """Contrat imposé par tools/command_runtime_audit.py.

        Passé de 112 à 122 : les dix bascules AutoMod qui manquaient. Mesuré sur
        le bot booté le 2026-09-25, seules antiraid et antinuke étaient classées
        ici, donc seules elles échappaient au « hidden = True » générique
        d'apply_surface() et à l'éligibilité slash. Les dix autres existaient,
        fonctionnaient, et n'apparaissaient ni dans +help ni sous
        /securite automod — le groupe n'exposait qu'une feuille sur vingt-cinq.

        +automod-status n'en fait PAS partie : elle reste dans
        SECURITY_MERGED_COMMANDS, et user_acceptance_audit exige son masquage.
        """
        self.assertEqual(len(NORMAL_DIRECT_COMMANDS), 122)


if __name__ == "__main__":
    unittest.main()
