"""Compact SentriX moderation acknowledgements, built with native Discord V2.

The full numbered sanction dossier stays in the configured logs. The response
at the command location is a concise card (not a second 800px report), with
clickable member identity, a real reason, and the persistent History action.
"""
from __future__ import annotations

import re

import discord


_ACTIONS: dict[str, tuple[str, int]] = {
    "ban": ("🔨 Bannissement effectué", 0xAB6B6B),
    "tempban": ("⏳ Bannissement temporaire effectué", 0xAB6B6B),
    "hackban": ("🔨 Bannissement par identifiant", 0xAB6B6B),
    "kick": ("🚪 Expulsion effectuée", 0x6D86AD),
    "mute": ("🔇 Timeout appliqué", 0xB58A60),
    "unmute": ("🔊 Timeout retiré", 0x6D9F89),
    "warn": ("⚠️ Avertissement enregistré", 0xB58A60),
    "unban": ("🔓 Bannissement levé", 0x6D9F89),
}

_SNOWFLAKE = re.compile(r"^[0-9]{17,22}$")


def _mark_safe(content: object, *, max_length: int = 360) -> str:
    """Escape user-supplied Markdown and avoid mass-mention text rendering."""
    result = discord.utils.escape_markdown(str(content or "Aucune raison fournie")[:max_length])
    return result.replace("@everyone", "@\u200beveryone").replace("@here", "@\u200bhere")


def _valid_id(value: object) -> bool:
    return bool(_SNOWFLAKE.fullmatch(str(value or "")))


def build_sanction_confirmation(
    *, action: str, target: discord.abc.User,
    actor: discord.abc.User | None = None,
    guild_id: int | None = None,
    reason: str = "",
    case_number: int | None = None,
    suffix: str = "",
    duration: str | None = None,
) -> discord.ui.LayoutView:
    """Return a view even when case persistence was unavailable.

    A failed DB write must NEVER turn a real Discord sanction into a false
    error. The response says so and still links to any available history.
    """
    title, _colour = _ACTIONS.get(action, ("🛡️ Action de modération effectuée", 0x76849B))
    view = discord.ui.LayoutView(timeout=None)
    # Pas de liseré coloré sur le flanc ; la bande fine des autres commandes en tête.
    card = discord.ui.Container()
    from utils import sentrix_panels as _panels

    if _panels.poser_bandeau(card, "moderation"):
        # Le fichier de la galerie DOIT partir avec le message : panels.envoyer
        # joint ce que rend fichiers() (sinon Discord refuse tout le message).
        view.fichiers = lambda: _panels.pieces_jointes_de_famille("moderation")
    target_id = getattr(target, "id", None)
    mention = (
        f"<@{int(target_id)}>" if target_id is not None
        else str(getattr(target, "mention", target))
    )
    display_name = _mark_safe(
        getattr(target, "display_name", None)
        or getattr(target, "global_name", None)
        or getattr(target, "name", None)
        or "Compte Discord", max_length=60,
    )
    id_info = (
        "-# ID : " + chr(96) + str(target_id) + chr(96)
        if target_id is not None else "-# Compte Discord"
    )
    top = f"**{title}**\n{display_name} · {mention}\n{id_info}"
    avatar_url = getattr(getattr(target, "display_avatar", None), "url", None)
    if avatar_url:
        card.add_item(discord.ui.Section(
            discord.ui.TextDisplay(top),
            accessory=discord.ui.Thumbnail(str(avatar_url)),
        ))
    else:
        card.add_item(discord.ui.TextDisplay(top))
    card.add_item(discord.ui.Separator())
    reason_label = _mark_safe(reason or "Aucune raison fournie", max_length=260)
    extra = []
    if duration:
        extra.append(f"**⏱️ Durée** · {_mark_safe(duration, max_length=70)}")
    if suffix:
        extra.append(f"-# {_mark_safe(suffix, max_length=200)}")
    card.add_item(discord.ui.TextDisplay(
        f"**📝 Motif**\n> {reason_label}"
        + ("\n" + "\n".join(extra) if extra else "")
    ))
    note_parts = []
    if actor is not None and getattr(actor, "id", None):
        note_parts.append(f"Par <@{actor.id}>")
    note_parts.append(
        f"Dossier #{case_number}" if case_number is not None
        else "Dossier non enregistré"
    )
    card.add_item(discord.ui.TextDisplay("-# " + " · ".join(note_parts)))
    if guild_id is not None and _valid_id(guild_id) and _valid_id(target_id):
        from cogs.log_history_center import PremiumLogAction
        card.add_item(discord.ui.ActionRow(
            PremiumLogAction("history", int(guild_id), int(target_id)),
        ))
    view.add_item(card)
    return view


def build_hierarchy_refusal(message: str) -> discord.ui.LayoutView | None:
    """Small, actionable diagnostic; no decorative full-page banner."""
    text = str(message or "").casefold()
    if "ne peut pas sanctionner ce membre" in text:
        heading = "🛑 Action refusée : hiérarchie de SentriX"
        explanation = "Le rôle du membre est égal ou supérieur à celui de SentriX."
        solution = (
            "Dans **Paramètres du serveur → Rôles**, place le rôle **SentriX** "
            "au-dessus du rôle du membre."
        )
    elif "ne peut pas gérer ce rôle" in text:
        heading = "🛑 Rôle inaccessible"
        explanation = "SentriX ne peut pas gérer un rôle égal ou supérieur au sien."
        solution = "Remonte le rôle **SentriX** au-dessus de ce rôle dans les paramètres."
    elif "vous ne pouvez pas sanctionner un membre ayant un rôle supérieur ou égal" in text:
        heading = "🛑 Action refusée : hiérarchie du staff"
        explanation = "Tu ne peux pas modérer un membre dont le rôle est égal ou supérieur au tien."
        solution = "Demande à un responsable disposant d'un rôle plus élevé."
    else:
        return None
    # Conserver une véritable carte SentriX structurée : les refus de hiérarchie
    # doivent être explicites et ne jamais être aplatis en erreur texte.
    from utils import sentrix_panels as panels
    return panels.Panneau(
        titre=heading.replace("🛑 ", "").replace("Action refusée", "Action refusée · Action impossible"),
        sous_titre=explanation,
        sections=(panels.Section("Comment corriger", texte=solution),),
        kind="warning",
        pied="Aucune sanction appliquée · Respect de la hiérarchie Discord",
    )


__all__ = [
    "build_hierarchy_refusal",
    "build_sanction_confirmation",
]
