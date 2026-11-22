"""Une menace écrite en SMS doit être vue (21/11/2026).

Captures d'un serveur harcelé, messages réels, tous laissés passer par
l'AutoMod : « Tu veut jte viol ta grand mère », « J'te d0x bb », « Vsy veski
pas ou jte bz ».

Le jeu de données multilingue (2663 termes) n'en détectait AUCUNE — il attrape
« ferme ta gueule » et laisse passer une menace de viol. La cause est
structurelle : une liste cherche des MOTS, une menace est une FORME.

Et l'architecture rendait le rattrapage impossible : _insulte_selon_contexte ne
pouvait qu'ANNULER une détection locale, jamais en créer une, donc l'IA n'était
même pas consultée sur ces messages.
"""
from __future__ import annotations

import os

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import pytest  # noqa: E402

from utils import menaces  # noqa: E402


@pytest.mark.parametrize(
    "message, attendu",
    [
        # Les messages EXACTS des captures.
        ("Tu veut jte viol ta grand mère sale trdc?", "menace_violence"),
        ("J'te d0x bb", "menace_dox"),
        ("Vsy veski pas ou jte bz", "menace_violence"),
        # Les formes voisines qu'on doit attraper aussi.
        ("jte nique ta race", "menace_violence"),
        ("je vais te defoncer", "menace_violence"),
        ("tu vas te faire ken", "menace_violence"),
        ("je te tue", "menace_violence"),
        ("jvais te butter", "menace_violence"),
        ("je balance ton ip", "menace_dox"),
        ("je vais te swat", "menace_dox"),
        ("jte viiiiiol", "menace_violence"),       # lettres répétées
        ("JTE V1OL", "menace_violence"),            # leet et majuscules
    ],
)
def test_une_menace_reelle_est_vue(message, attendu):
    assert menaces.menace_probable(message) == attendu


@pytest.mark.parametrize(
    "message",
    [
        "salut ca va les amis",
        "jte passe le lien",
        "je te vois demain",
        "on va te carry t'inquiète",
        "bien joué la team",
        "tu vas te faire carry lol",
        "",
    ],
)
def test_un_message_ordinaire_ne_leve_pas_la_main(message):
    assert menaces.menace_probable(message) is None


def test_le_detecteur_est_volontairement_large():
    """« je te baise au foot » lève la main — et c'est VOULU.

    Le partage est explicite : rappel ici, précision dans l'IA. Cette
    expression est déjà nommée dans la consigne de _insulte_selon_contexte
    comme exemple d'anodin, donc l'IA la disculpe. Resserrer le détecteur
    local pour « corriger » ça ferait repasser les vraies menaces.
    """
    assert menaces.menace_probable("je te baise au foot mdr") == "menace_violence"

    import inspect

    from cogs import automod

    consigne = inspect.getsource(automod.AutoMod._insulte_selon_contexte)
    assert "je te baise au foot" in consigne


def test_la_normalisation_couvre_leet_et_repetitions():
    assert menaces.normaliser("V1OL") == "viol"
    assert menaces.normaliser("niiiique") == "nique"
    # Les doubles normaux du français ne bougent pas : « baisse » != « baise ».
    assert menaces.normaliser("la baisse des prix") == "la baisse des prix"
    assert menaces.normaliser("D0XX") == "doxx"


def test_le_jeu_de_donnees_seul_ratait_tout():
    """La preuve du défaut, figée : sans ce module, rien n'était détecté."""
    from utils.moderation_dataset import MultilingualModerationDataset

    dataset = MultilingualModerationDataset()
    for message in (
        "Tu veut jte viol ta grand mère sale trdc?",
        "J'te d0x bb",
        "Vsy veski pas ou jte bz",
    ):
        assert dataset.match(message) is None, (
            f"si le jeu de données attrape enfin « {message} », ce test peut sauter"
        )
        assert menaces.menace_probable(message) is not None


def test_l_ia_peut_desormais_accuser_et_pas_seulement_disculper():
    """Le cœur du correctif architectural."""
    import inspect

    from cogs import automod

    source = inspect.getsource(automod.AutoMod._check_message) if hasattr(
        automod.AutoMod, "_check_message"
    ) else inspect.getsource(automod)
    assert "menaces.menace_probable" in source
    # Asymétrie volontaire : on sanctionne SAUF si l'IA dit explicitement anodin.
    assert "_insulte_selon_contexte(message) is not False" in source


# ------------------------------------------------- symboles ambigus (22/11/2026)

@pytest.mark.parametrize("message", [
    "jte vi@le",
    "jte vi0le",
    "je vais te d@x",
    "jte b@ise",
    "jte n!que",
])
def test_un_symbole_qui_remplace_une_autre_lettre_est_quand_meme_vu(message):
    """« vi@le » passait à travers, et pas faute de traduire le « @ ».

    Elle existait : « @ » valait « a ». Mais un même symbole remplace des
    lettres DIFFÉRENTES selon celui qui écrit — ici le « @ » tient la place du O
    de « viole », pas celle d'un A. La traduction donnait « viale », qui ne
    correspond à rien. On essaie donc chaque lecture plausible : il suffit
    qu'une corresponde.
    """
    assert menaces.menace_probable(message) is not None


@pytest.mark.parametrize("message", [
    "coucou ca va",
    "je baisse le son",
    "on va manger des pates a rincer",
    "jvais te p0ur5uivre en justice",
    "j'ai eu 20/20 au controle",
    "mon @ mail c'est truc@machin.fr",
])
def test_les_phrases_ordinaires_restent_tranquilles(message):
    """Un faux positif est un défaut au même titre qu'une fuite.

    Essayer plusieurs lectures élargit la détection : il faut donc vérifier dans
    les deux sens, sinon « j'ai eu 20/20 » finirait muté.
    """
    assert menaces.menace_probable(message) is None


def test_le_nombre_de_lectures_est_plafonne():
    """Un message truffé de symboles ne doit pas devenir une bombe de calcul.

    Sans plafond, le produit de toutes les lectures explose, et un message
    choisi exprès ferait travailler le filtre indéfiniment — sur le chemin de
    CHAQUE message du serveur.
    """
    pire = "@" * 400 + "!" * 400
    assert len(menaces.lectures(pire)) <= menaces._MAX_VARIANTES


def test_la_lecture_simple_vient_toujours_en_premier():
    """Le cas courant ne doit pas payer le coût des variantes."""
    assert menaces.lectures("jte viole")[0] == menaces.normaliser("jte viole")
