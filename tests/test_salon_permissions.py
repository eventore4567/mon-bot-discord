"""Afficher les permissions réelles d'un salon, rôle par rôle.

Demandé par Jayden le 2026-10-23. ``+channelinfo`` n'en donnait qu'un
résumé — privé ou public, le nombre de règles — ce qui ne dit jamais QUI
peut faire QUOI. Discord oblige à ouvrir les réglages du salon puis
chaque rôle un par un.

Point de conception à ne pas perdre : ``PermissionOverwrite`` rend trois
états — True, False et None. Seuls les deux premiers sont des décisions.
Afficher les None reviendrait à lister 55 lignes « non définie » et à
noyer les trois qui comptent.
"""
from __future__ import annotations

import os
from unittest.mock import MagicMock

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import discord
import pytest

from cogs import salon_permissions as sp


def _derogation(**kwargs) -> discord.PermissionOverwrite:
    return discord.PermissionOverwrite(**kwargs)


def test_seules_les_decisions_sont_listees():
    autorise, refuse = sp.resume_derogation(
        _derogation(view_channel=True, send_messages=False)
    )
    assert autorise == ["Voir les salons"]
    assert refuse == ["Envoyer des messages"]


def test_une_permission_neutre_n_apparait_pas():
    """None veut dire « on n'y touche pas », pas « refusé »."""
    autorise, refuse = sp.resume_derogation(_derogation(view_channel=None))
    assert autorise == [] and refuse == []


def test_une_derogation_vide_ne_produit_aucune_ligne():
    assert sp._ligne_cible(MagicMock(), _derogation()) is None


def test_les_libelles_sont_en_francais():
    autorise, _ = sp.resume_derogation(_derogation(manage_messages=True, connect=True))
    assert "Gérer les messages" in autorise
    assert "Se connecter" in autorise


def test_everyone_est_nomme_lisiblement():
    """@everyone mentionné pingrait tout le serveur à chaque affichage."""
    role = MagicMock(spec=discord.Role)
    role.is_default.return_value = True
    assert sp._nom_cible(role) == "@everyone"


def test_un_role_normal_est_mentionne():
    role = MagicMock(spec=discord.Role)
    role.is_default.return_value = False
    role.mention = "<@&42>"
    assert sp._nom_cible(role) == "<@&42>"


def test_une_longue_liste_est_tronquee_en_le_disant():
    """Un message trop long est REFUSÉ par Discord, pas raccourci."""
    beaucoup = _derogation(**{nom: True for nom in (
        "view_channel", "send_messages", "manage_messages", "embed_links",
        "attach_files", "read_message_history", "add_reactions", "connect",
        "speak", "stream", "move_members", "mute_members",
    )})
    ligne = sp._ligne_cible(MagicMock(), beaucoup)
    assert "(+" in ligne, "la troncature doit être annoncée"
    assert ligne.count(",") <= sp.MAX_PERMS_PAR_CIBLE


def test_les_bornes_restent_raisonnables():
    assert 0 < sp.MAX_CIBLES <= 25
    assert 0 < sp.MAX_PERMS_PAR_CIBLE <= 25


def test_la_commande_est_reservee_a_qui_gere_les_salons():
    """Les dérogations d'un salon privé ne regardent pas tout le monde."""
    import inspect

    src = inspect.getsource(sp)
    assert 'has_permission_or_modrole("manage_channels")' in src


def test_le_module_n_ecrit_jamais_de_permission():
    """Lecture seule : une commande d'affichage ne doit rien modifier."""
    import inspect

    src = inspect.getsource(sp)
    for interdit in ("set_permissions", "edit(", "delete("):
        assert interdit not in src, f"{interdit} n'a rien à faire dans un module de lecture"
