"""`/sentrix` répondait en privé (ephemeral=True sur le defer ET sur chaque follow-up,
cogs/direct_sentrix_slash_v22.py) alors que `+sentrix` (cogs/ai.py:536,
`await ctx.defer()` sans ephemeral) et le déclencheur passif « SentriX ... »
(cogs/ai.py:684-716, réponse normale dans le salon) répondent tous deux publiquement.
Un utilisateur qui tape `/sentrix` obtenait donc une réponse visible de lui seul pour
la même question, la même IA, le même moteur — juste parce qu'il avait utilisé `/`
plutôt que `+`.

Corrigé en retirant `ephemeral=True` du defer et des follow-ups de la V22. Test
d'exécution réel : le vrai callback construit par `_build_callback`, avec une
interaction et un cog IA factices (aucun réseau)."""
from __future__ import annotations

import os
import unittest
from unittest.mock import AsyncMock, MagicMock

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import discord
from discord.ext import commands

from cogs.direct_sentrix_slash_v22 import _build_callback


class DirectSentrixSlashVisibilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_defer_ne_force_plus_ephemeral(self):
        """C'est exactement le bug rapporté : avant le correctif, defer() était
        appelé avec ephemeral=True."""
        bot = MagicMock()
        ai_cog = MagicMock()
        ai_cog.histories = {}
        ai_cog.ask_ai = AsyncMock(return_value="une réponse publique")
        bot.get_cog.return_value = ai_cog

        callback = _build_callback(bot)

        interaction = MagicMock(spec=discord.Interaction)
        interaction.response = MagicMock()
        interaction.response.is_done.return_value = False
        interaction.response.defer = AsyncMock()
        interaction.guild_id = 1
        interaction.channel_id = 2
        interaction.user = MagicMock(id=42, display_name="Testeur")

        with unittest.mock.patch(
            "cogs.direct_sentrix_slash_v22._edit_original", new=AsyncMock()
        ):
            await callback(interaction, "une question")

        interaction.response.defer.assert_awaited_once()
        _, kwargs = interaction.response.defer.call_args
        self.assertNotIn("ephemeral", kwargs, "defer() ne doit plus forcer ephemeral=True")

    async def test_followup_n_est_plus_ephemeral(self):
        """Vérifie le second point de fuite : les follow-ups (réponses longues
        découpées en plusieurs messages) ne doivent plus non plus être ephemeral."""
        from cogs.direct_sentrix_slash_v22 import _followup

        interaction = MagicMock(spec=discord.Interaction)
        interaction.followup = MagicMock()
        interaction.followup.send = AsyncMock()

        with unittest.mock.patch(
            "cogs.direct_sentrix_slash_v22._raw_transports", return_value=(None, None)
        ):
            await _followup(interaction, content="suite de la réponse")

        interaction.followup.send.assert_awaited_once()
        _, kwargs = interaction.followup.send.call_args
        self.assertNotIn("ephemeral", kwargs)


if __name__ == "__main__":
    unittest.main()
