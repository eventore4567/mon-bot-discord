"""Panneaux de tickets SentriX V3 : bannière visible et actions natives Discord.

Source unique pour l'ouverture, la fermeture et la réouverture. Les décisions
sur les rôles, permissions et transitions de statut restent dans les services
existants ; cette couche ne fait que présenter les données réelles.
"""
from __future__ import annotations

from functools import lru_cache
import io
from typing import Iterable

import discord

BANNER_FILENAME = "sentrix-ticket-cover-v3.png"


def _font(size: int, bold: bool = False):
    """Police standard disponible sur la plupart des images Linux Railway."""
    from PIL import ImageFont
    names = (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
    ) if bold else (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    )
    for path in names:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


@lru_cache(maxsize=1)
def banner_bytes() -> bytes:
    """Bannière originale 1200 × 172 : sobre, contrastée, pas de GIF ni d'URL morte."""
    from PIL import Image, ImageDraw

    width, height = 1200, 172
    picture = Image.new("RGB", (width, height))
    pixels = picture.load()
    for y in range(height):
        for x in range(width):
            glow = max(0.0, 1.0 - (((x - 930) / 700.0) ** 2 + ((y + 35) / 280.0) ** 2))
            pixels[x, y] = (
                int(11 + glow * 10),
                int(17 + glow * 21),
                int(28 + glow * 44),
            )

    paint = ImageDraw.Draw(picture)
    for x in (830, 920, 1010, 1100):
        paint.line(((x, 0), (x - 90, height)), fill=(26, 47, 71), width=2)
    paint.rounded_rectangle((40, 36, 128, 124), radius=21,
                            fill=(35, 78, 121), outline=(71, 138, 205), width=2)
    # Symbole de dossier stylisé, sans aucune police emoji non disponible.
    paint.rounded_rectangle((61, 65, 108, 97), radius=5,
                            fill=(201, 226, 250))
    paint.rounded_rectangle((61, 59, 84, 73), radius=4,
                            fill=(201, 226, 250))
    paint.line(((64, 80), (105, 80)), fill=(80, 137, 190), width=3)
    paint.text((162, 43), "SENTRIX", font=_font(36, True), fill=(245, 250, 255))
    paint.text((166, 101), "TICKETS  /  SUPPORT", font=_font(16, True),
               fill=(133, 195, 246))
    paint.rounded_rectangle((1146, 42, 1156, 129), radius=5, fill=(78, 157, 226))
    output = io.BytesIO()
    picture.save(output, format="PNG", optimize=True)
    return output.getvalue()


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
    ) -> None:
        super().__init__(timeout=None)
        self._ticket_banner = True
        container = discord.ui.Container()
        cover = discord.ui.MediaGallery()
        cover.add_item(media=f"attachment://{BANNER_FILENAME}")
        container.add_item(cover)

        # Un état lisible au lieu du surtitre technique en majuscules (22/10/2026).
        pastille = {"ouvert": "🟢 Ouvert", "fermé": "🔒 Fermé", "ferme": "🔒 Fermé",
                    "pris en charge": "🟡 Pris en charge", "en attente": "⏳ En attente",
                    "non effectué": "⚠️ Non effectué", "rouvert": "🔓 Rouvert", "supprimé": "🗑️ Supprimé"}.get(
            str(status or "").casefold(), f"🎫 {str(status or '').capitalize()}")
        intro = f"-# 🎫 Support · {pastille}\n## {_safe(title, 180)}"
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
                "**📄 Transcription du ticket**\n"
                "-# Archive TXT du salon avant fermeture. Accessible au staff."
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
                emoji="🔗",
                url=navigation_url,
            ))
            container.add_item(row)

        container.add_item(discord.ui.TextDisplay("-# SentriX · Gestion des tickets"))
        self.add_item(container)

    def fichiers(self) -> list[discord.File]:
        return [discord.File(io.BytesIO(banner_bytes()), filename=BANNER_FILENAME)]


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
            ("📋 Votre ticket",
             f"**Salon :** `#{safe_channel}`\n"
             f"**Catégorie :** {safe_type}\n"
             "**État :** en attente de prise en charge"),
            ("💬 Prochaine étape",
             "Ouvrez le salon pour expliquer votre demande. "
             "Le staff pourra prendre en charge le ticket et le fermer avec un motif."),
        ),
        navigation_url=link,
        navigation_label="Ouvrir mon ticket",
    )


def _emoji_categorie(ticket_type: str) -> str:
    try:
        from cogs.tickets import emoji_de_categorie
    except Exception:  # noqa: BLE001
        return "🎫"
    return emoji_de_categorie(ticket_type, None)


