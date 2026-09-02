"""Preuve que ``+commande`` et ``/commande`` rendent la MÊME décision.

Couvre les sept profils demandés : membre, modérateur limité, administrateur,
propriétaire du serveur, owner global SentriX, rôle personnalisé, @everyone.
"""
from __future__ import annotations

import asyncio
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils import access_matrix as M  # noqa: E402

GUILD_ID = 100
OWNER_ID = 1          # propriétaire du serveur Discord
GLOBAL_OWNER_ID = 9   # créateur SentriX
ROLE_MOD = 500
ROLE_CUSTOM = 501
ROLE_EVERYONE = GUILD_ID  # @everyone porte l'id de la guilde


class Perms:
    def __init__(self, **flags):
        self._flags = flags

    def __getattr__(self, item):
        return self._flags.get(item, False)


class Role:
    def __init__(self, rid):
        self.id = rid


class Member:
    def __init__(self, uid, *, roles=(), **perms):
        self.id = uid
        self.roles = [Role(r) for r in roles]
        self.guild_permissions = Perms(**perms)


class Guild:
    def __init__(self, gid=GUILD_ID, owner_id=OWNER_ID):
        self.id = gid
        self.owner_id = owner_id


class FakeBackend(M.Backend):
    """Backend en mémoire : aucune base, décisions déterministes."""

    def __init__(self, *, rules=None, modules=None, blacklist=None,
                 staff_role=ROLE_MOD, embed_roles=(), ai=None):
        self.rules = rules or {}          # (subject_type, subject_id, cmd) -> bool
        self.modules = modules or {}      # module -> bool
        self.blacklist = blacklist or {}
        self.staff_role = staff_role
        self.embed_roles = set(embed_roles)
        self.ai = ai or {"commands_enabled": True, "image_generation_enabled": True}

    async def is_global_owner(self, user_id):
        return int(user_id) == GLOBAL_OWNER_ID

    async def blacklist_reason(self, user_id):
        return self.blacklist.get(int(user_id))

    async def module_enabled(self, guild_id, module):
        return self.modules.get(module, True)

    async def explicit_rule(self, guild_id, author, name):
        uid = getattr(author, "id", None)
        if uid is not None and ("user", int(uid), name) in self.rules:
            return self.rules[("user", int(uid), name)], "user"
        role_hits = [self.rules[("role", r.id, name)]
                     for r in getattr(author, "roles", ())
                     if ("role", r.id, name) in self.rules]
        if role_hits:
            return (False not in role_hits), "role"
        if ("everyone", 0, name) in self.rules:
            return self.rules[("everyone", 0, name)], "everyone"
        return None, ""

    async def has_staff_role(self, guild_id, author):
        return any(r.id == self.staff_role for r in getattr(author, "roles", ()))

    async def can_use_embed_builder(self, guild_id, author):
        p = getattr(author, "guild_permissions", None)
        if p is not None and (p.manage_messages or p.manage_guild):
            return True
        return bool(self.embed_roles & {r.id for r in getattr(author, "roles", ())})

    async def ai_features(self, guild_id):
        return dict(self.ai)


class Bot:
    def __init__(self, backend):
        self.sentrix_access_backend = backend
        self.blacklist_cache = {}


def decide(backend, author, name, guild=None):
    bot = Bot(backend)
    return asyncio.run(
        M.evaluate(bot, command_name=name, author=author,
                   guild=Guild() if guild is None else guild)
    )


# --------------------------------------------------------------- les profils
def member():
    return Member(10)


def limited_mod():
    """Warn/Mute/Clear/Kick ON, Ban OFF — sans Administrateur."""
    return Member(11, roles=[ROLE_MOD], moderate_members=True,
                  manage_messages=True, kick_members=True, ban_members=False)


def administrator():
    return Member(12, administrator=True)


def guild_owner():
    return Member(OWNER_ID)


def global_owner():
    return Member(GLOBAL_OWNER_ID)


def custom_role_member():
    return Member(13, roles=[ROLE_CUSTOM])


ALL_COMMANDS = sorted(M.KNOWN_COMMANDS)


