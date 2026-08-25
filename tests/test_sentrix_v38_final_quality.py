from __future__ import annotations

from types import SimpleNamespace

import discord

from cogs import community_v34
from cogs import sentrix_final_quality_v38 as quality
from cogs import sentrix_v3_global_style as visual


def test_mod_role_fallback_is_limited_to_daily_moderation() -> None:
    # Actions de modération normales : le rôle staff configuré reste utile.
    for permission in (
        "ban_members",
        "kick_members",
        "moderate_members",
        "manage_messages",
        "manage_nicknames",
        "move_members",
    ):
        assert quality.mod_role_fallback_allowed(permission)

    # Permissions structurelles / élévation de privilèges : jamais de raccourci mod-role.
    for permission in (
        "administrator",
        "manage_guild",
        "manage_channels",
        "manage_roles",
        "manage_emojis_and_stickers",
        "manage_webhooks",
    ):
        assert not quality.mod_role_fallback_allowed(permission)


def test_registered_slash_roots_include_tree_and_hybrid_roots() -> None:
    class DummyTree:
        def get_commands(self):
            return [SimpleNamespace(name="help"), SimpleNamespace(name="setup")]

    root = SimpleNamespace(name="profile")
    hybrid = SimpleNamespace(name="profile-card", root_parent=root)
    dummy_bot = SimpleNamespace(
        tree=DummyTree(),
        commands=[SimpleNamespace(name="ping", root_parent=None), hybrid],
    )
    assert quality._registered_slash_roots(dummy_bot) == frozenset({
        "help", "setup", "ping", "profile",
    })


def test_normal_slash_roots_become_public_by_default() -> None:
    class DummyTree:
        def get_commands(self):
            return [SimpleNamespace(name="help"), SimpleNamespace(name="profile")]

    dummy_bot = SimpleNamespace(
        tree=DummyTree(),
        commands=[SimpleNamespace(name="ping", root_parent=None)],
    )
    previous = community_v34.SHARED_SLASH_ROOTS
    try:
        quality._make_normal_slash_public(dummy_bot)
        assert {"help", "profile", "ping"}.issubset(community_v34.SHARED_SLASH_ROOTS)
    finally:
        community_v34.SHARED_SLASH_ROOTS = previous


def test_rich_information_panel_keeps_meaningful_title() -> None:
    quality._patch_visual_finish(visual)
    embed = discord.Embed(
        title="SentriX • Configuration",
        description="Vue générale de la configuration du serveur. " * 8,
    )
    visual._promote_real_title(embed, kind="info")
    assert embed.title == "Configuration"
    assert embed.title != "Information"


def test_short_information_card_stays_compact_and_generic() -> None:
    quality._patch_visual_finish(visual)
    embed = discord.Embed(
        title="SentriX • Utilitaires",
        description="Réponse rapide.",
    )
    visual._promote_real_title(embed, kind="info")
    assert embed.title == "Information"


def test_error_and_success_titles_are_not_rewritten_as_panel_names() -> None:
    quality._patch_visual_finish(visual)

    error = discord.Embed(title="SentriX • Sécurité", description="Action refusée.")
    visual._promote_real_title(error, kind="danger")
    assert error.title == "Action impossible"

    success = discord.Embed(title="SentriX • Configuration", description="Action terminée.")
    visual._promote_real_title(success, kind="success")
    assert success.title == "Action réussie"
