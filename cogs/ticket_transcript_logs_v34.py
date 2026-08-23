"""SentriX V34 — fermeture de ticket compacte avec transcript HTML.

Le transcript reste complet en pièce jointe, tandis que le journal Discord utilise le
même principe que les autres logs : une carte basse et horizontale, sans avatar ni
séparateurs empilés.
"""
from __future__ import annotations

import html
import io
import logging
import re
import unicodedata
from datetime import datetime, timezone

import discord
from discord.ext import commands

from . import premium_logs_v2
from . import log_rectangle_v25 as v25

logger = logging.getLogger("bot.ticket-transcript-logs-v34")
_INSTALLED = False


def _plain(value: str | None) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-zA-Z0-9]+", " ", text).casefold()
    return re.sub(r"\s+", " ", text).strip()


def _one_line(value: object, limit: int = 220) -> str:
    text = re.sub(r"\s*\n\s*", " · ", str(value or "").strip())
    text = re.sub(r"\s{2,}", " ", text)
    if not text:
        return "Non disponible"
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _field(embed: discord.Embed, *tokens: str) -> str:
    wanted = tuple(_plain(token) for token in tokens)
    for item in embed.fields:
        name = _plain(str(item.name))
        if any(token in name for token in wanted):
            return str(item.value)
    return ""


def _first_id(value: str | None) -> int | None:
    match = re.search(r"(?<!\d)(\d{15,22})(?!\d)", str(value or ""))
    return int(match.group(1)) if match else None


def _looks_like_ticket_close(embed: discord.Embed | None, file: discord.File | None) -> bool:
    if embed is None or file is None:
        return False
    title = _plain(str(embed.title or ""))
    filename = _plain(str(getattr(file, "filename", "")))
    return (
        "ticket" in title
        and any(token in title for token in ("ferme", "fermeture", "close"))
        and "transcript" in filename
    )


def _read_file_text(file: discord.File) -> str | None:
    fp = getattr(file, "fp", None)
    if fp is None or not hasattr(fp, "read"):
        return None
    try:
        old_pos = fp.tell() if hasattr(fp, "tell") else None
    except Exception:
        old_pos = None
    try:
        if hasattr(fp, "seek"):
            fp.seek(0)
        data = fp.read()
        return data if isinstance(data, str) else bytes(data).decode("utf-8", "replace")
    except Exception:
        return None
    finally:
        if old_pos is not None:
            try:
                fp.seek(old_pos)
            except Exception:
                pass


_LINE_RE = re.compile(
    r"^\[(?P<date>\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})\]\s+(?P<name>.+?)\s+\((?P<id>\d{15,22})\):",
    re.MULTILINE,
)


def _transcript_meta(text: str) -> tuple[int | None, list[tuple[str, int]]]:
    created_ts: int | None = None
    participants: list[tuple[str, int]] = []
    seen: set[int] = set()
    for match in _LINE_RE.finditer(text or ""):
        if created_ts is None:
            try:
                stamp = datetime.strptime(
                    match.group("date"), "%Y-%m-%d %H:%M"
                ).replace(tzinfo=timezone.utc)
                created_ts = int(stamp.timestamp())
            except ValueError:
                pass
        uid = int(match.group("id"))
        if uid in seen:
            continue
        seen.add(uid)
        participants.append((match.group("name").strip(), uid))
    return created_ts, participants


