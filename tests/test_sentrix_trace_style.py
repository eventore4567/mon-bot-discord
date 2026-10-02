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


def test_trace_meta_has_brand_category_and_event_code():
    meta = wide_logs._trace_meta("message_delete", emoji="")
    assert "SENTRIX TRACE" in meta
    assert "Messages" in meta
    assert "MSG-DEL" in meta


def test_trace_footer_removes_old_brand_prefix():
    footer = wide_logs._trace_footer(
        "member_timeout",
        "SentriX • 02/10/2026 10:00",
    )
    assert footer == "SentriX Trace · MBR-TO · 02/10/2026 10:00"


def test_every_wide_log_uses_the_trace_renderer():
    source = (ROOT / "utils" / "wide_logs.py").read_text(encoding="utf-8")

    assert "class WideLogView" in source
    assert "_trace_meta(event_type" in source
    assert "_trace_title(event_type" in source
    assert 'discord.ui.TextDisplay("### Contexte")' in source
    assert "_trace_footer(event_type, footer)" in source
    assert "view = WideLogView(" in source


def test_old_external_style_names_are_not_user_facing_in_automod():
    source = (ROOT / "cogs" / "automod.py").read_text(encoding="utf-8")
    assert '"AutoMod Manage"' not in source
    assert '"Protection SentriX"' in source