def opening_card(*, ticket_number: int, ticket_type: str, opener: discord.abc.User,
                 description: str, staff_role: discord.Role | None = None,
                 answers: Iterable[tuple[str, str]] = ()) -> TicketCardV3:
    summary = [
        f"**Demandeur :** {opener.mention}",
        f"**Catégorie :** {_safe(ticket_type, 120)}",
        f"**Ouverture :** <t:{int(discord.utils.utcnow().timestamp())}:F>",
    ]
    if staff_role:
        summary.append(f"**Équipe notifiée :** {staff_role.mention}")
    sections = [("📋 Dossier", "\n".join(summary))]
    questions = [
        f"**{discord.utils.escape_markdown(_safe(key, 70))}**\n"
        f"{discord.utils.escape_mentions(discord.utils.escape_markdown(_safe(value, 380)))}"
        for key, value in answers if str(value or "").strip()
    ]
    if questions:
        sections.append(("📝 Réponses au formulaire", "\n\n".join(questions)[:1450]))
    sections.append(("💬 Assistance", "Expliquez votre demande dans ce salon. "
                     "Un membre du staff peut la prendre en charge, puis fermer "
                     "le ticket avec une raison."))
    return TicketCardV3(
        title=f"{_emoji_categorie(ticket_type)} Ticket #{int(ticket_number)} · {_safe(ticket_type, 70)}",
        description=_safe(description, 430),
        sections=sections, avatar_url=str(opener.display_avatar.url),
    )


def closed_card(*, ticket_id: int, opener_id: int, closer: discord.abc.User,
                reason: str, duration: str | None, transcript_filename: str | None,
                avatar_url: str | None = None, claimed_by_id: int | None = None,
                closed_at: int | None = None) -> TicketCardV3:
    values = [
        f"**Créé par :** <@{int(opener_id)}>",
        f"**Pris en charge par :** <@{int(claimed_by_id)}>" if claimed_by_id else "**Prise en charge :** Non attribuée",
        f"**Fermé par :** {closer.mention}",
        f"**Durée :** {duration or 'Indisponible'}",
        f"**Fermeture :** <t:{int(closed_at or discord.utils.utcnow().timestamp())}:F>",
    ]
    reason_display = discord.utils.escape_mentions(
        discord.utils.escape_markdown(_safe(reason, 650))
    )
    return TicketCardV3(
        title=f"Ticket #{int(ticket_id)} · Fermé",
        description="Le ticket est archivé. Le salon est masqué au demandeur, "
                    "mais conservé pour le staff.",
        status="fermé",
        avatar_url=avatar_url,
        sections=(
            ("📋 Résumé de clôture", "\n".join(values)),
            ("📝 Raison de fermeture", reason_display),
            ("⚙️ Suite du dossier", "Le staff peut rouvrir le salon ou le supprimer "
                                     "définitivement. La suppression demande confirmation."),
        ),
        transcript_filename=transcript_filename,
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
        description="La fermeture est enregistrée. Le membre ne peut plus "
                    "consulter le salon, mais le staff conserve son historique.",
        sections=(
            ("📋 Détails de fermeture",
             f"**Salon :** `#{discord.utils.escape_markdown(_safe(channel_name, 72))}`\n"
             f"**Fermé par :** {closer.mention}\n"
             f"**Heure :** <t:{int(closed_at or discord.utils.utcnow().timestamp())}:F>\n"
             f"**Durée :** {duration or 'Indisponible'}"),
            ("📝 Motif enregistré", _safe_reason(reason)),
            ("🔓 Actions disponibles",
             "Le staff peut **rouvrir** le ticket ou le **supprimer** depuis "
             "les boutons du panneau de clôture."),
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
            ("🗑️ Suppression effectuée",
             f"**Ancien salon :** `#{discord.utils.escape_markdown(_safe(channel_name, 70))}`\n"
             f"**Supprimé par :** {deleted_by.mention}\n"
             f"**Heure :** <t:{stamp}:F>"),
            ("📝 Motif", _safe_reason(reason)),
            ("📁 Historique",
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
            ("⚠️ Aucune modification",
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
            ("🔓 Réouverture", f"**Réouvert par :** {by.mention}\n"
                              f"**Date :** <t:{int(discord.utils.utcnow().timestamp())}:F>"),
            ("💬 Prise en charge", "Le ticket est de nouveau actif. "
                                  "Le staff peut reprendre la conversation puis le fermer."),
        ),
        avatar_url=str(by.display_avatar.url),
    )