def _html_transcript(
    guild: discord.Guild,
    title: str,
    text: str,
    participants: list[tuple[str, int]],
) -> bytes:
    participants_html = "".join(
        f"<span class='pill'>{html.escape(name)} <small>{uid}</small></span>"
        for name, uid in participants[:30]
    ) or "<span class='muted'>Aucun participant détecté.</span>"
    safe_text = html.escape(text or "Aucun message.")
    safe_guild = html.escape(guild.name)
    safe_title = html.escape(title)
    document = f"""<!doctype html>
<html lang='fr'>
<head>
<meta charset='utf-8'>
<meta name='viewport' content='width=device-width,initial-scale=1'>
<title>{safe_title} — {safe_guild}</title>
<style>
:root{{--bg:#0f0b1b;--card:#1b1530;--line:#322650;--text:#f5f3fb;--muted:#9e95b6;--accent:#8b5cf6}}
*{{box-sizing:border-box}}body{{margin:0;background:linear-gradient(145deg,#0d0917,#151027);font-family:Inter,system-ui,-apple-system,Segoe UI,sans-serif;color:var(--text)}}
.wrap{{max-width:1100px;margin:36px auto;padding:0 20px}}.card{{background:var(--card);border:1px solid var(--line);border-radius:18px;overflow:hidden;box-shadow:0 24px 70px #0007}}
.head{{padding:26px 30px;border-left:6px solid var(--accent);border-bottom:1px solid var(--line)}}.eyebrow{{color:#b9add5;font-size:12px;font-weight:800;letter-spacing:.13em;text-transform:uppercase}}
h1{{margin:8px 0 5px;font-size:30px}}.muted{{color:var(--muted)}}.meta{{padding:20px 30px;border-bottom:1px solid var(--line)}}
.pill{{display:inline-block;margin:4px 7px 4px 0;padding:7px 10px;border-radius:999px;background:#28203f;border:1px solid #40335f}}small{{color:#9b91b3}}
pre{{margin:0;padding:26px 30px;white-space:pre-wrap;word-break:break-word;font:13px/1.65 ui-monospace,SFMono-Regular,Menlo,monospace;background:#120e20;color:#e9e5f2}}
.foot{{padding:14px 30px;color:var(--muted);font-size:12px;border-top:1px solid var(--line)}}
</style></head>
<body><main class='wrap'><section class='card'><header class='head'><div class='eyebrow'>SentriX • Ticket Transcript</div><h1>{safe_title}</h1><div class='muted'>{safe_guild}</div></header><div class='meta'><strong>Participants</strong><br>{participants_html}</div><pre>{safe_text}</pre><footer class='foot'>Transcript généré automatiquement par SentriX.</footer></section></main></body></html>"""
    return document.encode("utf-8")


def _mention(user_id: int | None, fallback: str = "Non disponible") -> str:
    return f"<@{user_id}>" if user_id else _one_line(fallback, 130)


class TicketClosureLogView(discord.ui.LayoutView):
    """Carte de fermeture compacte ; le détail complet reste dans le transcript."""

    _sentrix_log_layout = True
    _sentrix_rectangle_v25 = True
    _sentrix_reference_v26 = True
    _sentrix_ticket_v34 = True

    def __init__(
        self,
        bot: commands.Bot,
        guild: discord.Guild,
        embed: discord.Embed,
        *,
        created_ts: int | None,
        participants: list[tuple[str, int]],
        transcript_url: str | None = None,
    ):
        super().__init__(timeout=24 * 60 * 60)
        del bot
        member_value = _field(embed, "cible", "membre", "utilisateur", "auteur")
        actor_value = _field(embed, "effectue par", "acteur", "moderateur", "modérateur")
        reason = _field(embed, "raison") or "Non précisée"
        salon = _field(embed, "salon")
        member_id = _first_id(member_value)
        actor_id = _first_id(actor_value)
        stamp = embed.timestamp or discord.utils.utcnow()
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        ts = int(stamp.timestamp())

        context = [
            f"🛡️ **Modo** {_mention(actor_id, actor_value or 'Inconnu')}",
            f"👤 **Membre** {_mention(member_id, member_value or 'Inconnu')}",
        ]
        if salon:
            context.append(f"💬 **Salon** {_one_line(salon, 130)}")
        detail = f"📝 **Raison** {_one_line(reason, 260)}  •  👥 **Participants** {len(participants)}"
        if created_ts:
            detail += f"  •  🕘 **Créé** <t:{created_ts}:R>"

        ids = [f"serveur `{guild.id}`"]
        if member_id:
            ids.insert(0, f"membre `{member_id}`")
        if actor_id:
            ids.insert(1 if member_id else 0, f"modo `{actor_id}`")
        text = "\n".join([
            f"-# 🎫 SENTRIX • TICKETS • {guild.name} • <t:{ts}:R>",
            "## 🔒 Fermeture du ticket",
            "  •  ".join(context[:3]),
            detail,
            "-# " + " • ".join(ids[:3]),
        ])[:1700]

        container = discord.ui.Container(accent_colour=0x8B5CF6)
        container.add_item(discord.ui.TextDisplay(text))
        row = discord.ui.ActionRow()
        if transcript_url:
            row.add_item(discord.ui.Button(label="Transcript", style=discord.ButtonStyle.link, url=transcript_url))
        button_index = 0
        for label, value in (("ID membre", member_id), ("ID modérateur", actor_id)):
            if value:
                row.add_item(premium_logs_v2.CopyIdButton(label, int(value), button_index))
                button_index += 1
        if row.children:
            container.add_item(row)

        self._sentrix_log_fingerprint = v25._fingerprint_embed(guild.id, embed)
        self._sentrix_is_log_layout = True
        self.add_item(container)


