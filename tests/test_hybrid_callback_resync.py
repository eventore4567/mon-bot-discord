"""Cause structurelle commune trouvée le 2026-09-08, confirmée par lecture du code
source de discord.py 2.7.1 (discord/ext/commands/hybrid.py::HybridAppCommand.__init__)
puis par exécution réelle (voir tools/command_callback_integrity_audit.py) :

    >>> demo.callback = wrapper
    >>> demo.callback is demo.app_command._callback
    False

``HybridAppCommand.__init__`` fige une COPIE de la référence de fonction dans
``app_command._callback`` au moment de la construction — ce n'est jamais une liaison
vivante vers ``command.callback``. Une quinzaine de modules SentriX (dédoublonnage de
sanctions, sécurité, logs...) font ``command.callback = wrapper`` sur des commandes
DÉJÀ slash-actives. Le chemin préfixe voit le nouveau callback immédiatement
(``Command.invoke`` relit ``self.callback`` à chaque appel) ; le chemin slash continue
d'exécuter l'ANCIEN callback pour toujours, silencieusement. Confirmé en production
sur exactement ce scénario : /ban /kick /mute /warn /unban /clear (entre autres)
n'étaient JAMAIS protégées par le dédoublonnage de sanctions de
cogs/v17_moderation_security.py — seules leurs versions + l'étaient.

Ce test reproduit le bug avec une vraie HybridCommand discord.py (pas un mock — le
bug vit dans la vraie machinerie de construction de HybridAppCommand), applique le
même motif `command.callback = wrapper` que les modules réels, puis vérifie que
cogs.hybrid_callback_resync.resync() répare la divergence."""
from __future__ import annotations

import os
import unittest

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import discord
from discord.ext import commands

from cogs.hybrid_callback_resync import resync


class HybridCallbackResyncTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        intents = discord.Intents.none()
        self.bot = commands.Bot(command_prefix="+", intents=intents)

        @self.bot.hybrid_command(name="demo")
        async def demo(ctx, valeur: int):
            pass

        self.demo = demo

    def test_le_bug_est_reproduit_avant_correction(self):
        """Documente le bug lui-même (pas encore le correctif) : confirme que le
        scénario qu'on s'apprête à corriger existe vraiment sur une vraie
        HybridCommand, pas seulement en théorie."""
        original = self.demo.callback

        async def wrapper(*args, **kwargs):
            return await original(*args, **kwargs)

        self.demo.callback = wrapper

        self.assertIsNot(self.demo.callback, self.demo.app_command._callback)
        self.assertIs(self.demo.app_command._callback, original)

    def test_resync_repare_la_divergence(self):
        """C'est le correctif : après resync(), / exécute le même code que +."""
        original = self.demo.callback
        calls = []

        async def wrapper(*args, **kwargs):
            calls.append("wrapped")
            return await original(*args, **kwargs)

        self.demo.callback = wrapper
        self.assertIsNot(self.demo.callback, self.demo.app_command._callback)  # bug présent

        fixed = resync(self.bot)

        self.assertIn("demo", fixed)
        self.assertIs(self.demo.callback, self.demo.app_command._callback)
        self.assertIs(self.demo.app_command._callback, wrapper)

    def test_resync_ne_touche_pas_les_commandes_deja_synchronisees(self):
        """Non-régression : une commande jamais re-wrappée ne doit apparaître dans
        aucun rapport, et son callback ne doit pas être touché."""
        original_callback = self.demo.callback
        fixed = resync(self.bot)

        self.assertNotIn("demo", fixed)
        self.assertIs(self.demo.callback, original_callback)
        self.assertIs(self.demo.app_command._callback, original_callback)

    def test_resync_ignore_sans_planter_les_commandes_sans_app_command(self):
        """Non-régression : une commande +uniquement (with_app_command=False, jamais
        restaurée en slash) a app_command == discord.utils.MISSING, pas None — ne
        doit jamais faire planter resync() (bug réellement rencontré en écrivant ce
        correctif : AttributeError sur _MissingSentinel)."""
        @self.bot.hybrid_command(name="prefix-only", with_app_command=False)
        async def prefix_only(ctx):
            pass

        prefix_only.callback = lambda *a, **k: None  # ne doit lever aucune exception

        fixed = resync(self.bot)  # ne doit pas planter

        self.assertNotIn("prefix-only", fixed)


if __name__ == "__main__":
    unittest.main()