class ParityTests(unittest.TestCase):
    """Le coeur : + et / partagent la même fonction, donc la même décision."""

    def test_prefix_and_slash_agree_on_every_command_for_every_profile(self):
        # Load only permission_guard.py. Importing ``cogs`` executes the whole
        # cog registry and incorrectly requires a production DISCORD_TOKEN in
        # this isolated unit test.
        import importlib.util
        guard_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "cogs", "permission_guard.py",
        )
        spec = importlib.util.spec_from_file_location(
            "sentrix_permission_guard_under_test", guard_path
        )
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        pg = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(pg)

        class Cmd:
            def __init__(self, name):
                self.name = name
                self.root_parent = None

        class Ctx:
            def __init__(self, cmd, author, guild):
                self.command, self.author, self.guild = cmd, author, guild

        class Interaction:
            def __init__(self, cmd, user, guild):
                self.command, self.user, self.guild = cmd, user, guild
                self.data = {"name": cmd.name}

        backend = FakeBackend()
        profiles = [member(), limited_mod(), administrator(),
                    guild_owner(), global_owner(), custom_role_member()]
        divergences = []
        for name in ALL_COMMANDS:
            cmd = Cmd(name)
            for who in profiles:
                bot = Bot(backend)
                guild = Guild()
                prefix = asyncio.run(pg.evaluate_command_access(
                    bot, command_name=pg.command_root_name(cmd),
                    author=who, guild=guild))
                slash = asyncio.run(pg.evaluate_interaction_access(
                    bot, Interaction(cmd, who, guild)))
                if (prefix.allowed, prefix.policy) != (slash.allowed, slash.policy):
                    divergences.append((name, who.id, prefix.policy, slash.policy))
        self.assertEqual(divergences, [], f"{len(divergences)} divergence(s) +/ vs /")

    def test_every_command_is_classified(self):
        unclassified = [c for c in ALL_COMMANDS if M.access_tier(c) == "fail-closed"]
        self.assertEqual(unclassified, [])

    def test_no_command_sits_in_two_levels(self):
        overlaps = []
        for n in ALL_COMMANDS:
            hits = sum([
                n in M.PUBLIC_COMMANDS,
                n in M.OWNER_ONLY_COMMANDS,
                n in M.CUSTOM_PERMISSION_COMMANDS,
                n in M.DISCORD_PERMISSION_COMMANDS,
                sum(n in s for s in M.CATEGORY_COMMANDS.values()),
            ])
            if hits > 1:
                overlaps.append(n)
        self.assertEqual(overlaps, [])


class MemberTests(unittest.TestCase):
    def test_member_gets_public_commands(self):
        b = FakeBackend()
        for cmd in ("help", "balance", "ping", "level", "ticket"):
            self.assertTrue(decide(b, member(), cmd).allowed, cmd)

    def test_member_gets_no_moderation_or_admin_command(self):
        b = FakeBackend()
        for cmd in ("ban", "kick", "mute", "clear", "setup", "antiraid", "dmall"):
            self.assertFalse(decide(b, member(), cmd).allowed, cmd)

    def test_denial_always_carries_the_standard_header(self):
        d = decide(FakeBackend(), member(), "ban")
        self.assertFalse(d.allowed)
        self.assertTrue(d.message.startswith(M.DENIAL_HEADER))
        self.assertIn("Bannir des membres", d.message)


class LimitedModeratorTests(unittest.TestCase):
    """Warn ON, Mute ON, Clear ON, Kick ON, Ban OFF — sans Administrateur."""

    def setUp(self):
        self.b = FakeBackend()
        self.mod = limited_mod()

    def test_allowed_actions(self):
        for cmd in ("warn", "mute", "clear", "kick"):
            self.assertTrue(decide(self.b, self.mod, cmd).allowed, cmd)

    def test_ban_is_refused(self):
        d = decide(self.b, self.mod, "ban")
        self.assertFalse(d.allowed)
        self.assertEqual(d.policy, "discord:ban_members")

    def test_no_administrator_needed_for_an_explicit_setup_allow(self):
        b = FakeBackend(rules={("role", ROLE_MOD, "ban"): True})
        d = decide(b, self.mod, "ban")
        self.assertTrue(d.allowed)
        self.assertEqual(d.policy, "setup:role:allow")

    def test_configured_staff_role_replaces_the_discord_permission(self):
        plain = Member(14, roles=[ROLE_MOD])
        d = decide(self.b, plain, "mute")
        self.assertTrue(d.allowed)
        self.assertEqual(d.policy, "staff-role")


