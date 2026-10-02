from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("DISCORD_TOKEN", "test-token")

from utils import sentrix_panels as panels

ROOT = Path(__file__).resolve().parents[1]


def test_sentrix_core_signature_is_the_command_panel_identity():
    assert panels.CORE_NAME == "SENTRIX CORE"
    assert panels.signature_core("music").startswith("SENTRIX CORE · Musique")
    assert panels.signature_core("security").startswith("SENTRIX CORE · Sécurité")


def test_sections_use_numbered_core_grammar():
    first = panels.Section("Identité", [panels.Ligne("Membre", "@User")]).rendu(1)
    second = panels.Section("Activité", [panels.Ligne("Niveau", "42")]).rendu(2)

    assert first.startswith("### 01 · Identité")
    assert second.startswith("### 02 · Activité")
    assert "●" not in first
    assert "◢" not in first


def test_core_footer_does_not_duplicate_legacy_brand():
    footer = panels.pied_core("music", "SentriX")
    assert footer == "SENTRIX CORE · Musique"
    assert footer.count("SentriX") == 0  # Core signature is intentionally uppercase.


def test_native_panels_always_render_core_signature_and_footer():
    panel = panels.Panneau(
        titre="Lecture",
        sections=[
            panels.Section("Piste", [panels.Ligne("Titre", "Test")]),
            panels.Section("Lecture", [panels.Ligne("Volume", "80%")]),
        ],
        kind="musique",
        banniere=False,
    )
    text = panels.texte_complet(panel)

    assert "SENTRIX CORE · Musique" in text
    assert "## Lecture" in text
    assert "### 01 · Piste" in text
    assert "### 02 · Lecture" in text


def test_legacy_command_renderer_uses_same_core_grammar():
    source = (ROOT / "utils" / "command_visuals.py").read_text(encoding="utf-8")

    assert '"SENTRIX CORE"' in source
    assert "_core_signature(ctx, family)" in source
    assert '"### 01 · Résultat"' in source
    assert "_core_footer(ctx, family, footer)" in source


def test_help_uses_sentrix_core_and_numbered_sections():
    source = (ROOT / "cogs" / "help.py").read_text(encoding="utf-8")

    assert "panels.signature_core('special')" in source
    assert "section.rendu(section_index)" in source
    assert "panels.pied_core('special', 'Centre d’aide')" in source


def test_active_command_renderers_have_no_external_bot_style_names():
    paths = [
        ROOT / "utils" / "sentrix_panels.py",
        ROOT / "utils" / "command_visuals.py",
        ROOT / "cogs" / "final_interaction_policy.py",
        ROOT / "cogs" / "help.py",
    ]
    forbidden = ("oxyde", "draftbot", "carl-bot", "ticket tool", "mee6", "dyno", "probot")
    for path in paths:
        source = path.read_text(encoding="utf-8").casefold()
        for name in forbidden:
            assert name not in source, f"{path.name}: external style reference {name}"


def test_native_core_panel_buttons_can_host_real_callbacks():
    async def callback(_interaction):
        return None

    panel = panels.Panneau(
        titre="Actions",
        kind="musique",
        banniere=False,
        timeout=120,
        boutons=[
            panels.Bouton(
                "Action",
                custom_id="sentrix:test:action",
                callback=callback,
            )
        ],
    )

    assert panel.timeout == 120
    assert panel.boutons_source[0].callback is callback
