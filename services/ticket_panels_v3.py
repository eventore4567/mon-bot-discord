"""Panneaux de tickets SentriX V3 : bannière visible et actions natives Discord.

Source unique pour l'ouverture, la fermeture et la réouverture. Les décisions
sur les rôles, permissions et transitions de statut restent dans les services
existants ; cette couche ne fait que présenter les données réelles.
"""
from __future__ import annotations

from typing import Iterable

import discord

from utils import sentrix_emojis
from utils.premium_log_banners import BANNER_FILENAME, get_premium_log_banner


def banner_bytes() -> bytes:
    """Unique bandeau neutre translucide partagé avec SentriX Core et les logs."""
    return get_premium_log_banner().read_bytes()


def _icon(name: str, label: str) -> str:
    """Icône d'application SentriX si disponible, jamais d'emoji Unicode de repli."""
    return sentrix_emojis.titre(name, label)



def _safe(value: object, length: int = 750) -> str:
    # Escape only untrusted user-entered answers/reasons; Discord mentions
    # intentionally authored by the code must remain clickable.
    text = str(value or "").strip()
    if len(text) > length:
        text = text[:length - 1] + "…"
    return text or "Non renseigné"


class TicketCardV3(discord.ui.LayoutView):
    """Un panneau = une seule bannière, trois sections maximum, puis vrais boutons."""

    def __init__(
        self, *,
        title: str,
        description: str,
        sections: Iterable[tuple[str, str]],
        avatar_url: str | None = None,
        status: str = "ouvert",
        transcript_filename: str | None = None,
        navigation_url: str | None = None,
        navigation_label: str = "Ouvrir mon ticket",
        language: str = "fr",
    ) -> None:
        super().__init__(timeout=None)
        container = discord.ui.Container()
        cover = discord.ui.MediaGallery()
        cover.add_item(media=f"attachment://{BANNER_FILENAME}")
        container.add_item(cover)

        # Aucun emoji Unicode ni grande image de couverture : un seul bandeau
        # transparent, les mêmes icônes d'application que les autres panneaux.
        state = str(status or "ouvert").casefold()
        status_text = {
            "ouvert": "Ouvert", "fermé": "Fermé", "ferme": "Fermé",
            "pris en charge": "Pris en charge", "en attente": "En attente",
            "non effectué": "Non effectué", "rouvert": "Rouvert",
            "supprimé": "Supprimé",
        }.get(state, str(status or "Ouvert").capitalize())
        if language == "en":
            status_text = {
                "ouvert": "Open", "fermé": "Closed", "ferme": "Closed",
                "pris en charge": "Claimed", "en attente": "Pending",
                "non effectué": "Not completed", "rouvert": "Reopened",
                "supprimé": "Deleted",
            }.get(state, str(status or "Open").capitalize())
        state_icon = {
            "ouvert": "ticket_open", "fermé": "lock", "ferme": "lock",
            "rouvert": "unlock", "supprimé": "trash",
            "non effectué": "warning",
        }.get(state, "ticket")
        intro = (
            f"-# {_icon(state_icon, 'Support')} · {status_text}\n"
            f"## {_safe(title, 180)}"
        )
        if description:
            intro += "\n" + _safe(description, 550)
        if avatar_url:
            try:
                container.add_item(discord.ui.Section(
                    discord.ui.TextDisplay(intro),
                    accessory=discord.ui.Thumbnail(str(avatar_url)),
                ))
            except (TypeError, ValueError):
                container.add_item(discord.ui.TextDisplay(intro))
        else:
            container.add_item(discord.ui.TextDisplay(intro))

        for name, body in list(sections)[:4]:
            clean = _safe(body, 1500)
            container.add_item(discord.ui.Separator())
            container.add_item(discord.ui.TextDisplay(
                f"**{_safe(name, 100)}**\n{clean}"
            ))

        if transcript_filename:
            container.add_item(discord.ui.Separator())
            container.add_item(discord.ui.TextDisplay(
                (f"**{_icon('file', 'Ticket transcript')}**\n"
                 "-# HTML archive of the channel. Staff access only."
                 if language == "en" else
                 f"**{_icon('file', 'Transcription du ticket')}**\n"
                 "-# Archive HTML du salon : ouvrez le fichier joint dans un navigateur. Accessible au staff.")
            ))
            component = getattr(discord.ui, "File", None)
            if component:
                container.add_item(component(media=f"attachment://{transcript_filename}"))

        if navigation_url:
            container.add_item(discord.ui.Separator())
            # Le bouton lien est natif et fonctionne sans callback, même si
            # le message privé/éphémère a été affiché avant le cache Discord.
            row = discord.ui.ActionRow()
            row.add_item(discord.ui.Button(
                style=discord.ButtonStyle.link,
                label=navigation_label[:80],
                url=navigation_url,
            ))
            container.add_item(row)

        self.add_item(container)

    def fichiers(self) -> list[discord.File]:
        return [discord.File(str(get_premium_log_banner()), filename=BANNER_FILENAME)]


