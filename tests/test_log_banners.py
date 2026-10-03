"""Contrat visuel actuel : aucune bannière décorative dans SentriX.

Les assets historiques peuvent rester dans le dépôt pour compatibilité, mais le
produit ne doit plus les joindre, les référencer ni les afficher dans les panneaux.
"""
from __future__ import annotations

import inspect

import discord

from utils import command_visuals
from utils import sentrix_panels as panels


def test_banners_are_globally_disabled_even_when_a_legacy_caller_forces_true():
    assert panels.BANDEAUX_ACTIFS is False
    panel = panels.Panneau(titre="Test", banniere=True)
    assert panel.avec_banniere is False
    assert panel.fichiers() == []


def test_panel_has_no_banner_gallery_or_top_core_signature():
    source = inspect.getsource(panels.Panneau.__init__)
    assert "self.avec_banniere = False" in source
    assert 'discord.ui.TextDisplay(f"-# {_core_signature' not in source
    assert "position if numeroter else None" not in source


def test_legacy_command_renderer_also_disables_banners():
    assert command_visuals.banniere_desactivee() is True
    source = inspect.getsource(command_visuals.CommandPanelView.__init__)
    assert 'attachment://{banner_filename}' not in source
    assert "### 01 · Résultat" not in source
    assert '_core_signature(ctx, identity_family' not in source


def test_legacy_banner_image_is_removed_but_semantic_image_is_preserved():
    old = command_visuals.banner_url("info")
    banner_embed = discord.Embed(title="Test")
    banner_embed.set_image(url=old)
    cleaned = command_visuals._decorate_embed(banner_embed, "info")
    assert not getattr(cleaned.image, "url", None)

    semantic = discord.Embed(title="Test")
    semantic.set_image(url="https://cdn.example.test/real-image.png")
    kept = command_visuals._decorate_embed(semantic, "info")
    assert kept.image.url == "https://cdn.example.test/real-image.png"


def test_embed_to_panel_keeps_real_content_image():
    embed = discord.Embed(title="Média")
    embed.set_image(url="https://cdn.example.test/photo.webp")
    panel = panels.depuis_embed(embed)
    payload = panel.to_components()
    rendered = repr(payload)
    assert "https://cdn.example.test/photo.webp" in rendered
