"""Messages récurrents SentriX : aucun worker ni listener nouveau.

Traitement via SentriXPlus.scheduled_worker, déjà chargé et actif seulement
lorsque l'instance HA est connectée à Discord. Toute règle est créée en pause.
"""
from __future__ import annotations

import logging
import re
import time

import discord
from discord.ext import commands

from utils import sentrix_panels as panels

logger = logging.getLogger("bot.recurring-messages")
SCHEMA = """
CREATE TABLE IF NOT EXISTS recurring_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    content TEXT NOT NULL,
    every_s INTEGER NOT NULL,
    next_at INTEGER NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 0
)
"""
INTERVAL_RE = re.compile(r"^([0-9]{1,5})(m|h|d)$", re.I)
MIN_INTERVAL = 600
MAX_INTERVAL = 30 * 86400
_LAST_CHECK = 0.0


def parse_interval(value: str) -> int | None:
    match = INTERVAL_RE.fullmatch(str(value or "").strip())
    if not match:
        return None
    amount, unit = int(match.group(1)), match.group(2).lower()
    seconds = amount * {"m": 60, "h": 3600, "d": 86400}[unit]
    return seconds if MIN_INTERVAL <= seconds <= MAX_INTERVAL else None


def is_logs_channel(channel: discord.TextChannel) -> bool:
    """Interdit les destinations qui ressemblent à des salons de journalisation."""
    def forbidden(name: str) -> bool:
        parts = re.split(r"[^a-z0-9]+", str(name or "").casefold())
        return any(part in {"log", "logs", "journal", "journaux", "audit", "moderation-logs"} for part in parts)
    return forbidden(channel.name) or (
        channel.category is not None and forbidden(channel.category.name)
    )


async def is_reserved_channel(bot, channel: discord.TextChannel) -> bool:
    """Empêche aussi les salons de logs renommés (log_config est canonique)."""
    if is_logs_channel(channel):
        return True
    row = await bot.db.fetchone(
        "SELECT 1 AS configured FROM log_config "
        "WHERE guild_id=? AND channel_id=? LIMIT 1",
        (channel.guild.id, channel.id),
    )
    return bool(row)


def card(title: str, text: str, *, kind: str = "info") -> panels.Panneau:
    return panels.Panneau(titre=title, sous_titre=text, kind=kind)