def ticket_created_confirmation(
    *, ticket_number: int, ticket_type: str,
    guild_id: int, channel_id: int, channel_name: str,
) -> TicketCardV3:
    """Accusé de création court et navigable, sans mention « # inconnu ».

    Les mentions <#channel> ne sont pas toujours résolues dans les réponses
    éphémères, surtout après modification des permissions ou suppression d'un
    ancien ticket. Le nom lisible et l'URL Discord restent utilisables.
    """
    safe_channel = discord.utils.escape_markdown(_safe(channel_name, 90))
    safe_type = discord.utils.escape_mentions(
        discord.utils.escape_markdown(_safe(ticket_type, 90))
    )
    link = f"https://discord.com/channels/{int(guild_id)}/{int(channel_id)}"
    return TicketCardV3(
        title=f"Ticket #{int(ticket_number)} créé",
        description="Votre demande a bien été enregistrée. "
                    "Le salon privé est accessible avec le bouton ci-dessous.",
        status="ouvert",
        sections=(
            ("Votre ticket",
             f"**Salon :** `#{safe_channel}`\n"
             f"**Catégorie :** {safe_type}\n"
             "**État :** en attente de prise en charge"),
            ("Prochaine étape",
             "Ouvrez le salon pour expliquer votre demande. "
             "Le staff pourra prendre en charge le ticket et le fermer avec un motif."),
        ),
        navigation_url=link,
        navigation_label="Ouvrir mon ticket",
    )


def opening_card(*, ticket_number: int, ticket_type: str, opener: discord.abc.User,
                 description: str, staff_role: discord.Role | None = None,
                 answers: Iterable[tuple[str, str]] = ()) -> TicketCardV3:
    # Minimalisme (Jayden, 28/10/2026 : « les embeds tickets sont immenses ») :
    # une ligne d'informations, les réponses du formulaire, rien d'autre.
    ligne = (
        f"{opener.mention} · <t:{int(discord.utils.utcnow().timestamp())}:R>"
        + (f" · {staff_role.mention}" if staff_role else "")
    )
    sections = [("Demande", ligne)]
    questions = [
        f"**{discord.utils.escape_markdown(_safe(key, 70))}**\n"
        f"{discord.utils.escape_mentions(discord.utils.escape_markdown(_safe(value, 380)))}"
        for key, value in answers if str(value or "").strip()
    ]
    if questions:
        sections.append(("Formulaire", "\n".join(questions)[:1450]))
    return TicketCardV3(
        title=_icon("ticket", f"Ticket #{int(ticket_number)} · {_safe(ticket_type, 70)}"),
        description=_safe(description, 300),
        sections=sections, avatar_url=str(opener.display_avatar.url),
    )


