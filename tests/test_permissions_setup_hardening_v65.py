"""Régressions V65 : Setup ne peut jamais créer une permission Discord."""
from __future__ import annotations

import asyncio
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils import access_matrix as M  # noqa: E402
from cogs.permission_setup_hardening_v65 import (  # noqa: E402
    secure_evaluate,
    secure_help_requirement,
)

GUILD_ID = 100
GUILD_OWNER_ID = 1
GLOBAL_OWNER_ID = 9
ROLE_STAFF = 500
ROLE_CUSTOM = 501


class Perms:
    def __init__(self, **flags):
        self.flags = flags

    def __getattr__(self, name):
        return self.flags.get(name, False)


class Role:
    def __init__(self, role_id):
        self.id = role_id


class Member:
    def __init__(self, user_id, *, roles=(), **perms):
        self.id = user_id
        self.roles = [Role(role_id) for role_id in roles]
        self.guild_permissions = Perms(**perms)


class Guild:
    id = GUILD_ID
    owner_id = GUILD_OWNER_ID


class Backend:
    def __init__(self, *, rules=None, modules=None, blacklist=None, ai=None):
        self.rules = rules or {}
        self.modules = modules or {}
        self.blacklist = blacklist or {}
        self.ai = ai or {"commands_enabled": True, "image_generation_enabled": True}

    async def is_global_owner(self, user_id):
        return int(user_id) == GLOBAL_OWNER_ID

    async def blacklist_reason(self, user_id):
        return self.blacklist.get(int(user_id))

    async def module_enabled(self, guild_id, module):
        return self.modules.get(module, True)

    async def explicit_rule(self, guild_id, author, name):
        hits = []
        for role in getattr(author, "roles", ()):
            key = (role.id, name)
            if key in self.rules:
                hits.append(self.rules[key])
        everyone = (GUILD_ID, name)
        if everyone in self.rules:
            hits.append(self.rules[everyone])
        if False in hits:
            return False, "role"
        if True in hits:
            return True, "role"
        return None, ""

    async def ai_features(self, guild_id):
        return dict(self.ai)


class Bot:
    def __init__(self, backend):
        self.sentrix_access_backend = backend
        self.blacklist_cache = {}


def decide(backend, member, command):
    return asyncio.run(
        secure_evaluate(
            Bot(backend), command_name=command, author=member, guild=Guild()
        )
    )


class NativePermissionTests(unittest.TestCase):
    def test_legacy_allow_cannot_grant_ban(self):
        backend = Backend(rules={(ROLE_CUSTOM, "ban"): True})
        result = decide(backend, Member(10, roles=[ROLE_CUSTOM]), "ban")
        self.assertFalse(result.allowed)
        self.assertEqual(result.policy, "discord:ban_members")

    def test_configured_staff_role_alone_cannot_grant_moderation(self):
        result = decide(Backend(), Member(11, roles=[ROLE_STAFF]), "mute")
        self.assertFalse(result.allowed)
        self.assertEqual(result.policy, "discord:moderate_members")

    def test_exact_native_permission_allows_the_action(self):
        result = decide(Backend(), Member(12, ban_members=True), "ban")
        self.assertTrue(result.allowed)
        self.assertEqual(result.policy, "discord:ban_members")

    def test_setup_deny_can_remove_an_existing_native_permission(self):
        backend = Backend(rules={(ROLE_CUSTOM, "ban"): False})
        result = decide(
            backend,
            Member(13, roles=[ROLE_CUSTOM], ban_members=True),
            "ban",
        )
        self.assertFalse(result.allowed)
        self.assertEqual(result.policy, "setup:role:deny")

    def test_administrator_is_still_native_superuser_but_deny_can_restrict(self):
        admin = Member(14, administrator=True)
        self.assertTrue(decide(Backend(), admin, "ban").allowed)
        denied = decide(Backend(rules={(GUILD_ID, "ban"): False}), admin, "ban")
        self.assertFalse(denied.allowed)

    def test_public_command_cannot_be_accidentally_blocked_by_acl(self):
        backend = Backend(rules={(GUILD_ID, "ping"): False})
        result = decide(backend, Member(15), "ping")
        self.assertTrue(result.allowed)
        self.assertEqual(result.policy, "public")

    def test_module_off_still_blocks_public_commands_in_that_module(self):
        result = decide(Backend(modules={"economy": False}), Member(15), "balance")
        self.assertFalse(result.allowed)
        self.assertEqual(result.policy, "module:economy:off")


class OwnerBoundaryTests(unittest.TestCase):
    def test_guild_admin_cannot_open_global_owner_command(self):
        result = decide(Backend(), Member(20, administrator=True), "bl")
        self.assertFalse(result.allowed)
        self.assertEqual(result.policy, "owner-global")

    def test_guild_owner_cannot_open_global_owner_command(self):
        result = decide(Backend(), Member(GUILD_OWNER_ID), "bl")
        self.assertFalse(result.allowed)
        self.assertEqual(result.policy, "owner-global")

    def test_global_owner_keeps_global_owner_command(self):
        result = decide(Backend(), Member(GLOBAL_OWNER_ID), "bl")
        self.assertTrue(result.allowed)
        self.assertEqual(result.policy, "owner-global")

    def test_setup_recovery_remains_available_to_guild_owner(self):
        backend = Backend(rules={(GUILD_ID, "setup"): False})
        result = decide(backend, Member(GUILD_OWNER_ID), "setup")
        self.assertTrue(result.allowed)
        self.assertEqual(result.policy, "guild-owner:setup-recovery")


class ConfigurationPermissionTests(unittest.TestCase):
    def test_setup_requires_manage_guild_for_non_owner_non_admin(self):
        result = decide(Backend(), Member(30), "setup")
        self.assertFalse(result.allowed)
        self.assertEqual(result.policy, "categorie:configuration")
        self.assertIn("Gérer le serveur", result.message)

    def test_manage_guild_allows_configuration_command(self):
        result = decide(Backend(), Member(31, manage_guild=True), "setup")
        self.assertTrue(result.allowed)
        self.assertEqual(result.policy, "discord:manage_guild")

    def test_complete_commands_still_require_administrator(self):
        manager = Member(32, manage_guild=True)
        self.assertFalse(decide(Backend(), manager, "wipe-server").allowed)
        admin = Member(33, administrator=True)
        self.assertTrue(decide(Backend(), admin, "wipe-server").allowed)

    def test_help_never_claims_a_setup_role_can_replace_native_permission(self):
        label = secure_help_requirement("ban")
        self.assertEqual(label, "Bannir des membres")
        self.assertNotIn("rôle autorisé", label.casefold())
        self.assertEqual(secure_help_requirement("bl"), "Propriétaire global SentriX")


class ClassificationTests(unittest.TestCase):
    def test_known_high_risk_actions_have_exact_native_permissions(self):
        expected = {
            "ban": "ban_members",
            "kick": "kick_members",
            "mute": "moderate_members",
            "clear": "manage_messages",
            "lock": "manage_channels",
            "giverole": "manage_roles",
        }
        for command, permission in expected.items():
            self.assertEqual(M.DISCORD_PERMISSION_COMMANDS.get(command), permission)


if __name__ == "__main__":
    unittest.main(verbosity=2)
