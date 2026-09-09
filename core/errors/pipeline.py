"""Génération de référence d'erreur + journalisation de la trace complète.

Aucun état partagé avec Discord : `report()` prend des primitives (chaînes,
entiers), jamais un ``Context``/``Interaction``, pour rester testable sans
jamais instancier le moindre objet discord.py.
"""
from __future__ import annotations

import itertools
import logging
import time
from dataclasses import dataclass, field

logger = logging.getLogger("core.errors")

_counter = itertools.count(1)


def next_code() -> str:
    """Référence courte affichée à l'utilisateur ET recherchable dans les logs.

    Ne cherche pas l'unicité globale inter-redémarrage (ce n'est pas son rôle :
    l'horodatage du log qui l'accompagne suffit à retrouver le bon redémarrage).
    Un compteur monotone par processus suffit à corréler un message Discord à
    sa ligne de log, ce qui est le seul besoin exprimé : « dans les logs je dois
    pouvoir retrouver exactement la stack trace liée ».
    """
    return f"SXR-CMD-{next(_counter):04d}"


@dataclass
class ErrorReport:
    code: str
    exc_type: str
    exc_message: str
    command: str
    transport: str
    guild_id: int | None = None
    user_id: int | None = None
    stage: str | None = None
    created_at: float = field(default_factory=time.time)

    def user_message(self) -> str:
        return clean_message(self)


def clean_message(report: ErrorReport) -> str:
    """Jamais de texte d'exception brut — juste une référence à recouper côté logs."""
    return f"Une erreur est survenue. Référence : {report.code}"


def report(
    exc: BaseException,
    *,
    command: str,
    transport: str,
    guild_id: int | None = None,
    user_id: int | None = None,
    stage: str | None = None,
) -> ErrorReport:
    """Journalise la trace complète et retourne une référence courte à afficher.

    ``transport`` vaut "prefix" ou "slash" — jamais autre chose, pour que les
    logs restent grep-ables (``transport=slash``) sans normalisation a posteriori.
    """
    code = next_code()
    entry = ErrorReport(
        code=code,
        exc_type=type(exc).__name__,
        exc_message=str(exc)[:500],
        command=command,
        transport=transport,
        guild_id=guild_id,
        user_id=user_id,
        stage=stage,
    )
    logger.error(
        "event=command_error code=%s command=%s transport=%s guild=%s user=%s stage=%s exc_type=%s",
        entry.code,
        entry.command,
        entry.transport,
        entry.guild_id,
        entry.user_id,
        entry.stage,
        entry.exc_type,
        exc_info=exc,
    )
    return entry


def reset_for_tests() -> None:
    """Remet le compteur à 1 — tests uniquement, jamais appelé par le runtime."""
    global _counter
    _counter = itertools.count(1)
