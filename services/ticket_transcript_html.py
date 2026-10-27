"""Transcriptions HTML autonomes et messages privés de fermeture des tickets.

Le rendu se construit depuis le texte déjà récupéré par le système de tickets.
Aucun second accès à l'historique Discord n'est nécessaire.
Toutes les données des membres sont échappées avant insertion dans le HTML.
"""
from __future__ import annotations

from datetime import datetime, timezone
from html import escape
import io
import re
from urllib.parse import urlsplit

import discord


_MESSAGE = re.compile(
    r"^\[(?P<date>\d{4}-\d{2}-\d{2} \d{2}:\d{2})\] "
    r"(?P<author>.+?) \((?P<id>\d+)\):(?: ?(?P<content>.*))?$"
)
_ATTACHMENT = re.compile(r"^\s+\[Pièce jointe\] (?P<url>\S+)")
_SAFE_FILENAME = re.compile(r"[^A-Za-z0-9_-]+")
_COLORS = ("#5865f2", "#3ba7a0", "#d58b52", "#9a7bdb", "#5b9dd6", "#c07396")


def parse_transcript(text: str) -> list[dict]:
    """Reconstruit les messages du TXT historique, sans interpréter leur contenu."""
    messages: list[dict] = []
    for line in str(text or "").splitlines():
        match = _MESSAGE.match(line)
        if match:
            messages.append({
                "date": match.group("date"),
                "author": match.group("author"),
                "id": match.group("id"),
                "content": [match.group("content") or ""],
                "attachments": [],
            })
            continue
        attachment = _ATTACHMENT.match(line)
        if attachment and messages:
            messages[-1]["attachments"].append(attachment.group("url"))
        elif messages:
            messages[-1]["content"].append(line)
    return messages


def _stamp(value: int | float | None) -> str:
    if not value:
        return "Non renseignée"
    try:
        return datetime.fromtimestamp(int(value), timezone.utc).strftime("%d/%m/%Y à %H:%M UTC")
    except (ValueError, TypeError, OverflowError, OSError):
        return "Non renseignée"


def _duration(created: int | None, closed: int | None) -> str:
    if not created or not closed:
        return "Non disponible"
    try:
        seconds = max(0, int(closed) - int(created))
    except (TypeError, ValueError):
        return "Non disponible"
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes = remainder // 60
    return " ".join(
        part for part in (f"{days} j" if days else "", f"{hours} h" if hours else "", f"{minutes} min")
        if part
    ) or "Moins d'une minute"


def _attachment(url: str) -> str:
    """Autorise les liens HTTPS, jamais du code HTML ou un protocole exécutable."""
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.netloc or parts.username or parts.password:
        return '<div class="attachment">Pièce jointe indisponible</div>'
    href = escape(url, quote=True)
    filename = escape(parts.path.rsplit("/", 1)[-1] or "Ouvrir la pièce jointe")
    return (
        '<a class="attachment" href="' + href
        + '" target="_blank" rel="noopener noreferrer">Pièce jointe · ' + filename + "</a>"
    )


