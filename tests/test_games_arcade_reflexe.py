"""Bloc réflexe et mémoire : 🎯 target, 🏹 archery, 👻 ghost, 🧩 sequence.

Quatre jeux, un seul socle : ``utils.game_ui.VueReflexe`` porte le signal, le
faux départ et la mesure monotone. Les recopier quatre fois garantirait qu'un
correctif n'en atteigne qu'un.

Le point le plus important tient en une phrase : **la bonne réponse ne doit
jamais se lire dans le payload**. Un custom_id du genre ``ghost:winning`` se
voit dans les outils de développement du client, et le jeu n'existe plus.
"""
from __future__ import annotations

import asyncio
import os
import time
from types import SimpleNamespace

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import discord
import pytest

from cogs.games_arcade import (
    ARCHERY_PERIODE_MS,
    ARCHERY_ZONES,
    GHOST_PORTES,
    SEQUENCE_SYMBOLES,
    TARGET_COULEURS,
    zone_archery,
)
from utils.game_ui import VueReflexe, positions_melangees, valider_composants

_COG = SimpleNamespace(bot=None, emoji_monnaie="🪙", ligne_recompense=lambda r: "")
_CTX = SimpleNamespace(
    guild=SimpleNamespace(id=1), author=SimpleNamespace(id=2), channel=SimpleNamespace(id=3)
)


def _vue(classe, *args):
    return classe(_COG, _CTX, "sid-test", *args)


# ------------------------------------------------------------ socle commun

def test_la_mesure_utilise_une_horloge_monotone():
    """Un décalage NTP ou un changement d'heure produirait un « record »
    négatif avec l'heure système. L'horloge monotone ne recule pas."""
    import inspect

    from utils import game_ui

    source = inspect.getsource(game_ui.VueReflexe)
    assert "time.monotonic()" in source
    assert "time.time()" not in source, "l'heure système ne doit jamais servir de chronomètre"


def test_aucune_mesure_n_est_possible_avant_le_signal():
    vue = VueReflexe(1)
    assert vue.arme is False
    assert vue.mesurer() is None
    vue.armer()
    assert vue.arme is True
    assert vue.mesurer() is not None


def test_la_mesure_est_coherente():
    vue = VueReflexe(1)
    vue.armer()
    time.sleep(0.03)
    mesure = vue.mesurer()
    assert 20 <= mesure <= 300, f"{mesure} ms pour 30 ms attendues"


def test_un_faux_depart_termine_la_manche():
    vue = VueReflexe(1)
    vue.declarer_faux_depart()
    assert vue.faux_depart is True
    assert vue.terminee is True


def test_les_positions_sont_melangees_uniformement():
    """Une bonne réponse toujours à la même place donnerait un avantage à qui
    l'a remarqué — et ces manches paient."""
    import collections

    compte = collections.Counter()
    for _ in range(6000):
        compte[positions_melangees(list(range(5))).index(0)] += 1
    ecart = max(abs(v - 1200) / 1200 for v in compte.values())
    assert ecart < 0.15, f"positions non uniformes : {dict(compte)}"


# ------------------------------------------------------------ 🎯 target

def test_la_cible_annoncee_existe_exactement_une_fois():
    """Un doublon rendrait la manche ambiguë : deux boutons corrects, un seul
    accepté, et le joueur ne comprendrait pas pourquoi il a perdu."""
    from cogs.games_arcade import _VueTarget

    for _ in range(80):
        vue = _vue(_VueTarget)
        assert vue.cible in vue.choix
        assert vue.choix.count(vue.cible) == 1
        assert len(set(vue.choix)) == len(vue.choix), "deux couleurs identiques"
        assert set(vue.choix) == set(TARGET_COULEURS)


def test_les_boutons_de_target_ne_disent_pas_laquelle_est_bonne():
    from cogs.games_arcade import _VueTarget

    vue = _vue(_VueTarget)
    ids = [e.custom_id for e in vue.children if isinstance(e, discord.ui.Button)]
    assert len(ids) == len(set(ids))
    assert all(i.startswith("target:") and i.split(":")[1].isdigit() for i in ids)
    assert not any(vue.cible in i for i in ids), "la cible fuit dans le custom_id"
    valider_composants(vue)


# ------------------------------------------------------------ 🏹 archery

