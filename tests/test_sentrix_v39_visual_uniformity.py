import os
from types import SimpleNamespace

# Les modules SentriX importent config.py au chargement. Les tests visuels n'utilisent
# jamais le réseau Discord, mais config.py exige quand même une valeur non vide.
os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import discord

from cogs import sentrix_emoji_runtime as emoji_runtime
from cogs import sentrix_v3_global_style as style


def _command(name: str, cog: str = "Configuration"):
    return SimpleNamespace(qualified_name=name, cog_name=cog)


def test_large_panel_removes_artificial_padding_and_keeps_real_title():
    embed = discord.Embed(
        title="SentriX • Configuration",
        description="Gère le serveur depuis un seul panneau.",
    )
    embed.add_field(name="Serveur", value="Prêt", inline=True)
    embed.add_field(name="Modules", value="Tickets\nLogs\nAutoMod\nNiveaux", inline=True)
    for _ in range(4):
        embed.add_field(name="\u200b", value="\u200b", inline=True)

    result = style._refine_embed(embed, command=_command("setup"), category="configuration")

    assert result.title == "Configuration"
    assert len(result.fields) == 2
    assert all(str(field.name).replace("\u200b", "").strip() for field in result.fields)
    assert result.author.name == "SentriX"
    assert result.fields[1].inline is False


def test_compact_cards_do_not_receive_fake_fields():
    embed = discord.Embed(title="SentriX • Utilitaires", description="Réponse courte.")
    result = style._refine_embed(embed, command=_command("ping", "Utility"), category="utility")

    assert style._layout_size(result, command=_command("ping", "Utility"), category="utility") == "compact"
    assert len(result.fields) == 0
    assert result.title == "Utilitaires"


def test_large_panel_deduplicates_title_field():
    embed = discord.Embed(title="SentriX • Sécurité", description="État général du serveur.")
    embed.add_field(name="Sécurité", value="Protection active", inline=False)
    embed.add_field(name="AutoMod", value="Actif", inline=True)

    result = style._refine_embed(embed, command=_command("security", "Security"), category="security")

    assert result.title == "Sécurité"
    assert "Protection active" in (result.description or "")
    assert [field.name for field in result.fields] == ["AutoMod"]


def test_navigation_icons_are_static_and_clear():
    assert emoji_runtime._static_icon("Sécurité", category="security") == "🛡️"
    assert emoji_runtime._static_icon("Tickets", category="tickets") == "🎫"
    assert emoji_runtime._static_icon("Modération", category="moderation") == "🔨"
    assert emoji_runtime._button_animated_key("Tickets") is None
    assert emoji_runtime._button_animated_key("Sécurité") is None
    assert emoji_runtime._button_animated_key("Actualiser") == "update"
    assert emoji_runtime._button_animated_key("Confirmer") == "ok"


def test_legacy_large_alias_still_maps_to_panel_layout():
    embed = discord.Embed(title="Titre", description="Texte")
    embed.add_field(name="Un", value="A", inline=True)
    style._apply_two_size_layout(embed, size="large")
    assert len(embed.fields) == 1
