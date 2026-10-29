"""Parcours de confirmation /ban (slash) : oui, non, sélection et annulation."""
from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from cogs.moderation import Moderation, _BanPurgeSelect, _BanPurgeView


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


class BanPurgeUiTests(unittest.IsolatedAsyncioTestCase):
    async def test_slash_ne_bannit_pas_avant_une_reponse(self):
        ctx, target = _context()
        cog = Moderation.__new__(Moderation)
        cog.bot = SimpleNamespace()

        await Moderation.ban.callback(cog, ctx, target, raison="spam")

        ctx.send.assert_awaited_once()
        self.assertIs(ctx.send.await_args.kwargs["ephemeral"], True)
        view = ctx.send.await_args.kwargs["view"]
        self.assertIsInstance(view, _BanPurgeView)
        self.assertEqual({b.label for b in view.children}, {"Oui", "Non", "Annuler"})

    async def test_oui_montre_les_durees_sans_bannir(self):
        ctx, target = _context()
        cog = Mock()
        cog._perform_ban = AsyncMock(return_value="Banni.")
        view = _BanPurgeView(cog, ctx, target, "spam")
        interaction = SimpleNamespace(response=SimpleNamespace(edit_message=AsyncMock()))

        yes = next(b for b in view.children if b.label == "Oui")
        await yes.callback(interaction)

        selects = [child for child in view.children if isinstance(child, _BanPurgeSelect)]
        self.assertEqual(len(selects), 1)
        self.assertEqual([int(o.value) for o in selects[0].options], [900, 3600, 86400])
        cog._perform_ban.assert_not_awaited()

    async def test_non_bannit_sans_supprimer_les_messages(self):
        ctx, target = _context()
        cog = Mock()
        cog._perform_ban = AsyncMock(return_value="Membre banni.")
        view = _BanPurgeView(cog, ctx, target, "spam")
        interaction = SimpleNamespace(
            response=SimpleNamespace(edit_message=AsyncMock()),
            edit_original_response=AsyncMock(),
        )

        no = next(b for b in view.children if b.label == "Non")
        await no.callback(interaction)

        cog._perform_ban.assert_awaited_once_with(
            ctx, target, "spam", delete_message_seconds=0, send_confirmation=False,
        )
        interaction.edit_original_response.assert_awaited_once()

    async def test_annuler_ne_bannit_pas(self):
        ctx, target = _context()
        cog = Mock()
        cog._perform_ban = AsyncMock()
        view = _BanPurgeView(cog, ctx, target, "spam")
        interaction = SimpleNamespace(response=SimpleNamespace(edit_message=AsyncMock()))

        cancel = next(b for b in view.children if b.label == "Annuler")
        await cancel.callback(interaction)

        cog._perform_ban.assert_not_awaited()
        self.assertTrue(view.is_finished())


if __name__ == "__main__":
    unittest.main()
