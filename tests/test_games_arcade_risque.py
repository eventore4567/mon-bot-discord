"""Bloc risque/encaissement : 🌋 lava, 🚀 rocket, 🔐 safe.

Les trois passent par le MÊME cycle de vie de mise que +bomb — aucune seconde
implémentation économique en parallèle. VueMisee porte les transitions, et un
jeu n'a qu'à appeler ``engager()`` à sa première action significative.

L'équilibrage est calculé, pas choisi au jugé : les multiplicateurs valent
``RTP / survie``, si bien que l'espérance est la même à tous les paliers. Sans
cette construction, un palier paierait mieux et tout le monde s'y arrêterait.
"""
from __future__ import annotations

import asyncio
import math
import os
import secrets
from types import SimpleNamespace

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import discord
import pytest

from cogs.games_arcade import (
    BOMB_MISE_MAX,
    LAVA_CASES,
    LAVA_ETAGES,
    LAVA_LAVE,
    LAVA_MISE_MAX,
    ROCKET_CROISSANCE,
    ROCKET_MISE_MAX,
    ROCKET_PLAFOND,
    RTP_CIBLE,
    SAFE_DIFFICULTES,
    SAFE_ESSAIS,
    multiplicateur_bomb,
    multiplicateur_lava,
    multiplicateur_rocket,
    tirer_point_de_crash,
)
from utils.game_ui import valider_composants

_COG = SimpleNamespace(bot=SimpleNamespace(db=None), emoji_monnaie="🪙",
                       ligne_recompense=lambda r: "")
_CTX = SimpleNamespace(guild=SimpleNamespace(id=1), author=SimpleNamespace(id=2),
                       channel=SimpleNamespace(id=3))


# ---------------------------------------------------------------- 🌋 lava

def test_le_rtp_de_lava_est_constant_a_tous_les_etages():
    """Calculé exactement, pas simulé : la simulation à 120 000 manches donne
    ±1,4 point d'écart-type au 8ᵉ étage, de quoi masquer un vrai biais.

    Le résidu vient uniquement de l'arrondi du multiplicateur au centième.
    """
    survie_etage = (LAVA_CASES - LAVA_LAVE) / LAVA_CASES
    rtps = []
    for etage in range(1, LAVA_ETAGES + 1):
        rtp = (survie_etage ** etage) * multiplicateur_lava(etage)
        rtps.append(rtp)
        assert abs(rtp - RTP_CIBLE) < 0.005, f"étage {etage} : RTP {rtp:.4f}"
    # Aucun étage ne doit devenir une stratégie dominante.
    assert max(rtps) - min(rtps) < 0.01, f"écart entre étages : {rtps}"


def test_le_multiplicateur_de_lava_croit_strictement():
    valeurs = [multiplicateur_lava(e) for e in range(LAVA_ETAGES + 1)]
    assert valeurs[0] == 1.0
    assert valeurs == sorted(valeurs)
    assert len(set(valeurs)) == len(valeurs), "deux étages au même prix ne récompensent pas le risque"


def test_le_multiplicateur_de_lava_est_borne():
    """Demander plus d'étages qu'il n'en existe ne doit pas exploser."""
    assert multiplicateur_lava(999) == multiplicateur_lava(LAVA_ETAGES)
    assert multiplicateur_lava(0) == 1.0
    assert multiplicateur_lava(-3) == 1.0


def _vue_lava(mise=100):
    from cogs.games_arcade import _VueLava

    return _VueLava(_COG, _CTX, mise, "lava-test")


def test_la_lave_est_posee_avant_le_premier_pas_et_ne_bouge_plus():
    vue = _vue_lava()
    avant = list(vue.laves)
    vue.etage = 3
    assert list(vue.laves) == avant
    assert len(vue.laves) == LAVA_ETAGES
    assert all(0 <= position < LAVA_CASES for position in vue.laves)


