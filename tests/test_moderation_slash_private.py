"""En « / », la confirmation d'une action de modération est privée (02/11/2026)."""
from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from utils import slash_privacy  # noqa: E402


def _ctx(name: str, slash: bool = True):
    return SimpleNamespace(
        interaction=object() if slash else None,
        command=SimpleNamespace(qualified_name=name),
    )


def test_les_actions_staff_en_slash_sont_privees():
    for name in ("ban", "kick", "mute", "warn", "clear", "lock", "slowmode", "nickname", "giverole"):
        assert slash_privacy.reponse_privee(_ctx(name)), name


def test_le_prefixe_et_les_consultations_restent_publics():
    assert not slash_privacy.reponse_privee(_ctx("ban", slash=False))
    for name in ("warnings", "case", "modhistory", "userinfo", "help"):
        assert not slash_privacy.reponse_privee(_ctx(name)), name


def test_le_minuteur_lent_lit_la_commande_source_du_catalogue():
    # « /timeout » publie la commande source « mute » (utils/slash_catalog.py).
    callback = SimpleNamespace(_sentrix_original_command="mute")
    interaction = SimpleNamespace(command=SimpleNamespace(name="timeout", callback=callback))
    assert slash_privacy.interaction_privee(interaction)
    other = SimpleNamespace(command=SimpleNamespace(name="lock", callback=SimpleNamespace(_sentrix_original_command="voice-lock")))
    assert not slash_privacy.interaction_privee(other)


def test_moderation_et_roles_utilisent_la_decision_commune():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    moderation = (root / "cogs" / "moderation.py").read_text(encoding="utf-8")
    assert "ephemere = ephemere or reponse_privee(ctx)" in moderation
    assert "defer(ephemeral=reponse_privee(ctx))" in moderation
    assert "ephemere=privee, allowed_mentions=_SANS_PING" in moderation
    roles = (root / "cogs" / "verification.py").read_text(encoding="utf-8")
    assert roles.count("ephemere=reponse_privee(ctx)") >= 4
    slow = (root / "sentrix_grouped_slash_fix.py").read_text(encoding="utf-8")
    assert "ephemeral=interaction_privee(interaction)" in slow
