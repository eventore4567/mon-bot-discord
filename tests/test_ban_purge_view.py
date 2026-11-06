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
    async def test_slash_bannit_directement_sans_panneau_et_conserve_par_defaut(self):
        ctx, target = _context()
        cog = Moderation.__new__(Moderation)
        cog.bot = SimpleNamespace()
        cog.check_targetable = AsyncMock(return_value=True)
        cog._ack = AsyncMock()
        cog._perform_ban = AsyncMock(return_value="success")
        await Moderation.ban.callback(cog, ctx, target, raison="spam", envoyer_mp=False)
        ctx.send.assert_not_awaited()
        cog._perform_ban.assert_awaited_once_with(ctx, target, "spam", delete_message_seconds=0, send_confirmation=True, envoyer_mp=False)

    async def test_chaque_option_transmet_la_bonne_duree(self):
        for choice,seconds in (("Conserver",0),("15 minutes",900),("1 heure",3600),("24 heures",86400)):
            with self.subTest(choice=choice):
                ctx,target=_context()
                cog=Mock()
                cog.check_targetable=AsyncMock(return_value=True)
                cog._ack=AsyncMock()
                cog._perform_ban=AsyncMock(return_value="success")
                await Moderation.ban.callback(cog,ctx,target,supprimer_messages=choice)
                self.assertEqual(cog._perform_ban.call_args.kwargs['delete_message_seconds'],seconds)
                ctx.send.assert_not_awaited()

    async def test_option_invalide_ne_lance_pas_le_ban(self):
        ctx,target=_context()
        cog=Mock()
        cog.check_targetable=AsyncMock(return_value=True)
        cog._reply=AsyncMock()
        cog._perform_ban=AsyncMock()
        await Moderation.ban.callback(cog,ctx,target,supprimer_messages="invalide")
        cog._perform_ban.assert_not_awaited()
        self.assertIn('Choisissez',cog._reply.call_args.args[1])

    async def test_cible_protegee_refusee_avant_le_panneau(self):
        ctx, target = _context()
        cog = Moderation.__new__(Moderation)
        cog.bot = SimpleNamespace()
        cog.check_targetable = AsyncMock(return_value=False)

        await Moderation.ban.callback(cog, ctx, target, raison="spam", envoyer_mp=False)

        cog.check_targetable.assert_awaited_once_with(ctx, target)
        ctx.send.assert_not_awaited()

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
            envoyer_mp=True,
        )
        interaction.edit_original_response.assert_awaited_once()

    async def test_choix_mp_false_est_transmis_sans_envoi(self):
        ctx, target = _context()
        cog = Mock()
        cog._perform_ban = AsyncMock(return_value="Membre banni.")
        view = _BanPurgeView(cog, ctx, target, "spam", envoyer_mp=False)
        interaction = SimpleNamespace(
            response=SimpleNamespace(edit_message=AsyncMock()),
            edit_original_response=AsyncMock(),
        )

        no = next(b for b in view.children if b.label == "Non")
        await no.callback(interaction)

        cog._perform_ban.assert_awaited_once_with(
            ctx, target, "spam", delete_message_seconds=0,
            send_confirmation=False, envoyer_mp=False,
        )

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
