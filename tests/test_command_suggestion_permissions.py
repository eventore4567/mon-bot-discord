"""Core V2, Phase 3 (docs/core-v2-plan.md) : command_response_guard._can_suggest_command
lit maintenant utils/access_matrix.py directement (l'audit avait trouvé la copie
locale de main.py en dérive de 34 commandes publiques,
docs/core-v2-audit-technical-debt.md §16). Ces tests patchent donc access_matrix
lui-même plutôt que l'ancien point d'indirection _runtime_main, retiré."""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest import mock

from cogs import command_response_guard
from utils import access_matrix


def _command(name: str, *, hidden: bool = False, enabled: bool = True):
    return SimpleNamespace(
        name=name,
        root_parent=None,
        hidden=hidden,
        enabled=enabled,
    )


def _ctx(**permissions):
    defaults = {
        "administrator": False,
        "manage_guild": False,
        "ban_members": False,
        "moderate_members": False,
        "manage_messages": False,
    }
    defaults.update(permissions)
    return SimpleNamespace(
        author=SimpleNamespace(
            guild_permissions=SimpleNamespace(**defaults)
        )
    )


class CommandSuggestionPermissionTests(unittest.TestCase):
    def _allowed(self, ctx, name: str, **command_kwargs) -> bool:
        with mock.patch.multiple(
            access_matrix,
            PUBLIC_COMMANDS={"help", "balance", "gamble"},
            OWNER_ONLY_COMMANDS={"sync", "setstatus"},
            DISCORD_PERMISSION_COMMANDS={
                "ban": "ban_members",
                "mute": "moderate_members",
                "clear": "manage_messages",
            },
            CATEGORY_COMMANDS={
                "economie": {"shopsetup", "give-money"},
                "configuration": {"setup"},
            },
        ):
            return command_response_guard._can_suggest_command(
                ctx,
                _command(name, **command_kwargs),
            )

    def test_public_command_is_suggested_to_normal_member(self):
        self.assertTrue(self._allowed(_ctx(), "balance"))
        self.assertTrue(self._allowed(_ctx(), "help"))

    def test_permission_command_requires_matching_permission(self):
        self.assertFalse(self._allowed(_ctx(), "ban"))
        self.assertTrue(self._allowed(_ctx(ban_members=True), "ban"))

    def test_admin_can_receive_staff_category_suggestion(self):
        self.assertFalse(self._allowed(_ctx(), "shopsetup"))
        self.assertTrue(self._allowed(_ctx(manage_guild=True), "shopsetup"))

    def test_owner_only_commands_are_never_leaked_by_typo_suggestions(self):
        self.assertFalse(self._allowed(_ctx(administrator=True), "sync"))

    def test_unknown_fail_closed_command_requires_admin(self):
        self.assertFalse(self._allowed(_ctx(), "mystery-admin-tool"))
        self.assertTrue(self._allowed(_ctx(administrator=True), "mystery-admin-tool"))

    def test_hidden_or_disabled_commands_are_never_suggested(self):
        self.assertFalse(self._allowed(_ctx(administrator=True), "balance", hidden=True))
        self.assertFalse(self._allowed(_ctx(administrator=True), "balance", enabled=False))


if __name__ == "__main__":
    unittest.main()
