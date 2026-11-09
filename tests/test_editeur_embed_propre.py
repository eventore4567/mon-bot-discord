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
    vue.draft = draft
    statut = vue.build_panel_embeds()[0]
    noms = {f.name: f for f in statut.fields}
    assert {"Texte", "Apparence", "Éléments", "Brouillon"} <= set(noms)
    assert not noms["Apparence"].inline and not noms["Éléments"].inline
    cleaned = _clean_embed(statut, root="embeds")
    assert "Apparence" in [f.name for f in cleaned.fields]
    assert "•" not in (cleaned.description or "")


def test_le_bouton_mentions_devient_vert_quand_il_est_active():
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock

    from cogs.embed_builder import MENTIONS_OFF, MENTIONS_ON, EmbedSendView

    async def scenario():
        parent = SimpleNamespace(draft=EmbedDraft(), author_id=1, build_panel_embeds=lambda: [])
        vue = EmbedSendView(parent)
        bouton = vue.toggle_mentions
        assert bouton.style == discord.ButtonStyle.secondary and bouton.label == MENTIONS_OFF
        membre = MagicMock(spec=discord.Member)
        membre.guild_permissions = SimpleNamespace(mention_everyone=True)
        interaction = SimpleNamespace(user=membre, response=SimpleNamespace(edit_message=AsyncMock()))
        await bouton.callback(interaction)
        assert vue.allow_mentions and bouton.style == discord.ButtonStyle.success and bouton.label == MENTIONS_ON
        await bouton.callback(interaction)
        assert not vue.allow_mentions and bouton.style == discord.ButtonStyle.secondary

    asyncio.run(scenario())


def test_l_ecran_de_confirmation_a_un_vrai_titre_et_tout_le_resume():
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from cogs.embed_builder import EmbedSendView

    async def scenario():
        draft = EmbedDraft()
        draft.title = "Règlement officiel du serveur"
        draft.description = "Soyez respectueux."
        parent = SimpleNamespace(draft=draft, author_id=1, build_panel_embeds=lambda: [])
        vue = EmbedSendView(parent)
        vue.channel = SimpleNamespace(mention="<#42>")
        interaction = SimpleNamespace(response=SimpleNamespace(edit_message=AsyncMock()))
        await vue.proceed.callback(interaction)
        carte = interaction.response.edit_message.await_args.kwargs["embeds"][0]
        assert carte.title == "📨 Confirmer l'envoi ?"
        assert "<#42>" in carte.description and "désactivées" in carte.description

    asyncio.run(scenario())
