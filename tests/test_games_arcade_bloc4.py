"""Bloc 4 — +race, +detective, +crown : la table, les départs, les paiements.

Un jeu solo refuse tout clic qui n'est pas du propriétaire et jette le second
clic simultané. Les deux règles sont fausses à plusieurs, et c'est ce que ce
fichier vérifie : quatre joueurs qui cliquent en même temps doivent être
servis tous les quatre, et chaque gagnant doit être payé sous son propre
identifiant de manche — ``game_session_id`` étant UNIQUE en base, un seul
identifiant partagé n'en paierait qu'un, en silence.
"""
from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import discord
import pytest

from cogs import games_arcade as arcade
from utils import party_games as party
from utils.game_ui import VueSalon, composants_invisibles, valider_composants
from utils.pve_engine import AleaPseudo

ORGANISATEUR = 2


def _cog():
    return SimpleNamespace(bot=None, emoji_monnaie="🪙",
                           ligne_recompense=lambda r: "", rendre=None)


def _ctx():
    return SimpleNamespace(
        guild=SimpleNamespace(id=1),
        author=SimpleNamespace(id=ORGANISATEUR, display_name="Organisateur"),
        channel=SimpleNamespace(id=3))


def _interaction(user_id: int, custom_id: str = "x", deja_repondu: bool = True):
    """Interaction DÉJÀ déférée : l'état réel dans un callback de bouton."""
    refus: list[str] = []

    async def envoyer(texte, **_kwargs):
        refus.append(texte)

    async def rien(*_a, **_k):
        return None

    return SimpleNamespace(
        user=SimpleNamespace(id=user_id, display_name=f"joueur{user_id}"),
        data={"custom_id": custom_id}, refus=refus,
        followup=SimpleNamespace(send=envoyer),
        response=SimpleNamespace(is_done=lambda: deja_repondu, defer=rien,
                                 send_message=envoyer))


def _boutons(vue):
    return [e for e in vue.children if isinstance(e, discord.ui.Button)]


def _vue_race():
    return arcade._VueRace(_cog(), _ctx(), "sid-race")


def _vue_detective():
    return arcade._VueDetective(
        _cog(), _ctx(), party.generer_enquete(AleaPseudo(4)), "sid-detective")


def _vue_crown():
    return arcade._VueCrown(_cog(), _ctx(), "sid-crown")


TABLES = ("race", "detective", "crown")


def _vue(nom):
    return {"race": _vue_race, "detective": _vue_detective, "crown": _vue_crown}[nom]()


# =============================================================================
# Socle du salon
# =============================================================================

def test_l_organisateur_est_inscrit_d_office():
    for nom in TABLES:
        vue = _vue(nom)
        assert vue.actifs == [ORGANISATEUR], nom


def test_un_partant_reste_connu_pour_le_tableau_final():
    """Le supprimer effacerait son pseudo : une ligne « <@123> » ne dit rien."""
    salon = VueSalon(1, joueurs_min=2)
    salon.joindre(7, "Camille")
    assert salon.quitter(7) == "ok"
    assert 7 not in salon.actifs
    assert salon.nom(7) == "Camille"
    assert salon.quitter(7) == "absent"


def test_la_table_refuse_au_dela_du_maximum():
    salon = VueSalon(1, joueurs_min=2, joueurs_max=3)
    assert [salon.joindre(i, str(i)) for i in range(1, 5)] == ["ok", "ok", "ok", "complet"]


def test_on_ne_rejoint_plus_une_partie_commencee():
    salon = VueSalon(1, joueurs_min=2)
    salon.joindre(2, "b")
    salon.demarree = True
    assert salon.joindre(3, "c") == "commencee"


def test_une_place_liberee_par_un_depart_se_reprend():
    salon = VueSalon(1, joueurs_min=2, joueurs_max=2)
    salon.joindre(1, "a")
    salon.joindre(2, "b")
    assert salon.joindre(3, "c") == "complet"
    salon.quitter(2)
    assert salon.joindre(3, "c") == "ok"
    assert sorted(salon.actifs) == [1, 3]


