"""Domaines sosies : les deux colonnes, attaques ET innocents.

Un détecteur de sosies qui voit tout est aussi inutile qu'un détecteur qui ne
voit rien — et bien plus dangereux, parce qu'il supprime les messages des
membres honnêtes. Le corpus de domaines légitimes est donc plus gros que le
corpus d'attaques, volontairement.

Mesuré avant ce module, sur dix liens d'hameçonnage réels : un seul était vu.
La règle existante de ``cogs/automod`` demande « une marque ET un appât » dans
l'hôte, ce qui est précis mais rate tout le typosquatting — là où la marque
n'est justement PAS écrite correctement.
"""
from __future__ import annotations

import os

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import pytest

from utils import lookalike_domains as L


# =============================================================================
# Ce qui doit être vu
# =============================================================================

#: (hôte, marque attendue). Chaque ligne est une technique distincte.
ATTAQUES = [
    ("discrod.com", "discord"),              # transposition (le plus courant)
    ("dicsord.com", "discord"),              # transposition ailleurs
    ("discodr.com", "discord"),              # transposition en fin
    ("disccord.com", "discord"),             # lettre doublée
    ("discordd.com", "discord"),             # lettre doublée en fin
    ("dlscord.com", "discord"),              # l pour i
    ("disc0rd.gg", "discord"),               # zéro pour o
    ("paypa1.com", "paypal"),                # un pour l
    ("r0blox.com", "roblox"),                # zéro pour o
    ("rob1ox.com", "roblox"),                # un pour l
    ("robiox.com", "roblox"),                # i pour l
    ("roblxo.com", "roblox"),                # transposition
    ("micr0soft.com", "microsoft"),
    ("youtbue.com", "youtube"),
    ("twicth.tv", "twitch"),
    ("steamcommunnity.com", "steamcommunity"),   # n doublé
    ("steamcomrnunity.com", "steamcommunity"),   # rn lu comme m
    ("discordapp.co", "discordapp"),         # bon nom, suffixe qui n'est pas le sien
    ("discord-nitro.ru", "discord"),         # marque accolée par un tiret
    ("free-discord.xyz", "discord"),         # marque accolée en second
    ("discord.gift-nitro.net", "discord"),   # marque reléguée en sous-domaine
    ("login.discord.evil.com", "discord"),   # marque au milieu, l'œil lit le début
    ("xn--discrd-jua.com", "discord"),       # punycode : charabia ASCII, marque à l'écran
    ("discordаpp.com", "discordapp"),   # « а » cyrillique — invisible à l'œil
    ("discοrd.com", "discord"),         # « ο » grec
]


@pytest.mark.parametrize("hote,marque", ATTAQUES)
def test_le_sosie_est_reconnu_et_la_marque_nommee(hote, marque):
    verdict = L.examiner(hote)
    assert verdict is not None, f"{hote} n'est pas vu"
    assert verdict[0] == marque, f"{hote} : marque {verdict[0]!r}, attendu {marque!r}"
    assert verdict[1].strip(), "la raison doit être dicible au staff"


def test_toutes_les_attaques_connues_sont_vues():
    """Compte global : un chiffre qui doit monter, jamais descendre."""
    rates = [hote for hote, _ in ATTAQUES if L.examiner(hote) is None]
    assert rates == [], f"{len(rates)} sosie(s) raté(s) : {rates}"


# =============================================================================
# Ce qui doit passer — la colonne qui compte le plus
# =============================================================================

