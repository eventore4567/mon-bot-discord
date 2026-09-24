"""Les filtres de sécurité doivent résister aux déguisements, sans sanctionner
une phrase banale.

Mesuré avant correctif, sur le corpus de tools/security_bypass_sweep.py :
20 attaques vues sur 37 pour les liens/invitations/arnaques, et 810 sur 2 000
pour le filtre multilingue d'insultes. Il suffisait d'espacer les lettres, de
mettre un « е » cyrillique ou des petites capitales.

Les faux positifs comptent autant : un filtre qui supprime les messages normaux
finit désactivé par les admins, et il ne protège alors plus rien du tout.
"""
from __future__ import annotations

import os

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import pytest

from utils.text_normalization import contient, motif_tolerant, normaliser


@pytest.mark.parametrize(
    ("brut", "attendu"),
    [
        ("𝗳𝗿𝗲𝗲 𝗻𝗶𝘁𝗿𝗼", "free nitro"),          # gras mathématique minuscule
        ("𝗙𝗥𝗘𝗘 𝗡𝗜𝗧𝗥𝗢", "free nitro"),          # gras mathématique capitale
        ("ｆｒｅｅ ｎｉｔｒｏ", "free nitro"),          # pleine chasse
        ("ᴅɪsᴄᴏʀᴅ", "discord"),                 # petites capitales
        ("disсord", "discord"),                 # с cyrillique
        ("frее", "free"),                       # е cyrillique
        ("FREE   NITRO", "free nitro"),         # espaces multiples
        ("café", "cafe"),                       # diacritiques
    ],
)
def test_la_normalisation_ramene_les_sosies_a_l_ascii(brut, attendu):
    assert normaliser(brut) == attendu


def test_le_motif_tolere_les_separateurs_sans_casser_les_mots():
    """Le piège de la solution naïve : coller tout le texte puis chercher la
    sous-chaîne ferait correspondre « offre e nitro »."""
    motif = motif_tolerant("free nitro")
    for variante in (
        "free nitro", "fr ee nitro", "f r e e   n i t r o",
        "f.r.e.e-n1tr0", "fr33 nitr0",
    ):
        assert motif.search(normaliser(variante)), variante
    for innocent in ("offre e nitro", "offreenitro", "freenitrogene"):
        assert not motif.search(normaliser(innocent)), innocent


def test_le_balayage_de_securite_ne_laisse_aucun_trou():
    """La porte : tout le corpus d'attaques doit être vu, et aucune phrase
    banale sanctionnée. C'est le même outil que tools/security_bypass_sweep."""
    from tools.security_bypass_sweep import FAMILLES

    evasions: list[str] = []
    faux_positifs: list[str] = []
    for nom, detecteur, attaques, banales in FAMILLES:
        evasions += [f"{nom}: {a!r}" for a in attaques if not detecteur(a)]
        faux_positifs += [f"{nom}: {b!r}" for b in banales if detecteur(b)]
    assert not evasions, f"{len(evasions)} attaque(s) passent : {evasions[:5]}"
    assert not faux_positifs, f"phrase(s) banale(s) sanctionnée(s) : {faux_positifs}"


def test_les_redirecteurs_d_invitation_sont_couverts():
    """discord.gg n'est pas le seul hôte d'invitation : ignorer dsc.gg,
    invite.gg ou discord.me laissait passer un lien sur quatre."""
    from cogs.automod import INVITE_RE

    for hote in ("discord.gg", "dsc.gg", "invite.gg", "discord.me", "discord.io"):
        assert INVITE_RE.search(f"{hote}/abcd"), hote
    # Un hôte connu SANS chemin n'est pas une invitation.
    assert not INVITE_RE.search("on parle de discord.gg en général")


def test_recoller_les_hotes_ne_recolle_que_les_hotes_connus():
    """Recoller tous les points transformerait « salut . com » en lien et
    ferait sanctionner une phrase banale."""
    from cogs.automod import _recoller_hotes_invitation

    assert "discord.gg" in _recoller_hotes_invitation("discord . gg/abcd")
    assert "salut.com" not in _recoller_hotes_invitation("salut . com")


