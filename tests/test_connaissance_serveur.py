"""Chaque module déclare ce qu'il sait ; l'IA le lit selon TA permission.

21/11/2026, demande de l'utilisateur : « fait que seules les personnes avec la
perm puissent demander les tickets, les trucs staff quoi. »

La règle appliquée, sans exception : une source est lisible par l'IA
exactement comme sa commande équivalente. Même donnée, même permission. On
interroge access_matrix — l'autorité qui décide déjà pour les commandes —
plutôt que d'inventer une seconde politique qui finirait par diverger. C'est
l'erreur qu'on avait corrigée sur peut_consulter la veille.

Ces tests vérifient les DEUX sens : le staff obtient, le membre ordinaire
n'obtient rien, et une source publique reste publique.
"""
from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import pytest  # noqa: E402

from utils import (  # noqa: E402
    connaissance_communaute,
    connaissance_serveur,
    connaissance_tickets,
    memoire_sanctions,
)


@pytest.fixture(autouse=True)
def _registre_propre():
    """Chaque test repart du registre réellement installé en production."""
    for module in (memoire_sanctions, connaissance_tickets, connaissance_communaute):
        module.installer()
    yield


def _membre(identifiant, nom, *, permission=None):
    permissions = SimpleNamespace(
        administrator=False, ban_members=False, kick_members=False,
        moderate_members=False, manage_guild=False, manage_channels=False,
        manage_messages=False,
    )
    if permission:
        setattr(permissions, permission, True)
    return SimpleNamespace(
        id=identifiant, name=nom, display_name=nom, bot=False,
        guild_permissions=permissions, roles=[],
    )


class _Bot:
    """Un bot minimal : deux tickets ouverts, aucune autre donnée."""

    def __init__(self, tickets=()):
        self._tickets = list(tickets)
        self.db = self

    async def get_guild_config(self, guild_id):
        return {"mod_role": None}

    async def fetchall(self, requete, params=()):
        if "FROM tickets" in requete:
            return self._tickets
        return []

    async def fetchone(self, requete, params=()):
        if "COUNT(*)" in requete and "tickets" in requete:
            return {"c": len(self._tickets)}
        return None

    async def get_invite_leaderboard_credited(self, guild_id, limit=10):
        # La VRAIE forme de production : une liste de tuples (inviter_id,
        # breakdown). La fixture renvoyait des dictionnaires et masquait un
        # AttributeError qui faisait disparaître toute la source.
        return [(99, {"credited": 7, "total": 9})]

    async def get_invite_stats(self, guild_id, inviter_id):
        return {"total": 7, "active": 5, "left": 2}


def _guild(membres):
    index = {m.id: m for m in membres}
    return SimpleNamespace(id=1, members=membres, get_member=index.get)


def _ticket(canal, demandeur):
    return {
        "channel_id": canal, "user_id": demandeur, "status": "ouvert",
        "category": "general", "priority": "haute", "claimed_by": None,
        "created_at": 1,
    }


# ------------------------------------------- les tickets sont réservés au staff
@pytest.mark.asyncio
async def test_un_membre_ordinaire_n_obtient_aucun_ticket():
    """Le cœur de la demande : un membre sans permission ne doit rien voir."""
    simple = _membre(50, "Membre")
    guild = _guild([simple])
    bot = _Bot([_ticket(777, 50)])

    bloc = await connaissance_serveur.bloc(bot, guild, simple, "combien de tickets ouverts ?")
    assert bloc == ""


@pytest.mark.asyncio
async def test_un_administrateur_obtient_les_tickets():
    admin = _membre(7, "Chef", permission="administrator")
    guild = _guild([admin])
    bot = _Bot([_ticket(777, 7)])

    bloc = await connaissance_serveur.bloc(bot, guild, admin, "combien de tickets ouverts ?")
    assert "Tickets ouverts" in bloc
    assert "777" in bloc
    assert "priorité haute" in bloc


@pytest.mark.asyncio
async def test_sans_ticket_ouvert_le_staff_a_une_vraie_reponse():
    """« Aucun » est une réponse ; un silence laisserait croire à une panne."""
    admin = _membre(7, "Chef", permission="administrator")
    bloc = await connaissance_serveur.bloc(
        _Bot([]), _guild([admin]), admin, "il reste des tickets ?"
    )
    assert "aucun ticket ouvert" in bloc


# ------------------------------------------------ une source publique le reste
@pytest.mark.asyncio
async def test_les_invitations_restent_accessibles_a_tous():
    """+invites répond à tout le monde : la source aussi, sinon elle diverge."""
    simple = _membre(99, "Natix")
    bloc = await connaissance_serveur.bloc(
        _Bot(), _guild([simple]), simple, "qui a le plus d'invitations ?"
    )
    assert "Classement des invitations" in bloc
    assert "Natix" in bloc


# ------------------------------------------------------- économie du registre
@pytest.mark.asyncio
async def test_une_question_ordinaire_n_interroge_aucune_source():
    """Charger les modules à chaque message gonflerait le prompt pour rien."""
    simple = _membre(50, "Membre")
    assert await connaissance_serveur.bloc(_Bot(), _guild([simple]), simple, "salut ça va ?") == ""
    assert await connaissance_serveur.bloc(_Bot(), _guild([simple]), simple, "mdr tkt") == ""


