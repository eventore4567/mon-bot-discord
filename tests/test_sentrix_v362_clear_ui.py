from __future__ import annotations

import discord

from cogs import sentrix_emoji_markup_guard_v361 as guard
from cogs import sentrix_emoji_runtime as ui


def test_repairs_legacy_a_fragments() -> None:
    assert guard._repair_broken("a a a Centre de contrôle") == "Centre de contrôle"
    assert guard._repair_broken("<a Sécurité & modération") == "Sécurité & modération"
    assert guard._repair_broken("a:sxv36_update:1541658913592713327> Configuration") == "Configuration"
    assert guard._repair_broken("a a a Information\n<a Tickets & support") == "Information\nTickets & support"


def test_clear_static_icons_are_unambiguous() -> None:
    assert ui._static_icon("Centre de contrôle", category="configuration") == "⚙️"
    assert ui._static_icon("Trouver n’importe quoi", category="utility") == "🔎"
    assert ui._static_icon("Systèmes principaux", category="utility") == "🧩"
    assert ui._static_icon("Sécurité", category="security") == "🛡️"
    assert ui._static_icon("Modération", category="moderation") == "🔨"
    assert ui._static_icon("Tickets", category="tickets") == "🎫"


def test_animations_are_reserved_for_states() -> None:
    assert ui._animated_state_key("Centre de contrôle", kind="info") is None
    assert ui._animated_state_key("Configuration", kind="info") is None
    assert ui._animated_state_key("Terminé", kind="success") == "ok"
    assert ui._animated_state_key("Erreur", kind="danger") == "error"
    assert ui._animated_state_key("Attention", kind="warning") == "alert"
    assert ui._animated_state_key("Chargement en cours", kind="info") == "loading"


def test_help_embed_does_not_keep_broken_markup() -> None:
    # En production le garde est installé après les renderers V2/V3.4/V3.6.
    guard.install(None)
    embed = discord.Embed(title="a a a Centre de contrôle")
    embed.add_field(name="<a Information", value="<a Sécurité & modération\n<a Tickets & support")
    result = ui._decorate_embed(embed, category="utility", kind="info")

    assert "a a a" not in (result.title or "")
    assert "<a" not in (result.title or "")
    assert (result.title or "").startswith("⚙️")
    assert "<a" not in result.fields[0].name
    assert "<a" not in result.fields[0].value


def test_buttons_use_simple_unicode_not_custom_animated_emoji() -> None:
    guard.install(None)
    view = discord.ui.View(timeout=None)
    view.add_item(discord.ui.Button(label="Setup & logs", custom_id="setup"))
    view.add_item(discord.ui.Button(label="Sécurité", custom_id="security"))
    view.add_item(discord.ui.Button(label="Modération", custom_id="moderation"))
    view.add_item(discord.ui.Button(label="Tickets", custom_id="tickets"))
    view.add_item(discord.ui.Button(label="Rechercher", custom_id="search"))
    view.add_item(discord.ui.Button(label="Fermer", custom_id="close"))

    ui._decorate_view(view)
    rendered = [str(item.emoji) for item in view.children]
    assert rendered == ["⚙️", "🛡️", "🔨", "🎫", "🔎", "❌"]
    assert not any("sxv36_" in value for value in rendered)
