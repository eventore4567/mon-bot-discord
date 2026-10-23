"""Un module ne doit pas être déclaré « dégradé » sans que rien ne soit bloqué.

Mesuré en production le 23/10/2026, pendant un test de tickets :

    Micro-kernel : appel bloqué détecté dans cogs.tickets depuis 359,7 s
    Micro-kernel : module dégradé : cogs.tickets

Rien n'était bloqué. Le compteur d'appels en vol était incrémenté dans un
CHECK de commande, et une commande hybride lancée en slash traverse DEUX
gardes — celle du préfixe (check global, main.py) et celle du slash
(core.module_gate). Deux entrées, une seule sortie : le compteur ne revenait
jamais à zéro et son horodatage restait figé, donc l'âge grandissait sans fin.
"""
import os
import time

os.environ.setdefault("DISCORD_TOKEN", "x")

from core.module_resilience import ModuleResilience  # noqa: E402
from core.module_state import ModuleState  # noqa: E402


def _resilience():
    etats = {"cogs.tickets": ModuleState(name="cogs.tickets")}
    return ModuleResilience(etats, lambda *a, **k: None), etats["cogs.tickets"]


def test_deux_gardes_une_invocation_ne_comptent_qu_une_fois():
    r, etat = _resilience()
    r.enter("cogs.tickets", ("i", 777))   # garde préfixe
    r.enter("cogs.tickets", ("i", 777))   # garde slash, MÊME interaction
    assert etat.in_flight == 1


def test_la_sortie_ramene_bien_a_zero():
    r, etat = _resilience()
    r.enter("cogs.tickets", ("i", 777))
    r.enter("cogs.tickets", ("i", 777))
    r.exit("cogs.tickets", ("i", 777))
    assert etat.in_flight == 0
    assert etat.in_flight_since is None, "un horodatage figé = faux appel bloqué"


def test_deux_invocations_distinctes_restent_distinctes():
    r, etat = _resilience()
    r.enter("cogs.tickets", ("m", 1))
    r.enter("cogs.tickets", ("m", 2))
    r.exit("cogs.tickets", ("m", 1))
    assert etat.in_flight == 1
    assert ("m", 2) in etat.appels_en_cours


def test_une_entree_jamais_refermee_est_reclamee():
    # Redémarrage en plein appel, tâche annulée, chemin de sortie manquant :
    # sans réclamation, le module restait « dégradé » pour toujours.
    r, etat = _resilience()
    r.enter("cogs.tickets", ("i", 1))
    etat.appels_en_cours[("i", 1)] = time.time() - r.DUREE_MAX_APPEL_SECONDES - 10
    r.enter("cogs.tickets", ("i", 2))
    assert etat.in_flight == 1
    assert ("i", 2) in etat.appels_en_cours


def test_l_horodatage_suit_la_plus_ancienne_invocation_vivante():
    r, etat = _resilience()
    r.enter("cogs.tickets", ("m", 1))
    premier = etat.in_flight_since
    time.sleep(0.01)
    r.enter("cogs.tickets", ("m", 2))
    assert etat.in_flight_since == premier
    r.exit("cogs.tickets", ("m", 1))
    assert etat.in_flight_since is not None and etat.in_flight_since > premier


def test_sans_cle_on_referme_la_plus_ancienne():
    # Chemin de repli : c'est la plus ancienne qui ferait croire à un blocage.
    r, etat = _resilience()
    r.enter("cogs.tickets", ("m", 1))
    time.sleep(0.01)
    r.enter("cogs.tickets", ("m", 2))
    r.exit("cogs.tickets")
    assert list(etat.appels_en_cours) == [("m", 2)]


def test_une_sortie_de_trop_ne_passe_pas_sous_zero():
    r, etat = _resilience()
    r.exit("cogs.tickets", ("m", 9))
    r.exit("cogs.tickets")
    assert etat.in_flight == 0


def test_la_cle_dinvocation_est_la_meme_des_deux_cotes():
    # C'est elle qui rend le double comptage impossible sur un hybride.
    from core.module_gate import cle_dinvocation

    class _Interaction:
        id = 555
        response = object()

    class _Ctx:
        interaction = _Interaction()
        message = type("M", (), {"id": 111})()

    assert cle_dinvocation(_Ctx()) == cle_dinvocation(_Interaction()) == ("i", 555)


def test_en_prefixe_pur_la_cle_vient_du_message():
    from core.module_gate import cle_dinvocation

    class _Ctx:
        interaction = None
        message = type("M", (), {"id": 111})()

    assert cle_dinvocation(_Ctx()) == ("m", 111)
