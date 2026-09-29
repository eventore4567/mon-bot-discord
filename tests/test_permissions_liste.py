"""``+permissions liste`` — la vue d'ensemble « qui peut lancer quoi ».

Deux surfaces d'explication existaient, et aucune ne répondait à la question :

* ``+permissions explain <commande>`` diagnostique UNE commande pour UN
  membre — parfait pour comprendre un refus précis, inutile pour relire la
  politique du bot ;
* ``+security permissions`` (alias ``permission-audit``) audite les
  permissions Discord dangereuses des RÔLES du serveur — qui possède
  Administrateur — ce qui est une autre question.

Ce que ces tests tiennent, dans l'ordre d'importance :

1. la vue et le garde disent la même chose. Une divergence serait le défaut le
   plus grave possible pour un outil d'audit : on relirait une politique qui
   n'est pas celle appliquée ;
2. la liste vient des commandes réellement chargées, pas d'une liste écrite à
   la main qui mentirait dès le premier ajout ;
3. la troncature est annoncée. Une liste coupée en silence se lit comme une
   liste complète.
"""
from __future__ import annotations

import os

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import pytest

from utils import access_matrix


# =============================================================================
# La vue et le garde disent la même chose
# =============================================================================

def test_chaque_niveau_a_un_libelle_non_vide():
    """``help_requirement`` est la seule source des libellés affichés. Un
    niveau sans libellé produirait une section vide dans l'audit."""
    for niveau in ("public", "owner-global", "guild-owner", "embed-staff",
                   "discord:ban_members", "categorie:securite", "fail-closed"):
        libelle = access_matrix.help_requirement(_commande_de_niveau(niveau))
        assert libelle and libelle.strip(), niveau


def _commande_de_niveau(niveau: str) -> str:
    """Une commande réelle dont ``access_tier`` rend ce niveau, pour ne pas
    tester des libellés sur des noms inventés."""
    exemples = {
        "public": "ping",
        "owner-global": next(iter(sorted(access_matrix.OWNER_ONLY_COMMANDS))),
        "guild-owner": next(iter(sorted(access_matrix.GUILD_OWNER_COMMANDS))),
        "embed-staff": "embed",
        "discord:ban_members": "ban",
        "categorie:securite": next(iter(sorted(access_matrix.CATEGORY_COMMANDS["securite"]))),
        "fail-closed": "commande-qui-nexiste-pas-xyz",
    }
    return exemples[niveau]


def test_le_libelle_du_public_est_bien_tout_le_monde():
    """C'est sur ce libellé exact que la vue groupe la section la plus ouverte."""
    assert access_matrix.help_requirement("ping") == "Tout le monde"


def test_une_permission_discord_est_nommee_en_clair():
    """« /ban → Bannir des membres », pas « /ban → ban_members ». Un audit lu
    par un administrateur doit employer les mots de l'interface Discord."""
    libelle = access_matrix.help_requirement("ban")
    assert "ban_members" not in libelle
    assert access_matrix.permission_label("ban_members") in libelle


def test_une_commande_owner_est_annoncee_comme_telle():
    owner = next(iter(sorted(access_matrix.OWNER_ONLY_COMMANDS)))
    assert access_matrix.help_requirement(owner) == "Propriétaire global SentriX"


def test_une_commande_non_classee_annonce_administrateur_et_le_dit():
    """Et c'est EXACT, contrairement à ce que j'avais cru : à l'étape (8) de la
    matrice, un administrateur est autorisé inconditionnellement, AVANT le
    refus fail-closed de l'étape (11). Une commande non classée n'est donc pas
    refusée à tout le monde — elle est refusée à tout ce qui est en dessous
    d'administrateur, y compris à un modérateur portant la permission Discord
    qui devrait suffire.
    """
    libelle = access_matrix.help_requirement("commande-qui-nexiste-pas-xyz")
    assert "Administrateur" in libelle
    assert "non classée" in libelle, (
        "le libellé doit signaler que c'est un défaut de classement, pas une "
        "politique choisie"
    )


# =============================================================================
# Le regroupement de la vue
# =============================================================================

