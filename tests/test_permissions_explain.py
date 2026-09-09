"""cogs/permissions_explain.py — /permissions explain (Core V2, Phase 3, section 6
de la demande initiale). Enveloppe fine autour de utils/access_matrix.py::evaluate() :
ces tests vérifient le CÂBLAGE (verdict rendu fidèlement, restriction "autre membre"
aux administrateurs) — la logique de décision elle-même est déjà testée séparément
dans tests/test_access_tiers_5.py."""
from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import discord

from cogs.permissions_explain import PermissionsExplain, _policy_label
from utils import sentrix_panels as panels


class _FakePerms:
    def __init__(self, **kwargs):
        self._values = kwargs

    def __getattr__(self, name):
        return self._values.get(name, False)


class _FakeMember:
    def __init__(self, id, *, perms=None, guild=None):
        self.id = id
        self.guild_permissions = perms or _FakePerms()
        self.mention = f"<@{id}>"
        self.guild = guild


def _fake_guild(owner_id=1):
    return SimpleNamespace(id=555, owner_id=owner_id)


def _fake_bot():
    return SimpleNamespace(db=SimpleNamespace(
        is_bot_creator=AsyncMock(return_value=False),
        blacklist_reason=AsyncMock(return_value=None),
        is_global_owner=AsyncMock(return_value=False),
        module_enabled=AsyncMock(return_value=True),
        explicit_rule=AsyncMock(return_value=(None, "")),
        has_staff_role=AsyncMock(return_value=False),
    ))


def _fake_ctx(author, guild, bot=None):
    return SimpleNamespace(
        guild=guild,
        author=author,
        interaction=None,
        send=AsyncMock(),
        bot=bot,
    )


class SelfCheckTests(unittest.IsolatedAsyncioTestCase):
    async def test_un_membre_peut_verifier_sa_propre_permission(self):
        guild = _fake_guild()
        bot = _fake_bot()
        membre = _FakeMember(42, perms=_FakePerms(administrator=False))
        cog = PermissionsExplain(bot)
        ctx = _fake_ctx(membre, guild, bot=bot)

        await PermissionsExplain.permissions_explain.callback(cog, ctx, "ban", None)

        ctx.send.assert_awaited()
        panneau = ctx.send.await_args.kwargs.get("view")
        self.assertIsInstance(panneau, panels.Panneau)
        self.assertIn("Diagnostic pour", panels.texte_complet(panneau))

    async def test_refuse_le_diagnostic_d_un_autre_membre_sans_etre_administrateur(self):
        guild = _fake_guild()
        bot = _fake_bot()
        auteur = _FakeMember(42, perms=_FakePerms(administrator=False))
        cible = _FakeMember(99, perms=_FakePerms(administrator=False))
        cog = PermissionsExplain(bot)
        ctx = _fake_ctx(auteur, guild, bot=bot)

        await PermissionsExplain.permissions_explain.callback(cog, ctx, "ban", cible)

        panneau = ctx.send.await_args.kwargs.get("view")
        self.assertIn("réservé aux administrateurs", panels.texte_complet(panneau))

    async def test_autorise_un_administrateur_a_diagnostiquer_un_autre_membre(self):
        guild = _fake_guild()
        bot = _fake_bot()
        auteur = _FakeMember(42, perms=_FakePerms(administrator=True))
        cible = _FakeMember(99, perms=_FakePerms(administrator=False))
        cog = PermissionsExplain(bot)
        ctx = _fake_ctx(auteur, guild, bot=bot)

        await PermissionsExplain.permissions_explain.callback(cog, ctx, "ban", cible)

        panneau = ctx.send.await_args.kwargs.get("view")
        # Le panneau de résultat contient toujours "Diagnostic pour", jamais le
        # message de refus "réservé aux administrateurs".
        texte = panels.texte_complet(panneau)
        self.assertIn("Diagnostic pour", texte)
        # Les faits de contexte (duck-typing sur guild_permissions, pas
        # isinstance) apparaissent bien pour une cible qui n'est pas un vrai
        # discord.Member — exactement le scénario testé ici avec _FakeMember.
        self.assertIn("Administrateur Discord", texte)
        self.assertIn("Propriétaire du serveur", texte)


class PolicyLabelTests(unittest.TestCase):
    def test_traduit_une_permission_discord(self):
        label = _policy_label("discord:ban_members")
        self.assertIn("Bannir", label)

    def test_traduit_une_regle_setup_allow(self):
        self.assertIn("Setup", _policy_label("setup:role:allow"))
        self.assertIn("autorisation", _policy_label("setup:role:allow"))

    def test_traduit_une_regle_setup_deny(self):
        self.assertIn("refus", _policy_label("setup:role:deny"))

    def test_traduit_fail_closed(self):
        self.assertIn("Administrateur", _policy_label("fail-closed"))

    def test_valeur_inconnue_ne_plante_pas(self):
        self.assertTrue(_policy_label("un-tag-jamais-vu"))


if __name__ == "__main__":
    unittest.main()
