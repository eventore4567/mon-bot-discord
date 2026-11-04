"""En « / », la confirmation d'une action de modération est privée (02/11/2026)."""
from __future__ import annotations

import os
from pathlib import Path
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


def test_le_prefixe_reste_public_les_consultations_staff_sont_privees():
    assert not slash_privacy.reponse_privee(_ctx("ban", slash=False))
    # 04/11/2026 : « tout truc de modo visible que pour soi-même ».
    for name in ("warnings", "case", "modhistory", "sentrixpro history", "snipe"):
        assert slash_privacy.reponse_privee(_ctx(name)), name
    for name in ("userinfo", "help", "balance"):
        assert not slash_privacy.reponse_privee(_ctx(name)), name


def test_une_consultation_staff_est_differee_en_prive_des_le_depart():
    callback = SimpleNamespace(_sentrix_original_command="modhistory")
    interaction = SimpleNamespace(command=SimpleNamespace(name="sanctions", callback=callback))
    assert slash_privacy.consultation_privee(interaction)
    autre = SimpleNamespace(command=SimpleNamespace(name="ban", callback=SimpleNamespace()))
    assert not slash_privacy.consultation_privee(autre)  # action : gérée par la commande elle-même
    slow = (Path(__file__).resolve().parents[1] / "sentrix_grouped_slash_fix.py").read_text(encoding="utf-8")
    assert "if consultation_privee(interaction) and not interaction.response.is_done():" in slow


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
