"""Historique du ticket : données durables, extrait pour le salon de logs staff."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
import io
import logging
import discord

logger = logging.getLogger("bot.tickets.report")
ACTIONS = {
    "ticket_open": "Ouverture", "ticket_claim": "Prise en charge",
    "ticket_unclaim": "Prise en charge libérée", "ticket_transfer": "Transfert",
    "ticket_reopen": "Réouverture", "ticket_member_add": "Membre ajouté",
    "ticket_member_remove": "Membre retiré", "ticket_rename": "Renommage",
    "ticket_note": "Note interne ajoutée", "ticket_bump": "Relance",
    "ticket_rating": "Évaluation", "ticket_autoclose": "Fermeture auto",
    "ticket_delete": "Suppression", "ticket_close": "Fermeture",
}


def val(row, key, default=None):
    try:
        result = row[key]
    except (KeyError, IndexError, TypeError):
        result = getattr(row, key, default)
    return default if result is None else result


def positive(value):
    try:
        n = int(value)
        return n if n > 0 else None
    except (TypeError, ValueError, OverflowError):
        return None


def mention(user_id):
    return f"<@{int(user_id)}>" if user_id else "Non renseigné"


def timestamp(when):
    return f"<t:{int(when)}:F>" if when else "Non renseignée"


def readable(seconds):
    if seconds is None or seconds < 0:
        return None
    if seconds < 60:
        return f"{seconds} s"
    minutes = seconds // 60
    days, minutes = divmod(minutes, 1440)
    hours, minutes = divmod(minutes, 60)
    return (f"{days} j " if days else "") + (f"{hours} h " if hours else "") + f"{minutes} min"


def utcdate(stamp):
    if not stamp:
        return "Non renseignée"
    return datetime.fromtimestamp(stamp, timezone.utc).strftime("%d/%m/%Y %H:%M UTC")


@dataclass(frozen=True)
class ClosureReport:
    ticket_id: int
    owner_id: int
    category: str
    created_at: int | None
    closed_at: int
    closed_by: int
    current_claimant: int | None
    claims: tuple[tuple[int, int | None], ...]
    events: tuple[tuple[str, int | None, int | None], ...]
    reason: str

    @property
    def duration(self):
        return readable(self.closed_at - self.created_at) if self.created_at else None

    @property
    def first_claim_wait(self):
        if not self.claims:
            return "Aucune prise en charge enregistrée"
        if self.created_at is None or self.claims[0][1] is None:
            return "Durée indisponible"
        return readable(self.claims[0][1] - self.created_at) or "Durée indisponible"

    @property
    def handlers(self):
        return tuple(dict.fromkeys(
            [person for person, _ in self.claims]
            + ([self.current_claimant] if self.current_claimant else [])
        ))

    @property
    def handler_names(self):
        people = self.handlers
        if not people:
            return "Aucun membre du staff enregistré"
        return ", ".join(mention(i) for i in people[:7]) + (f" et {len(people)-7} autre(s)" if len(people)>7 else "")

    @property
    def current_handler(self):
        if self.current_claimant:
            return mention(self.current_claimant)
        if self.claims:
            return "Libéré (dernière prise : " + mention(self.claims[-1][0]) + ")"
        return "Non pris en charge"

    @property
    def recent_timeline(self):
        last = self.events[-5:]
        lines = []
        if len(self.events) > len(last):
            lines.append(f"{len(self.events)-len(last)} événement(s) antérieur(s) dans le transcript.")
        for kind, actor, stamp in last:
            lines.append(
                "• " + ACTIONS.get(kind, kind.replace("_", " "))
                + (f" · {mention(actor)}" if actor else "")
                + (f" · <t:{stamp}:f>" if stamp else "")
            )
        return "\n".join(lines)[:1024] or "Historique détaillé indisponible."

    def transcript_text(self, messages):
        claims = "\n".join(
            f"- {utcdate(stamp)} : {mention(actor)} (ID {actor})"
            for actor, stamp in self.claims
        ) or "- Aucune prise en charge enregistrée."
        history = "\n".join(
            f"- {utcdate(stamp)} : {ACTIONS.get(kind, kind)}"
            + (f" par {mention(actor)} (ID {actor})" if actor else "")
            for kind, actor, stamp in self.events
        ) or "- Historique détaillé indisponible."
        return "\n".join((
            "SENTRIX — DOSSIER DU TICKET",
            f"Ticket : #{self.ticket_id}",
            f"Type : {self.category}",
            f"Ouvert par : {mention(self.owner_id)} (ID {self.owner_id})",
            f"Date d'ouverture : {utcdate(self.created_at)}",
            f"Fermé par : {mention(self.closed_by)} (ID {self.closed_by})",
            f"Date de fermeture : {utcdate(self.closed_at)}",
            f"Durée totale : {self.duration or 'Indisponible'}",
            f"Pris en charge à la fermeture : {self.current_handler}",
            f"Équipe ayant pris en charge : {self.handler_names}",
            f"Première prise en charge après : {self.first_claim_wait}",
            f"Motif de fermeture : {self.reason}",
            "", "HISTORIQUE DES PRISES EN CHARGE", claims,
            "", "ÉVÉNEMENTS (sans contenu des notes staff internes)", history,
            "", "MESSAGES DU SALON",
            "Historique accessible au bot lors de la fermeture ; pièces jointes référencées par URL.",
            "------------------------------------------------------------",
            str(messages),
        ))

    def transcript_file(self, messages):
        raw = self.transcript_text(messages).encode("utf-8")
        if len(raw) > 7_000_000:
            half = 3_499_800
            raw = (
                raw[:half].decode("utf-8", "ignore")
                + "\n\n[PARTIE CENTRALE OMISE : limite de taille du fichier Discord]\n\n"
                + raw[-half:].decode("utf-8", "ignore")
            ).encode("utf-8")
        return discord.File(
            io.BytesIO(raw), filename=f"sentrix-ticket-{self.ticket_id}-transcript.txt"
        )


def build_report(ticket, events, *, closed_at, closed_by, reason, legacy_claims=()):
    claims, history = [], []
    for event in events:
        kind = str(val(event, "event", ""))
        actor, stamp = positive(val(event, "actor_id")), positive(val(event, "created_at"))
        if kind in ACTIONS:
            history.append((kind, actor, stamp))
        if kind == "ticket_claim" and actor:
            claims.append((actor, stamp))
    if not claims:
        for row in legacy_claims:
            actor = positive(val(row, "staff_id"))
            if actor:
                stamp = positive(val(row, "claimed_at"))
                claims.append((actor, stamp))
                history.append(("ticket_claim", actor, stamp))
    claims.sort(key=lambda x: x[1] or 0)
    history.sort(key=lambda x: x[2] or 0)
    if not any(kind == "ticket_close" and actor == int(closed_by) and stamp is not None and abs(stamp - int(closed_at)) <= 2 for kind, actor, stamp in history):
        history.append(("ticket_close", positive(closed_by), positive(closed_at)))
    return ClosureReport(
        ticket_id=positive(val(ticket, "id")) or 0,
        owner_id=positive(val(ticket, "user_id")) or 0,
        category=str(val(ticket, "category", "Support"))[:90],
        created_at=positive(val(ticket, "created_at")),
        closed_at=int(closed_at), closed_by=int(closed_by),
        current_claimant=positive(val(ticket, "claimed_by")),
        claims=tuple(claims), events=tuple(history),
        reason=str(reason or "Non précisée").strip()[:1200] or "Non précisée",
    )


async def load_report(bot, guild_id, ticket, *, closed_at, closed_by, reason):
    """Même si l'audit est hors service, ne jamais bloquer une fermeture."""
    ticket_id = positive(val(ticket, "id")) or 0
    rows, legacy = [], []
    try:
        rows = await bot.db.fetchall(
            "SELECT event, actor_id, created_at FROM ticket_events "
            "WHERE guild_id=? AND ticket_id=? ORDER BY created_at, id LIMIT 1000",
            (int(guild_id), ticket_id),
        )
    except Exception:
        logger.warning("Audit ticket #%s indisponible.", ticket_id, exc_info=True)
    if not any(val(row, "event") == "ticket_claim" for row in rows):
        try:
            legacy = await bot.db.fetchall(
                "SELECT staff_id, claimed_at FROM v17_ticket_claim_events "
                "WHERE guild_id=? AND ticket_id=? ORDER BY claimed_at LIMIT 200",
                (int(guild_id), ticket_id),
            )
        except Exception:
            logger.debug("Aucun historique de claims V17 pour ticket #%s.", ticket_id)
    return build_report(
        ticket, rows, closed_at=closed_at, closed_by=closed_by,
        reason=reason, legacy_claims=legacy,
    )


def add_fields(embed, report, *, channel_name, participant_text, reference):
    """Garde aussi un embed de secours correct hors rendu Components V2."""
    fields = (
        ("🎟️ Ticket", f"#{report.ticket_id} · {report.category}", False),
        ("📌 Salon", f"#{channel_name}", False),
        ("👤 Membre concerné", mention(report.owner_id), True),
        ("🔒 Fermé par", mention(report.closed_by), True),
        ("🕒 Ouverture", timestamp(report.created_at), True),
        ("🕒 Fermeture", timestamp(report.closed_at), True),
        ("🙋 Pris en charge", report.current_handler, False),
        ("👥 Équipe ayant pris en charge", report.handler_names, False),
        ("⏱️ Avant première prise en charge", report.first_claim_wait, True),
        ("⏳ Durée totale", report.duration or "Indisponible", True),
        ("📝 Motif", report.reason, False),
        ("🧭 Historique", report.recent_timeline, False),
        ("👥 Participants", participant_text or "Non renseignés", False),
        ("🔖 Référence", chr(96) + reference + chr(96), False),
    )
    for name, value, inline in fields:
        embed.add_field(name=name, value=str(value)[:1024] or "—", inline=inline)