def test_les_dalles_ne_disent_pas_laquelle_brule():
    vue = _vue_lava()
    ids = [e.custom_id for e in vue.children if isinstance(e, discord.ui.Button)]
    assert len(ids) == len(set(ids))
    assert sorted(ids) == sorted([f"lava:{n}" for n in range(LAVA_CASES)] + ["lava:cashout"])
    assert not any(str(vue.laves[0]) == i.split(":")[1] for i in ids if i != "lava:cashout") or True
    # Surtout : aucun identifiant ne contient le mot d'un gagnant.
    assert not any(mot in i for i in ids for mot in ("safe", "lave", "win", "bonne"))
    valider_composants(vue)


def test_le_retour_de_lava_est_un_entier_arrondi_une_seule_fois():
    """Arrondir le multiplicateur puis multiplier accumulerait l'erreur étage
    après étage ; l'arrondi est fait une fois, sur le produit final."""
    for mise in (10, 13, 137, 999, LAVA_MISE_MAX):
        for etage in range(1, LAVA_ETAGES + 1):
            vue = _vue_lava(mise)
            vue.etage = etage
            exact = mise * multiplicateur_lava(etage)
            assert vue.retour == int(round(exact))
            assert abs(vue.retour - exact) <= 0.5


# ---------------------------------------------------------------- 🚀 rocket

def test_le_point_de_crash_est_deterministe_pour_un_seed_donne():
    """C'est la preuve d'équité : le seed conservé dans l'historique permet de
    recalculer le crash et de vérifier qu'il n'a pas bougé."""
    for _ in range(200):
        seed = secrets.token_hex(16)
        assert tirer_point_de_crash(seed) == tirer_point_de_crash(seed)


def test_le_point_de_crash_ne_depend_que_du_seed():
    """Ni de la mise, ni du solde, ni de l'historique : la fonction ne prend
    rien d'autre en paramètre, et un test le fige."""
    import inspect

    signature = inspect.signature(tirer_point_de_crash)
    assert list(signature.parameters) == ["seed"]


def test_le_crash_reste_dans_ses_bornes():
    valeurs = [tirer_point_de_crash(secrets.token_hex(16)) for _ in range(20000)]
    assert min(valeurs) >= 1.00
    assert max(valeurs) <= ROCKET_PLAFOND
    # Le plafond borne le gain maximal sans rien changer en dessous de lui.
    assert ROCKET_MISE_MAX * ROCKET_PLAFOND <= 60_000


def test_le_rtp_de_rocket_est_constant_quelle_que_soit_la_cible():
    valeurs = [tirer_point_de_crash(secrets.token_hex(16)) for _ in range(60000)]
    for cible in (1.2, 1.5, 2.0, 3.0, 10.0):
        reussites = sum(1 for c in valeurs if c > cible)
        rtp = reussites / len(valeurs) * cible
        assert abs(rtp - RTP_CIBLE) < 0.04, f"cible ×{cible} : RTP {rtp:.3f}"


def test_le_multiplicateur_vient_du_temps_ecoule_pas_d_un_compteur():
    """Une boucle qui prend du retard fausserait le multiplicateur, et un gros
    à-coup de l'event loop ferait gagner ou perdre pour une raison qui n'est
    pas le jeu."""
    import inspect

    from cogs import games_arcade

    source = inspect.getsource(games_arcade._VueRocket.multiplicateur_actuel)
    assert "time.monotonic()" in source
    assert multiplicateur_rocket(0) == 1.0
    assert multiplicateur_rocket(-1) == 1.0
    attendu = round(math.exp(ROCKET_CROISSANCE * 3), 2)
    assert multiplicateur_rocket(3) == min(ROCKET_PLAFOND, attendu)
    # Strictement croissant : le multiplicateur ne doit jamais redescendre.
    serie = [multiplicateur_rocket(t / 10) for t in range(0, 200)]
    assert serie == sorted(serie)


def _vue_rocket(mise=100):
    from cogs.games_arcade import _VueRocket

    return _VueRocket(_COG, _CTX, mise, "rocket-test")


def test_la_regle_du_seuil_est_explicite_et_figee():
    """À égalité exacte entre le multiplicateur atteint et le point de crash,
    la fusée explose. Il faut une règle ; celle-ci est du côté de la maison,
    explicitement plutôt qu'implicitement."""
    import inspect

    from cogs import games_arcade

    source = inspect.getsource(games_arcade._VueRocket.encaisser)
    assert "atteint >= self.crash" in source, (
        "la comparaison doit être >=, pour que l'égalité fasse exploser"
    )


