"""Une erreur courte a la même apparence qu'une réponse longue.

**Ce que Jayden a vu.** « Plein de trucs n'ont pas de bannière donc ça fait
très moche ; juste les petites phrases sont en texte, pas le gros texte. »

**Ce que la mesure a montré**, sur vingt-cinq commandes lancées sur le bot
booté : huit réponses partaient sans bannière, et toutes étaient des phrases
courtes — « Commande introuvable », « Il manque l'argument obligatoire ». Le
bot avait donc deux apparences selon la longueur du message : conteneur,
bannière et couleur pour une réponse riche, ligne de texte nue pour une erreur.

**Trois chemins traitaient le cas**, et c'est ce qui l'a rendu difficile à
corriger :

    sentrix_product_update._plain_send        installé en DERNIER sur
                                              bot.on_command_error, donc c'est
                                              lui qui gagnait
    cogs/final_error_embed_v5                 dessous, jamais atteint pour une
                                              commande inconnue
    cogs/error_experience_v3                  sa branche « argument manquant »
                                              rendait déjà un panneau, sa
                                              branche voisine « commande
                                              introuvable » du texte nu

Corriger les deux premiers sans le troisième ne changeait rien à l'écran —
mesuré, et c'est ce qui a coûté deux passes.

Le TEXTE des messages ne change pas : il est rédigé ailleurs, partagé avec le
transport slash, et figé par test_product_update_contract. Seule l'enveloppe
change.
"""
from __future__ import annotations

import os

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import pytest
from discord.ext import commands


# =============================================================================
# Le titre et la couleur disent CE QUI s'est passé
# =============================================================================

def _erreur(classe, *args):
    """Instancie une erreur discord.py sans dépendre de son constructeur."""
    try:
        return classe(*args)
    except Exception:
        return classe.__new__(classe)


CAS = [
    (commands.CommandNotFound, (), "Commande introuvable", "warning"),
    (commands.MissingRequiredArgument, (), "Argument manquant", "warning"),
    (commands.BadArgument, ("x",), "Argument invalide", "warning"),
    (commands.MissingPermissions, (["ban_members"],), "Permission requise", "danger"),
    (commands.BotMissingPermissions, (["ban_members"],), "Permission manquante pour SentriX", "danger"),
    (commands.NotOwner, ("x",), "Réservé au propriétaire", "danger"),
    (commands.CheckFailure, ("x",), "Accès refusé", "danger"),
    (commands.NoPrivateMessage, ("x",), "Serveur requis", "warning"),
]


@pytest.mark.parametrize("classe,args,titre,kind", CAS)
def test_chaque_erreur_a_son_titre_et_sa_couleur(classe, args, titre, kind):
    from cogs.final_error_embed_v5 import _titre_et_couleur

    obtenu_titre, obtenu_kind = _titre_et_couleur(_erreur(classe, *args))
    assert obtenu_titre == titre
    assert obtenu_kind == kind


def test_une_faute_de_frappe_nest_pas_affichee_comme_une_faute_grave():
    """Une commande mal tapée et un refus de permission ne méritent pas la même
    couleur. Tout afficher en rouge les rendrait tous également alarmants, et
    plus rien ne ressortirait."""
    from cogs.final_error_embed_v5 import _titre_et_couleur

    _titre, typo = _titre_et_couleur(_erreur(commands.CommandNotFound))
    _titre, refus = _titre_et_couleur(_erreur(commands.MissingPermissions, ["ban_members"]))
    assert typo == "warning"
    assert refus == "danger"
    assert typo != refus


def test_les_sous_classes_passent_avant_leurs_parents():
    """MissingPermissions hérite de CheckFailure. Si l'ordre de la table
    s'inversait, un refus de permission précis s'afficherait sous le titre
    générique « Accès refusé » et le membre ne saurait pas quelle permission
    lui manque."""
    from cogs.final_error_embed_v5 import _titre_et_couleur

    titre, _ = _titre_et_couleur(_erreur(commands.MissingPermissions, ["ban_members"]))
    assert titre == "Permission requise"
    titre_bot, _ = _titre_et_couleur(_erreur(commands.BotMissingPermissions, ["ban_members"]))
    assert titre_bot == "Permission manquante pour SentriX"


def test_une_erreur_inconnue_reste_traitee():
    """Fail-safe : une erreur qu'on n'a pas prévue doit quand même s'afficher,
    pas disparaître."""
    from cogs.final_error_embed_v5 import _titre_et_couleur

    titre, kind = _titre_et_couleur(RuntimeError("bug inattendu"))
    assert titre and kind == "danger"


# =============================================================================
# Les trois chemins envoient bien un panneau
# =============================================================================

def test_le_chemin_gagnant_envoie_un_panneau():
    """sentrix_product_update est installé EN DERNIER sur on_command_error :
    c'est lui qui décide pour une commande inconnue. Corriger les deux autres
    sans celui-ci ne changeait rien à l'écran."""
    import inspect

    import sentrix_product_update as spu

    source = inspect.getsource(spu._plain_send)
    assert "panels.envoyer" in source
    assert "depuis_embed" in source


def test_le_chemin_gagnant_garde_un_repli_texte():
    """Cette fonction est appelée DEPUIS la gestion d'erreur : si elle lève,
    le membre n'a plus aucun message du tout. Un message nu vaut mieux que
    rien."""
    import inspect

    import sentrix_product_update as spu

    source = inspect.getsource(spu._plain_send)
    assert "except Exception" in source
    assert "Messageable.send" in source


def test_le_texte_exact_du_contrat_est_conserve():
    """Ce module existe pour garantir un message exact ; seule son enveloppe a
    changé. Si le texte bougeait, test_product_update_contract le dirait — on
    le vérifie aussi ici pour que la raison soit lisible au bon endroit."""
    import sentrix_product_update as spu

    assert spu.UNKNOWN_COMMAND_TEXT == (
        "Commande introuvable. Merci de consulter les commandes avec /help."
    )


def test_les_deux_branches_voisines_rendent_la_meme_chose():
    """Dans cogs/error_experience_v3, « commande introuvable » et « argument
    manquant » sont deux branches voisines du même if/elif. L'une rendait un
    panneau, l'autre du texte nu — deux apparences à quinze lignes d'écart."""
    import inspect

    from cogs import error_experience_v3

    source = inspect.getsource(error_experience_v3._handle_user_error)
    debut = source.index("CommandNotFound")
    fin = source.index("MissingRequiredArgument")
    branche_introuvable = source[debut:fin]
    assert "panels.envoyer" in branche_introuvable, (
        "la commande introuvable est repassée en texte nu"
    )


def test_une_faute_de_frappe_seface_toute_seule():
    """Elle ne doit pas encombrer le salon comme une vraie erreur : trente
    secondes pour une erreur technique avec sa référence de support, quelques
    secondes pour un mot mal tapé."""
    import inspect

    from cogs import error_experience_v3, final_error_embed_v5

    assert final_error_embed_v5._DUREE_COMMANDE_INTROUVABLE < final_error_embed_v5._DUREE_AFFICHAGE
    source = inspect.getsource(error_experience_v3._handle_user_error)
    assert "delete_after=5" in source


def test_lenvoi_de_panneau_accepte_une_duree():
    """Sans ce paramètre, toutes les erreurs restaient trente secondes, y
    compris les fautes de frappe."""
    import inspect

    from cogs.final_error_embed_v5 import _raw_prefix_send

    assert "supprimer_apres" in inspect.signature(_raw_prefix_send).parameters
