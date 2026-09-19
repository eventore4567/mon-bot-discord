"""Les erreurs de commande inconnue sont temporaires.

Une faute de frappe comme +vouch ne doit pas laisser un message SentriX permanent
dans un salon. Tous les propriétaires historiques de CommandNotFound utilisent la
même durée courte afin que l'ordre d'installation ne change pas le comportement.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_final_renderer_uses_short_unknown_command_lifetime():
    source = _read("cogs/final_error_embed_v5.py")
    assert "_DUREE_COMMANDE_INTROUVABLE = 8" in source
    assert "isinstance(base, commands.CommandNotFound)" in source
    assert "_texte_prefix_send(ctx, texte, supprimer_apres=duree)" in source


def test_official_plain_unknown_reply_expires():
    source = _read("cogs/error_experience_v3.py")
    assert "await _send_plain(ctx, text, delete_after=8)" in source
    assert '"delete_after": float(delete_after)' in source


def test_legacy_unknown_listeners_do_not_leave_permanent_messages():
    v16 = _read("cogs/bot_v16_commands.py")
    v5 = _read("cogs/bot_experience_v5.py")
    assert "delete_after=8" in v16
    assert "delete_after=8" in v5