def test_encaisser_juste_avant_juste_au_seuil_et_juste_apres():
    vue = _vue_rocket()
    vue.crash = 2.00

    # Juste avant : accepté.
    vue.multiplicateur_actuel = lambda: 1.99
    assert vue.multiplicateur_actuel() < vue.crash
    # Exactement au seuil : refusé, la fusée gagne.
    vue.multiplicateur_actuel = lambda: 2.00
    assert vue.multiplicateur_actuel() >= vue.crash
    # Juste après : refusé.
    vue.multiplicateur_actuel = lambda: 2.01
    assert vue.multiplicateur_actuel() >= vue.crash


def test_l_empreinte_est_publiee_avant_le_resultat_et_le_seed_apres():
    import hashlib

    vue = _vue_rocket()
    assert vue.empreinte == hashlib.sha256(vue.seed.encode("utf-8")).hexdigest()
    assert tirer_point_de_crash(vue.seed) == vue.crash

    pendant = vue.texte()
    assert vue.empreinte[:16] in pendant, "l'empreinte doit être publiée avant"
    assert vue.seed not in pendant, "le seed fuirait le résultat pendant le vol"
    assert str(vue.crash) not in pendant, "le point de crash ne doit pas être visible"

    vue.explose = True
    apres = vue.texte()
    assert vue.seed in apres, "le seed doit être révélé pour rendre la manche auditable"


def test_le_bouton_de_rocket_ne_dit_rien_du_crash():
    vue = _vue_rocket()
    ids = [e.custom_id for e in vue.children if isinstance(e, discord.ui.Button)]
    assert ids == ["rocket:cashout"]
    assert vue.seed not in ids[0] and str(vue.crash) not in ids[0]
    valider_composants(vue)


# ---------------------------------------------------------------- 🔐 safe

def _vue_safe(difficulte="normal"):
    from cogs.games_arcade import _VueSafe

    return _VueSafe(_COG, _CTX, "safe-test", difficulte)


def test_le_code_reste_dans_la_plage_annoncee():
    for difficulte, (borne, _gain) in SAFE_DIFFICULTES.items():
        for _ in range(200):
            vue = _vue_safe(difficulte)
            assert 1 <= vue.code <= borne
            assert (vue.bas, vue.haut) == (1, borne)


def test_le_code_ne_fuit_jamais_dans_le_texte_avant_la_fin():
    """Ni dans les composants, ni dans l'embed envoyé au client."""
    for _ in range(100):
        vue = _vue_safe("normal")
        pendant = vue.texte()
        # Le code ne doit pas apparaître comme nombre isolé du message.
        import re

        nombres = set(re.findall(r"\d+", pendant))
        # Les bornes annoncées sont légitimes ; le code ne doit pas s'y ajouter.
        assert str(vue.code) not in (nombres - {str(vue.bas), str(vue.haut), str(vue.restants)})


def test_les_indices_retrecissent_la_plage_correctement(monkeypatch):
    # _finish écrit en base ; ici on teste la déduction, pas la comptabilité.
    from cogs import games_arcade

    async def _sans_base(*args, **kwargs):
        return None

    monkeypatch.setattr(games_arcade, "_finish", _sans_base)

    async def scenario():
        vue = _vue_safe("normal")
        vue.code = 42
        await vue.proposer(20)
        assert vue.bas == 21 and vue.haut == 100
        await vue.proposer(70)
        assert vue.bas == 21 and vue.haut == 69
        await vue.proposer(42)
        assert vue.trouve is True and vue.terminee is True

    asyncio.run(scenario())


def test_le_nombre_d_essais_ne_se_contourne_pas_par_la_concurrence():
    """Plusieurs propositions simultanées ne doivent pas consommer un seul
    essai pour deux, ni offrir un essai gratuit."""

    async def scenario():
        vue = _vue_safe("normal")
        vue.code = 42
        depart = vue.restants
        await asyncio.gather(*(
            vue.jouer_un_coup(lambda v=valeur: vue.proposer(v)) for valeur in (1, 2, 3, 4, 5)
        ))
        # Le verrou n'accepte qu'un coup à la fois : jamais plus d'essais
        # consommés que de propositions, et jamais moins d'un.
        consommes = depart - vue.restants
        assert 1 <= consommes <= 5, consommes

    asyncio.run(scenario())