async def process_due(bot) -> int:
    """Appelé depuis le worker existant, jamais directement en boucle."""
    global _LAST_CHECK
    now_monotonic = time.monotonic()
    if now_monotonic - _LAST_CHECK < 55:
        return 0
    _LAST_CHECK = now_monotonic
    now = int(time.time())
    rows = await bot.db.fetchall(
        "SELECT id,guild_id,channel_id,content,every_s FROM recurring_messages "
        "WHERE enabled=1 AND next_at<=? ORDER BY next_at,id LIMIT 20",
        (now,),
    )
    sent = 0
    for row in rows:
        channel = bot.get_channel(int(row["channel_id"]))
        if (not isinstance(channel, discord.TextChannel)
                or channel.guild.id != int(row["guild_id"])
                or await is_reserved_channel(bot, channel)):
            await bot.db.execute("UPDATE recurring_messages SET enabled=0 WHERE id=?", (row["id"],))
            logger.warning("Message récurrent %s désactivé : salon supprimé ou journal.", row["id"])
            continue
        # Planifie le prochain passage AVANT l'envoi : au plus une publication,
        # même en cas d'exception ou d'ancien retard non rattrapé.
        next_at = int(time.time()) + max(int(row["every_s"]), MIN_INTERVAL)
        claim = await bot.db.execute(
            "UPDATE recurring_messages SET next_at=? "
            "WHERE id=? AND enabled=1 AND next_at<=?",
            (next_at, row["id"], now),
        )
        # La transition peut être concurrencée par le relais HA. Sans claim
        # effectué par cette instance, n'envoyer AUCUN message.
        if getattr(claim, "rowcount", 0) != 1:
            continue
        try:
            await channel.send(str(row["content"]), allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            logger.warning("Message récurrent %s non distribué dans %s", row["id"], row["channel_id"])
            continue
        sent += 1
    return sent


class RecurringMessages(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        await self.bot.db.execute(SCHEMA)

    @commands.group(name="recurring", invoke_without_command=True)
    @commands.guild_only()
    async def recurring(self, ctx):
        await self.recurring_list(ctx)

    @recurring.command(name="create", help="Créer un message périodique, initialement désactivé.")
    async def recurring_create(self, ctx, salon: discord.TextChannel, intervalle: str, *, texte: str):
        seconds = parse_interval(intervalle)
        if seconds is None:
            return await panels.envoyer(ctx, card("Intervalle invalide", "Entre 10 minutes et 30 jours (10m, 6h, 2d).", kind="danger"))
        if await is_reserved_channel(self.bot, salon):
            return await panels.envoyer(ctx, card("Salon refusé", "Les messages récurrents sont interdits dans les journaux.", kind="danger"))
        content = texte.strip()
        if not 1 <= len(content) <= 1700:
            return await panels.envoyer(ctx, card("Texte invalide", "Longueur autorisée : 1 à 1 700 caractères.", kind="danger"))
        existing = await self.bot.db.fetchone("SELECT COUNT(*) AS total FROM recurring_messages WHERE guild_id=?", (ctx.guild.id,))
        if existing and existing["total"] >= 20:
            return await panels.envoyer(ctx, card("Limite atteinte", "Vous avez déjà 20 messages récurrents.", kind="warning"))
        now = int(time.time())
        await self.bot.db.execute(
            "INSERT INTO recurring_messages(guild_id,channel_id,content,every_s,next_at,enabled) VALUES (?,?,?,?,?,0)",
            (ctx.guild.id, salon.id, content, seconds, now + seconds),
        )
        await panels.envoyer(ctx, card(
            "Message récurrent créé",
            "La règle est en pause. Activez-la explicitement avec /recurring resume et son identifiant.",
            kind="success",
        ))

    @recurring.command(name="list", help="Lister les messages récurrents du serveur.")
    async def recurring_list(self, ctx):
        rows = await self.bot.db.fetchall(
            "SELECT id,channel_id,every_s,enabled FROM recurring_messages WHERE guild_id=? ORDER BY id DESC LIMIT 20",
            (ctx.guild.id,),
        )
        text = "\n".join(
            f"#{row['id']} | <#{row['channel_id']}> | {row['every_s'] // 60} min | "
            + ("actif" if row["enabled"] else "en pause") for row in rows
        ) or "Aucune publication récurrente."
        await panels.envoyer(ctx, card("Publications récurrentes", text))

    @recurring.command(name="pause", help="Mettre un message récurrent en pause.")
    async def recurring_pause(self, ctx, ident: int):
        await self._toggle(ctx, ident, False)

    @recurring.command(name="resume", help="Activer un message récurrent.")
    async def recurring_resume(self, ctx, ident: int):
        await self._toggle(ctx, ident, True)

    async def _toggle(self, ctx, ident: int, active: bool):
        row = await self.bot.db.fetchone(
            "SELECT id,channel_id,every_s FROM recurring_messages WHERE guild_id=? AND id=?",
            (ctx.guild.id, ident),
        )
        if not row:
            return await panels.envoyer(ctx, card("Introuvable", "Aucun message avec cet identifiant.", kind="warning"))
        channel = self.bot.get_channel(int(row["channel_id"]))
        if active and (not isinstance(channel, discord.TextChannel) or await is_reserved_channel(self.bot, channel)):
            return await panels.envoyer(ctx, card("Salon refusé", "Impossible d'activer ce message dans un salon de logs.", kind="danger"))
        await self.bot.db.execute(
            "UPDATE recurring_messages SET enabled=?,next_at=? WHERE id=? AND guild_id=?",
            (int(active), int(time.time()) + int(row["every_s"]), ident, ctx.guild.id),
        )
        await panels.envoyer(ctx, card(
            "Publication activée" if active else "Publication en pause",
            f"Message récurrent #{ident}.", kind="success",
        ))

    @recurring.command(name="delete", help="Supprimer un message récurrent.")
    async def recurring_delete(self, ctx, ident: int):
        await self.bot.db.execute("DELETE FROM recurring_messages WHERE guild_id=? AND id=?", (ctx.guild.id, ident))
        await panels.envoyer(ctx, card("Message supprimé", f"Règle #{ident} supprimée.", kind="success"))


async def setup(bot):
    await bot.add_cog(RecurringMessages(bot))