#: Recopié de la commande : l'ordre d'affichage, du plus ouvert au plus fermé.
ORDRE_ATTENDU = (
    "Tout le monde",
    "Gérer les messages / Gérer le serveur / rôle +embed",
    "Administrateur (ou rôle autorisé dans Setup)",
    "Administrateur (commande non classée)",
    "Propriétaire du serveur uniquement",
    "Propriétaire global SentriX",
)


def test_lordre_daffichage_couvre_les_libelles_reellement_produits():
    """Un libellé absent de l'ordre se rangerait au rang 1, donc juste après le
    public — ce qui ferait passer une commande d'administration pour presque
    publique. On vérifie que les libellés fixes sont tous prévus."""
    from cogs import permissions_explain

    source = permissions_explain.PermissionsExplain.permissions_liste
    assert source is not None
    produits = {
        access_matrix.help_requirement(_commande_de_niveau(n))
        for n in ("public", "owner-global", "guild-owner", "embed-staff", "fail-closed")
    }
    manquants = produits - set(ORDRE_ATTENDU)
    assert manquants == set(), f"libellés non prévus dans l'ordre : {manquants}"


def test_le_public_vient_avant_le_proprietaire():
    """La lecture va du plus ouvert au plus fermé : c'est ce qui rend l'audit
    survolable."""
    assert ORDRE_ATTENDU.index("Tout le monde") < ORDRE_ATTENDU.index(
        "Propriétaire global SentriX"
    )


def test_une_commande_non_classee_ne_passe_pas_pour_publique():
    """Elle doit se ranger APRÈS l'administrateur, pas au rang des permissions
    Discord nommées."""
    assert ORDRE_ATTENDU.index("Administrateur (commande non classée)") > ORDRE_ATTENDU.index(
        "Tout le monde"
    )


# =============================================================================
# La commande elle-même
# =============================================================================

def test_la_commande_est_une_sous_commande_du_groupe_existant():
    """Pas une nouvelle racine : les contrats de surface sont figés, et une
    racine de plus casserait les comptages de tools/command_runtime_audit."""
    from cogs import permissions_explain

    groupe = permissions_explain.PermissionsExplain.permissions
    noms = {c.name for c in groupe.commands}
    assert "liste" in noms
    assert "explain" in noms


def test_la_commande_a_des_alias_utilisables():
    from cogs import permissions_explain

    liste = next(
        c for c in permissions_explain.PermissionsExplain.permissions.commands
        if c.name == "liste"
    )
    assert "audit" in liste.aliases


def test_la_vue_ne_prend_aucune_decision_de_permission():
    """Le contrat du module : il met en forme, il ne décide pas. Une seconde
    logique de décision divergerait de la matrice au premier changement — c'est
    exactement le défaut trouvé sur la confirmation des actions IA, où deux
    chemins décidaient chacun de leur côté.
    """
    import inspect

    from cogs import permissions_explain

    # .callback et non l'attribut : le decorateur en fait un HybridCommand,
    # dont inspect ne sait pas lire la source.
    source = inspect.getsource(
        permissions_explain.PermissionsExplain.permissions_liste.callback
    )
    # Elle lit la matrice…
    assert "help_requirement" in source
    # …et ne recalcule aucune appartenance elle-même.
    for interdit in ("PUBLIC_COMMANDS", "OWNER_ONLY_COMMANDS", "CATEGORY_COMMANDS"):
        assert interdit not in source, (
            f"la vue consulte {interdit} directement au lieu de passer par "
            "help_requirement() : deux sources de vérité"
        )


def test_la_troncature_est_annoncee():
    """Une liste coupée en silence se lit comme une liste complète, et l'audit
    devient trompeur. On vérifie que le code annonce le reste."""
    import inspect

    from cogs import permissions_explain

    # .callback et non l'attribut : le decorateur en fait un HybridCommand,
    # dont inspect ne sait pas lire la source.
    source = inspect.getsource(
        permissions_explain.PermissionsExplain.permissions_liste.callback
    )
    assert "autres" in source, "la troncature n'est pas annoncée au lecteur"
