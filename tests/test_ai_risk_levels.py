"""Niveaux de risque de l'IA : lecture directe, modération sous permissions,
destructif sous confirmation supplémentaire.

**Le défaut central, mesuré.** Les deux chemins d'exécution de l'IA
décidaient la confirmation différemment.

Le chemin multi-actions lisait les champs du registre :

    sensitive = any(a.spec.confirm or a.spec.risk == "high" for a in plan)

Le chemin à action unique, lui, décidait sur un ensemble de deux noms
d'intentions écrits en dur dans cogs/ai.py :

    action.intent in {"tickets.grant_access", "category.restrict_role"}

Ni ``risk`` ni ``confirm`` n'y étaient lus. Conséquence : ``moderation.purge``,
pourtant déjà classé ``high``, s'exécutait sans confirmation dès qu'il arrivait
seul — « SentriX supprime 100 messages » partait directement. Idem pour
``security.antinuke``.

Ces tests fixent une source unique, ``ai_actions.exige_confirmation()``, et
refusent que les deux chemins se remettent à décider chacun de leur côté.
"""
from __future__ import annotations

import ast
import inspect
import os
import textwrap

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import pytest

from utils import ai_actions
from utils.ai_actions import ACTIONS, NIVEAUX_DE_RISQUE, exige_confirmation


# =============================================================================
# La source unique
# =============================================================================

def test_un_spec_absent_exige_la_confirmation():
    """Fail-closed, comme la matrice d'accès : une action que l'on ne sait pas
    classer ne part jamais toute seule."""
    assert exige_confirmation(None) is True


def test_le_haut_risque_exige_la_confirmation():
    for nom, spec in ACTIONS.items():
        if spec.risk == "high":
            assert exige_confirmation(spec) is True, nom


def test_le_drapeau_confirm_suffit_meme_sans_haut_risque():
    """Une action de risque moyen peut réclamer une confirmation pour une autre
    raison que sa destructivité — config.logs.route touche au routage des
    journaux de tout le serveur."""
    moyens_avec_confirm = [
        nom for nom, s in ACTIONS.items() if s.risk == "medium" and s.confirm
    ]
    assert moyens_avec_confirm, "le test ne mesure plus rien"
    for nom in moyens_avec_confirm:
        assert exige_confirmation(ACTIONS[nom]) is True, nom


def test_une_lecture_ne_demande_jamais_de_confirmation():
    """Faire confirmer « SentriX c'est quoi mon solde ? » rendrait l'IA
    inutilisable, et ne protégerait de rien."""
    for nom, spec in ACTIONS.items():
        if spec.risk == "low":
            assert exige_confirmation(spec) is False, nom


# =============================================================================
# Le classement lui-même
# =============================================================================

def test_aucun_niveau_inventé():
    invalides = {nom: s.risk for nom, s in ACTIONS.items() if s.risk not in NIVEAUX_DE_RISQUE}
    assert invalides == {}, f"niveaux hors des trois prévus : {invalides}"


#: Ce que chaque action de modération doit valoir. Figé volontairement : un
#: changement de niveau sur une de ces actions doit être un geste explicite,
#: pas un effet de bord.
CLASSEMENT_ATTENDU = {
    # Destructif — ne se défait pas, ou pas proprement.
    "moderation.ban": "high",
    "moderation.tempban": "high",
    "moderation.purge": "high",
    "security.antinuke": "high",
    # Modération — les permissions décident seules.
    "moderation.kick": "medium",      # réversible : le membre peut revenir
    "moderation.unban": "medium",     # RESTAURE un accès, l'inverse d'un acte destructif
    "moderation.mute": "medium",
    "moderation.unmute": "medium",
    "moderation.warn": "medium",
    # Lecture — ne change rien.
    "moderation.warnings": "low",
    "moderation.history": "low",
    "economy.balance": "low",
    "levels.leaderboard": "low",
    "server.info": "low",
}


@pytest.mark.parametrize("intention,niveau", sorted(CLASSEMENT_ATTENDU.items()))
def test_le_classement_est_celui_attendu(intention, niveau):
    assert intention in ACTIONS, f"{intention} a disparu du registre"
    assert ACTIONS[intention].risk == niveau


def test_mute_warn_et_unmute_ne_sont_plus_des_lectures():
    """Ces trois-là étaient classés `low`, au même niveau que `economy.balance`
    et `music.play`. Un mute change l'état du serveur : ce n'est pas une
    lecture, et le confondre avec une lecture brouille tout le classement."""
    for intention in ("moderation.mute", "moderation.unmute", "moderation.warn"):
        assert ACTIONS[intention].risk != "low", intention


def test_bannir_demande_une_confirmation():
    """Un bannissement demandé en langage naturel partait sur un seul message,
    sans que personne ne relise la cible. C'est l'action la moins réversible
    du bot."""
    assert exige_confirmation(ACTIONS["moderation.ban"]) is True
    assert exige_confirmation(ACTIONS["moderation.tempban"]) is True