def render_transcript_html(
    transcript_text: str,
    *,
    guild_name: str,
    ticket_label: str,
    subject: str = "",
    created_at: int | None = None,
    closed_at: int | None = None,
    closed_by: str = "",
    close_reason: str = "",
) -> str:
    """Page HTML locale, lisible sans serveur web ni scripts distants."""
    messages = parse_transcript(transcript_text)
    heading = escape(ticket_label or "Ticket", quote=True)
    guild = escape(guild_name or "Serveur Discord", quote=True)
    topic = escape(subject or "Assistance", quote=True)
    closer = escape(closed_by or "Non renseigné", quote=True)
    reason = escape(close_reason or "Non précisée", quote=True)
    items = []
    for message in messages:
        author = escape(message["author"], quote=True)
        user_id = escape(message["id"], quote=True)
        timestamp = escape(message["date"] + " UTC", quote=True)
        initials = escape((message["author"].strip()[:1] or "?").upper(), quote=True)
        color = _COLORS[sum(ord(ch) for ch in message["id"]) % len(_COLORS)]
        body = escape("\n".join(message["content"]), quote=True).replace("\n", "<br>")
        if not body.strip():
            body = '<span class="muted">Message sans texte</span>'
        attachments = "".join(_attachment(url) for url in message["attachments"])
        items.append(
            '<article class="message"><div class="avatar" style="background:' + color + '">'
            + initials + '</div><div class="message-main">'
            + '<div class="message-heading"><strong>' + author
            + '</strong><span class="user-id">ID ' + user_id
            + '</span><time>' + timestamp + '</time></div>'
            + '<div class="message-text">' + body + '</div>'
            + attachments + '</div></article>'
        )
    if not items:
        items.append('<div class="empty">Aucun message disponible dans la transcription.</div>')
    # Le fichier est autonome ; la politique de sécurité bloque scripts et contenus actifs.
    style = """
    :root{color-scheme:dark;--bg:#202127;--surface:#292b32;--tile:#1c1e23;
    --stroke:#3b3e46;--text:#f0f1f4;--muted:#a6aab6;--accent:#8795ff}
    *{box-sizing:border-box}html{font-family:Inter,system-ui,-apple-system,"Segoe UI",sans-serif}
    body{background:var(--bg);color:var(--text);margin:0;font-size:15px;line-height:1.5}
    .header{background:#181a20;border-bottom:1px solid var(--stroke);padding:30px max(22px,calc((100% - 1020px)/2))}
    .brand{display:flex;align-items:center;gap:17px}.logo{width:58px;height:58px;border-radius:18px;
    background:linear-gradient(140deg,#5865f2,#293584);display:grid;place-items:center;
    font-size:29px;font-weight:800}.header h1{font-size:24px;margin:0;overflow-wrap:anywhere}
    .subtitle{color:var(--muted);font-size:13px;margin-top:3px}
    main{max-width:1060px;margin:auto;padding:20px 20px 60px}
    .summary{display:grid;grid-template-columns:2fr repeat(3,minmax(0,1fr));gap:12px;margin-bottom:22px}
    .stat{padding:13px 16px;border-radius:10px;background:var(--tile);border:1px solid var(--stroke);
    min-width:0;overflow-wrap:anywhere}.label{display:block;text-transform:uppercase;letter-spacing:.07em;
    font-size:11px;color:var(--muted);margin-bottom:5px}.value{font-weight:650;font-size:13px}
    .details{border:1px solid var(--stroke);background:var(--surface);border-radius:10px;
    padding:15px 18px;margin-bottom:16px;font-size:13px}
    .details strong{color:#e6e8ff}.details p{margin:4px 0}
    .message{display:flex;gap:15px;padding:15px 14px;border-radius:8px;border-bottom:1px solid #34363f;
    overflow-wrap:anywhere}.message:hover{background:#30323a}
    .avatar{width:42px;height:42px;flex:0 0 42px;border-radius:50%;display:grid;place-items:center;
    font-weight:700;color:#fff;font-size:20px}.message-main{min-width:0;flex:1}
    .message-heading{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap}
    .message-heading strong{font-size:15px}.user-id,.message-heading time{font-size:11px;color:var(--muted)}
    .message-text{white-space:normal;overflow-wrap:anywhere;margin-top:3px}
    .attachment{display:block;width:fit-content;margin-top:9px;border:1px solid #5964aa;
    padding:8px 13px;border-radius:8px;background:#292f47;color:#b8c4ff;
    text-decoration:none;font-size:13px;max-width:100%;overflow-wrap:anywhere}
    .attachment:hover{background:#353d5f}.muted,.empty{color:var(--muted)}
    .empty{padding:38px;text-align:center}.footer{margin-top:30px;border-top:1px solid var(--stroke);
    padding-top:16px;color:var(--muted);font-size:12px}
    @media(max-width:720px){.header{padding:22px}.summary{grid-template-columns:1fr 1fr}
    .message{padding:12px 2px;gap:10px}.avatar{width:36px;height:36px;flex-basis:36px}
    .header h1{font-size:19px}}@media(max-width:440px){.summary{grid-template-columns:1fr}}
    """
    return (
        '<!doctype html><html lang="fr"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<meta http-equiv="Content-Security-Policy" content="default-src &#39;none&#39;; '
        'style-src &#39;unsafe-inline&#39;; base-uri &#39;none&#39;; '
        'form-action &#39;none&#39;">'
        '<title>' + heading + ' · Transcription SentriX</title>'
        '<style>' + style + '</style></head><body>'
        '<header class="header"><div class="brand"><div class="logo">S</div><div>'
        '<h1>' + heading + '</h1><div class="subtitle">' + guild
        + ' · Transcription du ticket · Heures affichées en UTC</div></div></div></header>'
        '<main><section class="summary">'
        '<div class="stat"><span class="label">Sujet</span><span class="value">' + topic + '</span></div>'
        '<div class="stat"><span class="label">Créé le</span><span class="value">' + escape(_stamp(created_at)) + '</span></div>'
        '<div class="stat"><span class="label">Fermé le</span><span class="value">' + escape(_stamp(closed_at)) + '</span></div>'
        '<div class="stat"><span class="label">Messages</span><span class="value">' + str(len(messages)) + '</span></div>'
        '</section><section class="details"><p><strong>Fermé par :</strong> ' + closer + '</p>'
        '<p><strong>Durée :</strong> ' + escape(_duration(created_at, closed_at)) + '</p>'
        '<p><strong>Raison :</strong> ' + reason + '</p></section>'
        '<section class="timeline" aria-label="Messages du ticket">' + "".join(items) + '</section>'
        '<footer class="footer">SentriX · Archive HTML locale du ticket. '
        'Ce fichier contient des échanges privés : ne le partagez pas publiquement.</footer>'
        '</main></body></html>'
    )


