"""cogs/moderation.py::kick — Core V2, Phase 2 : même câblage que ban() (voir
tests/test_moderation_ban_cog_wiring.py), adaptée pour l'expulsion."""
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
        kick=AsyncMock(),
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
    def __init__(self, *, case_number=17):
        self.fetchone = AsyncMock(return_value=None)  # pas de gabarit MP personnalisé
        self.record_sanction = AsyncMock(return_value=case_number)
        self.get_sanction_count = AsyncMock(return_value=1)


def _make_cog(*, case_number=17):
    bot = SimpleNamespace(db=_FakeDB(case_number=case_number))
    cog = Moderation.__new__(Moderation)
    cog.bot = bot
    cog.log_action = AsyncMock()  # pipeline de log déjà testé séparément
    return cog


class KickCogWiringTests(unittest.IsolatedAsyncioTestCase):
    async def test_expulsion_reussie_appelle_le_service_et_rend_le_panneau(self):
        cog = _make_cog(case_number=17)
        ctx, guild, actor, target = _fake_ctx()

        await Moderation.kick.callback(cog, ctx, target, raison="spam")

        guild.kick.assert_awaited_once()
        target.send.assert_awaited_once()  # MP par défaut envoyé
        ctx.send.assert_awaited()
        cog.log_action.assert_awaited_once()

    async def test_refus_de_hierarchie_n_appelle_jamais_guild_kick(self):
        cog = _make_cog()
        ctx, guild, actor, target = _fake_ctx(actor_top=1, target_top=20)

        await Moderation.kick.callback(cog, ctx, target, raison="spam")

        guild.kick.assert_not_awaited()
        target.send.assert_not_awaited()
        ctx.send.assert_awaited()  # le panneau de refus est bien rendu

    async def test_echec_de_persistance_n_empeche_pas_le_panneau_de_succes(self):
        """Même invariant que pour ban() : la sanction Discord a réussi, donc
        le panneau reste un succès même si la persistance du dossier échoue."""
        cog = _make_cog()
        cog.bot.db.record_sanction = AsyncMock(side_effect=RuntimeError("disque plein"))
        ctx, guild, actor, target = _fake_ctx()

        await Moderation.kick.callback(cog, ctx, target, raison="spam")

        guild.kick.assert_awaited_once()
        ctx.send.assert_awaited()
        panneau = ctx.send.await_args.kwargs.get("view")
        self.assertIsInstance(panneau, panels.Panneau)
        self.assertEqual(panneau.kind, "moderation")


if __name__ == "__main__":
    unittest.main()