def test_les_boutons_d_inscription_sont_ouverts_a_tous():
    """Le contrôle passe par le suffixe du custom_id, parce que discord.py
    appelle interaction_check avant de savoir quel composant répondra."""
    for suffixe in VueSalon.SUFFIXES_OUVERTS:
        assert suffixe.startswith(":")
    for nom in TABLES:
        identifiants = {b.custom_id for b in _boutons(_vue(nom))}
        assert f"{nom}:rejoindre" in identifiants
        assert f"{nom}:quitter" in identifiants


def test_un_non_inscrit_est_refuse_sur_les_boutons_de_jeu():
    async def scenario():
        vue = _vue_race()
        vue.demarree = True
        await vue.demarrer()
        interaction = _interaction(999, "race:avancer")
        assert await vue.interaction_check(interaction) is False
        assert interaction.refus, "un intrus doit recevoir une explication"
        assert await vue.interaction_check(_interaction(999, "race:rejoindre")) is True

    asyncio.run(scenario())


def test_deux_clics_du_meme_joueur_n_en_valent_qu_un():
    async def scenario():
        vue = _vue_race()
        appels: list[int] = []

        async def lent():
            await asyncio.sleep(0.03)
            appels.append(1)

        resultats = await asyncio.gather(vue.jouer_pour(5, lent), vue.jouer_pour(5, lent))
        return appels, resultats

    appels, resultats = asyncio.run(scenario())
    assert appels == [1]
    assert sorted(resultats) == [False, True]


def test_les_clics_de_joueurs_differents_sont_tous_servis():
    """La règle solo jetterait les trois derniers : un bug invisible à un
    joueur, systématique dès qu'ils sont quatre."""
    async def scenario():
        vue = _vue_race()
        appels: list[int] = []

        async def lent(uid):
            await asyncio.sleep(0.02)
            appels.append(uid)

        resultats = await asyncio.gather(
            *[vue.jouer_pour(uid, lambda uid=uid: lent(uid)) for uid in (10, 11, 12, 13)])
        return appels, resultats

    appels, resultats = asyncio.run(scenario())
    assert sorted(appels) == [10, 11, 12, 13]
    assert resultats == [True, True, True, True]


def test_la_recompense_de_table_n_est_marquee_qu_une_fois():
    vue = _vue_race()
    assert vue.marquer_recompense_versee() is True
    assert vue.marquer_recompense_versee() is False


def test_chaque_gagnant_recoit_un_identifiant_de_manche_distinct():
    """``game_session_id`` est UNIQUE : un identifiant partagé ne paierait
    que le premier gagnant, les autres recevant « already_rewarded »."""
    import inspect

    source = inspect.getsource(arcade._VuePartie.payer)
    assert 'f"{self.session_id}-{user_id}"' in source


# =============================================================================
# Composants
# =============================================================================

@pytest.mark.parametrize("nom", TABLES)
def test_aucun_bouton_vide_avant_ni_apres_le_lancement(nom):
    vue = _vue(nom)
    valider_composants(vue)
    assert composants_invisibles(vue) == []
    vue.demarree = True
    asyncio.run(vue.demarrer())
    vue._reconstruire()
    valider_composants(vue)
    assert composants_invisibles(vue) == []


@pytest.mark.parametrize("nom", TABLES)
def test_les_identifiants_sont_uniques_et_prefixes(nom):
    vue = _vue(nom)
    vue.demarree = True
    asyncio.run(vue.demarrer())
    vue._reconstruire()
    identifiants = [b.custom_id for b in _boutons(vue)]
    assert len(identifiants) == len(set(identifiants))
    assert all(i.startswith(f"{nom}:") for i in identifiants), identifiants


@pytest.mark.parametrize("nom", TABLES)
def test_la_table_tient_dans_les_cinq_rangees(nom):
    vue = _vue(nom)
    vue.demarree = True
    asyncio.run(vue.demarrer())
    vue._reconstruire()
    boutons = _boutons(vue)
    assert len(boutons) <= 25
    assert max((b.row for b in boutons if b.row is not None), default=0) <= 4


