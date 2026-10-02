"""La bibliothèque d'icônes SentriX ne peut jamais casser un affichage.

Une icône personnalisée s'écrit ``<:nom:identifiant>``, et cet identifiant
n'existe qu'APRÈS le téléversement. Il y a donc toujours une fenêtre — premier
démarrage, échec réseau, limite Discord atteinte — pendant laquelle aucune
icône n'est disponible. Si la résolution rendait ``None`` ou un marquage à
moitié formé, chaque panneau du bot afficherait ``<:sentrix_ticket:None>``.

Ces tests figent la règle : toute fonction de résolution rend quelque chose
d'affichable, toujours.
"""
from __future__ import annotations

import os

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import pathlib

import discord
import pytest

from utils import sentrix_emojis as se

#: Limite Discord par fichier d'emoji.
LIMITE_OCTETS = 256 * 1024


@pytest.fixture(autouse=True)
def _cache_vide():
    """Chaque test part sans icône résolue : c'est l'état du premier démarrage."""
    se.reinitialiser()
    yield
    se.reinitialiser()


# =============================================================================
# Le pack lui-même
# =============================================================================

def test_le_pack_est_present_et_nomme_correctement():
    noms = se.noms_disponibles()
    assert len(noms) >= 100, f"pack incomplet : {len(noms)} icônes"
    hors_norme = [n for n in noms if not n.startswith(se.PREFIXE)]
    assert hors_norme == [], f"noms sans le préfixe {se.PREFIXE} : {hors_norme}"


def test_chaque_fichier_tient_dans_la_limite_discord():
    """Un fichier trop lourd est refusé au téléversement, et l'icône manque
    ensuite partout sans que rien ne le signale à l'usage."""
    trop_lourds = [
        (p.name, p.stat().st_size)
        for p in se.DOSSIER.iterdir()
        if p.suffix.lower() in (".png", ".gif") and p.stat().st_size > LIMITE_OCTETS
    ]
    assert trop_lourds == [], f"au-dessus de 256 Ko : {trop_lourds}"


def test_chaque_nom_a_un_fichier_lisible():
    manquants = [n for n in se.noms_disponibles() if se.fichier(n) is None]
    assert manquants == [], f"noms sans fichier résoluble : {manquants}"


# =============================================================================
# La règle d'animation
# =============================================================================

def test_seuls_les_etats_vivants_sont_animes():
    """« Ne mets pas des animations partout » : une interface qui bouge en
    permanence fatigue. Le GIF n'est choisi que pour un état qui vit —
    quelque chose est en cours, ou vient de changer."""
    animes = [
        n for n in se.noms_disponibles()
        if (f := se.fichier(n)) is not None and f.suffix.lower() == ".gif"
    ]
    intrus = sorted(set(animes) - se.ANIMES_AUTORISES)
    assert intrus == [], f"icônes animées hors de la liste autorisée : {intrus}"


def test_un_anime_qui_a_une_version_statique_peut_y_retomber():
    """Le repli demandé : plutôt une icône fixe qu'un affichage cassé."""
    avec_statique = [n for n in se.ANIMES_AUTORISES if se.statique(n) is not None]
    assert avec_statique, "aucun état vivant n'a de version statique de repli"
    for nom in avec_statique:
        assert se.fichier(nom).suffix.lower() == ".gif"
        assert se.statique(nom).suffix.lower() == ".png"


# =============================================================================
# La résolution ne casse jamais un affichage
# =============================================================================

def test_sans_synchronisation_rien_nest_casse():
    """L'état du premier démarrage. Aucun marquage à moitié formé ne doit
    sortir : ni ``None``, ni ``<:nom:None>``."""
    for nom in se.noms_disponibles():
        rendu = se.emoji(nom)
        assert isinstance(rendu, str)
        assert "None" not in rendu
        assert not rendu.startswith("<:") or rendu.endswith(">")
        assert se.partiel(nom) is None


def test_un_nom_inconnu_ne_leve_pas():
    assert se.emoji("cette_icone_nexiste_pas") == ""
    assert se.partiel("cette_icone_nexiste_pas") is None
    assert se.titre("cette_icone_nexiste_pas", "Texte") == "Texte"


