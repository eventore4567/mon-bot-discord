from __future__ import annotations

import re
from pathlib import Path


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding='utf-8')
    count = text.count(old)
    if count != 1:
        raise SystemExit(f'{path}: {label}: expected 1 occurrence, found {count}')
    path.write_text(text.replace(old, new, 1), encoding='utf-8')


def regex_replace_once(path: Path, pattern: str, replacement: str, label: str) -> None:
    text = path.read_text(encoding='utf-8')
    new, count = re.subn(pattern, replacement, text, count=1, flags=re.S)
    if count != 1:
        raise SystemExit(f'{path}: {label}: regex occurrence count={count}')
    path.write_text(new, encoding='utf-8')


matrix = Path('utils/access_matrix.py')
perm_guard = Path('cogs/permission_guard.py')
tests = Path('tests/test_access_matrix.py')

# Setup V2 persists command permissions in command_role_permissions, not in the
# synthetic command_access_rules table used by the incoming patch.
explicit_rule_impl = '''    async def explicit_rule(self, guild_id: int, author: Any, name: str):
        """Read the exact role rules persisted by Setup V2.

        Discord includes @everyone in Member.roles (its id equals guild.id), so
        one role query covers both @everyone and custom roles. If several roles
        disagree, an explicit deny wins.
        """
        role_ids = sorted(_role_ids(author))
        if not role_ids:
            return None, ""
        marks = ",".join("?" for _ in role_ids)
        try:
            rows = await self.bot.db.fetchall(
                "SELECT role_id, decision FROM command_role_permissions "
                "WHERE guild_id=? AND command_name=? "
                f"AND role_id IN ({marks})",
                (int(guild_id), name, *role_ids),
            )
        except Exception:
            logger.exception("Lecture des règles Setup impossible guild=%s", guild_id)
            return None, ""

        denied = [row for row in rows if str(row["decision"]).casefold() == "deny"]
        allowed = [row for row in rows if str(row["decision"]).casefold() == "allow"]
        if denied:
            source = "everyone" if all(int(row["role_id"]) == int(guild_id) for row in denied) else "role"
            return False, source
        if allowed:
            source = "everyone" if all(int(row["role_id"]) == int(guild_id) for row in allowed) else "role"
            return True, source
        return None, ""

'''
regex_replace_once(
    matrix,
    r'    async def explicit_rule\(.*?(?=    async def has_staff_role)',
    explicit_rule_impl,
    'replace Setup permission backend',
)
replace_once(
    matrix,
    'FROM ai_features WHERE guild_id=?',
    'FROM ai_feature_settings_v2 WHERE guild_id=?',
    'wire AI features to Setup V2 table',
)

# Explicit deny may restrict the guild owner for dangerous commands, but setup
# always stays reachable so the owner can repair the matrix.
setup_anchor = '''    # (5) et (6) règle explicite Setup
    explicit, source = await backend.explicit_rule(guild_id, author, name)
'''
setup_recovery = '''    # Recovery exception: an explicit deny may restrict the guild owner for
    # dangerous commands, but +setup and /setup must always stay reachable so
    # the owner can repair the permission matrix.
    if name == "setup" and _is_guild_owner(author, guild):
        return AccessDecision(True, policy="guild-owner:setup-recovery")

    # (5) et (6) règle explicite Setup
    explicit, source = await backend.explicit_rule(guild_id, author, name)
'''
replace_once(matrix, setup_anchor, setup_recovery, 'guild-owner setup recovery')

