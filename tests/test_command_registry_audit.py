from __future__ import annotations

from types import SimpleNamespace

import pytest

from utils.command_registry_audit import (
    assert_registry_clean,
    audit_command_registry,
    critical_issues,
)


class FakeTree:
    def __init__(self, roots):
        self.roots = list(roots)

    def get_commands(self, **_kwargs):
        return list(self.roots)


class FakeBot:
    def __init__(self, roots=(), prefix=()):
        self.tree = FakeTree(roots)
        self._prefix = list(prefix)

    def walk_commands(self):
        return list(self._prefix)


def slash(name, *, callback=None, description="Description", children=(), parameters=()):
    return SimpleNamespace(
        name=name,
        callback=callback,
        description=description,
        commands=list(children),
        parameters=list(parameters),
    )


def prefix(name, callback, *, hidden=False, description="Description", aliases=()):
    return SimpleNamespace(
        name=name,
        qualified_name=name,
        callback=callback,
        hidden=hidden,
        description=description,
        help=None,
        aliases=list(aliases),
    )


def test_clean_registry_has_no_critical_issue():
    async def play():
        return None

    bot = FakeBot(
        roots=[
            slash(
                "musique",
                children=[slash("jouer", callback=play, description="Jouer un titre.")],
                description="Commandes musique.",
            )
        ],
        prefix=[prefix("music play", play)],
    )

    issues = audit_command_registry(bot)

    assert critical_issues(issues) == []
    assert_registry_clean(bot)


def test_duplicate_slash_callback_is_critical():
    async def same_business_action():
        return None

    bot = FakeBot(
        roots=[
            slash("a", callback=same_business_action),
            slash("b", callback=same_business_action),
        ],
        prefix=[prefix("business", same_business_action)],
    )

    codes = {issue.code for issue in critical_issues(audit_command_registry(bot))}
    assert "duplicate-slash-callback" in codes


def test_duplicate_slash_path_is_critical_even_with_different_callbacks():
    async def first():
        return None

    async def second():
        return None

    bot = FakeBot(
        roots=[
            slash("outil", callback=first),
            slash("outil", callback=second),
        ]
    )

    codes = {issue.code for issue in critical_issues(audit_command_registry(bot))}
    assert "duplicate-slash-path" in codes


def test_internal_ctx_option_and_legacy_generic_name_are_critical():
    async def callback(ctx: str):
        return None

    bot = FakeBot(
        roots=[
            slash(
                "musique",
                children=[
                    slash(
                        "more",
                        callback=callback,
                        parameters=[SimpleNamespace(name="ctx")],
                    )
                ],
            )
        ]
    )

    codes = {issue.code for issue in critical_issues(audit_command_registry(bot))}
    assert "internal-option-exposed" in codes
    assert "legacy-generic-name" in codes


def test_group_over_discord_child_limit_is_critical():
    children = [
        slash(f"cmd-{index}", callback=(lambda: None))
        for index in range(26)
    ]
    bot = FakeBot(roots=[slash("outils", children=children)])

    issues = audit_command_registry(bot)

    assert any(issue.code == "slash-group-limit" for issue in critical_issues(issues))


def test_hidden_business_callback_must_not_stay_published_as_slash():
    async def callback():
        return None

    bot = FakeBot(
        roots=[slash("obsolete", callback=callback)],
        prefix=[prefix("obsolete", callback, hidden=True)],
    )

    issues = audit_command_registry(bot)

    assert any(
        issue.code == "hidden-command-still-slash"
        for issue in critical_issues(issues)
    )


def test_prefix_alias_hygiene_is_reported_without_breaking_ci():
    async def callback():
        return None

    bot = FakeBot(
        prefix=[
            prefix(
                "ping",
                callback,
                aliases=["ping", "p", "p"],
            )
        ]
    )

    issues = audit_command_registry(bot)
    codes = {issue.code for issue in issues}

    assert "useless-self-alias" in codes
    assert "duplicate-prefix-alias" in codes
    assert critical_issues(issues) == []


def test_assert_registry_clean_explains_critical_regressions():
    bot = FakeBot(roots=[slash("page-2", callback=lambda: None)])

    with pytest.raises(AssertionError, match="legacy-generic-name"):
        assert_registry_clean(bot)
