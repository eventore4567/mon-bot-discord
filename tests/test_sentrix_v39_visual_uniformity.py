import os
from types import SimpleNamespace

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import discord

from cogs import sentrix_emoji_runtime as emoji_runtime
from cogs import sentrix_v3_global_style as style


def _command(name: str, cog: str = "Configuration"):
    return SimpleNamespace(qualified_name=name, cog_name=cog)


def test_short_setup_is_compact_and_has_no_artificial_padding():
    embed = discord.Embed(
        title="SentriX • Configuration",
        description="Choisis une catégorie ci-dessous pour configurer SentriX.",
    )
    for _ in range(4):
        embed.add_field(name="\u200b", value="\u200b", inline=True)

    result = style._refine_embed(embed, command=_command("setup"), category="configuration")

    assert result.title == "Configuration"
    assert style._layout_size(result, command=_command("setup"), category="configuration") == "compact"
    assert len(result.fields) == 0
    assert result.author.name is None


def test_rich_content_still_uses_panel_layout():
    embed = discord.Embed(title="SentriX • Configuration", description="Panneau détaillé.")
    embed.add_field(name="Serveur", value="Prêt", inline=True)
    embed.add_field(name="Modules", value="Tickets\nLogs\nAutoMod\nNiveaux", inline=True)
    embed.add_field(name="Sécurité", value="Active", inline=True)

    result = style._refine_embed(embed, command=_command("setup"), category="configuration")

    assert style._layout_size(result, command=_command("setup"), category="configuration") == "panel"
    assert result.author.name == "SentriX"
    assert len(result.fields) == 3


def test_compact_cards_do_not_receive_fake_fields():
    embed = discord.Embed(title="SentriX • Utilitaires", description="Réponse courte.")
    result = style._refine_embed(embed, command=_command("ping", "Utility"), category="utility")
    assert style._layout_size(result, command=_command("ping", "Utility"), category="utility") == "compact"
    assert len(result.fields) == 0
    assert result.title == "Utilitaires"
    assert result.author.name is None


def test_panel_deduplicates_title_and_repeated_information():
    embed = discord.Embed(
        title="SentriX • Sécurité",
        description="Protection active.\n\nProtection active.",
    )
    embed.add_field(name="Sécurité", value="Protection active.", inline=False)
    embed.add_field(name="Information", value="Protection active.", inline=False)
    embed.add_field(name="AutoMod", value="Actif", inline=True)
    embed.add_field(name="AutoMod", value="Actif", inline=True)

    result = style._refine_embed(embed, command=_command("security", "Security"), category="security")

    assert result.title == "Sécurité"
    assert (result.description or "").count("Protection active") == 1
    assert [field.name for field in result.fields] == ["AutoMod"]


def test_footer_is_canonical_and_does_not_repeat_sentrix():
    embed = discord.Embed(title="SentriX • Utilitaires", description="Réponse courte.")
    embed.set_footer(text="SentriX • SentriX • SentriX")
    result = style._refine_embed(embed, command=_command("ping", "Utility"), category="utility")
    assert result.footer.text == "SentriX"


def test_navigation_icons_are_static_and_components_never_animated():
    assert emoji_runtime._static_icon("Sécurité", category="security") == "🛡️"
    assert emoji_runtime._static_icon("Tickets", category="tickets") == "🎫"
    assert emoji_runtime._static_icon("Modération", category="moderation") == "🔨"
    assert emoji_runtime._button_animated_key("Tickets") is None
    assert emoji_runtime._button_animated_key("Sécurité") is None
    assert emoji_runtime._button_animated_key("Actualiser") is None
    assert emoji_runtime._button_animated_key("Confirmer") is None


def test_embed_fields_never_get_decorative_emoji_prefixes():
    embed = discord.Embed(title="SentriX • Configuration", description="Choisis une catégorie.")
    embed.add_field(name="Serveur", value="Prêt", inline=False)
    result = emoji_runtime._decorate_embed(embed, command=_command("setup"), category="configuration")
    assert result.fields[0].name == "Serveur"
    assert result.title.startswith("⚙️ ")


def test_legacy_large_alias_still_maps_to_panel_layout():
    embed = discord.Embed(title="Titre", description="Texte")
    embed.add_field(name="Un", value="A", inline=True)
    style._apply_two_size_layout(embed, size="large")
    assert len(embed.fields) == 1
