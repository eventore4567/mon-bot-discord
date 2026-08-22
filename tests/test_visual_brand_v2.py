from pathlib import Path
from types import SimpleNamespace

import discord

from utils import brand_assets, design_system, premium_style


def _command(cog: str, name: str):
    return SimpleNamespace(cog_name=cog, qualified_name=name)


def test_all_visual_assets_exist_and_are_mapped():
    categories = {
        "security", "ai", "moderation", "games", "economy", "tickets",
        "levels", "music", "events", "invites", "configuration", "logs",
        "profile", "shop", "leaderboard",
    }
    for category in categories:
        filename = brand_assets.CATEGORY_ASSETS[category]
        path = Path(brand_assets.ASSET_DIR) / filename
        assert path.is_file(), f"asset missing for {category}: {path}"


def test_priority_categories_select_dedicated_icons():
    assert premium_style.infer_category(command=_command("Economy", "shop")) == "shop"
    assert premium_style.infer_category(command=_command("Levels", "profile")) == "profile"
    assert premium_style.infer_category(command=_command("Levels", "leaderboard-levels")) == "leaderboard"
    assert premium_style.infer_category(command=_command("SentriXUltimate", "sentrixpro")) == "premium"


def test_progress_bars_are_emoji_free_and_include_percentage():
    premium = premium_style.progress_bar(5, 10)
    legacy = design_system.progress_bar(5, 10, filled="🟪", empty="⬛")
    assert premium.endswith("50 %")
    assert legacy.endswith("50 %")
    assert "🟪" not in legacy and "⬛" not in legacy


def test_state_and_category_colours_remain_distinct():
    assert premium_style.COLORS["premium"] == 0xF2C94C
    assert premium_style.COLORS["success"] != premium_style.COLORS["danger"]
    assert premium_style.COLORS["shop"] != premium_style.COLORS["profile"]


def test_category_attachment_does_not_replace_existing_thumbnail():
    embed = discord.Embed(title="Profil")
    embed.set_thumbnail(url="https://example.test/member.png")
    kwargs = brand_assets.decorate_send_kwargs({}, embed=embed, category="profile")
    assert kwargs == {}
    assert embed.thumbnail.url == "https://example.test/member.png"


def test_category_attachment_does_not_duplicate_remote_author_icon():
    embed = discord.Embed(title="Configuration")
    embed.set_author(name="SentriX", icon_url="https://cdn.discordapp.com/avatar.png")
    kwargs = brand_assets.decorate_send_kwargs({}, embed=embed, category="configuration")
    assert kwargs == {}
    assert not embed.thumbnail.url


def test_interactive_panels_never_attach_category_artwork():
    embed = discord.Embed(title="Configuration")
    view = discord.ui.View()
    kwargs = brand_assets.decorate_send_kwargs(
        {"view": view},
        embed=embed,
        category="configuration",
    )
    assert kwargs == {"view": view}
    assert not embed.thumbnail.url


def test_bot_avatar_is_used_as_a_small_remote_thumbnail():
    bot_user = SimpleNamespace(
        display_avatar=SimpleNamespace(url="https://cdn.discordapp.com/avatar.png")
    )
    embed = premium_style.style_embed(
        discord.Embed(title="Configuration"),
        bot_user=bot_user,
    )
    assert embed.thumbnail.url == "https://cdn.discordapp.com/avatar.png"
    assert not embed.thumbnail.url.startswith("attachment://")
