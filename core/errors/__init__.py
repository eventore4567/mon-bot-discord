"""Pipeline d'erreur unique — Core V2, Phase 1.

Corrige une lacune vivante confirmée par l'audit (docs/core-v2-audit-technical-debt.md,
§2) : le gestionnaire d'erreur réellement actif en production aujourd'hui
(cogs/final_error_embed_v5.py) ne journalise aucune trace pour une exception
générique non prévue — seul un compteur anonyme est incrémenté. Un incident réel
en production n'y laisse donc aucune trace exploitable.

Ce module ne remplace ni ne chaîne aucun gestionnaire existant : c'est une
fonction pure, sans dépendance à discord.py, que le gestionnaire déjà actif
appelle pour obtenir une référence courte (SXR-CMD-xxxx) et faire journaliser la
trace complète côté serveur, avant de continuer à construire son propre panneau
utilisateur exactement comme avant.
"""
from .pipeline import ErrorReport, clean_message, next_code, report, reset_for_tests

__all__ = ["ErrorReport", "clean_message", "next_code", "report", "reset_for_tests"]