def closed_card(*, ticket_id: int, opener_id: int, closer: discord.abc.User,
                reason: str, duration: str | None, transcript_filename: str | None,
                avatar_url: str | None = None, claimed_by_id: int | None = None,
                closed_at: int | None = None, language: str = "fr") -> TicketCardV3:
    english = language == "en"
    prise = (f" · claimed by <@{int(claimed_by_id)}>" if english else f" · pris par <@{int(claimed_by_id)}>") if claimed_by_id else ""
    ligne = (
        f"<@{int(opener_id)}>{prise} · {'closed by' if english else 'fermé par'} {closer.mention}"
        f" · {duration or ('duration unavailable' if english else 'durée inconnue')} · <t:{int(closed_at or discord.utils.utcnow().timestamp())}:F>"
    )
    reason_display = discord.utils.escape_mentions(
        discord.utils.escape_markdown(_safe(reason, 650))
    )
    return TicketCardV3(
        title=f"Ticket #{int(ticket_id)} · {'Closed' if english else 'Fermé'}",
        description=("Hidden from the requester; kept for staff." if english
                     else "Masqué au demandeur, conservé pour le staff."),
        status="fermé",
        avatar_url=avatar_url,
        sections=(
            ("Closure" if english else "Clôture", ligne),
            ("Reason" if english else "Raison", reason_display),
        ),
        transcript_filename=transcript_filename,
        language=language,
    )



def _safe_reason(reason: str | None, limit: int = 480) -> str:
    """Le motif est saisi par un utilisateur : pas de mentions ni de faux champs."""
    return discord.utils.escape_mentions(
        discord.utils.escape_markdown(_safe(reason or "Non précisé", limit))
    )


def ticket_closed_confirmation(
    *, ticket_id: int, closer: discord.abc.User,
    reason: str, duration: str | None, guild_id: int, channel_id: int,
    channel_name: str, closed_at: int | None = None,
) -> TicketCardV3:
    """Retour du formulaire Fermer : informatif, privé et jamais « en attente »."""
    return TicketCardV3(
        title=f"Ticket #{int(ticket_id)} fermé",
        status="fermé",
        description=f"Durée : {duration or 'inconnue'} · <t:{int(closed_at or discord.utils.utcnow().timestamp())}:F>",
        sections=(
            ("Raison", _safe_reason(reason)),
        ),
        navigation_url=f"https://discord.com/channels/{int(guild_id)}/{int(channel_id)}",
        navigation_label="Voir le ticket fermé",
    )


def ticket_deleted_confirmation(
    *, ticket_id: int, deleted_by: discord.abc.User,
    reason: str, channel_name: str,
    event_time: int | None = None,
) -> TicketCardV3:
    """Accusé privé après suppression ; aucun bouton vers le salon disparu."""
    stamp = int(event_time or discord.utils.utcnow().timestamp())
    return TicketCardV3(
        title=f"Ticket #{int(ticket_id)} supprimé",
        status="supprimé",
        description="Le salon a été supprimé définitivement de Discord.",
        sections=(
            ("Suppression effectuée",
             f"**Ancien salon :** `#{discord.utils.escape_markdown(_safe(channel_name, 70))}`\n"
             f"**Supprimé par :** {deleted_by.mention}\n"
             f"**Heure :** <t:{stamp}:F>"),
            ("Motif", _safe_reason(reason)),
            ("Historique",
             "Les logs et transcripts déjà archivés restent accessibles "
             "dans le salon de suivi du staff, s'ils ont été enregistrés."),
        ),
    )


def ticket_action_failure(
    *, ticket_id: int, action: str, explanation: str,
) -> TicketCardV3:
    """Même vocabulaire visuel pour un refus, sans simuler une action réussie."""
    return TicketCardV3(
        title=f"Ticket #{int(ticket_id)} · {str(action)[:70]}",
        status="non effectué",
        description=discord.utils.escape_mentions(
            discord.utils.escape_markdown(_safe(explanation, 350))
        ),
        sections=(
            ("Aucune modification",
             "Le ticket n'a pas été supprimé. Vérifiez les permissions "
             "ou son état, puis réessayez si nécessaire."),
        ),
    )


def reopened_card(*, ticket_id: int, by: discord.abc.User) -> TicketCardV3:
    return TicketCardV3(
        title=f"Ticket #{int(ticket_id)} · Rouvert",
        description="Le membre peut de nouveau consulter le salon et répondre.",
        status="rouvert",
        sections=(
            ("Réouverture", f"**Réouvert par :** {by.mention}\n"
                              f"**Date :** <t:{int(discord.utils.utcnow().timestamp())}:F>"),
            ("Prise en charge", "Le ticket est de nouveau actif. "
                                  "Le staff peut reprendre la conversation puis le fermer."),
        ),
        avatar_url=str(by.display_avatar.url),
    )
