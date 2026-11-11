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
    return Database._invite_row_assessment(_ligne(**champs), seuil_age=3, timestamp=1000)


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


def test_le_resume_se_lit_et_s_additionne():
    """« Arrivées − Reparties − Fakes + Bonus » : quatre lignes, pas un chiffre seul."""
    from cogs.invites import resume_du_calcul, texte_du_resume

    # Le cas réel de la capture, côté InviteLogger : 24 − 6 − 0 = 18.
    b = {"total": 24, "left": 6, "fake": 0, "pending": 0, "rejoined": 0,
         "bonus": 0, "credited": 18}
    assert resume_du_calcul(b) == [("Arrivées", 24), ("Reparties", 6), ("Fakes", 0), ("Bonus", 0)]
    assert b["total"] - b["left"] - b["fake"] + b["bonus"] == b["credited"]

    texte = texte_du_resume(b)
    for attendu in ("**Arrivées** · 24", "**Reparties** · 6", "**Fakes** · 0", "**Bonus** · 0"):
        assert attendu in texte, (attendu, texte)

    # « En attente » ne s'affiche que là où le serveur a réglé un délai ou un rôle.
    assert "En attente" not in texte
    avec_attente = texte_du_resume({**b, "pending": 2})
    assert "**En attente** · 2" in avec_attente


def _breakdown(reglages: dict):
    """Le même serveur, les mêmes arrivées : seuls les réglages changent."""
    import asyncio

    lignes = [
        _ligne(member_id=1, id=1),                       # réelle
        _ligne(member_id=2, id=2, left_at=900),          # repartie
        _ligne(member_id=3, id=3, account_age_days=1, fake_flags=1),  # compte d'un jour
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


def test_le_credit_est_celui_d_invitelogger():
    """Arrivées − reparties − fakes + bonus, exactement comme InviteLogger.

    Sa capture le dit : 2 arrivées, 1 repartie, 1 fake, 0 bonus → 0 invitation.
    """
    b = _breakdown({})
    assert b["credited"] == b["total"] - b["left"] - b["fake"] - b["pending"] + b["bonus"] == 4


def test_un_compte_de_six_jours_n_est_plus_accuse():
    """11/11/2026 : le seuil était à 7 jours sans que personne l'ait choisi.

    Un compte créé six jours avant son arrivée était marqué « fake », et le fake
    retirait une invitation réellement faite. Le seuil par défaut est revenu à 3
    jours ; un serveur qui veut plus sévère le règle lui-même.
    """
    six_jours = _etat(account_age_days=6, fake_flags=1)
    assert six_jours["real"] and not six_jours["fake"]

    # Deux jours, c'est un compte jetable : il reste un fake.
    deux_jours = _etat(account_age_days=2, fake_flags=1)
    assert deux_jours["fake"] and not deux_jours["real"]

    # Et le serveur qui remonte son seuil retrouve l'ancien comportement.
    strict = Database._invite_row_assessment(
        _ligne(account_age_days=6, fake_flags=1), seuil_age=7, timestamp=1000)
    assert strict["fake"]


def test_corriger_le_seuil_corrige_aussi_l_historique():
    """Le bit figé dans fake_flags ne doit plus condamner une arrivée à vie."""
    sept_jours = _breakdown({"min_account_age_days": 7})
    trois_jours = _breakdown({"min_account_age_days": 3})
    assert sept_jours["fake"] == 1 and trois_jours["fake"] == 1
    # La ligne d'un jour reste fake dans les deux cas ; celle de 400 jours jamais.
    assert trois_jours["real"] == 1