LEGITIMES = [
    # Les vrais domaines de Discord, y compris les hérités. discordapp.com et
    # discordapp.net servent encore les CDN : les signaler casserait l'affichage
    # des images sur tout le serveur.
    "discord.com", "discord.gg", "discord.gift", "discord.media", "discord.dev",
    "discord.new", "discordstatus.com", "discordapp.com", "discordapp.net",
    "cdn.discordapp.com", "media.discordapp.net", "images-ext-1.discordapp.net",
    "support.discord.com", "www.discord.com",
    # Autres marques protégées, écrites correctement.
    "roblox.com", "www.roblox.com", "rbxcdn.com", "steamcommunity.com",
    "store.steampowered.com", "epicgames.com", "minecraft.net", "paypal.com",
    "paypal.me", "microsoft.com", "twitch.tv", "youtube.com", "youtu.be",
    "instagram.com", "binance.com", "coinbase.com", "metamask.io",
    # Les pièges de la distance d'édition. Chacun est proche d'une marque
    # protégée et parfaitement légitime.
    "record.com",        # proche de discord à l'œil, distance réelle 3
    "recorder.io",
    "discover.com",      # distance 3 de discord
    "stream.com",        # proche de steam
    "steamdb.info",      # site communautaire connu
    "nitro.com", "nitropdf.com", "nitrotype.com",  # « nitro » n'est PAS protégé
    "crypto.com",        # « crypto » n'est PAS protégé
    "wallet.org",
    "mycloud.com",
    "microsite.com",
    # Domaines courants d'un salon de développement.
    "github.com", "github.io", "gitlab.com", "google.com", "wikipedia.org",
    "stackoverflow.com", "python.org", "npmjs.com", "pypi.org", "docker.com",
    "reddit.com", "twitter.com", "notion.so", "figma.com", "vercel.app",
    "railway.app", "cloudflare.com", "letsencrypt.org",
]


@pytest.mark.parametrize("hote", LEGITIMES)
def test_un_domaine_legitime_passe(hote):
    verdict = L.examiner(hote)
    assert verdict is None, f"FAUX POSITIF sur {hote} : {verdict}"


def test_aucun_faux_positif_sur_tout_le_corpus():
    faux = [(h, L.examiner(h)) for h in LEGITIMES if L.examiner(h) is not None]
    assert faux == [], f"{len(faux)} faux positif(s) : {faux}"


# =============================================================================
# Les deux défauts trouvés en construisant le module
# =============================================================================

def test_la_liste_blanche_ne_protege_pas_son_imitation():
    """Le défaut le plus grave, et le moins visible.

    ``est_de_confiance`` repliait d'abord les homoglyphes : ``discordаpp.com``
    en cyrillique devenait ``discordapp.com``, se trouvait dans la liste
    blanche, et était déclaré propre. Replier avant de vérifier la confiance
    transforme chaque domaine de la liste en cible parfaite — plus il est
    légitime, mieux son imitation est protégée.
    """
    assert L.est_de_confiance("discordapp.com") is True
    assert L.est_de_confiance("discordаpp.com") is False
    assert L.examiner("discordаpp.com") == ("discordapp", "caractères trompeurs")


def test_la_transposition_compte_pour_une_seule_faute():
    """``discrod`` est le typosquat le plus courant de ``discord``, et en
    Levenshtein simple il est à 2 — donc hors tolérance pour un mot de sept
    lettres. Tolérance qu'il ne faut PAS relâcher : à 2, des domaines sans
    rapport commencent à correspondre. Damerau-Levenshtein le met à 1 sans
    rien élargir."""
    assert L._distance("discrod", "discord", 2) == 1
    assert L.examiner("discrod.com") is not None
    # Et la preuve que rien n'a été élargi :
    assert L.examiner("record.com") is None
    assert L.examiner("discover.com") is None


def test_un_suffixe_compose_ne_perd_pas_la_marque():
    """Sans les suffixes composés, ``discord.co.uk`` verrait « co » comme
    étiquette enregistrable et la marque serait invisible."""
    assert L.decouper("discord.co.uk") == ("discord", "co.uk", ())
    assert L.decouper("login.discord.co.uk") == ("discord", "co.uk", ("login",))


def test_la_comparaison_porte_sur_des_etiquettes_entieres():
    """Jamais de sous-chaîne. « notdiscord.com » ne doit pas hériter de la
    confiance de « discord.com » parce qu'il finit par ces lettres, et
    « recorder » ne doit pas contenir « record »."""
    assert L.est_de_confiance("notdiscord.com") is False
    assert L.est_de_confiance("evildiscord.com") is False
    # Et l'inverse : un vrai sous-domaine passe.
    assert L.est_de_confiance("cdn.discord.com") is True