@pytest.mark.parametrize("nom", TABLES)
def test_plus_aucun_bouton_une_fois_la_partie_finie(nom):
    vue = _vue(nom)
    vue.terminer()
    vue._reconstruire()
    assert _boutons(vue) == []


def test_lancer_est_grise_tant_qu_il_manque_des_joueurs():
    vue = _vue_race()
    lancer = [b for b in _boutons(vue) if b.custom_id == "race:lancer"][0]
    assert lancer.disabled, "on ne lance pas une course à un coureur"
    vue.joindre(50, "autre")
    vue._reconstruire()
    lancer = [b for b in _boutons(vue) if b.custom_id == "race:lancer"][0]
    assert not lancer.disabled


def test_le_bouton_de_lancement_disparait_une_fois_la_partie_lancee():
    vue = _vue_race()
    vue.joindre(50, "autre")
    vue.demarree = True
    asyncio.run(vue.demarrer())
    vue._reconstruire()
    assert "race:lancer" not in {b.custom_id for b in _boutons(vue)}


def test_les_boutons_de_suspects_ne_trahissent_pas_le_coupable():
    """Un pictogramme différent pour le coupable suffirait à vendre la mèche."""
    vue = _vue_detective()
    vue.demarree = True
    vue._reconstruire()
    accusations = [b for b in _boutons(vue) if b.custom_id.startswith("detective:accuser:")]
    assert len(accusations) == party.SUSPECTS
    assert len({str(b.emoji) for b in accusations}) == 1, "un émoji distinct trahirait"
    assert len({b.style for b in accusations}) == 1, "un style distinct trahirait"
    coupable = vue.enquete.coupable.nom
    for bouton in accusations:
        assert coupable not in bouton.custom_id


def test_le_bouton_d_indice_disparait_quand_tout_est_revele():
    vue = _vue_detective()
    vue.demarree = True
    vue._reconstruire()
    assert "detective:indice" in {b.custom_id for b in _boutons(vue)}
    vue.indices_lus = len(vue.enquete.indices)
    vue._reconstruire()
    assert "detective:indice" not in {b.custom_id for b in _boutons(vue)}


# =============================================================================
# Rendu
# =============================================================================

@pytest.mark.parametrize("nom", TABLES)
def test_le_salon_annonce_l_effectif_requis(nom):
    texte = _vue(nom).texte()
    assert "Table" in texte
    assert str(_vue(nom).joueurs_min) in texte


def test_la_course_montre_une_ligne_par_coureur():
    vue = _vue_race()
    vue.joindre(50, "Bravo")
    vue.demarree = True
    asyncio.run(vue.demarrer())
    texte = vue.texte()
    assert texte.count("🏁") >= 2
    assert "Organisateur" in texte and "Bravo" in texte


def test_la_course_barre_le_nom_du_partant():
    vue = _vue_race()
    vue.joindre(50, "Bravo")
    vue.quitter(50)
    assert "~~Bravo~~" in vue.ligne_table()


def test_l_enquete_ne_montre_jamais_le_coupable_avant_la_fin():
    vue = _vue_detective()
    vue.demarree = True
    vue._reconstruire()
    texte = vue.texte()
    assert "coupable était" not in texte
    for indice in vue.enquete.indices[vue.indices_lus:]:
        assert indice.texte() not in texte, "un indice non révélé est affiché"


def test_l_enquete_revele_le_coupable_une_fois_finie():
    vue = _vue_detective()
    vue.demarree = True
    vue.terminer()
    vue._reconstruire()
    assert vue.enquete.coupable.nom in vue.texte()


def test_la_couronne_n_annonce_jamais_l_instant_de_fin():
    vue = _vue_crown()
    vue.demarree = True
    asyncio.run(vue.demarrer())
    texte = vue.texte()
    assert str(vue.duree) not in texte, "la durée exacte est scellée, pas affichée"
    assert "👑" in texte


def test_l_instant_de_fin_de_la_couronne_est_dans_la_fenetre():
    for _ in range(40):
        vue = _vue_crown()
        asyncio.run(vue.demarrer())
        assert party.CROWN_FENETRE[0] <= vue.duree <= party.CROWN_FENETRE[1]
