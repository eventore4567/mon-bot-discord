from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("DISCORD_TOKEN", "test-token")

from utils import wide_logs

ROOT = Path(__file__).resolve().parents[1]


def test_trace_titles_are_sentrix_owned_and_event_specific():
    assert wide_logs._trace_title("message_delete", "ancien titre") == "Message supprimé"
    assert wide_logs._trace_title("member_ban", "ancien titre") == "Membre banni"
    assert wide_logs._trace_title("ticket_open", "ancien titre") == "Ticket ouvert"
    assert wide_logs._trace_title("automod_link", "ancien titre") == "Lien bloqué"


def test_trace_meta_is_human_facing_without_internal_event_codes():
    meta = wide_logs._trace_meta("message_delete", emoji="")
    assert "Messages" in meta
    assert "SENTRIX TRACE" not in meta
    assert "MSG-DEL" not in meta


def test_trace_identity_labels_are_human_not_generic():
    assert wide_logs._trace_identity_label("message_delete") == "Auteur"
    assert wide_logs._trace_identity_label("member_timeout") == "Membre"
    assert wide_logs._trace_identity_label("channel_delete") == "Salon"
    assert wide_logs._trace_identity_label("role_update") == "Rôle"
    assert wide_logs._trace_identity_label("guild_update") == "Serveur"
    assert wide_logs._trace_identity_label("invite_create") == "Créateur"


def test_trace_footer_removes_internal_trace_code():
    footer = wide_logs._trace_footer(
        "member_timeout",
        "SentriX • 02/10/2026 10:00",
    )
    assert footer == "SentriX · 02/10/2026 10:00"
    assert "Trace" not in footer
    assert "MBR-TO" not in footer


def test_every_wide_log_uses_the_trace_renderer():
    source = (ROOT / "utils" / "wide_logs.py").read_text(encoding="utf-8")

    assert "class WideLogView" in source
    assert "_trace_meta(event_type" in source
    assert "_trace_title(event_type" in source
    assert "_trace_identity_label(event_type)" in source
    assert "_trace_body_parts(body)" in source
    assert 'discord.ui.TextDisplay("### Informations")' not in source
    assert "### Détails" not in source
    assert "_trace_time_text(embed)" in source
    assert "_trace_footer(event_type, footer)" in source
    assert "view = WideLogView(" in source


def test_deleted_message_media_uses_trace_preview_and_file_actions():
    logs_source = (ROOT / "cogs" / "logs.py").read_text(encoding="utf-8")
    service_source = (ROOT / "utils" / "log_service.py").read_text(encoding="utf-8")

    assert "def _attachment_media(" in logs_source
    assert "def _attachment_summary(" in logs_source
    assert "def _attachment_links(" in logs_source
    assert '("Pièces jointes", _attachment_summary(media_items), False)' in logs_source
    assert "links=_attachment_links(media_items)" in logs_source
    assert "media_items=media_items" in logs_source
    assert "media_items: list[tuple[str, str, str]] | None = None" in service_source


def test_old_external_style_names_are_not_user_facing_in_automod():
    source = (ROOT / "cogs" / "automod.py").read_text(encoding="utf-8")
    assert '"AutoMod Manage"' not in source
    assert '"Protection SentriX"' in source



def test_trace_v7_splits_summary_from_long_details():
    summary, details = wide_logs._trace_body_parts(
        "Un message a été supprimé.\n\n**Contenu**\n```hello```"
    )
    assert summary == "Un message a été supprimé."
    assert "**Contenu**" in details


def test_trace_v7_layout_is_compact_and_media_stays_below_context():
    source = (ROOT / "utils" / "wide_logs.py").read_text(encoding="utf-8")
    block = source[
        source.index("class WideLogView"):
        source.index("def _database_path", source.index("class WideLogView"))
    ]

    assert "SentriX Trace V7" in block
    assert "header_lines = [meta, f\"## {title}\"]" in block
    assert "summary, details = _trace_body_parts(body)" in block
    assert block.index("summary, details = _trace_body_parts(body)") < block.index("if media_items:")
    assert "📎" not in block



def test_message_content_keeps_real_mentions_outside_code_blocks():
    rendered = wide_logs._message_quote("<@1499827796560580850> salut")
    assert "<@1499827796560580850>" in rendered
    assert "```" not in rendered
    assert rendered.startswith("> ")


def test_trace_identity_uses_real_discord_references():
    assert wide_logs._trace_identity_ref("message_edit", 1499827796560580850) == "<@1499827796560580850>"
    assert wide_logs._trace_identity_ref("member_ban", 1499827796560580850) == "<@1499827796560580850>"
    assert wide_logs._trace_identity_ref("channel_update", 1499827796560580850) == "<#1499827796560580850>"
    assert wide_logs._trace_identity_ref("role_update", 1499827796560580850) == "<@&1499827796560580850>"


def test_trace_header_does_not_show_raw_identity_id_line():
    source = (ROOT / "utils" / "wide_logs.py").read_text(encoding="utf-8")
    block = source[
        source.index("class WideLogView"):
        source.index("def _database_path", source.index("class WideLogView"))
    ]
    assert '-# ID ·' not in block
    assert "_trace_identity_ref(event_type, identity_id)" in block