def test_une_marque_courte_nest_pas_protegee():
    """La règle qui évite des milliers de faux positifs : en dessous de
    LONGUEUR_MINIMALE, une étiquette n'est pas comparée par distance."""
    assert L.LONGUEUR_MINIMALE >= 6
    for marque in L.MARQUES:
        if len(marque) < L.LONGUEUR_MINIMALE:
            pytest.fail(
                f"{marque!r} est trop courte pour être comparée par distance "
                "sans produire des faux positifs"
            )


# =============================================================================
# Extraction des hôtes depuis un message
# =============================================================================

@pytest.mark.parametrize("message,attendu", [
    ("va sur https://discrod.com/gift maintenant", "discrod.com"),
    ("discrod.com", "discrod.com"),
    ("hxxps://discrod.com/gift", "discrod.com"),          # lien masqué
    ("discrod [.] com", "discrod.com"),                    # point échappé
    ("discrod dot com", "discrod.com"),                    # point écrit en mot
    ("<https://discrod.com/x>", "discrod.com"),
    ("http://user:pass@discrod.com/x", "discrod.com"),     # identifiants dans l'URL
    ("https://discrod.com:8443/x", "discrod.com"),         # port
])
def test_lhote_est_extrait_des_formes_dobfuscation(message, attendu):
    """Ces formes ne sont pas théoriques : c'est exactement ainsi que les liens
    d'hameçonnage sont collés pour échapper aux filtres."""
    assert attendu in list(L.extraire_hotes(message))


def test_examiner_texte_rend_lhote_la_marque_et_la_raison():
    verdict = L.examiner_texte("clique vite sur https://disc0rd.gg/free")
    assert verdict is not None
    hote, marque, raison = verdict
    assert hote == "disc0rd.gg"
    assert marque == "discord"
    assert raison.strip()


def test_un_message_sans_sosie_rend_rien():
    assert L.examiner_texte("le serveur officiel est sur https://discord.gg/abcd") is None
    assert L.examiner_texte("aucun lien ici, juste du texte") is None


def test_un_message_vide_ne_leve_pas():
    assert L.examiner_texte("") is None
    assert L.examiner_texte(None) is None
    assert L.examiner("") is None
    assert L.examiner(None) is None


# =============================================================================
# Branchement réel dans l'anti-scam
# =============================================================================

def test_lanti_scam_voit_les_sosies_par_son_propre_chemin():
    """Le test qui compte : pas le module isolé, mais ``automod._scam_hit``,
    la fonction que le bot appelle réellement sur chaque message."""
    from cogs import automod

    for hote, _marque in ATTAQUES:
        motif = automod._scam_hit(f"regarde https://{hote}/gift")
        assert motif, f"l'anti-scam ne voit pas {hote}"
        assert "domaine suspect" in motif


def test_lanti_scam_epargne_les_domaines_legitimes():
    from cogs import automod

    faux = []
    for hote in LEGITIMES:
        if automod._scam_hit(f"regarde https://{hote}/page"):
            faux.append(hote)
    assert faux == [], f"l'anti-scam sanctionne {len(faux)} domaine(s) légitime(s) : {faux}"


def test_lanti_scam_laisse_parler_de_scams():
    """Interdire de DISCUTER des arnaques serait le pire des faux positifs :
    ce sont justement les messages qui protègent les autres membres."""
    from cogs import automod

    for phrase in (
        "J'ai reçu un lien bizarre qui parlait de nitro gratuit, c'est un scam ?",
        "Attention, quelqu'un fait tourner une arnaque au robux, signalez-le",
        "Mon frère s'est fait avoir par un faux nitro l'an dernier",
    ):
        assert automod._scam_hit(phrase) is None, f"faux positif sur : {phrase}"
