"""Actions staff dont la réponse « / » est privée (éphémère).

02/11/2026 : en « / », la confirmation d'une sanction ou d'une action de salon
n'est visible que par le modérateur qui l'a lancée. Les logs staff, le MP de
sanction et l'effet sur Discord ne changent pas. En préfixe « + », Discord ne
sait pas faire d'éphémère : rien ne change.

Les consultations (warnings, case, modhistory…) restent normales.
"""
from __future__ import annotations

from typing import Any

PRIVATE_SLASH_ACTIONS = frozenset({
    "ban", "tempban", "unban", "hackban", "kick",
    "mute", "unmute", "warn", "unwarn", "clearwarnings",
    "clear", "slowmode", "lock", "unlock", "hide", "show",
    "nickname", "resetnick", "move", "disconnect",
    "giverole", "removerole",
})


def commande_privee(nom: str | None) -> bool:
    return str(nom or "").casefold().strip() in PRIVATE_SLASH_ACTIONS


def reponse_privee(ctx: Any) -> bool:
    """Vrai pour une action staff lancée en « / » : sa réponse doit être éphémère."""
    if getattr(ctx, "interaction", None) is None:
        return False
    return commande_privee(getattr(getattr(ctx, "command", None), "qualified_name", None))


def interaction_privee(interaction: Any) -> bool:
    """Même décision depuis l'interaction (avant que la commande ait répondu)."""
    command = getattr(interaction, "command", None)
    source = getattr(getattr(command, "callback", None), "_sentrix_original_command", None)
    return commande_privee(source or getattr(command, "name", None))


__all__ = ["PRIVATE_SLASH_ACTIONS", "commande_privee", "interaction_privee", "reponse_privee"]
