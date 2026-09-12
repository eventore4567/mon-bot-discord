"""Observabilité par commande — Core V2, Phase 1.

Compteurs et latences en mémoire, par commande et par transport (+/), en
écoute passive : ce module ne remplace ni n'enveloppe aucun code existant, il
est alimenté par un unique listener additif (cogs/core_command_observability.py)
qui n'affecte jamais le comportement d'une commande, seulement les métriques.
"""
from .metrics import CommandStats, record, record_error, reset_for_tests, snapshot

__all__ = ["CommandStats", "record", "record_error", "reset_for_tests", "snapshot"]
