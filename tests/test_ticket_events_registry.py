"""Chaque événement de ticket doit arriver dans le journal Tickets.

Le piège que ces tests ferment est silencieux. ``log_categories.resolve()``
ne signale pas un type inconnu : il retombe sur ``DEFAULT_CATEGORY``, qui
vaut ``"server"``. Un ``ticket_unclaim`` oublié dans le registre part donc
dans le journal **Serveur**, avec la bannière Serveur, sans une ligne
d'avertissement — le staff conclut que l'abandon de prise en charge « ne
journalise pas ».

On ne grep pas le code source ici : un test qui cherche ``"ticket_rename"``
dans un fichier échoue sur son propre commentaire et casse au premier
renommage de variable. On part de la table que la primitive utilise
réellement pour émettre — ``EVENEMENTS_TICKET`` — et on vérifie le
comportement de bout en bout.
"""
from __future__ import annotations

import os

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import pytest

from database import db as db_module
from services import tickets as tickets_service
from utils import log_banners, log_categories, log_service


EVENEMENTS = sorted(tickets_service.EVENEMENTS_TICKET)


#: Les douze événements réclamés, plus la note interne et le rappel. Figée
#: volontairement : ajouter un événement doit être un geste explicite, pas un
#: effet de bord d'un autre lot.
ATTENDUS = {
    "ticket_open", "ticket_close", "ticket_autoclose", "ticket_claim",
    "ticket_unclaim", "ticket_member_add", "ticket_member_remove",
    "ticket_rename", "ticket_transfer", "ticket_reopen", "ticket_delete",
    "ticket_rating", "ticket_note", "ticket_bump",
}


def test_les_quatorze_evenements_sont_couverts():
    assert set(EVENEMENTS) == ATTENDUS


@pytest.mark.parametrize("evenement", EVENEMENTS)
def test_chaque_evenement_est_route_vers_tickets(evenement):
    """Le cœur : sans inscription au registre, ceci renvoie "server"."""
    assert log_categories.category_for(evenement) == "tickets"


@pytest.mark.parametrize("evenement", EVENEMENTS)
def test_chaque_evenement_porte_la_banniere_tickets(evenement):
    """On vérifie le FICHIER de bannière, pas le nom du style.

    ``assert banner_kind(...)`` ne mesurait rien : un type totalement inconnu
    rend "info", une chaîne non vide, et l'assertion passait. Le fichier, lui,
    ne peut pas se tromper.
    """
    assert log_banners.get_banner(evenement).name == "banner_tickets.webp"


def test_la_banniere_tickets_est_bien_distincte_des_autres():
    """Garde-fou du test précédent : si tous les événements du bot rendaient
    banner_tickets.webp, l'assertion ci-dessus serait vraie et vide de sens."""
    assert log_banners.get_banner("member_ban").name == "banner_error.webp"
    assert log_banners.get_banner("automod_scam").name == "banner_security.webp"
    assert log_banners.get_banner("voice_join").name == "banner_success.webp"


@pytest.mark.parametrize("evenement", EVENEMENTS)
def test_la_carte_legacy_de_db_est_daccord(evenement):
    """db.py tient sa propre carte type -> catégorie. Deux tables distinctes
    qui doivent rester d'accord : inscrire dans une seule est exactement
    l'erreur déjà commise sur les listes de commandes publiques."""
    assert db_module.legacy_log_category(evenement) == "tickets"


@pytest.mark.parametrize("evenement", EVENEMENTS)
def test_la_cle_devenement_se_relit_comme_le_bon_type(evenement):
    """``log_service._event_from_key`` relit parts[1] et l'emporte sur le
    log_type passé à côté. Si le type n'est pas dans LOG_REGISTRY, il rend
    None et le routage repart du log_type — donc une clé qui se relit
    correctement prouve aussi l'inscription au registre."""
    cle = log_service.make_event_key(7, evenement, discriminator="TK-0001-1")
    assert log_service._event_from_key(cle) == evenement


@pytest.mark.parametrize("evenement", EVENEMENTS)
def test_chaque_evenement_a_un_titre_et_un_libelle_dacteur(evenement):
    titre, libelle = tickets_service.EVENEMENTS_TICKET[evenement]
    assert titre.strip() and libelle.strip()
    # Un emoji en tête : le journal se lit en survolant la colonne de gauche.
    assert not titre[0].isascii(), f"{evenement} : titre sans emoji de tête"


def test_aucun_titre_de_fermeture_ne_depend_du_mot_ferm():
    """Le classement par « "ferm" in title » est mort, mais le piège
    reviendrait si quelqu'un s'y fiait à nouveau : trois titres distincts
    contiennent « ferm », et deux événements sur les trois ne sont PAS une
    fermeture ordinaire."""
    avec_ferm = [e for e, (titre, _) in tickets_service.EVENEMENTS_TICKET.items()
                 if "ferm" in titre.casefold()]
    assert set(avec_ferm) == {"ticket_close", "ticket_autoclose"}
    # Donc un classement par titre confondrait ces deux-là — c'est précisément
    # ce qui se passait : la fermeture automatique était journalisée
    # « ticket_close », indistinguable d'une fermeture par un humain.


# --------------------------------------------------------------- référence

def test_la_reference_identifie_le_ticket_et_la_ligne():
    assert tickets_service.reference_incident(42, 317) == "TK-0042-317"


def test_la_reference_reste_utilisable_sans_ticket():
    """Un événement peut précéder l'insertion en base (échec d'ouverture)."""
    assert tickets_service.reference_incident(None, 317) == "TK-????-317"


def test_la_reference_reste_utilisable_sans_ligne_daudit():
    """Audit indisponible : on rend une référence dégradée, pas une exception,
    et surtout pas une chaîne vide que le staff ne pourrait pas citer."""
    assert tickets_service.reference_incident(42, None) == "TK-0042"


def test_deux_evenements_du_meme_ticket_ont_des_references_distinctes():
    a = tickets_service.reference_incident(42, 317)
    b = tickets_service.reference_incident(42, 318)
    assert a != b


# --------------------------------------------------------------- bouton lien

def test_le_bouton_voir_le_ticket_pointe_vers_le_salon():
    vue = tickets_service.vue_voir_le_ticket(111, 222)
    assert vue is not None
    bouton = vue.children[0]
    assert bouton.url == "https://discord.com/channels/111/222"
    # Un bouton lien n'a pas de custom_id : il survit au redémarrage sans
    # qu'aucun add_view() ne le réenregistre.
    assert bouton.custom_id is None


def test_pas_de_bouton_sans_salon():
    """Le cas de ticket_delete : le salon vient de disparaître. Un bouton qui
    mène dans le vide est pire que pas de bouton."""
    assert tickets_service.vue_voir_le_ticket(111, None) is None
    assert tickets_service.vue_voir_le_ticket(None, 222) is None


def test_le_bouton_survit_au_transport_components_v2():
    """wide_logs.build_rows() reconstruit les boutons et force le style
    ``secondary`` sur tout ce qui n'est pas un lien. Un bouton lien doit
    traverser en gardant son URL, sinon « Voir le ticket » arrive inerte."""
    import discord

    from utils import wide_logs

    rows = wide_logs.build_rows(tickets_service.vue_voir_le_ticket(111, 222))
    assert rows, "le bouton a disparu dans le transport"
    boutons = [item for row in rows for item in row.children]
    assert len(boutons) == 1
    assert boutons[0].style is discord.ButtonStyle.link
    assert boutons[0].url == "https://discord.com/channels/111/222"
