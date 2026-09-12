"""cogs/moderation.py::unban — Core V2, Phase 2 : le corps de la commande
n'est plus que l'adaptation Discord au-dessus de
services/moderation.py::unban(), déjà testé sans Discord dans
tests/test_services_moderation_unban.py. Ces tests vérifient le CÂBLAGE :
identifiant invalide, utilisateur introuvable, et surtout l'échec de
persistance qui ne doit jamais empêcher le panneau de succès — le trou
corrigé par cette migration."""
from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import discord

from cogs.moderation import Moderation
from utils import sentrix_panels as panels


class _FakeUser:
    def __init__(self, id):
        self.id = id
        self.mention = f"<@{id}>"
        self.display_avatar = SimpleNamespace(url="https://example.com/a.png")
        self.send = AsyncMock()

    def __str__(self):
        return f"utilisateur#{self.id}"


class _FakeMember:
    def __init__(self, id, *, display_name=None):
        self.id = id
        self.display_name = display_name or f"membre{id}"
        self.mention = f"<@{id}>"

    def __str__(self):
        return self.display_name


def _fake_ctx():
    guild = SimpleNamespace(id=555, name="Serveur Test", unban=AsyncMock())
    actor = _FakeMember(1001)
    ctx = SimpleNamespace(
        guild=guild,
        author=actor,
        channel=SimpleNamespace(send=AsyncMock()),
        interaction=None,
        send=AsyncMock(),
        typing=AsyncMock(),
    )
    return ctx, guild, actor


class _FakeDB:
    def __init__(self, *, case_number=8):
        self.fetchone = AsyncMock(return_value=None)  # pas de gabarit MP personnalisé
        self.record_sanction = AsyncMock(return_value=case_number)
        self.get_sanction_count = AsyncMock(return_value=1)


def _make_cog(*, case_number=8, fetch_user=None):
    bot = SimpleNamespace(db=_FakeDB(case_number=case_number), fetch_user=fetch_user or AsyncMock())
    cog = Moderation.__new__(Moderation)
    cog.bot = bot
    cog.log_action = AsyncMock()
    return cog


class UnbanCogWiringTests(unittest.IsolatedAsyncioTestCase):
    async def test_identifiant_invalide_n_appelle_jamais_le_service(self):
        cog = _make_cog()
        ctx, guild, actor = _fake_ctx()

        await Moderation.unban.callback(cog, ctx, "pas-un-id", raison="test")

        cog.bot.fetch_user.assert_not_awaited()
        ctx.send.assert_awaited()

    async def test_utilisateur_introuvable_affiche_le_message_dedie(self):
        fetch_user = AsyncMock(side_effect=discord.NotFound(Mock(status=404), "introuvable"))
        cog = _make_cog(fetch_user=fetch_user)
        ctx, guild, actor = _fake_ctx()

        await Moderation.unban.callback(cog, ctx, "2002", raison="test")

        guild.unban.assert_not_awaited()
        ctx.send.assert_awaited()

    async def test_debannissement_reussi_appelle_le_service_et_rend_le_panneau(self):
        user = _FakeUser(2002)
        cog = _make_cog(fetch_user=AsyncMock(return_value=user))
        ctx, guild, actor = _fake_ctx()

        await Moderation.unban.callback(cog, ctx, "2002", raison="erreur de modération")

        guild.unban.assert_awaited_once()
        ctx.send.assert_awaited()
        cog.log_action.assert_awaited_once()

    async def test_echec_de_persistance_n_empeche_pas_le_panneau_de_succes(self):
        user = _FakeUser(2002)
        cog = _make_cog(fetch_user=AsyncMock(return_value=user))
        cog.bot.db.record_sanction = AsyncMock(side_effect=RuntimeError("disque plein"))
        ctx, guild, actor = _fake_ctx()

        await Moderation.unban.callback(cog, ctx, "2002", raison="test")

        guild.unban.assert_awaited_once()
        ctx.send.assert_awaited()
        panneau = ctx.send.await_args.kwargs.get("view")
        self.assertIsInstance(panneau, panels.Panneau)
        self.assertEqual(panneau.kind, "moderation")


if __name__ == "__main__":
    unittest.main()
