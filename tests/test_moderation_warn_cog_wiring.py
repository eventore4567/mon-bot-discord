"""cogs/moderation.py::warn — Core V2, Phase 2 : le corps de la commande n'est
plus que l'adaptation Discord au-dessus de services/moderation.py::warn(),
déjà testé sans Discord dans tests/test_services_moderation_warn.py. Ces tests
vérifient le CÂBLAGE : le panneau de succès reste affiché même quand le
dossier de l'avertissement OU celui du bannissement automatique échoue à se
persister, et le rendu (rôle, total, bannissement automatique) reste fidèle
au comportement existant."""
from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import discord

from cogs.moderation import Moderation
from utils import sentrix_panels as panels


class _FakeRole:
    def __init__(self, id, position, *, mention=None):
        self.id = id
        self.position = position
        self.mention = mention or f"<@&{id}>"

    def __ge__(self, other):
        return self.position >= other.position

    def __gt__(self, other):
        return self.position > other.position

    def __eq__(self, other):
        return self is other

    def __hash__(self):
        return id(self)


class _FakeMember:
    def __init__(self, id, *, top_role_position, display_name=None, guild=None, roles=None):
        self.id = id
        self.top_role = _FakeRole(id * 100, top_role_position)
        self.display_name = display_name or f"membre{id}"
        self.mention = f"<@{id}>"
        self.display_avatar = SimpleNamespace(url="https://example.com/a.png")
        self.send = AsyncMock()
        self.add_roles = AsyncMock()
        self.guild = guild
        self.roles = roles if roles is not None else []

    def __str__(self):
        return self.display_name


class _FakeClientUser:
    id = 42
    mention = "<@42>"

    def __str__(self):
        return "SentriX"


def _fake_ctx(*, actor_top=20, target_top=1, owner_id=1):
    guild = SimpleNamespace(
        id=555,
        name="Serveur Test",
        owner_id=owner_id,
        me=_FakeMember(999, top_role_position=30),
        ban=AsyncMock(),
        get_role=lambda role_id: None,
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
    def __init__(self, *, case_number=5, fetchall_rows=None, guild_config=None):
        self.fetchone = AsyncMock(return_value=None)  # pas de gabarit MP personnalisé
        self.record_sanction = AsyncMock(return_value=case_number)
        self.get_sanction_count = AsyncMock(return_value=1)
        self.execute = AsyncMock()
        self.fetchall = AsyncMock(return_value=fetchall_rows if fetchall_rows is not None else [{"id": 1}])
        self.get_guild_config = AsyncMock(return_value=guild_config)


def _make_cog(*, case_number=5, fetchall_rows=None, guild_config=None):
    bot = SimpleNamespace(
        db=_FakeDB(case_number=case_number, fetchall_rows=fetchall_rows, guild_config=guild_config),
        user=_FakeClientUser(),
    )
    cog = Moderation.__new__(Moderation)
    cog.bot = bot
    cog.log_action = AsyncMock()
    return cog


class WarnCogWiringTests(unittest.IsolatedAsyncioTestCase):
    async def test_avertissement_reussi_appelle_le_service_et_rend_le_panneau(self):
        cog = _make_cog(case_number=5, fetchall_rows=[{"id": 1}])
        ctx, guild, actor, target = _fake_ctx()

        await Moderation.warn.callback(cog, ctx, target, raison="spam")

        cog.bot.db.execute.assert_awaited_once()  # INSERT INTO warnings
        ctx.send.assert_awaited()
        cog.log_action.assert_awaited_once()
        guild.ban.assert_not_awaited()  # pas de seuil configuré -> pas de ban automatique

    async def test_refus_de_hierarchie_n_insere_jamais_d_avertissement(self):
        cog = _make_cog()
        ctx, guild, actor, target = _fake_ctx(actor_top=1, target_top=20)

        await Moderation.warn.callback(cog, ctx, target, raison="spam")

        cog.bot.db.execute.assert_not_awaited()
        ctx.send.assert_awaited()

    async def test_echec_du_dossier_n_empeche_pas_le_panneau_de_succes(self):
        cog = _make_cog()
        cog.bot.db.record_sanction = AsyncMock(side_effect=RuntimeError("disque plein"))
        ctx, guild, actor, target = _fake_ctx()

        await Moderation.warn.callback(cog, ctx, target, raison="spam")

        ctx.send.assert_awaited()
        panneau = ctx.send.await_args.kwargs.get("view")
        self.assertIsInstance(panneau, panels.Panneau)
        self.assertEqual(panneau.kind, "moderation")

    async def test_echec_du_comptage_n_empeche_pas_le_panneau_de_succes(self):
        cog = _make_cog()
        cog.bot.db.fetchall = AsyncMock(side_effect=RuntimeError("disque plein"))
        ctx, guild, actor, target = _fake_ctx()

        await Moderation.warn.callback(cog, ctx, target, raison="spam")

        ctx.send.assert_awaited()
        panneau = ctx.send.await_args.kwargs.get("view")
        self.assertIsInstance(panneau, panels.Panneau)
        texte = panels.texte_complet(panneau)
        self.assertIn("inconnu", texte)

    async def test_ban_automatique_declenche_au_seuil_appelle_guild_ban(self):
        cog = _make_cog(
            fetchall_rows=[{"id": 1}, {"id": 2}, {"id": 3}],
            guild_config={"warn_role": None, "warn_ban_threshold": 3},
        )
        ctx, guild, actor, target = _fake_ctx()

        await Moderation.warn.callback(cog, ctx, target, raison="spam")

        guild.ban.assert_awaited_once()
        target.send.assert_awaited()  # MP envoyé au moins une fois (gabarit par défaut, warn et/ou ban)
        cog.log_action.assert_awaited()  # une fois pour le warn, une fois pour le ban automatique
        self.assertEqual(cog.log_action.await_count, 2)

    async def test_echec_discord_du_ban_automatique_affiche_un_message_dedie(self):
        cog = _make_cog(
            fetchall_rows=[{"id": 1}, {"id": 2}, {"id": 3}],
            guild_config={"warn_role": None, "warn_ban_threshold": 3},
        )
        ctx, guild, actor, target = _fake_ctx()
        guild.ban = AsyncMock(side_effect=discord.HTTPException(Mock(status=403), "refusé"))

        await Moderation.warn.callback(cog, ctx, target, raison="spam")

        guild.ban.assert_awaited_once()
        # Le panneau du warn ET le message d'échec du ban automatique sont envoyés.
        self.assertGreaterEqual(ctx.send.await_count, 2)


if __name__ == "__main__":
    unittest.main()
