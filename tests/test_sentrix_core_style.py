from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("DISCORD_TOKEN", "test-token")

from utils import sentrix_panels as panels
from utils import sentrix_emojis

ROOT = Path(__file__).resolve().parents[1]


def test_core_helpers_remain_available_but_are_not_forced_into_every_panel():
    assert panels.CORE_NAME == "SENTRIX CORE"
    assert panels.signature_core("music").startswith("SENTRIX CORE · Musique")
    panel = panels.Panneau(titre="Lecture", kind="musique")
    assert "SENTRIX CORE" not in panels.texte_complet(panel)


def test_sections_render_without_automatic_numbering():
    first = panels.Section("Identité", [panels.Ligne("Membre", "@User")]).rendu(None)
    second = panels.Section("Activité", [panels.Ligne("Niveau", "42")]).rendu(None)

    assert first.startswith("### Identité")
    assert second.startswith("### Activité")
    assert "01 ·" not in first
    assert "02 ·" not in second


def test_core_footer_does_not_duplicate_legacy_brand():
    footer = panels.pied_core("music", "SentriX")
    assert footer == "SENTRIX CORE · Musique"
    assert footer.count("SentriX") == 0  # Core signature is intentionally uppercase.


def test_native_panels_start_directly_with_useful_content():
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

    assert "SENTRIX CORE" not in text
    assert "## Lecture" in text
    assert "### Piste" in text
    assert "### Lecture" in text
    assert "01 ·" not in text


def test_legacy_command_renderer_uses_the_same_clean_grammar():
    source = (ROOT / "utils" / "command_visuals.py").read_text(encoding="utf-8")

    assert 'attachment://{banner_filename}' not in source
    assert '"### 01 · Résultat"' not in source
    assert 'discord.ui.Container()' in source


def test_help_has_no_banner_signature_or_numbered_sections():
    source = (ROOT / "cogs" / "help.py").read_text(encoding="utf-8")

    assert "panels.poser_bandeau(" not in source
    assert "panels.signature_core('special')" not in source
    assert "section.rendu(section_index)" not in source
    assert "section.rendu(None)" in source
    assert "return []" in source


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



def test_core_title_removes_only_redundant_legacy_brand():
    assert panels.titre_core("SentriX — Économie") == "Économie"
    assert panels.titre_core("SentriX - SentriX — Inventaire") == "Inventaire"
    assert panels.titre_core("🎵 Lecture en cours") == "🎵 Lecture en cours"


def test_state_panel_keeps_domain_metadata_without_rendering_it_as_noise(monkeypatch):
    monkeypatch.setattr(panels, "famille_de_la_commande", lambda: "economy")

    panel = panels.Panneau(
        titre="SentriX — Récompense",
        sous_titre="250 pièces reçues.",
        kind="success",
        banniere=False,
    )
    text = panels.texte_complet(panel)

    assert panel.famille == "success"
    assert panel.identite_famille == "economy"
    assert panel.titre == "Récompense"
    assert "SENTRIX CORE" not in text
    assert "## Récompense" in text


def test_error_panel_keeps_security_domain_metadata_without_top_signature(monkeypatch):
    monkeypatch.setattr(panels, "famille_de_la_commande", lambda: "security")

    panel = panels.Panneau(
        titre="Action impossible",
        sous_titre="Permission manquante.",
        kind="danger",
        banniere=False,
    )
    text = panels.texte_complet(panel)

    assert panel.famille == "error"
    assert panel.identite_famille == "security"
    assert "SENTRIX CORE" not in text


def test_phase7_native_domains_do_not_repeat_sentrix_in_titles():
    economy = (ROOT / "cogs" / "economy.py").read_text(encoding="utf-8")
    music = (ROOT / "cogs" / "music.py").read_text(encoding="utf-8")
    tickets = (ROOT / "cogs" / "tickets.py").read_text(encoding="utf-8")

    assert 'titre="SentriX —' not in economy
    assert 'titre="SentriX Music"' not in music
    assert 'titre="Lecture en cours"' in music
    assert 'titre="Ticket ouvert"' in tickets

def test_cross_module_stability_guards_block_resource_recreation():
    tickets = (ROOT / "cogs" / "setup_ticket_autoconfig_v72.py").read_text(encoding="utf-8")
    welcome = (ROOT / "cogs" / "setup_v2_completion.py").read_text(encoding="utf-8")
    snipe = (ROOT / "cogs" / "snipe.py").read_text(encoding="utf-8")

    # Activation/configuration must never invent Discord resources behind the admin's back.
    assert "guild.create_role(" not in tickets
    assert "guild.create_category(" not in tickets
    assert "guild.create_text_channel(" not in tickets
    assert "guild.create_text_channel" not in welcome

    # Welcome/departure remain separately gated and HA-deduplicated.
    assert 'module_enabled(bot, member.guild.id, "welcome")' in welcome
    assert 'module_enabled(bot, member.guild.id, "goodbye")' in welcome
    assert 'join_dedup.reclamer(bot, member.guild.id, member.id, "welcome")' in welcome
    assert 'join_dedup.reclamer(bot, member.guild.id, member.id, "goodbye")' in welcome

    # Snipe stays bounded, temporary and ignores messages deleted by clear.
    assert "SNIPE_RETENTION_SECONDS" in snipe
    assert "SNIPE_MESSAGE_CACHE_LIMIT" in snipe
    assert "log_service.is_purged" in snipe

def test_core_truncation_never_exposes_half_custom_emoji():
    markup = "<:sentrix_security:410000000000000099>"
    source = f"Protection {markup} configuration avancée"

    direct = sentrix_emojis.tronquer(source, 24)
    panel_text = panels._texte(source, 24)

    for rendered in (direct, panel_text):
        assert len(rendered) <= 24
        assert "<:sentrix_security:" not in rendered
        assert rendered == "Protection…"


def test_setup_emoji_summary_uses_safe_truncation():
    source = (ROOT / "cogs" / "setup_v2_ui.py").read_text(encoding="utf-8")
    assert "description=sentrix_emojis.tronquer(" in source
    assert "emojis_json" in source