class AdministratorTests(unittest.TestCase):
    def test_administrator_reaches_server_functions(self):
        b = FakeBackend()
        for cmd in ("setup", "antiraid", "ticketsetup", "ban"):
            self.assertTrue(decide(b, administrator(), cmd).allowed, cmd)

    def test_administrator_never_reaches_global_owner_commands(self):
        b = FakeBackend()
        for cmd in sorted(M.OWNER_ONLY_COMMANDS):
            d = decide(b, administrator(), cmd)
            self.assertFalse(d.allowed, cmd)
            self.assertEqual(d.policy, "owner-global")

    def test_administrator_cannot_broadcast_to_every_member(self):
        d = decide(FakeBackend(), administrator(), "dmall")
        self.assertFalse(d.allowed)
        self.assertEqual(d.policy, "guild-owner-only")

    def test_explicit_setup_deny_beats_administrator(self):
        b = FakeBackend(rules={("everyone", 0, "ban"): False})
        d = decide(b, administrator(), "ban")
        self.assertFalse(d.allowed)
        self.assertEqual(d.policy, "setup:everyone:deny")


class GuildOwnerTests(unittest.TestCase):
    def test_guild_owner_reaches_his_own_server_functions(self):
        b = FakeBackend()
        for cmd in ("setup", "ban", "antiraid", "ticketsetup", "dmall"):
            self.assertTrue(decide(b, guild_owner(), cmd).allowed, cmd)

    def test_guild_owner_never_reaches_global_owner_commands(self):
        b = FakeBackend()
        for cmd in sorted(M.OWNER_ONLY_COMMANDS):
            self.assertFalse(decide(b, guild_owner(), cmd).allowed, cmd)

    def test_guild_owner_is_still_bound_by_an_explicit_deny(self):
        b = FakeBackend(rules={("everyone", 0, "ban"): False})
        self.assertFalse(decide(b, guild_owner(), "ban").allowed)

    def test_guild_owner_cannot_lock_himself_out_of_setup(self):
        b = FakeBackend(rules={("everyone", 0, "setup"): False})
        d = decide(b, guild_owner(), "setup")
        self.assertTrue(d.allowed)
        self.assertEqual(d.policy, "guild-owner:setup-recovery")

    def test_none_ids_never_grant_guild_owner_access(self):
        """None == None ouvrait l'accès dans l'ancien wrapper V2."""
        ghost = Member(None)
        ghost.id = None
        b = FakeBackend()
        self.assertFalse(decide(b, ghost, "ban", guild=Guild(owner_id=None)).allowed)


class GlobalOwnerTests(unittest.TestCase):
    def test_global_owner_keeps_global_commands(self):
        b = FakeBackend()
        for cmd in sorted(M.OWNER_ONLY_COMMANDS):
            self.assertTrue(decide(b, global_owner(), cmd).allowed, cmd)

    def test_global_owner_passes_even_when_a_module_is_off(self):
        b = FakeBackend(modules={"moderation": False, "economy": False})
        self.assertTrue(decide(b, global_owner(), "ban").allowed)

    def test_global_owner_is_not_blocked_by_the_blacklist(self):
        b = FakeBackend(blacklist={GLOBAL_OWNER_ID: "test"})
        self.assertTrue(decide(b, global_owner(), "ping").allowed)


