"""11/11/2026 : la fiche /invites doit expliquer son propre chiffre.

Capture de l'utilisateur, comparée à InviteLogger : « 17 invitations créditées au
total » au-dessus de « Réelles 17, Reparties 5, Bonus 0, Fakes 1 ». Le total des
arrivées n'était écrit nulle part, et rien ne disait d'où venait le 17.

Pire : « rejoined » servait de filtre à « real » mais n'était compté nulle part. Un
membre revenu disparaissait du détail, donc les compteurs ne pouvaient pas
s'additionner, même en théorie.
"""
from __future__ import annotations

import os

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from database.db import Database  # noqa: E402


def _ligne(**champs):
    base = {
        "left_at": None, "account_age_days": 400, "fake_flags": 0,
        "required_role_id": 0, "role_confirmed": 1, "pending_until": 0,
    }
    base.update(champs)
    return base


def _etat(**champs):
    return Database._invite_row_assessment(_ligne(**champs), legacy_threshold=3, timestamp=1000)


BUCKETS = ("left", "fake", "pending", "rejoined", "real")


def test_chaque_arrivee_tombe_dans_exactement_un_compteur():
    cas = [
        _etat(),                                   # présent, sain
        _etat(left_at=900),                        # reparti
        _etat(fake_flags=1),                       # compte trop récent
        _etat(fake_flags=8),                       # revenu
        _etat(fake_flags=9),                       # revenu ET suspect
        _etat(pending_until=5000),                 # vérification en cours
        _etat(required_role_id=7, role_confirmed=0),
        _etat(left_at=900, fake_flags=9),          # parti, et suspect à l'arrivée
        _etat(fake_flags=None, account_age_days=1),  # ancienne ligne, seuil d'époque
    ]
    for etat in cas:
        comptes = [nom for nom in BUCKETS if etat[nom]]
        assert len(comptes) == 1, (comptes, etat)


def test_un_membre_revenu_est_compte_au_lieu_de_disparaitre():
    revenu = _etat(fake_flags=8)
    assert revenu["rejoined"] and not revenu["real"]
    # Il ne crédite pas une nouvelle invitation, mais il reste visible.
    assert not revenu["fake"], "revenir n'est pas tricher"


def test_un_depart_prime_sur_le_soupcon():
    parti = _etat(left_at=900, fake_flags=1)
    assert parti["left"] and not parti["fake"]


def test_la_fiche_montre_la_soustraction_complete():
    from cogs.invites import detail_du_calcul

    # Le cas réel de la capture : 23 arrivées, 5 reparties, 1 suspecte signalée.
    # La suspecte n'est plus retranchée : elle est dite, pas déduite.
    ligne = detail_du_calcul({"total": 23, "left": 5, "fake": 1, "pending": 0,
                              "rejoined": 0, "bonus": 0})
    assert "**23** arrivées" in ligne and "−5 reparties" in ligne
    assert "1 suspecte signalée" in ligne and "−1 suspecte" not in ligne

    complet = detail_du_calcul({"total": 24, "left": 6, "fake": 0, "pending": 1,
                                "rejoined": 2, "bonus": 3})
    for attendu in ("**24** arrivées", "−6 reparties", "−1 en attente",
                    "2 déjà comptées", "+3 bonus"):
        assert attendu in complet, (attendu, complet)

    # Le serveur qui demande explicitement d'écarter les suspectes les voit déduites.
    strict = detail_du_calcul({"total": 23, "left": 5, "fake": 1, "pending": 0,
                               "rejoined": 0, "bonus": 0, "fakes_deduits": True})
    assert "−1 suspecte" in strict

    # Rien à retrancher : une seule mention, au singulier.
    seul = detail_du_calcul({"total": 1, "left": 0, "fake": 0, "pending": 0,
                             "rejoined": 0, "bonus": 0})
    assert seul == "-# **1** arrivée"


def _breakdown(reglages: dict):
    """Le même serveur, les mêmes arrivées : seuls les réglages changent."""
    import asyncio

    lignes = [
        _ligne(member_id=1, id=1),                       # réelle
        _ligne(member_id=2, id=2, left_at=900),          # repartie
        _ligne(member_id=3, id=3, fake_flags=1),         # suspecte
        _ligne(member_id=4, id=4, fake_flags=8),         # revenue
    ]

    class _DB(Database):
        def __init__(self):
            pass

        async def get_invite_detection_settings(self, guild_id):
            return reglages

        async def fetchall(self, *_a, **_k):
            return lignes

        async def fetchone(self, *_a, **_k):
            return {"s": 2}

    return asyncio.run(_DB().get_invite_breakdown(1, 1))


def test_les_cinq_compteurs_couvrent_exactement_le_total():
    b = _breakdown({})
    assert b["total"] == 4
    assert b["real"] == 1 and b["left"] == 1 and b["fake"] == 1 and b["rejoined"] == 1
    # Les cinq compteurs couvrent exactement le total : plus personne ne disparaît.
    assert b["left"] + b["fake"] + b["pending"] + b["rejoined"] + b["real"] == b["total"]


def test_une_suspecte_est_creditee_comme_chez_invitelogger():
    """11/11/2026 : SentriX affichait 17 là où InviteLogger affichait 18.

    Un compte jugé « trop récent » était retiré du crédit sans que le serveur l'ait
    demandé. Par défaut, SentriX crédite maintenant toutes les arrivées encore
    présentes : réelles + revenues + suspectes, plus le bonus du staff.
    """
    b = _breakdown({})
    assert b["fakes_deduits"] is False
    assert b["credited"] == b["real"] + b["rejoined"] + b["fake"] + b["bonus"] == 5
    # Seul un départ retire une invitation : 4 arrivées − 1 repartie + 2 bonus.
    assert b["credited"] == b["total"] - b["left"] - b["pending"] + b["bonus"]


def test_le_serveur_peut_encore_ecarter_les_suspectes():
    b = _breakdown({"exclude_fakes": True})
    assert b["fakes_deduits"] is True
    assert b["credited"] == b["real"] + b["bonus"] == 3
