"""V93 — résolution robuste des panels tickets par nom ou ID."""
from __future__ import annotations

import re
import unicodedata

from discord.ext import commands

from . import runtime_finish_v92 as v92


def _norm(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = text.replace("＆", "&")
    text = re.sub(r"\s+", " ", text).strip()
    return text.casefold()


def _patch_ticket_panel_lookup(bot: commands.Bot) -> bool:
    cog = bot.get_cog("Tickets")
    if cog is None:
        return False
    cls = cog.__class__
    current = getattr(cls, "get_panel_by_name", None)
    if current is None or getattr(current, "_sentrix_v93_lookup", False):
        return bool(current)

    async def get_panel_by_name_v93(self, guild_id: int, name: str):
        raw = str(name or "").strip()
        numeric = raw[1:] if raw.startswith("#") else raw
        if numeric.isdigit():
            row = await self.bot.db.fetchone(
                "SELECT * FROM ticket_panels_v2 WHERE guild_id = ? AND id = ?",
                (guild_id, int(numeric)),
            )
            if row:
                return row

        row = await self.bot.db.fetchone(
            "SELECT * FROM ticket_panels_v2 "
            "WHERE guild_id = ? AND LOWER(TRIM(name)) = LOWER(TRIM(?))",
            (guild_id, raw),
        )
        if row:
            return row

        wanted = _norm(raw)
        rows = await self.bot.db.fetchall(
            "SELECT * FROM ticket_panels_v2 WHERE guild_id = ? ORDER BY id",
            (guild_id,),
        )
        for panel in rows:
            if _norm(panel["name"]) == wanted:
                return panel
        return None

    get_panel_by_name_v93._sentrix_v93_lookup = True
    get_panel_by_name_v93._sentrix_previous = current
    cls.get_panel_by_name = get_panel_by_name_v93
    return True


async def install(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_runtime_finish_v93", False):
        return
    await v92.install(bot)
    _patch_ticket_panel_lookup(bot)
    bot._sentrix_runtime_finish_v93 = True


__all__ = ["install"]
