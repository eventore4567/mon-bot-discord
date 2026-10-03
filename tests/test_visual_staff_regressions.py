"""Garde-fous pour la finalisation visuelle et la suite staff premium."""
from __future__ import annotations

import inspect
from pathlib import Path

import discord

from cogs.staff_suite import EvidenceModal, StaffSuite
from utils import access_matrix
from utils import sentrix_panels as panels


ROOT = Path(__file__).resolve().parents[1]


def _flat_components(view: discord.ui.LayoutView) -> list[dict]:
    result: list[dict] = []

    def visit(items):
        for item in items or ():
            result.append(item)
            for key in ("components", "accessory"):
                child = item.get(key)
                if isinstance(child, list):
                    visit(child)
                elif isinstance(child, dict):
                    visit([child])

    visit(view.to_components())
    return result


def test_banner_flag_cannot_restore_global_decorations(monkeypatch):
    generated = False

    def forbidden_generation(*_args, **_kwargs):
        nonlocal generated
        generated = True
        raise AssertionError("aucune bannière ne doit être générée")

    monkeypatch.setattr(panels, "ensure_banners", forbidden_generation)
    for requested in (None, False, True):
        panel = panels.Panneau(
            titre="Fiche membre",
            sections=[panels.Section("Résumé", texte="Information utile")],
            banniere=requested,
        )
        assert panel.fichiers() == []
        assert not any(item.get("type") == 12 for item in _flat_components(panel))
        assert panel.to_components()[0].get("accent_color") is None
    assert generated is False


def test_semantic_media_stays_visible_without_banner():
    url = "https://cdn.discordapp.com/attachments/1/2/preuve.png?ex=abc&is=def"
    panel = panels.Panneau(titre="Preuve", image=url, banniere=True)
    galleries = [item for item in _flat_components(panel) if item.get("type") == 12]
    assert len(galleries) == 1
    assert galleries[0]["items"][0]["media"]["url"] == url
    assert panel.fichiers() == []


def test_staff_suite_is_loaded_before_visual_finalizer_and_classified():
    main_source = (ROOT / "main.py").read_text(encoding="utf-8")
    assert main_source.index('"cogs.staff_suite"') < main_source.index('"cogs.visual_experience_v5"')

    expected = {
        "member": "discord:moderate_members",
        "note": "discord:moderate_members",
        "history": "discord:moderate_members",
        "staff-proof": "discord:moderate_members",
        "incident": "discord:moderate_members",
        "watch": "discord:moderate_members",
        "staff": "discord:moderate_members",
        "handover": "discord:moderate_members",
        "report": "discord:moderate_members",
        "absence": "discord:moderate_members",
        "staff-reminder": "discord:moderate_members",
        "urgence": "discord:manage_channels",
        "audit": "discord:manage_guild",
    }
    assert {name: access_matrix.access_tier(name) for name in expected} == expected
    assert access_matrix.access_tier("proof") == "public"


def test_staff_and_public_proof_commands_have_distinct_names():
    staff_names = {command.name for command in StaffSuite.__cog_commands__}
    assert "staff-proof" in staff_names
    assert "proof" not in staff_names
    proof_source = (ROOT / "cogs" / "proof_verification.py").read_text(encoding="utf-8")
    assert '@commands.hybrid_command(name="proof"' in proof_source


def test_staff_evidence_keeps_signed_discord_cdn_url():
    source = inspect.getsource(EvidenceModal.on_submit)
    assert '.split("?", 1)' not in source
    assert "str(attachment.url)" in source