replace_once(
    matrix,
    ' 5. deny explicite Setup               -> refus\n 6. allow explicite Setup              -> accès, sans exiger Administrateur\n 7. owner du serveur Discord           -> accès aux fonctions de SON serveur\n',
    ' 5. setup pour owner serveur           -> accès de récupération garanti\n 6. deny explicite Setup               -> refus\n 7. allow explicite Setup              -> accès, sans exiger Administrateur\n 8. owner du serveur Discord           -> accès aux fonctions de SON serveur\n',
    'document setup recovery priority',
)
replace_once(
    matrix,
    ' 8. Administrateur Discord             -> accès serveur, jamais owner global\n 9. permission Discord requise / rôle staff configuré\n10. commande publique\n11. fail-closed                        -> Administrateur requis\n',
    ' 9. Administrateur Discord             -> accès serveur, jamais owner global\n10. permission Discord requise / rôle staff configuré\n11. commande publique\n12. fail-closed                        -> Administrateur requis\n',
    'renumber documented priority',
)
replace_once(
    matrix,
    'Pourquoi le deny explicite (5) passe AVANT l\'owner du serveur (7) : sinon un\npropriétaire ne peut pas se retirer volontairement une commande dangereuse, et\nun compte propriétaire compromis contourne toute la configuration. Le\npropriétaire garde ``setup``, qui est owner-serveur par nature, donc il peut\ntoujours se ré-accorder la règle.\n',
    'Pourquoi le deny explicite passe AVANT le bypass owner du serveur : sinon un\npropriétaire ne peut pas se retirer volontairement une commande dangereuse.\n``setup`` est l\'exception de récupération : le propriétaire du serveur y garde\ntoujours accès afin de pouvoir réparer ses propres règles.\n',
    'document deny/owner rationale',
)

# Do not delete safety/context checks. Remove only permission predicates that
# the central matrix actually replaces.
selective_strip = '''def _is_redundant_authorization_check(predicate: Any) -> bool:
    if getattr(predicate, "_sentrix_keep", False):
        return False

    label = str(getattr(predicate, "_sentrix_permission_label", "") or "")
    if label:
        # Keep the explicit global-owner check as a defence in depth. The matrix
        # returns the same decision, so it cannot create +// divergence.
        if "Propriétaire global SentriX" in label:
            return False
        return True

    module = str(getattr(predicate, "__module__", "") or "")
    qualname = str(getattr(predicate, "__qualname__", "") or "")
    if module.startswith("discord.ext.commands"):
        return (
            "has_permissions.<locals>.predicate" in qualname
            or "has_guild_permissions.<locals>.predicate" in qualname
        )
    return False


def _strip_redundant_local_checks(bot: commands.Bot) -> int:
    """Remove only local authorization checks replaced by the access matrix.

    Context and execution-safety checks (guild_only, target hierarchy,
    modifiability, bot permissions, business validation...) are deliberately
    preserved.
    """
    removed = 0
    for command in bot.walk_commands():
        root = command.root_parent or command
        if normalise(getattr(root, "name", "")) not in access_matrix.KNOWN_COMMANDS:
            continue
        for holder in (command, getattr(command, "app_command", None)):
            if holder is None:
                continue
            checks_list = getattr(holder, "checks", None)
            if not isinstance(checks_list, list):
                continue
            keep = [c for c in checks_list if not _is_redundant_authorization_check(c)]
            removed += len(checks_list) - len(keep)
            checks_list[:] = keep
    return removed


'''
regex_replace_once(
    perm_guard,
    r'def _strip_redundant_local_checks\(.*?(?=def install\()',
    selective_strip,
    'preserve safety/context checks',
)

# Regression tests for the integration issues found during review.
owner_test_anchor = '''    def test_guild_owner_is_still_bound_by_an_explicit_deny(self):
        b = FakeBackend(rules={("everyone", 0, "ban"): False})
        self.assertFalse(decide(b, guild_owner(), "ban").allowed)

'''
owner_test = owner_test_anchor + '''    def test_guild_owner_cannot_lock_himself_out_of_setup(self):
        b = FakeBackend(rules={("everyone", 0, "setup"): False})
        d = decide(b, guild_owner(), "setup")
        self.assertTrue(d.allowed)
        self.assertEqual(d.policy, "guild-owner:setup-recovery")

'''
replace_once(tests, owner_test_anchor, owner_test, 'test setup recovery')

schema_class = '''class ProductionSchemaTests(unittest.TestCase):
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


'''
replace_once(
    tests,
    'class NormalisationTests(unittest.TestCase):\n',
    schema_class + 'class NormalisationTests(unittest.TestCase):\n',
    'schema integration tests',
)

print('permissions-v3 review hotfixes applied')
