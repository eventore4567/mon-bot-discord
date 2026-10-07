"""Règles du catalogue slash (utils/slash_catalog.py), la source unique du « / ».

Ces tests ne bootent pas le bot : ils vérifient la déclaration elle-même, donc ils
tournent en quelques millisecondes et peuvent garder le build. La preuve que le
catalogue est réellement publié, routé et contrôlé à l'identique du préfixe est
mesurée sur le bot booté par tools/permission_audit_sweep.py (1960 couples, zéro
divergence + / slash au 07/10/2026).
"""
from __future__ import annotations

import collections
import re

from utils import slash_catalog as sc

NOM = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")
ACCENTS = re.compile(r"[àâäéèêëîïôöùûüçœ]", re.IGNORECASE)
MOTS_FRANCAIS = re.compile(
    r"\b(le|la|les|des|une|du|pour|avec|sur|dans|votre|vos|membre|serveur|salon|"
    r"afficher|activer|désactiver|supprimer|ajouter|retirer)\b",
    re.IGNORECASE,
)
#: Mots qui trahissent une commande de développement, de test ou de réparation.
#: Ils n'ont rien à faire dans le menu d'un membre (brief SentriX, point 6).
MOTS_DEV = re.compile(
    r"(^|-)(test|tests|debug|diag|diagnostic|probe|sonde|dev|sandbox|smoke|"
    r"repair|migrate|migration|legacy|tmp|temp|v\d+)($|-)"
)
#: Sous-groupe numéroté comme une page : « /utility tools-2 » était exactement ça.
PAGE = re.compile(r"-\d+$")


def _segments():
    for entry in sc.CATALOG:
        for segment in entry.path.split():
            yield entry, segment


def test_chaque_chemin_est_unique():
    doublons = [p for p, n in collections.Counter(e.path for e in sc.CATALOG).items() if n > 1]
    assert doublons == []


def test_une_source_nest_publiee_quune_fois():
    """Pas de synonyme : une fonction, un chemin. L'audit bloquant du registre
    refuserait d'ailleurs de publier deux chemins sur le même callback."""
    doublons = [s for s, n in collections.Counter(e.source for e in sc.CATALOG).items() if n > 1]
    assert doublons == []


def test_une_source_nest_pas_a_la_fois_publiee_et_retiree():
    assert {e.source for e in sc.CATALOG} & set(sc.RETIRED) == set()


def test_chaque_retrait_a_une_raison():
    assert all(raison.strip() for raison in sc.RETIRED.values())


def test_noms_valides_pour_discord():
    fautifs = [(e.path, s) for e, s in _segments() if not NOM.match(s)]
    assert fautifs == [], fautifs


def test_aucun_mot_de_developpement_dans_un_chemin():
    fautifs = [e.path for e, s in _segments() if MOTS_DEV.search(s)]
    assert fautifs == [], fautifs


def test_aucun_sous_groupe_numerote_comme_une_page():
    fautifs = [e.path for e, s in _segments() if PAGE.search(s)]
    assert fautifs == [], fautifs


def test_au_plus_trois_niveaux():
    assert all(1 <= len(e.path.split()) <= 3 for e in sc.CATALOG)


def test_limites_discord_respectees():
    racines = sc.entries_by_root()
    assert len(racines) <= 100
    enfants = collections.defaultdict(set)
    for entry in sc.CATALOG:
        parts = entry.path.split()
        for depth in range(1, len(parts)):
            enfants[" ".join(parts[:depth])].add(parts[depth])
    trop = {groupe: len(n) for groupe, n in enfants.items() if len(n) > 25}
    assert trop == {}, trop


def test_un_nom_nest_pas_a_la_fois_commande_et_groupe():
    """Discord interdit qu'une racine soit à la fois une commande et un groupe."""
    feuilles = {e.path for e in sc.CATALOG}
    groupes = {" ".join(e.path.split()[:d]) for e in sc.CATALOG for d in range(1, len(e.path.split()))}
    assert feuilles & groupes == set()


def test_descriptions_courtes_et_anglaises():
    for entry in sc.CATALOG:
        d = entry.description
        assert d and len(d) <= 100, entry.path
        assert not d.lower().startswith("use "), (
            f"/{entry.path} : « {d} » ne dit pas ce que fait la commande"
        )
        assert not ACCENTS.search(d), f"/{entry.path} : description en français"
        assert not MOTS_FRANCAIS.search(d), f"/{entry.path} : description en français"


def test_chaque_groupe_a_une_description_anglaise():
    groupes = {" ".join(e.path.split()[:d]) for e in sc.CATALOG for d in range(1, len(e.path.split()))}
    sans = sorted(g for g in groupes if g not in sc.GROUP_DESCRIPTIONS)
    assert sans == [], sans
    for groupe, d in sc.GROUP_DESCRIPTIONS.items():
        assert d and len(d) <= 100 and not ACCENTS.search(d), groupe


def test_la_moderation_quotidienne_reste_a_la_racine():
    """Brief SentriX, point 45 : /ban /kick /timeout /warn /unban /clear."""
    racines = {e.path for e in sc.CATALOG if " " not in e.path}
    assert {"ban", "kick", "timeout", "warn", "unban", "clear"} <= racines


def test_les_outils_du_proprietaire_ne_sont_pas_publies():
    """Brief SentriX, point 7 : les outils internes ne polluent pas le « / »."""
    for source in ("bot-leave", "bot-servers", "set-bot", "setstatus", "status-rotate", "theme", "footer"):
        assert source in sc.RETIRED
        assert source not in {e.source for e in sc.CATALOG}