def transcript_html_file(
    channel: discord.TextChannel,
    text: str,
    *,
    ticket_id: int | None = None,
    guild_name: str = "",
    subject: str = "",
    created_at: int | None = None,
    closed_at: int | None = None,
    closed_by: str = "",
    close_reason: str = "",
) -> discord.File:
    safe_name = _SAFE_FILENAME.sub("-", channel.name)[:70] or "ticket"
    label = f"TICKET-{int(ticket_id):04d}" if ticket_id is not None else safe_name
    html = render_transcript_html(
        text, guild_name=guild_name or channel.guild.name,
        ticket_label=label, subject=subject or channel.name,
        created_at=created_at, closed_at=closed_at,
        closed_by=closed_by, close_reason=close_reason,
    )
    # Évite les pièces jointes refusées par Discord pour les tickets très longs.
    data = html.encode("utf-8")
    if len(data) > 7_000_000:
        html = render_transcript_html(
            "Transcription trop volumineuse pour être jointe en intégralité.",
            guild_name=guild_name or channel.guild.name,
            ticket_label=label, subject=subject or channel.name,
            created_at=created_at, closed_at=closed_at,
            closed_by=closed_by,
            close_reason="Archive complète disponible via les journaux du serveur.",
        )
        data = html.encode("utf-8")
    return discord.File(io.BytesIO(data), filename=f"{label}.html")


async def resolve_ticket_recipient(
    bot: discord.Client, guild: discord.Guild, user_id: int
) -> tuple[discord.Member | None, discord.abc.User | None]:
    """Retrouve le destinataire même si le membre n'est pas en cache.

    La réponse est (membre encore présent dans le serveur, utilisateur à contacter).
    Ne jamais employer un discord.User comme cible de permissions de salon.
    """
    user_id = int(user_id)
    member = guild.get_member(user_id)
    if member is None:
        try:
            member = await guild.fetch_member(user_id)
        except (discord.Forbidden, discord.NotFound, discord.HTTPException):
            member = None

    if member is not None:
        return member, member

    user = bot.get_user(user_id)
    if user is None:
        try:
            user = await bot.fetch_user(user_id)
        except (discord.Forbidden, discord.NotFound, discord.HTTPException):
            user = None
    return None, user


async def send_closure_dm(
    owner: discord.abc.User,
    guild: discord.Guild,
    channel: discord.TextChannel,
    transcript_text: str,
    *,
    ticket_id: int,
    created_at: int | None,
    closed_at: int | None,
    closer: discord.abc.User | str,
    reason: str,
    subject: str = "",
) -> None:
    """Un seul MP : fiche de fermeture + fichier HTML navigable en pièce jointe."""
    closer_name = getattr(closer, "display_name", None) or str(closer)
    count = len(parse_transcript(transcript_text))
    label = f"TICKET-{int(ticket_id):04d}"
    e = discord.Embed(
        title=f"Transcription — {label}",
        description=(
            f"Votre ticket sur **{discord.utils.escape_markdown(guild.name)}** a été fermé.\n\n"
            f"**Sujet :** {discord.utils.escape_markdown((subject or channel.name)[:240])}\n"
            "Merci d'avoir contacté le support."
        ),
        color=discord.Color(0x5865F2),
    )
    e.add_field(name="Durée", value=_duration(created_at, closed_at), inline=False)
    e.add_field(name="Fermé par", value=str(closer_name)[:256], inline=True)
    e.add_field(name="Messages", value=str(count), inline=True)
    e.add_field(
        name="Transcription",
        value=f"Ouvrez le fichier **{label}.html** ci-joint dans votre navigateur pour consulter la conversation.",
        inline=False,
    )
    e.set_footer(text=f"SentriX · {guild.name}"[:2048])
    await owner.send(
        embed=e,
        file=transcript_html_file(
            channel, transcript_text, ticket_id=ticket_id, guild_name=guild.name,
            subject=subject, created_at=created_at, closed_at=closed_at,
            closed_by=str(closer_name), close_reason=reason,
        ),
        allowed_mentions=discord.AllowedMentions.none(),
    )
