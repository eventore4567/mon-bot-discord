"""Chronométrage des tickets sans Discord, réseau ou serveur réel."""
from utils.ticket_open_timings import TicketOpenTimings


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def test_confirmation_exclut_le_journal_envoye_ensuite():
    clock = Clock()
    trace = TicketOpenTimings(clock=clock)
    clock.now = 0.12
    trace.mark("db_ticket_count")
    clock.now = 0.62
    trace.mark("discord_channel_create")
    clock.now = 1.05
    trace.mark_confirmed()
    clock.now = 1.65
    trace.mark("ticket_log")
    result = trace.summary()
    assert result["confirmed_ms"] == 1050.0
    assert result["total_ms"] == 1650.0
    assert result["stages_ms"] == {
        "db_ticket_count": 120.0,
        "discord_channel_create": 500.0,
        "user_confirmation": 430.0,
        "ticket_log": 600.0,
    }


def test_une_horloge_anormale_ne_produit_pas_de_duree_negative():
    clock = Clock()
    clock.now = 10
    trace = TicketOpenTimings(clock=clock)
    clock.now = 9
    trace.mark("test")
    trace.mark_confirmed()
    result = trace.summary()
    assert result["stages_ms"]["test"] == 0.0
    assert result["confirmed_ms"] == 0.0
    assert result["total_ms"] == 0.0


def test_summary_returns_copy_without_mutating_metrics():
    clock = Clock()
    trace = TicketOpenTimings(clock=clock)
    clock.now = 0.5
    trace.mark("db")
    result = trace.summary()
    result["stages_ms"]["db"] = 999
    assert trace.stages_ms["db"] == 500.0