@pytest.mark.parametrize(
    ("ecart", "libelle"),
    [(0.0, "Parfait"), (0.05, "Parfait"), (0.2, "Excellent"),
     (0.4, "Bon"), (0.8, "Raté"), (1.0, "Raté")],
)
def test_les_zones_de_precision_sont_continues(ecart, libelle):
    assert zone_archery(ecart)[1] == libelle


def test_les_zones_couvrent_tout_l_intervalle_sans_trou():
    limites = [limite for limite, _e, _l, _f in ARCHERY_ZONES]
    assert limites == sorted(limites)
    assert limites[-1] >= 1.0, "un écart de 1 doit tomber quelque part"
    facteurs = [f for _li, _e, _l, f in ARCHERY_ZONES]
    assert facteurs == sorted(facteurs, reverse=True), "plus précis doit payer plus"
    assert facteurs[-1] == 0.0, "un raté ne paie pas"


def test_la_trajectoire_est_deterministe_et_ne_fuit_pas():
    """La cible suit une trajectoire fixée AVANT la manche : deux mesures au
    même instant donnent le même écart, et la phase n'est nulle part dans le
    payload."""
    from cogs.games_arcade import _VueArchery

    vue = _vue(_VueArchery)
    assert vue.position_cible(500) == vue.position_cible(500)
    ids = [e.custom_id for e in vue.children if isinstance(e, discord.ui.Button)]
    assert ids == ["archery:shoot"]
    assert str(vue.phase_ms) not in ids[0]


def test_la_cible_passe_bien_par_le_centre_et_par_le_bord():
    """Sans cela, certaines manches seraient ingagnables ou triviales."""
    from cogs.games_arcade import _VueArchery

    vue = _vue(_VueArchery)
    echantillons = [vue.position_cible(t) for t in range(0, ARCHERY_PERIODE_MS, 20)]
    assert min(echantillons) < 0.05, "la cible n'atteint jamais le centre"
    assert max(echantillons) > 0.95, "la cible n'atteint jamais le bord"


def test_la_periode_est_assez_lente_pour_ne_pas_recompenser_la_latence():
    """Un jeu où seule la connexion compte ne serait pas un jeu d'adresse :
    100 ms de réseau ne doivent pas faire basculer de zone."""
    zone_parfaite = ARCHERY_ZONES[0][0]
    # Vitesse maximale de l'écart, en fraction par milliseconde.
    vitesse = 2.0 / ARCHERY_PERIODE_MS
    derive_100ms = vitesse * 100
    assert derive_100ms < zone_parfaite, (
        f"100 ms de latence déplacent l'écart de {derive_100ms:.3f}, "
        f"soit plus que la zone parfaite ({zone_parfaite})"
    )


# ------------------------------------------------------------ 👻 ghost

def test_la_bonne_porte_ne_se_lit_pas_dans_le_payload():
    """Un custom_id du genre « ghost:winning » se voit dans les outils de
    développement du client, et le jeu n'existe plus."""
    from cogs.games_arcade import _VueGhost

    for _ in range(50):
        vue = _vue(_VueGhost)
        ids = [e.custom_id for e in vue.children if isinstance(e, discord.ui.Button)]
        assert len(ids) == GHOST_PORTES == len(set(ids))
        assert all(i == f"ghost:{n}" for n, i in enumerate(ids))
        assert not any(mot in i for i in ids for mot in ("win", "good", "true", "bonne"))
        # Les libellés non plus ne doivent pas trahir la bonne porte.
        libelles = [e.label for e in vue.children if isinstance(e, discord.ui.Button)]
        assert libelles == [str(n + 1) for n in range(GHOST_PORTES)]


def test_la_porte_gagnante_est_uniformement_repartie():
    import collections

    from cogs.games_arcade import _VueGhost

    compte = collections.Counter(_vue(_VueGhost).bonne_porte for _ in range(4000))
    assert set(compte) == set(range(GHOST_PORTES))
    assert max(abs(v - 1000) / 1000 for v in compte.values()) < 0.15, dict(compte)


# ------------------------------------------------------------ 🧩 sequence

def test_la_suite_vit_uniquement_cote_serveur():
    from cogs.games_arcade import _VueSequence

    vue = _vue(_VueSequence, 5)
    ids = [e.custom_id for e in vue.children if isinstance(e, discord.ui.Button)]
    assert len(ids) == len(set(ids))
    assert all(i.startswith("sequence:") and i.split(":")[1].isdigit() for i in ids)
    # Ni la réponse ni la suite ne doivent apparaître dans les identifiants.
    assert not any(vue.manquant in i for i in ids)
    for symbole in vue.suite:
        assert not any(symbole in i for i in ids)