def test_titre_ne_laisse_pas_despace_en_tete():
    """Le défaut classique du repli vide : ``f"{emoji(x)} {t}"`` décale tous
    les titres d'un cran quand l'icône manque."""
    assert se.titre("ticket", "Ticket #42") == "Ticket #42"
    se.amorcer({"sentrix_ticket": "<:sentrix_ticket:410000000000000001>"})
    assert se.titre("ticket", "Ticket #42") == "<:sentrix_ticket:410000000000000001> Ticket #42"


def test_le_prefixe_est_optionnel_a_lappel():
    """Le code appelant écrit « ticket_claim », pas « sentrix_ticket_claim »."""
    se.amorcer({"sentrix_ticket_claim": "<:sentrix_ticket_claim:410000000000000002>"})
    assert se.emoji("ticket_claim") == se.emoji("sentrix_ticket_claim")


def test_partiel_rend_un_objet_utilisable_par_discord():
    """Discord refuse un marquage texte sur un bouton : il lui faut un objet."""
    se.amorcer({"sentrix_ticket": "<:sentrix_ticket:123456789012345678>"})
    partiel = se.partiel("ticket")
    assert isinstance(partiel, discord.PartialEmoji)
    assert partiel.name == "sentrix_ticket"
    discord.ui.Button(label="Ouvrir", emoji=partiel)  # ne doit pas lever


# =============================================================================
# La frontière avec les emojis décoratifs
# =============================================================================

def test_une_icone_sentrix_se_distingue_dun_emoji_decoratif():
    """C'est cette distinction qui permet à la politique visuelle d'interdire
    les emojis Unicode décoratifs sur les boutons SANS interdire l'identité
    SentriX. Sans elle, la règle devrait tout interdire ou tout permettre."""
    se.amorcer({"sentrix_ban": "<:sentrix_ban:410000000000000003>"})
    assert se.est_sentrix(se.emoji("ban")) is True
    assert se.est_sentrix(se.partiel("ban")) is True
    for decoratif in ("🎁", "🏆", "🔨", "⚠️", "✅", ""):
        assert se.est_sentrix(decoratif) is False, decoratif


# =============================================================================
# La synchronisation
# =============================================================================

class _BotSansReseau:
    """Le cas qui ne doit pas empêcher le démarrage."""

    async def fetch_application_emojis(self):
        raise RuntimeError("réseau indisponible")


class _BotQuiRefuse:
    async def fetch_application_emojis(self):
        return []

    async def create_application_emoji(self, *, name, image):
        raise RuntimeError("limite atteinte")


class _BotDejaFourni:
    def __init__(self, noms):
        self._noms = noms

    async def fetch_application_emojis(self):
        return [
            discord.PartialEmoji(name=n, id=1000 + i)
            for i, n in enumerate(self._noms)
        ]

    async def create_application_emoji(self, *, name, image):  # pragma: no cover
        raise AssertionError("un emoji déjà présent a été re-téléversé")


@pytest.mark.asyncio
async def test_un_echec_reseau_ne_leve_pas():
    bilan = await se.synchroniser(_BotSansReseau())
    assert bilan["envoyes"] == 0
    assert se.emoji("ticket") == ""


@pytest.mark.asyncio
async def test_un_refus_de_discord_laisse_les_replis(monkeypatch):
    monkeypatch.setattr(se, "DELAI_ENTRE_ENVOIS", 0)
    bilan = await se.synchroniser(_BotQuiRefuse())
    assert bilan["echecs"] > 0
    assert bilan["envoyes"] == 0
    # Le repli sobre reste affichable.
    assert se.emoji("success") == "✓"


@pytest.mark.asyncio
async def test_la_synchronisation_est_idempotente():
    """Un redémarrage ne doit rien re-téléverser : _BotDejaFourni lève si on
    essaie."""
    noms = se.noms_disponibles()
    bilan = await se.synchroniser(_BotDejaFourni(noms))
    assert bilan["existants"] == len(noms)
    assert bilan["envoyes"] == 0
    assert se.emoji(noms[0]).startswith("<")


def test_un_marquage_malforme_ne_produit_pas_de_bouton_casse():
    """``PartialEmoji.from_str`` n'échoue PAS sur un marquage invalide : il
    rend un emoji dont le nom est la chaîne entière et l'identifiant ``None``.
    Discord refuserait alors le bouton, et la cause serait introuvable."""
    se.amorcer({"sentrix_ban": "<:sentrix_ban:3>"})  # identifiant trop court
    assert se.partiel("ban") is None
