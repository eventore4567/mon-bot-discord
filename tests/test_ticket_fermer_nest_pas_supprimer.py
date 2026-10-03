"""Fermer un ticket n'est plus le supprimer.

Demandé par Jayden : « close ferme, mais quelqu'un doit delete ».

**Ce qui l'empêchait.** ``ticket_delete_delay`` valait 30 secondes, et les six
endroits qui le lisaient écrivaient tous la même chose :

    delay = (conf["ticket_delete_delay"] if conf else 30) or 30

où ``0 or 30`` rend 30. Mettre zéro pour dire « ne supprime pas » était donc
impossible : la valeur était silencieusement ramenée à trente secondes. Le
réglage existait, il ne pouvait simplement pas exprimer ce cas.

Trente secondes, c'est aussi trop court pour relire quoi que ce soit : le
salon disparaît avant que le staff ait pu y revenir.
"""
from __future__ import annotations

import os
import time

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import pytest
import discord

from services import tickets as ts


# =============================================================================
# Le délai
# =============================================================================

def test_zero_veut_dire_suppression_manuelle():
    """Le cœur du lot. C'est le seul cas dont le comportement change."""
    assert ts.delai_de_suppression({"ticket_delete_delay": 0}) is None


def test_lancienne_expression_ramenait_zero_a_trente():
    """La preuve que le réglage était inexprimable, pas seulement ignoré."""
    for valeur in (0, None):
        ancien = (valeur if valeur is not None else 30) or 30
        assert ancien == 30
    # Et maintenant les deux cas se distinguent.
    assert ts.delai_de_suppression({"ticket_delete_delay": 0}) is None
    assert ts.delai_de_suppression({"ticket_delete_delay": None}) == 30


def test_une_valeur_explicite_est_respectee():
    assert ts.delai_de_suppression({"ticket_delete_delay": 30}) == 30
    assert ts.delai_de_suppression({"ticket_delete_delay": 3600}) == 3600


@pytest.mark.parametrize("config", [None, {}, {"ticket_delete_delay": None}])
def test_une_configuration_absente_garde_le_defaut(config):
    """Les serveurs qui n'ont jamais touché ce réglage ne changent pas de
    comportement — c'est la condition pour que ce lot soit sûr à déployer."""
    assert ts.delai_de_suppression(config) == ts.DELAI_SUPPRESSION_DEFAUT


def test_une_valeur_illisible_retombe_sur_le_defaut():
    """Pas sur « manuel » : un réglage corrompu ne doit pas faire s'accumuler
    des salons fermés que personne ne pense à supprimer."""
    assert ts.delai_de_suppression({"ticket_delete_delay": "abc"}) == 30
    assert ts.delai_de_suppression({"ticket_delete_delay": []}) == 30


def test_un_delai_negatif_vaut_manuel():
    assert ts.delai_de_suppression({"ticket_delete_delay": -5}) is None
    assert ts.SUPPRESSION_MANUELLE == 0


# =============================================================================
# La durée
# =============================================================================

def _maintenant() -> int:
    return int(time.time())


def test_la_duree_est_lisible():
    fin = _maintenant()
    assert ts.duree_du_ticket({"created_at": fin - 8040}, fin=fin) == "2 heures, 14 minutes"


def test_une_duree_de_moins_dune_minute_saffiche_en_secondes():
    """format_duration arrondit à la minute et rendrait « 0 min » pour un
    ticket réglé en trente secondes — ce qui se lit comme une erreur, pas comme
    un support rapide."""
    fin = _maintenant()
    assert ts.duree_du_ticket({"created_at": fin - 30}, fin=fin) == "30 s"


def test_une_duree_incalculable_rend_none_plutot_quun_chiffre_faux():
    fin = _maintenant()
    assert ts.duree_du_ticket({"created_at": 0}, fin=fin) is None
    assert ts.duree_du_ticket({}) is None
    assert ts.duree_du_ticket({"created_at": "hier"}) is None


def test_une_fin_anterieure_au_debut_ne_rend_pas_une_duree_negative():
    """Peut arriver si l'horloge recule, ou si created_at a été réécrit."""
    fin = _maintenant()
    assert ts.duree_du_ticket({"created_at": fin + 100}, fin=fin) is None


# =============================================================================
# Le bouton de suppression
# =============================================================================

