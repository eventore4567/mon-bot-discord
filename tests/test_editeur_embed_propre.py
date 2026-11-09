"""10/11/2026 : capture /embeds create — carte vide « Information » et réglages tassés."""
from __future__ import annotations

import os

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import discord  # noqa: E402

from cogs.embed_builder import EmbedBuilderView, EmbedDraft  # noqa: E402
from cogs.final_interaction_policy import _clean_embed  # noqa: E402
from utils.command_style_v2 import est_bandeau_image, style_embed  # noqa: E402


def _bandeau() -> discord.Embed:
    embed = discord.Embed(colour=0x6C57CC)
    embed.set_image(url="attachment://bandeau.png")
    return embed


def test_une_banniere_seule_ne_devient_pas_une_carte_information():
    for nettoyer in (lambda e: _clean_embed(e, root="embeds"), lambda e: style_embed(e)):
        sortie = nettoyer(_bandeau())
        assert sortie.title is None and sortie.footer.text is None
        assert sortie.image.url == "attachment://bandeau.png"


def test_un_vrai_panneau_avec_image_reste_style():
    embed = _bandeau()
    embed.title = "Résultat"
    assert not est_bandeau_image(embed)


def test_les_reglages_de_l_editeur_ne_sont_plus_tasses_sur_une_ligne():
    draft = EmbedDraft()
    draft.template_name = "Règlement"
    vue = EmbedBuilderView.__new__(EmbedBuilderView)
    vue.draft, vue.banner_enabled = draft, False
    statut = vue.build_panel_embeds()[0]
    noms = {f.name: f for f in statut.fields}
    assert {"Texte", "Apparence", "Éléments", "Brouillon"} <= set(noms)
    assert not noms["Apparence"].inline and not noms["Éléments"].inline
    cleaned = _clean_embed(statut, root="embeds")
    assert "Apparence" in [f.name for f in cleaned.fields]
    assert "•" not in (cleaned.description or "")
