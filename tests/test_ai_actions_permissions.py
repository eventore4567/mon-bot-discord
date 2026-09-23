"""L'IA exécute des actions Discord : elle ne doit JAMAIS contourner les permissions.

Depuis ddfa2ba (« execute natural Discord actions directly »), une phrase naturelle
peut déclencher un bannissement. Deux chemins existent et chacun a sa garde :

- les actions qui correspondent à une commande (ban, kick, mute, purge…) passent par
  ``bot.invoke`` sur une copie du message : matrice d'accès, checks, hiérarchie,
  cooldowns et journalisation sont exactement ceux de la commande tapée à la main ;
- les actions natives (salon, rôle, pseudo, embed…) n'ont pas de commande derrière :
  chacune DOIT donc vérifier elle-même la permission de l'auteur ET celle du bot.

Ce test fige les deux contrats au niveau du code : une nouvelle action native sans
garde d'autorisation le fait échouer.
"""
from __future__ import annotations

import inspect
import re

from cogs import ai as ai_cog
from utils import ai_actions


def _corps_des_intentions_natives() -> dict[str, str]:
    """Découpe _execute_native_action en un bloc par intention gérée."""
    source = inspect.getsource(ai_cog.Ai._execute_native_action)
    morceaux = re.split(r"\n        if intent (?:==|in) ", source)
    blocs: dict[str, str] = {}
    for morceau in morceaux[1:]:
        entete = morceau.split("\n", 1)[0]
        for nom in re.findall(r'"([\w.]+)"', entete):
            blocs[nom] = morceau
    return blocs


def test_chaque_action_native_verifie_la_permission_de_l_auteur():
    """Sans commande derrière, l'action native est la SEULE garde : si elle oublie de
    regarder les permissions de l'auteur, n'importe quel membre fait agir le bot."""
    exemptes = {
        # Rejoindre/quitter un vocal : l'auteur doit déjà être dans le salon (ou avoir
        # une permission de gestion, vérifiée dans le bloc voice.leave).
        "voice.join",
    }
    manquantes = []
    for intent, bloc in _corps_des_intentions_natives().items():
        if intent in exemptes:
            continue
        if not re.search(r"actor\.guild_permissions\.\w+|actor_perms\.\w+|permissions_for\(actor\)", bloc):
            manquantes.append(intent)
    assert not manquantes, f"actions natives sans garde d'autorisation : {manquantes}"


def test_les_actions_natives_verifient_aussi_les_permissions_du_bot():
    """Sinon le membre reçoit « c'est fait » alors que Discord a refusé."""
    exemptes = {"voice.leave"}  # se déconnecter ne demande aucune permission
    manquantes = []
    for intent, bloc in _corps_des_intentions_natives().items():
        if intent in exemptes:
            continue
        if not re.search(r"me\.guild_permissions\.\w+|bot_perms\.\w+|permissions_for\(me\)", bloc):
            manquantes.append(intent)
    assert not manquantes, f"actions natives sans vérification des permissions du bot : {manquantes}"


def test_les_actions_sur_un_membre_verifient_la_hierarchie():
    """Un modérateur ne doit pas renommer ou déplacer quelqu'un au-dessus de lui."""
    blocs = _corps_des_intentions_natives()
    for intent in ("member.nickname", "category.restrict_role"):
        bloc = blocs.get(intent, "")
        assert re.search(r"top_role|check_hierarchy|check_role_target", bloc), intent


def test_une_action_avec_commande_passe_par_le_moteur_de_commandes():
    """C'est ce qui donne à l'IA la MÊME décision qu'à la commande tapée à la main :
    matrice d'accès, checks, hiérarchie, cooldowns, journal."""
    source = inspect.getsource(ai_cog.Ai._invoke_command_line)
    assert "self.bot.invoke(ctx)" in source
    assert "get_context" in source
    # Le message d'origine n'est jamais modifié : on invoque une copie.
    assert "copy.copy(message)" in source


def test_aucune_action_du_registre_ne_contourne_une_commande_de_sanction():
    """Une sanction doit rester une commande : si un intent de modération perdait son
    champ ``command``, il serait exécuté nativement, sans la matrice d'accès."""
    for intent, spec in ai_actions.ACTIONS.items():
        if intent.startswith("moderation."):
            assert spec.command, f"{intent} n'a plus de commande derrière lui"


def test_le_modele_ne_peut_pas_inventer_une_action():
    """Le classifieur choisit dans le registre ; il ne fabrique pas d'intention."""
    from utils.ai_actions import _validate_ai_payload

    assert _validate_ai_payload({"intent": "moderation.ban", "confidence": 95}) is not None
    # Une intention absente du registre est rejetée, quelle que soit la confiance.
    assert _validate_ai_payload({"intent": "serveur.autodestruction", "confidence": 100}) is None
    assert _validate_ai_payload({"intent": "", "confidence": 100}) is None
    # Une confiance faible ne déclenche rien non plus.
    assert _validate_ai_payload({"intent": "moderation.ban", "confidence": 40}) is None