def test_le_bouton_porte_lidentifiant_du_ticket():
    """Son custom_id encode le ticket, donc Discord le fait fonctionner même
    après un redémarrage. Quand la suppression est manuelle, ce bouton est le
    SEUL moyen de supprimer le salon depuis Discord : s'il cessait de répondre
    après un redéploiement, les salons fermés s'accumuleraient sans recours."""
    vue = ts.vue_supprimer_ticket(42)
    bouton = vue.children[0]
    assert bouton.custom_id == "sx_ticket_del:42"


def test_le_bouton_est_visible_et_signale_le_danger():
    import discord

    # .item : un DynamicItem ENVELOPPE le bouton, il n'en est pas un.
    bouton = ts.vue_supprimer_ticket(7).children[0].item
    assert bouton.label == "Supprimer le salon"
    assert str(bouton.emoji) == "🗑️"
    assert bouton.style is discord.ButtonStyle.danger


def test_la_vue_ne_expire_jamais():
    """Un timeout désactiverait le bouton au bout de quelques minutes, et le
    salon deviendrait impossible à supprimer autrement qu'à la main."""
    assert ts.vue_supprimer_ticket(1).timeout is None


def test_le_gabarit_du_bouton_accepte_son_propre_custom_id():
    """Garde-fou du mécanisme dynamique : si le gabarit et le custom_id
    divergent, Discord ne route plus le clic et le bouton devient muet."""
    import re

    gabarit = ts.BoutonSupprimerTicket.__discord_ui_compiled_template__
    del re
    assert gabarit.fullmatch("sx_ticket_del:42")
    assert gabarit.fullmatch(ts.vue_supprimer_ticket(42).children[0].custom_id)


def test_le_bouton_est_enregistre_au_demarrage():
    """Un DynamicItem non enregistré via add_dynamic_items ne répond plus après
    un redémarrage. C'est l'erreur qui avait déjà cassé la notation des tickets
    pendant des mois."""
    from pathlib import Path

    source = Path("main.py").read_text(encoding="utf-8")
    assert "BoutonSupprimerTicket" in source
    assert "add_dynamic_items(BoutonSupprimerTicket)" in source


# =============================================================================
# Close / Open / Delete — contrat 2026-10-03
# =============================================================================

def test_vue_ticket_ferme_propose_rouvrir_et_supprimer():
    vue = ts.vue_ticket_ferme(42)
    custom_ids = [item.custom_id for item in vue.children]
    assert "sx_ticket_open:42" in custom_ids
    assert "sx_ticket_del:42" in custom_ids

    buttons = [item.item for item in vue.children]
    labels = {button.label for button in buttons}
    assert "Rouvrir" in labels
    assert "Supprimer le salon" in labels


def test_bouton_rouvrir_est_persistant_et_encode_ticket_id():
    vue = ts.vue_ticket_ferme(7)
    open_item = next(item for item in vue.children if item.custom_id.startswith("sx_ticket_open:"))
    assert open_item.custom_id == "sx_ticket_open:7"
    assert open_item.item.style is discord.ButtonStyle.success


def test_close_masque_completement_le_salon_au_membre_et_ne_programme_plus_de_delete():
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "cogs" / "ticket_claim_security.py").read_text(encoding="utf-8")
    block = source.split("async def secure_close_ticket", 1)[1].split("async def secure_claim", 1)[0]

    assert "overwrite.view_channel = False" in block
    assert "overwrite.send_messages = False" in block
    assert "overwrite.read_message_history = False" in block
    assert "vue_ticket_ferme(ticket_id)" in block
    assert "asyncio.create_task(self._auto_delete" not in block


def test_reopen_restores_full_member_visibility():
    from pathlib import Path

    service_source = (Path(__file__).resolve().parents[1] / "services" / "tickets.py").read_text(encoding="utf-8")
    block = service_source.split("class BoutonRouvrirTicket", 1)[1].split("class BoutonSupprimerTicket", 1)[0]

    assert "overwrite.view_channel = True" in block
    assert "overwrite.send_messages = True" in block
    assert "overwrite.read_message_history = True" in block
    assert "status='ouvert'" in block


def test_reopen_button_is_registered_at_startup():
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8")
    assert "BoutonRouvrirTicket" in source
    assert "self.add_dynamic_items(BoutonRouvrirTicket, BoutonSupprimerTicket)" in source
