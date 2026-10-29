"""Tests du choix interactif de suppression des messages pendant /ban."""
from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from cogs.moderation import Moderation, _BanDeletionView, _BanMessagePeriod


def _context():
    guild = SimpleNamespace(id=123, name="Serveur")
    actor = SimpleNamespace(id=101)
    target = SimpleNamespace(id=202, mention="<@202>", display_name="Membre")
    ctx = SimpleNamespace(
        guild=guild,
        author=actor,
        interaction=SimpleNamespace(),
        send=AsyncMock(return_value=Mock()),
    )
    return ctx, target


class BanMessagePurgeChoiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_slash_ban_ouvre_la_question_avant_toute_sanction(self):
        ctx, target = _context()
        cog = Moderation.__new__(Moderation)
        cog.bot = SimpleNamespace()

        await Moderation.ban.callback(cog, ctx, target, raison="spam")

        ctx.send.assert_awaited_once()
        self.assertTrue(ctx.send.await_args.kwargs["ephemeral"])
        view = ctx.send.await_args.kwargs["view"]
        self.assertIsInstance(view, _BanDeletionView)
        self.assertEqual({child.label for child in view.children}, {"Oui", "Non", "Annuler"})

    async def test_oui_affiche_les_durees_sans_lancer_le_ban(self):
        ctx, target = _context()
        cog = Mock()
        cog._perform_ban = AsyncMock(return_value="Banni.")
        view = _BanDeletionView(cog, ctx, target, "spam")
        interaction = SimpleNamespace(response=SimpleNamespace(edit_message=AsyncMock()))

        yes = next(child for child in view.children if child.label == "Oui")
        await yes.callback(interaction)

        selects = [child for child in view.children if isinstance(child, _BanMessagePeriod)]
        self.assertEqual(len(selects), 1)
        self.assertEqual({choice.value for choice in selects[0].options}, {"900", "3600", "86400"})
        cog._perform_ban.assert_not_awaited()

    async def test_non_bannit_sans_supprimer_de_messages(self):
        ctx, target = _context()
        cog = Mock()
        cog._perform_ban = AsyncMock(return_value="Membre banni.")
        view = _BanDeletionView(cog, ctx, target, "spam")
        interaction = SimpleNamespace(
            response=SimpleNamespace(edit_message=AsyncMock()),
            edit_original_response=AsyncMock(),
        )

        no = next(child for child in view.children if child.label == "Non")
        await no.callback(interaction)

        cog._perform_ban.assert_awaited_once_with(
            ctx, target, "spam", delete_message_seconds=0,
        )
        interaction.edit_original_response.assert_awaited_once()

    async def test_annuler_ne_bannit_pas(self):
        ctx, target = _context()
        cog = Mock()
        cog._perform_ban = AsyncMock()
        view = _BanDeletionView(cog, ctx, target, "spam")
        interaction = SimpleNamespace(response=SimpleNamespace(edit_message=AsyncMock()))

        cancel = next(child for child in view.children if child.label == "Annuler")
        await cancel.callback(interaction)

        cog._perform_ban.assert_not_awaited()
        self.assertTrue(view.is_finished())


if __name__ == "__main__":
    unittest.main()