def test_le_filtre_d_insultes_resiste_aux_deguisements():
    """Avant : espacer les lettres ou utiliser des petites capitales contournait
    100 % des 2 663 termes du dataset."""
    from tools.security_bypass_sweep import _DEGUISEMENTS, _DATASET, _termes_temoins

    manques: list[str] = []
    for terme in _termes_temoins(25):
        for nom, deguiser in _DEGUISEMENTS:
            if not _DATASET.match(f"tu es un {deguiser(terme)} franchement"):
                manques.append(nom)
    assert not manques, f"déguisements non détectés : {sorted(set(manques))}"


def test_la_normalisation_reste_bon_marche():
    """Elle tourne sur CHAQUE message de 28 serveurs : elle doit rester
    négligeable, sinon c'est la latence du bot qui paie la sécurité."""
    import time

    messages = [
        "salut tout le monde ça va aujourd'hui ?",
        "https://exemple.com/un/chemin/assez/long?avec=des&parametres=1",
        "a" * 400,
    ]
    debut = time.perf_counter()
    for _ in range(300):
        for message in messages:
            normaliser(message)
    par_message = (time.perf_counter() - debut) * 1000 / (300 * len(messages))
    assert par_message < 1.0, f"{par_message:.3f} ms par message"


def test_les_petites_capitales_sont_couvertes_sur_tous_leurs_blocs():
    """Unicode répartit les 45 petites capitales latines sur SIX blocs. Ne
    balayer que deux d'entre eux laissait dehors la petite capitale Q, donc
    « ᴀʀɴᴀꞯᴜᴇ » traversait tous les filtres."""
    from utils.text_normalization import _PETITES_CAPITALES

    assert normaliser("ᴀʀɴᴀꞯᴜᴇ") == "arnaque"
    assert normaliser("ᴅɪsᴄᴏʀᴅ") == "discord"
    assert len(_PETITES_CAPITALES) >= 30, len(_PETITES_CAPITALES)


def test_le_filtre_de_mots_interdits_resiste_aux_deguisements():
    """C'est le seul filtre que les administrateurs configurent eux-mêmes, et
    il avait déjà les frontières de mots — mais pas la normalisation."""
    from cogs.automod import AutoMod

    for variante in (
        "arnaque", "ARNAQUE", "arnaqué", "a r n a q u e",
        "a.r.n.a.q.u.e", "4rn4qu3", "аrnaque", "ᴀʀɴᴀꞯᴜᴇ", "𝗮𝗿𝗻𝗮𝗾𝘂𝗲",
    ):
        assert AutoMod._blacklist_hit(["arnaque"], f"ceci est une {variante} ici"), variante


def test_le_filtre_de_mots_interdits_garde_ses_frontieres_et_son_prefixe():
    """« con » ne doit pas supprimer « connexion », et « merd* » doit toujours
    attraper « merdier » : les deux comportements existaient avant, ils ne
    doivent pas disparaître en gagnant la tolérance aux déguisements."""
    from cogs.automod import AutoMod

    for innocent in (
        "j'ai une bonne connexion internet",
        "il est reputé sérieux dans le métier",
        "je configure mon serveur ce soir",
        "on a promis de venir demain",
    ):
        assert not AutoMod._blacklist_hit(["arnaque", "promo*", "con"], innocent), innocent

    for attrape in ("promotion", "promos", "promo", "p r o m o t i o n"):
        assert AutoMod._blacklist_hit(["promo*"], attrape), attrape


def test_la_reponse_a_une_mention_n_annonce_que_des_commandes_reelles():
    """Elle annonçait « +aide » et « +configurer ». Mesuré sur le bot booté :
    les deux sont introuvables — help et setup n'ont aucun alias une fois la
    surface nettoyée. Envoyer quelqu'un vers une commande qui n'existe pas est
    pire que de ne rien dire."""
    from types import SimpleNamespace

    from cogs.language_runtime import _nom_reellement_utilisable

    reelles = {"help": object(), "setup": object()}
    bot = SimpleNamespace(get_command=lambda nom: reelles.get(nom))

    # L'alias français n'existe pas sur ce bot : on retombe sur le nom réel.
    assert _nom_reellement_utilisable(bot, "aide", "help") == "help"
    assert _nom_reellement_utilisable(bot, "configurer", "setup") == "setup"

    # S'il existe et pointe bien sur la même commande, on le préfère.
    reelles["aide"] = reelles["help"]
    assert _nom_reellement_utilisable(bot, "aide", "help") == "aide"

    # S'il existe mais désigne AUTRE chose, on ne l'annonce pas.
    reelles["configurer"] = object()
    assert _nom_reellement_utilisable(bot, "configurer", "setup") == "setup"
