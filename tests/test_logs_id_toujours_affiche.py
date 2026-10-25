"""Chaque carte de log montre l'ID de l'élément concerné, salon compris.

Une mention Discord ne survit pas au départ d'un membre ou à la suppression
d'un salon : la carte affichait alors « @utilisateur inconnu » sans moyen
de retrouver qui ou quoi. L'ID reste à côté de la mention.
"""
import os

os.environ.setdefault("DISCORD_TOKEN", "x")

import discord  # noqa: E402

from utils import wide_logs  # noqa: E402

MEMBRE = 111111111111111111
SALON = 222222222222222222


def _carte(embed, log_type, identity_id):
    vue = wide_logs.WideLogView(
        embed, banner_filename="", log_type=log_type,
        identity_name="Toxic", identity_id=identity_id, identity_icon=None,
    )
    return "\n".join(
        item.content for item in vue.children[0].walk_children()
        if isinstance(item, discord.ui.TextDisplay)
    )


def test_le_membre_et_son_id():
    embed = discord.Embed(title="Membre arrivé", description="Toxic a rejoint le serveur.")
    texte = _carte(embed, "member_join", MEMBRE)
    assert f"<@{MEMBRE}> · `{MEMBRE}`" in texte


def test_le_salon_d_un_message_supprime_et_son_id():
    embed = discord.Embed(title="Message supprimé", description="Bonjour")
    embed.add_field(name="Salon", value=f"<#{SALON}>")
    texte = _carte(embed, "message_delete", MEMBRE)
    assert f"`{MEMBRE}`" in texte
    assert f"<#{SALON}> · `{SALON}`" in texte


def test_le_salon_modifie_et_son_id():
    embed = discord.Embed(title="Salon modifié", description="Nom changé.")
    texte = _carte(embed, "channel_update", SALON)
    assert f"<#{SALON}> · `{SALON}`" in texte


def test_pas_de_faux_id_pour_un_compteur():
    assert wide_logs._id_chip(17) == ""
    assert wide_logs._id_chip("abc") == ""