def _html_file(original: discord.File, guild: discord.Guild, title: str, text: str, participants: list[tuple[str, int]]) -> discord.File:
    filename = str(getattr(original, "filename", "transcript-ticket.txt"))
    stem = filename.rsplit(".", 1)[0]
    payload = _html_transcript(guild, title, text, participants)
    return discord.File(io.BytesIO(payload), filename=f"{stem}.html")


def install(bot: commands.Bot, extension_name: str = "") -> None:
    del extension_name
    global _INSTALLED
    if _INSTALLED:
        return
    previous_send = discord.TextChannel.send
    if getattr(previous_send, "_sentrix_ticket_transcript_v34", False):
        _INSTALLED = True
        return

    async def send_ticket_log(self: discord.TextChannel, *args, **kwargs):
        embed = kwargs.get("embed")
        file = kwargs.get("file")
        if not isinstance(embed, discord.Embed) or not isinstance(file, discord.File) or not _looks_like_ticket_close(embed, file):
            return await previous_send(self, *args, **kwargs)
        text = _read_file_text(file)
        if not text:
            return await previous_send(self, *args, **kwargs)

        created_ts, participants = _transcript_meta(text)
        html_file = _html_file(file, self.guild, "Fermeture du ticket", text, participants)
        initial = TicketClosureLogView(bot, self.guild, embed, created_ts=created_ts, participants=participants)
        send_kwargs = dict(kwargs)
        send_kwargs.pop("embed", None)
        send_kwargs["file"] = html_file
        send_kwargs["view"] = initial
        send_kwargs["allowed_mentions"] = discord.AllowedMentions.none()
        message = await previous_send(self, *args, **send_kwargs)
        if message is None or not getattr(message, "attachments", None):
            return message

        try:
            url = str(message.attachments[0].url)
            final_view = TicketClosureLogView(bot, self.guild, embed, created_ts=created_ts, participants=participants, transcript_url=url)
            await message.edit(view=final_view)
        except (discord.Forbidden, discord.HTTPException):
            pass
        except Exception:
            logger.exception("V34 : impossible d'ajouter le bouton Transcript guild=%s", self.guild.id)
        return message

    send_ticket_log._sentrix_ticket_transcript_v34 = True
    send_ticket_log._sentrix_original = previous_send
    discord.TextChannel.send = send_ticket_log
    _INSTALLED = True
    logger.info("V34 tickets : fermeture rectangle compacte + transcript HTML actifs.")


__all__ = ["install", "TicketClosureLogView"]
