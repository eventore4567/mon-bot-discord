"""cogs/moderation.py::tempban — Core V2, Phase 2 : le corps de la commande
n'est plus que l'adaptation Discord au-dessus de
services/moderation.py::tempban(), déjà testé sans Discord dans
tests/test_services_moderation_tempban.py. Ces tests vérifient le CÂBLAGE :
le service est bien appelé avec le texte de MP rendu, la durée validée
remonte bien au panneau et au dossier de sanction, et un échec de l'une ou
l'autre des deux persistances (dossier de sanction / levée automatique)
n'empêche jamais le panneau de succès."""
from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from cogs.moderation import Moderation
from utils import sentrix_panels as panels


class _FakeRole:
    def __init__(self, position: int):
        self.position = position

    def __ge__(self, other):
        return self.position >= other.position

    def __gt__(self, other):
        return self.position > other.position


class _FakeMember:
    def __init__(self, id, *, top_role_position, display_name=None, guild=None):
        self.id = id
        self.top_role = _FakeRole(top_role_position)
        self.display_name = display_name or f"membre{id}"
        self.mention = f"<@{id}>"
        self.display_avatar = SimpleNamespace(url="https://example.com/a.png")
        self.send = AsyncMock()
        self.guild = guild

    def __str__(self):
        return self.display_name


def _fake_ctx(*, actor_top=20, target_top=1, owner_id=1):
    guild = SimpleNamespace(
        id=555,
        name="Serveur Test",
        owner_id=owner_id,
        me=_FakeMember(999, top_role_position=30),
        ban=AsyncMock(),
    )
    actor = _FakeMember(1001, top_role_position=actor_top, guild=guild)
    target = _FakeMember(2002, top_role_position=target_top, guild=guild)
    ctx = SimpleNamespace(
        guild=guild,
        author=actor,
        channel=SimpleNamespace(send=AsyncMock()),
        interaction=None,
        send=AsyncMock(),
        typing=AsyncMock(),
    )
    return ctx, guild, actor, target


class _FakeDB:
    def __init__(self, *, case_number=11):
        self.fetchone = AsyncMock(return_value=None)  # pas de gabarit MP personnalisé
        self.record_sanction = AsyncMock(return_value=case_number)
        self.get_sanction_count = AsyncMock(return_value=1)
        self.execute = AsyncMock()  # écriture tempactions


def _make_cog(*, case_number=11):
    bot = SimpleNamespace(db=_FakeDB(case_number=case_number))
    cog = Moderation.__new__(Moderation)
    cog.bot = bot
    cog.log_action = AsyncMock()
    return cog


class TempbanCogWiringTests(unittest.IsolatedAsyncioTestCase):
    async def test_bannissement_temporaire_reussi_appelle_le_service_et_rend_le_panneau(self):
        cog = _make_cog(case_number=11)
        ctx, guild, actor, target = _fake_ctx()

        await Moderation.tempban.callback(cog, ctx, target, "1h", raison="spam")

        guild.ban.assert_awaited_once()
        target.send.assert_awaited_once()  # MP par défaut envoyé (avant le ban)
        cog.bot.db.execute.assert_awaited_once()  # levée automatique programmée
        ctx.send.assert_awaited()
        cog.log_action.assert_awaited_once()

    async def test_refus_de_hierarchie_n_appelle_jamais_guild_ban(self):
        cog = _make_cog()
        ctx, guild, actor, target = _fake_ctx(actor_top=1, target_top=20)

        await Moderation.tempban.callback(cog, ctx, target, "1h", raison="spam")

        guild.ban.assert_not_awaited()
        target.send.assert_not_awaited()
        ctx.send.assert_awaited()  # le panneau de refus est bien rendu

    async def test_duree_invalide_n_appelle_jamais_guild_ban(self):
        cog = _make_cog()
        ctx, guild, actor, target = _fake_ctx()

        await Moderation.tempban.callback(cog, ctx, target, "pas une durée", raison="spam")

        guild.ban.assert_not_awaited()
        ctx.send.assert_awaited()

    async def test_echec_du_dossier_de_sanction_n_empeche_pas_le_panneau_de_succes(self):
        """Le trou corrigé par cette migration, côté commande complète : une
        exception sur record_sanction() ne doit jamais faire passer un
        bannissement Discord déjà réussi pour un échec."""
        cog = _make_cog()
        cog.bot.db.record_sanction = AsyncMock(side_effect=RuntimeError("disque plein"))
        ctx, guild, actor, target = _fake_ctx()

        await Moderation.tempban.callback(cog, ctx, target, "1h", raison="spam")

        guild.ban.assert_awaited_once()
        ctx.send.assert_awaited()
        panneau = ctx.send.await_args.kwargs.get("view")
        self.assertIsInstance(panneau, panels.Panneau)
        self.assertEqual(panneau.kind, "moderation")

    async def test_echec_de_la_programmation_de_la_levee_n_empeche_pas_le_panneau_de_succes(self):
        """Le DEUXIÈME trou corrigé par cette migration : l'écriture dans
        tempactions (levée automatique) était tout aussi non protégée que
        record_sanction() avant l'extraction."""
        cog = _make_cog()
        cog.bot.db.execute = AsyncMock(side_effect=RuntimeError("disque plein"))
        ctx, guild, actor, target = _fake_ctx()

        await Moderation.tempban.callback(cog, ctx, target, "1h", raison="spam")

        guild.ban.assert_awaited_once()
        ctx.send.assert_awaited()
        panneau = ctx.send.await_args.kwargs.get("view")
        self.assertIsInstance(panneau, panels.Panneau)
        self.assertEqual(panneau.kind, "moderation")


if __name__ == "__main__":
    unittest.main()
