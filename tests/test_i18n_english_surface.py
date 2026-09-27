from pathlib import Path

import discord
import pytest

from cogs import language_runtime


POLICY_SOURCE = Path("cogs/final_interaction_policy.py").read_text(encoding="utf-8")
LANG_SOURCE = Path("cogs/language_runtime.py").read_text(encoding="utf-8")


def test_language_runtime_and_final_policy_compile():
    compile(LANG_SOURCE, "cogs/language_runtime.py", "exec")
    compile(POLICY_SOURCE, "cogs/final_interaction_policy.py", "exec")


def test_english_surface_translates_core_sentrix_ui():
    text = (
        "Règlement · Vérification renforcée · Sécurité · Invitations · "
        "Activer / réparer · Commande introuvable."
    )
    translated = language_runtime.english_ui_text(text, setup=True)
    assert "Rules" in translated
    assert "Reinforced verification" in translated
    assert "Security" in translated
    assert "Invites" in translated
    assert "Enable / repair" in translated
    assert "Unknown command" in translated


def test_english_surface_preserves_code_urls_and_mentions():
    raw = "Règlement : \x60Règlement\x60 <#123456789012345678> https://example.com/Règlement Sécurité"
    translated = language_runtime.english_ui_text(raw, setup=True)
    assert translated.startswith("Rules")
    assert "\x60Règlement\x60" in translated
    assert "<#123456789012345678>" in translated
    assert "https://example.com/Règlement" in translated
    assert translated.endswith("Security")


def test_embed_translation_preserves_free_form_body():
    embed = discord.Embed(
        title="Vérification renforcée",
        description="Règlement raconté librement par un utilisateur.",
    )
    embed.add_field(name="Raison", value="Règlement et Sécurité sont mes mots.", inline=False)
    language_runtime.translate_embed_in_place(embed, setup=False, preserve_body=True)
    assert embed.title == "Reinforced verification"
    assert embed.description == "Règlement raconté librement par un utilisateur."
    assert embed.fields[0].value == "Règlement et Sécurité sont mes mots."


@pytest.mark.asyncio
async def test_component_translation_changes_buttons_and_select_options():
    view = discord.ui.View()
    view.add_item(discord.ui.Button(label="Activer / réparer"))
    select = discord.ui.Select(
        placeholder="Choisir un module à configurer",
        options=[discord.SelectOption(label="Sécurité", value="security")],
    )
    view.add_item(select)
    language_runtime.translate_view_in_place(view, setup=True)
    assert view.children[0].label == "Enable / repair"
    assert view.children[1].placeholder == "Choose a module to configure"
    assert view.children[1].options[0].label == "Security"


def test_final_transport_localizes_every_major_discord_surface():
    assert "async def _localize_outgoing" in POLICY_SOURCE
    for marker in (
        "async def context_send",
        "async def messageable_send",
        "async def message_edit",
        "async def response_send",
        "async def response_edit",
        "async def edit_original",
        "async def webhook_send",
    ):
        start = POLICY_SOURCE.index(marker)
        chunk = POLICY_SOURCE[start:start + 1800]
        assert "_localize_outgoing(" in chunk, marker


def test_language_confirmation_now_promises_broad_interface_coverage():
    assert "commands, panels, errors, setup, verification, security" in LANG_SOURCE
