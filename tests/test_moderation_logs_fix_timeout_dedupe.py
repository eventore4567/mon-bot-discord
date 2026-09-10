"""cogs/moderation_logs_fix.py — la déduplication des logs natifs de timeout
matchait un titre d'embed ("Timeout modifié") qui n'existe plus dans
cogs/logs.py depuis son renommage en "Timeout appliqué"/"Timeout retiré" ;
la déduplication ne s'était donc plus jamais déclenchée pour un mute/unmute,
sans qu'aucun test ne le remarque (fichier jamais couvert avant ce correctif).
Ces tests verrouillent le nouveau matching sur les titres RÉELLEMENT émis."""
from __future__ import annotations

import os
import unittest
import unittest.mock
from unittest.mock import AsyncMock

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import discord

from cogs import moderation_logs_fix


def _embed(title: str) -> discord.Embed:
    return discord.Embed(title=title)


class TimeoutActionTests(unittest.TestCase):
    def test_timeout_applique_est_classe_comme_mute(self):
        self.assertEqual(moderation_logs_fix._timeout_action(_embed("Timeout appliqué")), ("mute",))

    def test_timeout_retire_est_classe_comme_unmute(self):
        self.assertEqual(moderation_logs_fix._timeout_action(_embed("Timeout retiré")), ("unmute",))


class _FakeGuild:
    id = 1


class GenericDedupeTitleMatchingTests(unittest.IsolatedAsyncioTestCase):
    """Vérifie que le vrai patch installé par _install_generic_dedupe reconnaît
    les titres RÉELLEMENT émis par cogs/logs.py, pas l'ancien "Timeout modifié"
    qui n'existe plus depuis son renommage."""

    def setUp(self):
        moderation_logs_fix._INSTALLED_DEDUPE = False

    async def test_timeout_applique_declenche_la_verification_de_doublon_et_bloque_l_envoi(self):
        class Logs:
            def __init__(self, bot):
                self.bot = bot

            async def _send(self, guild, config_key, embed):
                raise AssertionError("original _send ne doit pas être appelé : le doublon doit être bloqué")

        fake_bot = unittest.mock.Mock()
        fake_bot.get_cog.return_value = Logs(fake_bot)

        recent_check = AsyncMock(return_value=True)
        original_check = moderation_logs_fix._recent_sanction_exists
        moderation_logs_fix._recent_sanction_exists = recent_check
        try:
            moderation_logs_fix._install_generic_dedupe(fake_bot)

            embed = _embed("Timeout appliqué")
            embed.set_footer(text="Identifiant : 123456789012345678")
            logs_instance = Logs(fake_bot)

            await Logs._send(logs_instance, _FakeGuild(), "log_moderation", embed)

            recent_check.assert_awaited_once()
            self.assertEqual(recent_check.await_args.args[3], ("mute",))
        finally:
            moderation_logs_fix._recent_sanction_exists = original_check

    async def test_timeout_retire_est_egalement_reconnu(self):
        class Logs:
            def __init__(self, bot):
                self.bot = bot

            async def _send(self, guild, config_key, embed):
                raise AssertionError("original _send ne doit pas être appelé : le doublon doit être bloqué")

        fake_bot = unittest.mock.Mock()
        fake_bot.get_cog.return_value = Logs(fake_bot)

        recent_check = AsyncMock(return_value=True)
        original_check = moderation_logs_fix._recent_sanction_exists
        moderation_logs_fix._recent_sanction_exists = recent_check
        try:
            moderation_logs_fix._install_generic_dedupe(fake_bot)

            embed = _embed("Timeout retiré")
            embed.set_footer(text="Identifiant : 123456789012345678")
            logs_instance = Logs(fake_bot)

            await Logs._send(logs_instance, _FakeGuild(), "log_moderation", embed)

            recent_check.assert_awaited_once()
            self.assertEqual(recent_check.await_args.args[3], ("unmute",))
        finally:
            moderation_logs_fix._recent_sanction_exists = original_check


if __name__ == "__main__":
    unittest.main()
