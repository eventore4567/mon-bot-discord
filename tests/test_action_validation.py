"""Non-régression : les commandes critiques gardent leur VALIDATION MÉTIER.

Ce test ne se contente pas de vérifier que ``command.checks`` est non vide — un
ancien check d'autorisation suffirait à le tromper. Il vérifie la nature du
check via la convention ``_sentrix_check_kind`` et la présence effective de la
validation de cible dans le corps de la commande.
"""
from __future__ import annotations

import ast
import os
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from utils import checks  # noqa: E402

# Doit rester aligné sur HIGH_RISK_LOCAL_CHECK de tools/permission_matrix_gate.py
CRITICAL = {
    "ban": ("ban_members", "member_moderation"),
    "unban": ("ban_members", "external_user"),
    "kick": ("kick_members", "member_moderation"),
    "mute": ("moderate_members", "member_moderation"),
    "unmute": ("moderate_members", "member_moderation"),
    "warn": ("moderate_members", "member_moderation"),
    "clear": ("manage_messages", "channel_target"),
    "lock": ("manage_channels", "channel_target"),
    "unlock": ("manage_channels", "channel_target"),
    "nickname": ("manage_nicknames", "member_moderation"),
    "resetnick": ("manage_nicknames", "member_moderation"),
    "giverole": ("manage_roles", "role_target"),
    "removerole": ("manage_roles", "role_target"),
}

# Validation de cible attendue dans le CORPS (les checks tournent avant le
# parsing des arguments, la cible n'y est donc pas disponible).
BODY_VALIDATOR = {
    "member_moderation": ("check_targetable", "check_hierarchy"),
    "role_target": ("check_role_target",),
    "channel_target": ("check_channel_target", "purge"),
    # La cible de +unban n'est pas membre du serveur : la hiérarchie n'a pas
    # d'objet. La validation métier consiste à résoudre l'identifiant et à
    # traiter proprement le cas "pas banni / inexistant".
    "external_user": ("fetch_user", "NotFound"),
}

SOURCES = ("cogs/moderation.py", "cogs/verification.py")


def _extract(decorator):
    """Récupère le prédicat posé par commands.check() sur une fonction nue."""

    async def target(ctx):
        return True

    decorator(target)
    return target.__commands_checks__[0]


def _decorated_commands():
    """{nom: (decorateurs, source du corps)} pour les commandes critiques."""
    found = {}
    for rel in SOURCES:
        tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
        src = (ROOT / rel).read_text(encoding="utf-8").splitlines()
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            name = None
            decos = []
            for d in node.decorator_list:
                decos.append(ast.unparse(d))
                if isinstance(d, ast.Call):
                    fn = ast.unparse(d.func)
                    if fn.endswith(("hybrid_command", "command")):
                        for kw in d.keywords:
                            if kw.arg == "name":
                                try:
                                    name = ast.literal_eval(kw.value)
                                except Exception:
                                    pass
            if name in CRITICAL:
                body = "\n".join(src[node.lineno - 1:node.end_lineno])
                found[name] = (decos, body)
    return found


class ConventionTests(unittest.TestCase):
    def test_action_validation_is_marked_as_business_validation(self):
        deco = checks.action_validation(bot_permissions=("ban_members",),
                                        target="member_moderation")
        predicate = _extract(deco)
        self.assertEqual(predicate._sentrix_check_kind,
                         checks.CHECK_KIND_ACTION_VALIDATION)
        self.assertEqual(predicate._sentrix_action_target, "member_moderation")
        self.assertTrue(predicate._sentrix_keep)

    def test_authorization_checks_are_marked_as_authorization(self):
        predicate = _extract(checks.has_permission_or_modrole("ban_members"))
        self.assertEqual(predicate._sentrix_check_kind,
                         checks.CHECK_KIND_AUTHORIZATION)


class CriticalCommandTests(unittest.TestCase):
    def setUp(self):
        self.found = _decorated_commands()

    def test_every_critical_command_is_found(self):
        self.assertEqual(sorted(self.found), sorted(CRITICAL))

    def test_critical_commands_declare_action_validation(self):
        """Échoue si une commande critique perd sa validation métier."""
        missing = []
        for name, (decos, _) in self.found.items():
            if not any("action_validation" in d for d in decos):
                missing.append(name)
        self.assertEqual(missing, [], f"validation métier absente : {missing}")

    def test_action_validation_declares_the_right_bot_permission(self):
        wrong = []
        for name, (decos, _) in self.found.items():
            expected_perm, expected_target = CRITICAL[name]
            deco = next((d for d in decos if "action_validation" in d), "")
            if expected_perm not in deco or expected_target not in deco:
                wrong.append((name, deco))
        self.assertEqual(wrong, [])

    def test_critical_commands_still_validate_their_target_in_the_body(self):
        """La cible n'est pas visible dans un check : le corps doit la valider."""
        missing = []
        for name, (_, body) in self.found.items():
            _, target = CRITICAL[name]
            if not any(v in body for v in BODY_VALIDATOR[target]):
                missing.append(name)
        self.assertEqual(missing, [], f"validation de cible absente : {missing}")

    def test_no_critical_command_keeps_a_local_authorization_check(self):
        """L'autorisation appartient à access_matrix, pas au cog."""
        leftovers = []
        for name, (decos, _) in self.found.items():
            for d in decos:
                if "has_permission_or_modrole" in d or "has_permissions" in d:
                    leftovers.append((name, d))
        self.assertEqual(leftovers, [])


class StripSafetyTests(unittest.TestCase):
    """Le nettoyage des checks doit être fail-safe."""

    def test_unmarked_check_is_never_removed(self):
        from cogs import permission_guard

        async def mystery(ctx):
            return True

        self.assertFalse(
            permission_guard._is_redundant_authorization_check(mystery),
            "un check non marqué doit être conservé (fail-safe)",
        )

    def test_action_validation_check_is_never_removed(self):
        from cogs import permission_guard

        predicate = _extract(checks.action_validation(
            bot_permissions=("ban_members",), target="member_moderation"))
        self.assertFalse(
            permission_guard._is_redundant_authorization_check(predicate)
        )

    def test_authorization_check_is_removed(self):
        from cogs import permission_guard

        predicate = _extract(checks.has_permission_or_modrole("ban_members"))
        self.assertTrue(
            permission_guard._is_redundant_authorization_check(predicate)
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
