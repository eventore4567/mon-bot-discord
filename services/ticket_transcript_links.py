"""Private, expiring, browser-openable SentriX ticket transcript links.

Never put a transcript in a ticket channel or expose a token through HTTP paths,
query strings, Discord public messages, or log statements. The 256-bit capability
is carried in the URL *fragment* and submitted to a single POST endpoint.
"""
from __future__ import annotations

import hashlib
import os
import re
import secrets
import time
from urllib.parse import urlsplit

TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{40,60}$")
EXPIRY_SECONDS = 90 * 86400

ARCHIVE_SCHEMA = """
CREATE TABLE IF NOT EXISTS ticket_transcripts (
    ticket_id BIGINT PRIMARY KEY,
    guild_id BIGINT NOT NULL,
    channel_id BIGINT NOT NULL,
    channel_name TEXT NOT NULL,
    transcript_text TEXT NOT NULL,
    created_at BIGINT NOT NULL
)
"""
LINK_SCHEMA = """
CREATE TABLE IF NOT EXISTS ticket_transcript_links (
    token_hash TEXT PRIMARY KEY,
    ticket_id BIGINT NOT NULL,
    guild_id BIGINT NOT NULL,
    viewer_id BIGINT NOT NULL,
    closer_name TEXT NOT NULL DEFAULT '',
    close_reason TEXT NOT NULL DEFAULT '',
    created_at BIGINT NOT NULL,
    expires_at BIGINT NOT NULL
)
"""
INDEX_SCHEMA = """
CREATE INDEX IF NOT EXISTS idx_ticket_transcript_links_expiry
ON ticket_transcript_links(expires_at)
"""


def public_origin() -> str | None:
    """Use a configured HTTPS dashboard origin, never derive a URL from a user request."""
    configured = os.getenv("SENTRIX_TRANSCRIPT_PUBLIC_URL", "").strip()
    if not configured:
        import config
        configured = str(
            getattr(config, "DASHBOARD_PUBLIC_URL", "")
            or os.getenv("DASHBOARD_PUBLIC_URL", "")
        ).strip()
    configured = configured.rstrip("/")
    if not configured:
        domain = os.getenv("RAILWAY_PUBLIC_DOMAIN", "").strip().strip("/")
        configured = "https://" + domain if domain else ""
    parsed = urlsplit(configured)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username
            or parsed.password or parsed.query or parsed.fragment):
        return None
    if parsed.path not in {"", "/"}:
        return None
    return f"https://{parsed.netloc}"


async def ensure_schema(db) -> None:
    await db.execute(ARCHIVE_SCHEMA)
    await db.execute(LINK_SCHEMA)
    await db.execute(INDEX_SCHEMA)


async def publish_link(
    bot, *,
    ticket_id: int, guild_id: int, channel_id: int, channel_name: str,
    transcript_text: str, viewer_id: int,
    closer_name: str = "", close_reason: str = "",
) -> str:
    """Persist archive and mint a new private URL for one recipient.

    A new link revokes the previous link for that recipient/ticket, not links
    issued to other authorized staff members.
    """
    origin = public_origin()
    if not origin:
        raise RuntimeError("DASHBOARD_PUBLIC_URL HTTPS absent : lien de transcription impossible")
    db = bot.db
    await ensure_schema(db)
    stamp = int(time.time())
    await db.execute(
        "INSERT INTO ticket_transcripts "
        "(ticket_id, guild_id, channel_id, channel_name, transcript_text, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(ticket_id) DO UPDATE SET "
        "guild_id=excluded.guild_id, channel_id=excluded.channel_id, "
        "channel_name=excluded.channel_name, transcript_text=excluded.transcript_text, "
        "created_at=excluded.created_at",
        (int(ticket_id), int(guild_id), int(channel_id),
         str(channel_name)[:100], str(transcript_text), stamp),
    )
    raw = secrets.token_urlsafe(32)
    digest = hashlib.sha256(raw.encode("ascii")).hexdigest()
    await db.execute(
        "DELETE FROM ticket_transcript_links WHERE ticket_id=? AND viewer_id=?",
        (int(ticket_id), int(viewer_id)),
    )
    await db.execute(
        "INSERT INTO ticket_transcript_links "
        "(token_hash, ticket_id, guild_id, viewer_id, closer_name, close_reason, created_at, expires_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (digest, int(ticket_id), int(guild_id), int(viewer_id),
         str(closer_name)[:150], str(close_reason)[:600], stamp, stamp + EXPIRY_SECONDS),
    )
    return f"{origin}/transcripts#{raw}"


async def load_archive(bot, raw_token: str):
    """Return an authorized archive or None. The raw token never touches storage."""
    if not isinstance(raw_token, str) or not TOKEN_RE.fullmatch(raw_token):
        return None
    digest = hashlib.sha256(raw_token.encode("ascii")).hexdigest()
    db = bot.db
    try:
        link = await db.fetchone(
            "SELECT ticket_id, guild_id, viewer_id, closer_name, close_reason, expires_at "
            "FROM ticket_transcript_links WHERE token_hash = ?", (digest,),
        )
        if link is None or int(link["expires_at"]) <= int(time.time()):
            return None
        archive = await db.fetchone(
            "SELECT ticket_id, guild_id, channel_name, transcript_text "
            "FROM ticket_transcripts WHERE ticket_id = ? AND guild_id = ?",
            (int(link["ticket_id"]), int(link["guild_id"])),
        )
        if not archive:
            return None
        ticket = await db.fetchone(
            "SELECT id, guild_id, user_id, created_at, closed_at "
            "FROM tickets WHERE id = ? AND guild_id = ?",
            (int(link["ticket_id"]), int(link["guild_id"])),
        )
        if ticket is None:
            return None
        return {
            "ticket": ticket, "archive": archive,
            "viewer_id": int(link["viewer_id"]),
            "closed_by": str(link["closer_name"] or ""),
            "close_reason": str(link["close_reason"] or ""),
        }
    except Exception:
        # The HTTP handler will surface a temporary 503 if schema is unavailable.
        raise