class CustomRoleTests(unittest.TestCase):
    def test_custom_role_allow_works_without_any_discord_permission(self):
        b = FakeBackend(rules={("role", ROLE_CUSTOM, "warn"): True})
        d = decide(b, custom_role_member(), "warn")
        self.assertTrue(d.allowed)
        self.assertEqual(d.policy, "setup:role:allow")

    def test_deny_wins_when_a_member_holds_two_conflicting_roles(self):
        both = Member(15, roles=[ROLE_MOD, ROLE_CUSTOM])
        b = FakeBackend(rules={("role", ROLE_MOD, "warn"): True,
                               ("role", ROLE_CUSTOM, "warn"): False})
        d = decide(b, both, "warn")
        self.assertFalse(d.allowed, "un refus de rôle doit l'emporter")

    def test_user_rule_beats_role_rule(self):
        who = Member(16, roles=[ROLE_CUSTOM])
        b = FakeBackend(rules={("role", ROLE_CUSTOM, "warn"): False,
                               ("user", 16, "warn"): True})
        self.assertEqual(decide(b, who, "warn").policy, "setup:user:allow")

    def test_everyone_rule_applies_and_role_rule_beats_it(self):
        b = FakeBackend(rules={("everyone", 0, "warn"): True})
        self.assertTrue(decide(b, member(), "warn").allowed)
        b2 = FakeBackend(rules={("everyone", 0, "warn"): True,
                                ("role", ROLE_CUSTOM, "warn"): False})
        self.assertFalse(decide(b2, custom_role_member(), "warn").allowed)

    def test_no_setup_rule_can_open_a_global_owner_command(self):
        for subject in (("everyone", 0), ("role", ROLE_CUSTOM), ("user", 13)):
            b = FakeBackend(rules={(subject[0], subject[1], "bl"): True})
            d = decide(b, custom_role_member(), "bl")
            self.assertFalse(d.allowed, subject)
            self.assertEqual(d.policy, "owner-global")


class ModuleTests(unittest.TestCase):
    def test_disabled_module_blocks_even_the_guild_owner(self):
        b = FakeBackend(modules={"moderation": False})
        d = decide(b, guild_owner(), "ban")
        self.assertFalse(d.allowed)
        self.assertEqual(d.policy, "module:moderation:off")

    def test_ai_image_switch_covers_image_and_image_prompt(self):
        b = FakeBackend(ai={"commands_enabled": True,
                            "image_generation_enabled": False})
        for cmd in ("image", "image-prompt"):
            d = decide(b, member(), cmd)
            self.assertFalse(d.allowed, cmd)
            self.assertEqual(d.policy, "ai:image-off")

    def test_ai_setup_stays_reachable_when_ai_commands_are_off(self):
        b = FakeBackend(ai={"commands_enabled": False,
                            "image_generation_enabled": False})
        self.assertTrue(decide(b, administrator(), "aisetup").allowed)


class HelpTests(unittest.TestCase):
    def test_help_is_public(self):
        self.assertTrue(decide(FakeBackend(), member(), "help").allowed)

    def test_every_command_exposes_a_requirement_label(self):
        for cmd in ALL_COMMANDS:
            label = M.help_requirement(cmd)
            self.assertTrue(label and isinstance(label, str), cmd)
            self.assertNotEqual(label, "Administrateur (commande non classée)", cmd)

    def test_admin_commands_stay_visible_with_their_requirement(self):
        self.assertEqual(M.help_requirement("ban"),
                         "Bannir des membres (ou rôle autorisé dans Setup)")
        self.assertEqual(M.help_requirement("bl"),
                         "Propriétaire global SentriX")
        self.assertEqual(M.help_requirement("dmall"),
                         "Propriétaire du serveur uniquement")


class ProductionSchemaTests(unittest.TestCase):
    def test_backend_reads_the_setup_v2_permission_table(self):
        import inspect
        source = inspect.getsource(M.Backend.explicit_rule)
        self.assertIn("command_role_permissions", source)
        self.assertNotIn("command_access_rules", source)

    def test_backend_reads_the_setup_v2_ai_feature_table(self):
        import inspect
        source = inspect.getsource(M.Backend.ai_features)
        self.assertIn("ai_feature_settings_v2", source)
        self.assertNotIn("FROM ai_features ", source)


class NormalisationTests(unittest.TestCase):
    def test_both_transports_normalise_identically(self):
        for raw in (" Ban ", "BAN", "+ban", "/ban", "ban"):
            self.assertEqual(M.normalise(raw), "ban")

    def test_blacklisted_user_is_refused_everywhere(self):
        b = FakeBackend(blacklist={10: "spam"})
        d = decide(b, member(), "ping")
        self.assertFalse(d.allowed)
        self.assertEqual(d.policy, "global-blacklist")


if __name__ == "__main__":
    unittest.main(verbosity=2)