@pytest.mark.asyncio
async def test_une_source_en_panne_ne_casse_pas_la_reponse():
    class _BotCasse(_Bot):
        async def fetchall(self, *a, **k):
            raise RuntimeError("base indisponible")

    admin = _membre(7, "Chef", permission="administrator")
    bloc = await connaissance_serveur.bloc(
        _BotCasse(), _guild([admin]), admin, "combien de tickets ouverts ?"
    )
    assert bloc == ""  # pas d'exception, juste rien à dire


# --------------------------------------------------------- forme du registre
def test_chaque_source_declare_sa_commande_equivalente():
    """Sans équivalence déclarée, une source serait publique par accident."""
    attendu = {
        "sanctions": "modhistory",
        "tickets": "sentrixpro ticket-summary",
        "invitations": "invites",
        "niveau": "level",
        "economie": "balance",
    }
    obtenu = {s.nom: s.commande_equivalente for s in connaissance_serveur.sources()}
    assert obtenu == attendu


def test_declarer_deux_fois_ne_duplique_pas():
    """Un rechargement de module ne doit pas interroger deux fois la base."""
    avant = len(connaissance_serveur.sources())
    connaissance_tickets.installer()
    connaissance_tickets.installer()
    assert len(connaissance_serveur.sources()) == avant


def test_les_sources_sont_declarees_la_ou_le_registre_est_lu():
    """Déclarées ailleurs, elles laisseraient un registre vide : c'est ainsi
    que le streaming est resté du code mort pendant trois jours."""
    import inspect

    from cogs import ai_context_v9

    source = inspect.getsource(ai_context_v9.install)
    assert "connaissance_tickets" in source
    assert "connaissance_communaute" in source
    assert "memoire_sanctions" in source


# ------------------------------------------- revue Codex du 21/11/2026
@pytest.mark.asyncio
async def test_le_classement_lit_la_vraie_forme_de_production():
    """get_invite_leaderboard_credited renvoie des TUPLES, pas des dicts.

    Appeler .get dessus levait AttributeError, le registre avalait l'erreur,
    et TOUTE la source invitations disparaissait — y compris les statistiques
    individuelles. Ma fixture renvoyait des dictionnaires : j'avais inventé la
    forme au lieu de la lire dans database/db.py.
    """
    natix = _membre(99, "Natix")
    bloc = await connaissance_serveur.bloc(
        _Bot(), _guild([natix]), natix, "qui a le plus d'invitations ?"
    )
    assert "1. Natix — 7 invitation(s)" in bloc
    assert "7 au total" in bloc, "les statistiques individuelles doivent suivre"


@pytest.mark.asyncio
async def test_l_economie_et_le_niveau_ont_des_portes_distinctes():
    """access_matrix range balance dans economy et level dans levels.

    Les lire tous les deux sous l'autorisation de `level` exposait le solde
    d'un serveur ayant désactivé l'économie, et inversement.
    """
    noms = {s.nom: s.commande_equivalente for s in connaissance_serveur.sources()}
    assert noms["niveau"] == "level"
    assert noms["economie"] == "balance"

    from utils import connaissance_communaute as communaute

    assert communaute.concerne_niveau("je suis niveau combien") is True
    assert communaute.concerne_niveau("j'ai combien d'argent") is False
    assert communaute.concerne_economie("j'ai combien d'argent") is True
    assert communaute.concerne_economie("je suis niveau combien") is False


@pytest.mark.asyncio
async def test_une_troncature_interdit_tout_dementi():
    """Couper un bloc en gardant « liste complète » produisait un démenti faux.

    C'est le défaut corrigé la veille sur la limite de huit dossiers,
    réintroduit un étage plus haut par la limite de longueur du registre.
    """
    long = "x" * (connaissance_serveur.LONGUEUR_MAX // 2 + 100)

    def _source(nom):
        return connaissance_serveur.Source(
            nom=nom, concerne=lambda t: True,
            lire=lambda b, g, a, t, _n=nom: _retour(f"{_n} : {long}"),
        )

    async def _retour(valeur):
        return valeur

    for nom in ("bavard_un", "bavard_deux"):
        connaissance_serveur.enregistrer(_source(nom))
    try:
        simple = _membre(50, "Membre")
        bloc = await connaissance_serveur.bloc(_Bot(), _guild([simple]), simple, "peu importe")
        assert "ATTENTION" in bloc
        assert "JAMAIS qu'une information n'existe pas" in bloc
        assert "dis que tu ne l'as pas sous les yeux" not in bloc
        # Un bloc entre entier ou pas du tout : jamais coupé au milieu.
        assert bloc.count("bavard_") == 1
    finally:
        connaissance_serveur._SOURCES[:] = [
            s for s in connaissance_serveur.sources() if not s.nom.startswith("bavard_")
        ]


@pytest.mark.asyncio
async def test_sans_troncature_le_dementi_reste_permis():
    natix = _membre(99, "Natix")
    bloc = await connaissance_serveur.bloc(
        _Bot(), _guild([natix]), natix, "qui a le plus d'invitations ?"
    )
    assert "dis que tu ne l'as pas sous les yeux" in bloc
    assert "ATTENTION" not in bloc
