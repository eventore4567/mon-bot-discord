"""Le temps qu'un modérateur subit vient des allers-retours Discord, pas du calcul.

Relevé en production : ``+mute`` tenait environ 2,35 s alors que la commande
réussissait. Profilé sur le bot booté, tout le travail local coûte 12 ms — la
latence est entièrement dans six appels HTTP enchaînés.

Deux d'entre eux n'avaient aucune raison d'être sur le chemin critique :
l'indicateur de frappe, qui n'a besoin que d'être demandé pour apparaître, et
la fiche de log, qui part vers un autre salon que la confirmation. Mesuré avec
300 ms de latence simulée par appel : +mute passe de 1 800 à 1 216 ms, +ban,
+kick et +unmute de 1 500 à 1 212, +warn de 1 200 à 911.
"""
from __future__ import annotations

import ast
import inspect
import os
import textwrap

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from cogs.moderation import Moderation


def test_l_accuse_de_reception_slash_reste_bloquant():
    """Discord ferme une interaction sans accusé sous trois secondes : celui-là
    doit être attendu, contrairement à l'indicateur de frappe."""
    source = inspect.getsource(Moderation._ack)
    avant_retour = source[:source.index("return")]
    assert "await ctx.interaction.response.defer()" in avant_retour


def test_l_indicateur_de_frappe_ne_bloque_plus():
    """En préfixe, attendre la confirmation du « SentriX écrit… » ajoutait un
    aller-retour complet avant même de commencer la sanction."""
    source = inspect.getsource(Moderation._ack)
    assert "await ctx.typing()" not in source, "l'indicateur est redevenu bloquant"
    assert "create_task" in source


def test_l_indicateur_de_frappe_garde_une_reference():
    """Une tâche sans référence forte peut être annulée par le ramasse-miettes.

    L'ensemble vit au niveau du module et non sur le cog : le poser sur
    l'instance le rendait indisponible aux tests qui construisent un
    Moderation sans passer par __init__, et vingt-sept d'entre eux tombaient.
    """
    from cogs import moderation as module

    assert isinstance(module._TACHES_TYPING, set)
    ack = inspect.getsource(Moderation._ack)
    assert "_TACHES_TYPING.add" in ack
    assert "add_done_callback" in ack


def test_l_echec_de_l_indicateur_ne_remonte_pas():
    """Un indicateur de frappe raté ne concerne personne, mais une exception
    dans une tâche détachée polluerait les journaux."""
    source = inspect.getsource(Moderation._typing_silencieux)
    assert "except Exception" in source
    assert "logger.debug" in source


def test_mute_lance_le_log_et_la_reponse_ensemble():
    """Deux destinations sans lien : le salon de logs et le salon courant.
    Les enchaîner faisait attendre l'auteur pour un message qu'il ne voit pas."""
    source = textwrap.dedent(inspect.getsource(Moderation.mute.callback))
    arbre = ast.parse(source)
    taches = [n for n in ast.walk(arbre)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
              and n.func.attr == "create_task"]
    assert taches, "la fiche de log est redevenue bloquante avant la réponse"


def test_le_log_de_sanction_est_toujours_attendu():
    """Une tâche abandonnée avalerait son erreur : un log de sanction perdu en
    silence est exactement ce qu'il ne faut pas."""
    source = textwrap.dedent(inspect.getsource(Moderation.mute.callback))
    assert "finally:" in source
    apres = source[source.index("finally:"):]
    assert "await journal" in apres


def test_aucun_delai_arbitraire_n_a_ete_ajoute():
    """Masquer la lenteur derrière un sleep ou un timeout ne la corrige pas."""
    source = inspect.getsource(Moderation.mute.callback) + inspect.getsource(Moderation._ack)
    assert "asyncio.sleep" not in source
    assert "wait_for" not in source