@pytest.mark.parametrize("longueur", [3, 4, 5, 6])
def test_les_symboles_d_une_manche_sont_tous_distincts(longueur):
    """Avec des répétitions, « l'élément manquant » deviendrait ambigu dès
    qu'il apparaît deux fois."""
    from cogs.games_arcade import _VueSequence

    for _ in range(40):
        vue = _vue(_VueSequence, longueur)
        assert len(vue.suite) == longueur
        assert len(set(vue.suite)) == longueur
        assert vue.manquant in vue.suite
        assert len(vue.affichee) == longueur - 1
        assert vue.manquant not in vue.affichee


def test_la_longueur_reste_dans_les_symboles_disponibles():
    assert len(SEQUENCE_SYMBOLES) >= 6, "sinon une manche de 6 aurait des doublons"


def test_aucun_bouton_de_ce_bloc_n_est_vide():
    from cogs.games_arcade import _VueArchery, _VueGhost, _VueSequence, _VueTarget

    for classe, args in ((_VueTarget, ()), (_VueArchery, ()), (_VueGhost, ()), (_VueSequence, (4,))):
        vue = _vue(classe, *args)
        valider_composants(vue)
        boutons = [e for e in vue.children if isinstance(e, discord.ui.Button)]
        assert boutons, classe.__name__
        assert all(b.emoji is not None or (b.label or "").strip() for b in boutons)


def test_les_vues_tiennent_sur_un_ecran_de_telephone():
    """Discord empile cinq boutons par rangée ; au-delà, mobile devient pénible."""
    from cogs.games_arcade import _VueArchery, _VueGhost, _VueSequence, _VueTarget

    for classe, args in ((_VueTarget, ()), (_VueArchery, ()), (_VueGhost, ()), (_VueSequence, (6,))):
        vue = _vue(classe, *args)
        boutons = [e for e in vue.children if isinstance(e, discord.ui.Button)]
        assert len(boutons) <= 6, f"{classe.__name__} : {len(boutons)} boutons"


# ------------------------------------------------------------ concurrence

def test_un_double_clic_ne_joue_qu_un_coup_sur_chaque_jeu():
    from cogs.games_arcade import _VueArchery, _VueGhost, _VueSequence, _VueTarget

    for classe, args in ((_VueTarget, ()), (_VueArchery, ()), (_VueGhost, ()), (_VueSequence, (4,))):
        vue = _vue(classe, *args)
        coups: list[int] = []

        async def coup():
            await asyncio.sleep(0.02)
            coups.append(1)

        async def scenario():
            return await asyncio.gather(vue.jouer_un_coup(coup), vue.jouer_un_coup(coup))

        resultats = asyncio.run(scenario())
        assert coups == [1], f"{classe.__name__} a joué deux fois"
        assert sorted(resultats) == [False, True]


def test_un_intrus_est_refuse_sur_chaque_jeu():
    from cogs.games_arcade import _VueArchery, _VueGhost, _VueSequence, _VueTarget

    async def intrus():
        envoyes = []

        async def send_message(contenu, **kwargs):
            envoyes.append(contenu)

        return SimpleNamespace(
            user=SimpleNamespace(id=999),
            response=SimpleNamespace(is_done=lambda: False, send_message=send_message),
        ), envoyes

    for classe, args in ((_VueTarget, ()), (_VueArchery, ()), (_VueGhost, ()), (_VueSequence, (4,))):
        vue = _vue(classe, *args)

        async def scenario():
            interaction, envoyes = await intrus()
            autorise = await vue.interaction_check(interaction)
            return autorise, envoyes

        autorise, envoyes = asyncio.run(scenario())
        assert autorise is False, classe.__name__
        assert envoyes, "l'intrus doit recevoir une explication"


def test_une_interaction_apres_la_fin_ne_peut_pas_gagner():
    from cogs.games_arcade import _VueTarget

    vue = _vue(_VueTarget)
    vue.terminer()

    async def scenario():
        envoyes = []

        async def send_message(contenu, **kwargs):
            envoyes.append(contenu)

        interaction = SimpleNamespace(
            user=SimpleNamespace(id=2),
            response=SimpleNamespace(is_done=lambda: False, send_message=send_message),
        )
        return await vue.interaction_check(interaction), envoyes

    autorise, envoyes = asyncio.run(scenario())
    assert autorise is False
    assert "terminée" in envoyes[0]
