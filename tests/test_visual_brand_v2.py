from pathlib import Path
from types import SimpleNamespace

import inspect
import re

import discord

from utils import brand_assets, design_system, premium_style, visual_v5
from cogs.visual_experience_v5 import VisualExperienceV5
from cogs import plain_response_policy
from cogs import final_interaction_policy
from cogs import help_clean_style
from cogs import command_response_guard
from cogs import setup_oxyde_style
from cogs import utility as utility_cog
from cogs import guild_arrival


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
    assert premium_style.infer_category(command=_command("Utility", "avatar")) == "profile"


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
    # Le style ajoute un appel a l'action sous l'etat vide ; ce qui compte est que la
    # mauvaise categorie pre-appliquee disparaisse sans etre dupliquee.
    assert styled.description.startswith("**File d'attente vide**")
    assert "Utilitaires" not in styled.description
    assert styled.description.count("File d'attente vide") == 1


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


def test_mentions_and_links_are_also_forced_into_command_embeds():
    ctx = SimpleNamespace(command=_command("Utility", "info"), guild=None, author=None, bot=None)
    for content in ("<@123456789012345678> profil", "https://example.test/result"):
        args, kwargs = plain_response_policy._rich_send_args(ctx, (content,), {})
        assert args == (None,)
        assert kwargs["content"] is None
        assert isinstance(kwargs["embed"], discord.Embed)


def test_final_interaction_policy_never_flattens_embeds_to_text():
    """Un embed reste un embed : il n'est jamais converti en champ content."""
    embed = discord.Embed(title="SentriX • Carte", description="Réponse encadrée")
    cleaned = final_interaction_policy._clean_embed(embed)
    assert isinstance(cleaned, discord.Embed)
    assert cleaned.title and "Carte" in cleaned.title

    source = inspect.getsource(final_interaction_policy._install_messageable_send)
    # Le wrapper officiel ne doit jamais fabriquer un content a partir d'un embed.
    assert 'kwargs["embed"] = _clean_embed(kwargs["embed"])' in source
    assert 'kwargs["content"]' not in source


def test_every_legacy_embed_flattener_is_disabled():
    """Les aplatisseurs historiques ne doivent plus etre le transport installe.

    community_v32/v33/v34 savent encore transformer un embed en texte, mais le
    transport officiel les court-circuite : _install_messageable_send part de
    _unwrap(current), donc de la methode Discord native, et repose son propre wrapper
    par-dessus. C'est cette garantie-la qui compte, pas la disparition du code mort.
    """
    final_interaction_policy._install_messageable_send()
    send = discord.abc.Messageable.send
    assert getattr(send, "_sentrix_official_command_embed", False), "transport non installe"
    assert send.__module__ == "cogs.final_interaction_policy"

    # La base sur laquelle il s'appuie n'est aucun des aplatisseurs.
    base = getattr(send, "_sentrix_original", None)
    assert base is not None
    assert getattr(base, "__module__", "") not in {
        "cogs.community_v32", "cogs.community_v33", "cogs.community_v34",
    }


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
    assert 'await self.defer()' in source
    assert 'raw_message_edit(interaction.message, *args, **kwargs)' in source


def test_final_response_policy_covers_every_command_transport():
    import inspect
    source = inspect.getsource(plain_response_policy.install)
    assert 'raw_context_send(self, *args, **kwargs)' in source
    assert 'self._sentrix_response_sent = True' in source
    assert 'raw_messageable_send(self, *args, **kwargs)' in source
    assert 'raw_message_edit(self, *args, **kwargs)' in source
    assert 'raw_response_send(self, *args, **kwargs)' in source
    assert 'raw_response_edit(self, *args, **kwargs)' in source
    assert 'raw_original_edit(self, *args, **kwargs)' in source
    assert 'raw_webhook_send(self, *args, **kwargs)' in source
    assert '_ACTIVE_WRAPPERS.get("response_edit") is not current_response_edit' in source
    assert 'reassert_rich_transports_after_ready' in source
    assert 'final_interaction_policy._disable_legacy_embed_flattening()' in source


def test_command_guard_never_adds_an_automatic_success_message():
    import inspect
    source = inspect.getsource(command_response_guard.install)
    assert 'add_listener(ensure_prefix_command_response' not in source
    assert 'add_listener(ensure_slash_command_response' not in source


def test_avatar_uses_the_target_display_name_and_real_animated_asset():
    import inspect
    source = inspect.getsource(utility_cog)
    assert 'display_name = (' in source
    assert 'await ctx.guild.fetch_member(membre.id)' in source
    assert 'await self.bot.fetch_user(membre.id)' in source
    assert 'getattr(ctx, "message", None), "author"' in source
    assert 'getattr(ctx, "message", None), "mentions"' in source
    assert 'asset.is_animated()' in source
    assert 'asset.with_format("gif")' in source
    assert 'data = await asset.read()' in source
    assert 'getattr(membre, "guild_avatar", None)' in source
    assert '"media.discordapp.net"' in source
    assert '_download_discord_avatar(' in source
    assert 'asyncio.as_completed(tasks, timeout=5)' in source
    assert '"/embed/avatars/" in original_url' in source
    # L'avatar est desormais rendu en panneau : l'URL verifiee part dans la
    # galerie de contenu du panneau, plus dans set_image d'un embed. La garantie
    # testee reste la meme — c'est bien l'URL VERIFIEE qui est affichee.
    assert 'self._panneau_avatar(display_name, membre, str(asset.url))' in source
    assert 'self._panneau_avatar(display_name, membre, verified_url)' in source
    assert 'image=url' in source
    assert 'file=discord.File(io.BytesIO(data), filename=filename)' not in source
    assert 'getattr(membre, "default_avatar", None)' not in source
    assert 'label="Ouvrir l\'avatar"' not in source


def test_guild_arrival_opens_the_real_setup_and_has_safe_fallbacks():
    import inspect
    source = inspect.getsource(guild_arrival)
    assert 'async def on_guild_join' in source
    assert 'guild.system_channel' in source
    assert 'permissions.send_messages and permissions.embed_links' in source
    # Le custom_id est versionne : on verifie la forme, pas un numero fige, sinon le
    # test casse a chaque revision du panneau d'accueil.
    assert re.search(r'custom_id="sentrix:guild-arrival:setup:v\d+"', source)
    assert 'configuration._open_setup_panel(interaction.channel, author=member)' in source
    assert 'await guild.owner.send(' in source
    assert 'title="SentriX • Installation réussie"' in source
    assert 'Placez le rôle **SentriX** au-dessus' in source
    assert 'name="Liens officiels"' in source
    assert 'Une fois le panneau terminé' not in source


def test_setup_is_compact_and_does_not_repeat_the_control_center():
    import inspect
    source = inspect.getsource(setup_oxyde_style)
    assert 'SENTRIX • CONTROL CENTER' not in source
    assert 'Ouvrir le dashboard web' not in source
    # La variable a ete renommee e -> embed ; c'est l'appel qui compte, pas son receveur.
    assert 'clear_fields()' in source
    assert '"prev", "next", "preview", "history"' in source
