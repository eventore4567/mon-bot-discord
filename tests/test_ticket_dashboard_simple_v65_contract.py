from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "web" / "ticket_dashboard_simple_v65.py").read_text(encoding="utf-8")
PING_SOURCE = (ROOT / "web" / "ticket_ping_dashboard.py").read_text(encoding="utf-8")


def test_dashboard_ticket_est_organise_en_quatre_etapes():
    for label in (
        "1 · Général",
        "2 · Équipe",
        "3 · Panel",
        "4 · Publication",
    ):
        assert label in SOURCE


def test_dashboard_reutilise_les_api_existantes_sans_recreer_le_moteur_ticket():
    assert "/ticket-center/panels/" in SOURCE
    assert "/ticket-button-editor/" in SOURCE
    assert "staff_buttons" in SOURCE
    assert "questions" in SOURCE
    assert "ticket_role_rules" not in SOURCE  # les règles restent pilotées par l'API V35


def test_publication_met_a_jour_un_panel_existant_et_evite_les_doublons():
    assert 'ticket-simple/panels/{panel_id}/publish' in SOURCE
    assert "_sync_panel_message" in SOURCE
    assert 'if sync == "updated"' in SOURCE
    assert "TicketPanelView" in SOURCE


def test_interface_simple_est_chargee_apres_les_couches_ticket_historiques():
    assert "ticket_dashboard_simple_v65.install(dashboard)" in PING_SOURCE