def test_supprimer_des_messages_demande_une_confirmation():
    """Le cas qui a motivé ce lot : classé `high` depuis le début, et
    s'exécutant pourtant sans confirmation parce que le chemin à action unique
    ne lisait pas le champ."""
    assert exige_confirmation(ACTIONS["moderation.purge"]) is True


def test_une_action_de_moderation_ne_demande_pas_de_clic_inutile():
    """Le staff modère à la journée. Une confirmation à chaque mute serait un
    obstacle, pas une sécurité — les permissions sont là pour ça."""
    for intention in ("moderation.mute", "moderation.unmute", "moderation.warn",
                      "moderation.kick", "moderation.unban"):
        assert exige_confirmation(ACTIONS[intention]) is False, intention


# =============================================================================
# Les deux chemins lisent la MÊME décision
# =============================================================================

def _source_de_ai():
    from cogs import ai

    return inspect.getsource(ai)


def test_les_deux_chemins_appellent_exige_confirmation():
    """Le cœur : deux appels, un par chemin. Moins de deux signifie qu'un
    chemin a repris sa propre règle."""
    source = _source_de_ai()
    assert source.count("exige_confirmation") >= 2, (
        "un des deux chemins d'exécution ne passe plus par la source unique"
    )


def test_aucun_chemin_ne_reintroduit_une_liste_dintentions_en_dur():
    """Le défaut exact qui est corrigé : une condition de confirmation qui
    énumère des noms d'intentions au lieu de lire le registre. On cherche
    l'ancienne forme précise, pas un mot-clé vague — un test qui échoue sur son
    propre commentaire ne sert personne.
    """
    source = _source_de_ai()
    ancienne_forme = 'action.intent in {"tickets.grant_access", "category.restrict_role"}'
    # Présente uniquement dans le commentaire qui explique le correctif : on
    # vérifie qu'elle n'est pas dans du CODE, en relisant l'arbre syntaxique.
    arbre = ast.parse(source)
    comparaisons_dintentions = []
    for noeud in ast.walk(arbre):
        if not isinstance(noeud, ast.Compare):
            continue
        if not any(isinstance(op, ast.In) for op in noeud.ops):
            continue
        gauche = ast.unparse(noeud.left)
        if "intent" not in gauche:
            continue
        for comparateur in noeud.comparators:
            if isinstance(comparateur, (ast.Set, ast.List, ast.Tuple)):
                membres = {
                    e.value for e in comparateur.elts
                    if isinstance(e, ast.Constant) and isinstance(e.value, str)
                }
                if any("." in m for m in membres):
                    comparaisons_dintentions.append((gauche, sorted(membres)))
    # Certaines comparaisons d'intentions sont légitimes (aiguiller vers un
    # traitement propre à une action). Ce qui ne doit plus exister, c'est
    # précisément l'ensemble qui servait de porte de confirmation.
    interdits = [
        c for c in comparaisons_dintentions
        if set(c[1]) == {"category.restrict_role", "tickets.grant_access"}
    ]
    assert interdits == [], (
        "la porte de confirmation est redevenue une liste d'intentions en dur : "
        f"{interdits}\n(forme d'origine : {ancienne_forme})"
    )


def test_ajouter_une_action_a_haut_risque_suffit():
    """La propriété qui rend le correctif durable : une nouvelle action classée
    `high` obtient sa confirmation sans qu'on touche à cogs/ai.py."""
    inventee = ai_actions.ActionSpec(
        "test.demolition", "wipe-server", (), (), None, "high",
        description="action de test",
    )
    assert exige_confirmation(inventee) is True


def test_une_action_inconnue_du_registre_ne_part_pas_seule():
    """``ParsedAction.spec`` rend None pour une intention absente du registre.
    exige_confirmation(None) valant True, une intention inventée par le modèle
    ne peut pas s'exécuter directement."""
    action = ai_actions.ParsedAction(intent="intention.inventee.par.le.modele", slots={})
    assert action.spec is None
    assert exige_confirmation(action.spec) is True


# =============================================================================
# Les permissions restent la première barrière, la confirmation la seconde
# =============================================================================

def test_la_confirmation_ne_remplace_pas_les_permissions():
    """Règle posée par Jayden : « L'IA ne doit JAMAIS permettre de contourner
    les permissions. » La confirmation s'AJOUTE aux permissions, elle ne s'y
    substitue pas — sinon un membre sans droits pourrait bannir en cliquant.

    On le vérifie sur la structure : la vue de confirmation exécute l'action
    par le même chemin d'invocation que tout le reste, celui qui passe par les
    gardes globales.
    """
    source = _source_de_ai()
    # Le chemin d'exécution après confirmation doit repasser par
    # _execute_action_plan / _handle_parsed_action, qui invoquent via
    # bot.invoke() — jamais un appel direct au callback de la commande.
    assert "await self.bot.invoke(ctx)" in source, (
        "l'IA n'invoque plus par bot.invoke() : les six gardes globales ne "
        "s'appliqueraient plus"
    )
    assert ".callback(" not in source.replace("command.callback.__name__", ""), (
        "un appel direct à un callback de commande contourne toutes les gardes"
    )