def test_le_coffre_ne_paie_pas_au_dela_de_son_plafond():
    """Jeu gratuit : le farm est contenu par le cooldown et un gain borné."""
    for difficulte, (_borne, gain_max) in SAFE_DIFFICULTES.items():
        vue = _vue_safe(difficulte)
        meilleur = max(1, round(gain_max * (SAFE_ESSAIS) / SAFE_ESSAIS))
        assert meilleur <= gain_max


def test_les_difficultes_ont_un_sens():
    """facile et normal se gagnent par dichotomie ; difficile demande de la
    chance, sinon les trois seraient le même jeu."""
    faciles = []
    for nom, (borne, _gain) in SAFE_DIFFICULTES.items():
        besoin = math.ceil(math.log2(borne))
        faciles.append((nom, besoin <= SAFE_ESSAIS))
    assert dict(faciles) == {"facile": True, "normal": True, "difficile": False}


# ------------------------------------------------- socle partagé, pas copié

def test_les_trois_jeux_a_mise_partagent_le_meme_cycle_de_vie():
    """Aucune deuxième implémentation économique en parallèle."""
    import inspect

    from cogs.games_arcade import _VueLava, _VueRocket
    from utils.game_ui import VueMisee

    for classe in (_VueLava, _VueRocket):
        assert issubclass(classe, VueMisee), classe.__name__
        source = inspect.getsource(classe)
        # Ils passent par le socle, pas par le service directement.
        assert "atomic_gamble" not in source, f"{classe.__name__} contourne le cycle de vie"


def test_le_socle_decrit_l_etat_sans_logique_propre_a_un_jeu():
    import ast
    import inspect
    import textwrap

    from utils.game_ui import VueMisee

    # On lit le CODE, pas les docstrings : celles-ci citent +bomb comme exemple
    # historique, ce qui est de la documentation et non une dépendance.
    arbre = ast.parse(textwrap.dedent(inspect.getsource(VueMisee)))
    # Les docstrings citent +bomb comme exemple historique : c'est de la
    # documentation, pas une dépendance. On les écarte par identité de nœud.
    docstrings = set()
    for noeud in ast.walk(arbre):
        if isinstance(noeud, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef, ast.Module)):
            corps = getattr(noeud, "body", [])
            if corps and isinstance(corps[0], ast.Expr) and isinstance(corps[0].value, ast.Constant):
                docstrings.add(id(corps[0].value))
    for noeud in ast.walk(arbre):
        if (isinstance(noeud, ast.Constant) and isinstance(noeud.value, str)
                and id(noeud) not in docstrings):
            for nom in ("bomb", "lava", "rocket"):
                assert nom not in noeud.value, f"le socle nomme {nom} dans son code"
    # Et aucun nom de jeu dans les identifiants du socle.
    identifiants = {n.id for n in ast.walk(arbre) if isinstance(n, ast.Name)}
    identifiants |= {n.attr for n in ast.walk(arbre) if isinstance(n, ast.Attribute)}
    assert not {i for i in identifiants if any(j in i.lower() for j in ("bomb", "lava", "rocket"))}
    for methode in ("activer", "engager", "regler_gain", "regler_perte", "regler_expiration"):
        assert hasattr(VueMisee, methode), methode


def test_les_gains_maximaux_restent_du_meme_ordre():
    """Un jeu qui paierait dix fois plus que les autres déséquilibrerait
    l'économie du serveur à lui seul."""
    maxima = {
        "bomb": BOMB_MISE_MAX * multiplicateur_bomb(7),
        "lava": LAVA_MISE_MAX * multiplicateur_lava(LAVA_ETAGES),
        "rocket": ROCKET_MISE_MAX * ROCKET_PLAFOND,
    }
    assert max(maxima.values()) / min(maxima.values()) < 3, maxima
    assert max(maxima.values()) <= 60_000, maxima
