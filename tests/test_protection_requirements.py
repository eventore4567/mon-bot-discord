"""Une protection cochée mais incapable d'agir doit le dire.

C'est l'état le plus dangereux du panneau Sécurité : « Anti-nuke ● ACTIF »
affiché à un propriétaire dont le rôle SentriX n'a pas le journal d'audit.
L'anti-nuke ne détecte alors rien — get_audit_actor ne peut pas nommer
l'auteur, et l'anti-nuke refuse par construction de sanctionner au hasard.
Le panneau listait bien la permission manquante, mais dans un fourre-tout,
sans jamais relier les deux.
"""
from __future__ import annotations

import os

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import discord

from utils.protection_requirements import (
    DEGRADEE,
    EXIGENCES,
    INERTE,
    OPERATIONNELLE,
    diagnostic,
    etat_protection,
)


def test_sans_journal_d_audit_l_antinuke_est_declare_inerte():
    permissions = discord.Permissions.all()
    permissions.update(view_audit_log=False)
    etat, manquantes = etat_protection(permissions, "antinuke")
    assert etat == INERTE
    assert "Voir le journal d'audit" in manquantes


def test_sans_gerer_le_serveur_l_antiraid_est_degrade_pas_inerte():
    """La nuance compte : l'anti-raid alerte toujours, seule la riposte tombe."""
    permissions = discord.Permissions.all()
    permissions.update(manage_guild=False)
    etat, manquantes = etat_protection(permissions, "antiraid")
    assert etat == DEGRADEE
    assert "Gérer le serveur" in manquantes


def test_sans_gerer_les_messages_les_filtres_ne_peuvent_rien_supprimer():
    permissions = discord.Permissions.all()
    permissions.update(manage_messages=False)
    for protection in ("antispam", "antilink", "antiinvite", "antiscam", "antiinsult"):
        etat, _manquantes = etat_protection(permissions, protection)
        assert etat == INERTE, protection


def test_avec_toutes_les_permissions_rien_n_est_signale():
    inertes, degradees = diagnostic(discord.Permissions.all(), list(EXIGENCES))
    assert not inertes and not degradees


def test_seules_les_protections_activees_sont_signalees():
    """Dire qu'une protection décochée manque d'une permission n'apprend rien."""
    permissions = discord.Permissions.none()
    inertes, _degradees = diagnostic(permissions, ["antispam"])
    assert [nom for nom, _m in inertes] == ["antispam"]


def test_chaque_protection_du_panneau_a_ses_exigences():
    """Une protection ajoutée au panneau sans exigences serait silencieusement
    réputée opérationnelle, quelles que soient les permissions du bot."""
    from cogs.setup_control_center import AUTOMOD

    sans_exigence = [champ for champ, _label in AUTOMOD if champ not in EXIGENCES]
    assert not sans_exigence, f"protections sans exigences déclarées : {sans_exigence}"


def test_une_protection_inconnue_reste_operationnelle_sans_lever():
    """Le panneau ne doit jamais planter sur un nom qu'il ne connaît pas."""
    assert etat_protection(discord.Permissions.none(), "inconnue") == (OPERATIONNELLE, [])


def test_le_panneau_securite_affiche_le_diagnostic():
    import inspect

    from cogs import setup_security_choice_v75

    source = inspect.getsource(setup_security_choice_v75._build_security_v75)
    assert "protection_requirements.diagnostic" in source
    assert "ne se déclenchera jamais" in source
