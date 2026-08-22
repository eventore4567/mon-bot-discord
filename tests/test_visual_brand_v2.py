from pathlib import Path
from types import SimpleNamespace

import discord

from utils import brand_assets, design_system, premium_style, visual_v5
from cogs.visual_experience_v5 import VisualExperienceV5
from cogs import plain_response_policy
from cogs import final_interaction_policy
from cogs import help_clean_style


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


def test_bot_avatar_is_used_only_as_the_small_author_icon():
    bot_user = SimpleNamespace(
        display_avatar=SimpleNamespace(url="https://cdn.discordapp.com/avatar.png")
    )
    embed = premium_style.style_embed(
        discord.Embed(title="Configuration"),
        bot_user=bot_user,
    )
    assert embed.author.icon_url == "https://cdn.discordapp.com/avatar.png"
    assert not embed.thumbnail.url


def test_v4_titles_are_calm_and_ordinary_cards_have_no_extra_timestamp():
    embed = premium_style.style_embed(discord.Embed(title="SENTRIX / CONFIGURATION"))
    assert embed.title == "SentriX • Configuration"
    assert embed.timestamp is None


def test_category_artwork_is_never_auto_attached_in_v4():
    embed = discord.Embed(title="Configuration")
    kwargs = brand_assets.decorate_send_kwargs({}, embed=embed, category="configuration")
    assert kwargs == {}
    assert not embed.thumbnail.url


def test_setup_summary_is_reduced_to_one_mobile_friendly_line():
    embed = discord.Embed(title="SENTRIX / CONFIGURATION")
    embed.add_field(name="Serveur", value="Communauté")
    embed.add_field(name="Progression", value="8 / 9")
    embed.add_field(name="Langue", value="Français")
    embed.add_field(name="Modules", value="Tickets\nLogs\nNiveaux")
    styled = premium_style.style_embed(embed, category="configuration")
    assert not styled.fields
    assert "**Serveur :** Communauté" in styled.description
    assert "**Progression :** 8 / 9" in styled.description
    assert "**Langue :** Français" in styled.description
    assert "Modules" not in styled.description


def test_v4_number_duration_and_list_formats_are_consistent():
    assert premium_style.format_number(1250000) == "1 250 000"
    assert premium_style.format_duration(15120) == "4 h 12 min"
    lines = premium_style.compact_lines([f"Commande {index}" for index in range(10)], limit=8)
    assert len(lines) == 9
    assert lines[-1] == "+2 autres"


def test_v4_button_hierarchy_keeps_one_primary_action_per_row():
    view = discord.ui.View()
    view.add_item(discord.ui.Button(label="Valider", style=discord.ButtonStyle.primary, row=0))
    view.add_item(discord.ui.Button(label="Enregistrer", style=discord.ButtonStyle.primary, row=0))
    view.add_item(discord.ui.Button(label="Fermer", style=discord.ButtonStyle.secondary, row=0))
    premium_style.style_view(view)
    styles = [item.style for item in view.children]
    assert styles.count(discord.ButtonStyle.primary) == 1
    assert styles[-1] is discord.ButtonStyle.danger


def test_v4_labels_are_short_enough_for_mobile():
    view = discord.ui.View()
    view.add_item(discord.ui.Button(label="Une action principale beaucoup trop longue", row=0))
    premium_style.style_view(view)
    assert len(view.children[0].label) <= premium_style.VISUAL_LIMITS["button_label"]


def test_v4_replaces_a_wrong_pre_styled_category_without_duplicating_it():
    command = _command("Music", "queue")
    embed = discord.Embed(
        title="SentriX • Utilitaires",
        description="SentriX • Utilitaires\n**File d'attente vide**",
    )
    styled = premium_style.style_embed(embed, command=command)
    assert styled.title == "SentriX • Musique"
    assert styled.description == "**File d'attente vide**"
    assert "Utilitaires" not in styled.description


def test_v4_styling_is_idempotent_across_context_and_messageable_layers():
    command = _command("Music", "queue")
    embed = premium_style.style_embed(
        discord.Embed(title="File d'attente vide"),
        command=command,
    )
    first = embed.to_dict()
    premium_style.style_embed(embed, command=command)
    premium_style.style_embed(embed)
    assert embed.to_dict() == first


def test_v5_theme_presets_and_aliases_are_complete():
    assert set(visual_v5.THEME_PRESETS) == {"sentrix", "cyber", "noir"}
    assert visual_v5.resolve_theme("bleu") == "cyber"
    assert visual_v5.resolve_theme("premium") == "noir"
    assert visual_v5.theme_settings("violet")["theme_preset"] == "sentrix"


def test_v5_profile_card_background_is_bundled():
    assert visual_v5.CARD_BACKGROUND.is_file()


def test_v5_error_references_are_unique_and_well_formed():
    first = visual_v5.error_reference()
    second = visual_v5.error_reference()
    assert first.startswith("SX-") and len(first) == 9
    assert first != second


def test_v5_danger_reference_is_added_once():
    embed = premium_style.style_embed(discord.Embed(title="Erreur", description="Action impossible"))
    first = embed.description
    premium_style.style_embed(embed)
    assert embed.description == first
    assert "Référence : `SX-" in embed.description


def test_v5_empty_music_state_guides_the_member():
    embed = premium_style.style_embed(
        discord.Embed(title="File d'attente vide"),
        command=_command("Music", "queue"),
    )
    assert "+play <titre>" in embed.description


def test_v5_commands_do_not_redeclare_the_existing_status_alias():
    names = {command.name for command in VisualExperienceV5.__cog_commands__}
    assert "status" not in names
    assert {"about", "design-theme", "profile-card", "iconsetup"} <= names


def test_command_text_is_consistently_wrapped_in_an_embed():
    ctx = SimpleNamespace(command=_command("Utility", "ping"), guild=None, author=None, bot=None)
    args, kwargs = plain_response_policy._rich_send_args(ctx, ("Réponse de test",), {})
    assert args == (None,)
    assert kwargs["content"] is None
    assert isinstance(kwargs["embed"], discord.Embed)


def test_final_interaction_policy_never_flattens_embeds_to_text():
    embed = discord.Embed(title="SentriX • Carte", description="Réponse encadrée")
    assert final_interaction_policy._embed_to_plain(embed, root="profile-card") is None
    args, kwargs = final_interaction_policy._convert_kwargs((), {"embed": embed}, root="ping")
    assert args == ()
    assert kwargs["embed"] is embed
    assert "content" not in kwargs


def test_every_legacy_embed_flattener_is_disabled():
    final_interaction_policy._disable_legacy_embed_flattening()
    embed = discord.Embed(title="Toujours encadré")
    assert final_interaction_policy.community_v32.simple_embed_text(embed) is None
    assert final_interaction_policy.community_v33._simple_embed_to_text(embed, has_view=False) is None
    assert final_interaction_policy.community_v34._embed_to_text(embed, root="ping") is None


def test_help_navigation_uses_direct_message_edits():
    import inspect
    source = inspect.getsource(help_clean_style.CleanHelpPagesView.__init__)
    assert "_edit_help_message" in source
    assert "interaction.response.edit_message" not in source


def test_final_response_policy_installs_absolute_button_wrappers():
    import inspect
    source = inspect.getsource(plain_response_policy.install)
    assert "_sentrix_absolute_rich" in source
    assert 'raw_response_edit(self, *args, **kwargs)' in source
