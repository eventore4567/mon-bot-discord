"""Rattrape les arrivées pendant une coupure, sans accueillir les anciens membres.

Le premier démarrage initialise un repère, sans opération de masse. Les suivants
relisent les membres arrivés depuis le dernier battement persisté. Discord doit
avoir l'intent Membres activé ; un échec conserve le repère pour une reprise.
"""
from __future__ import annotations

import asyncio
import logging
import time

logger = logging.getLogger("bot.onboarding-recovery")


async def ensure_schema(db):
    if getattr(db, "_sentrix_onboarding_schema_ready", False) is True:
        return
    await db.execute(
        "CREATE TABLE IF NOT EXISTS onboarding_heartbeat ("
        "guild_id INTEGER PRIMARY KEY, online_at REAL NOT NULL)"
    )
    await db.execute(
        "CREATE TABLE IF NOT EXISTS onboarding_welcomed ("
        "guild_id INTEGER NOT NULL, user_id INTEGER NOT NULL, joined_at REAL NOT NULL, "
        "PRIMARY KEY (guild_id, user_id))"
    )

    db._sentrix_onboarding_schema_ready = True


def joined_timestamp(member):
    joined = getattr(member, "joined_at", None)
    return joined.timestamp() if joined is not None else None


async def welcomed(db, member):
    joined = joined_timestamp(member)
    if joined is None:
        return False
    row = await db.fetchone(
        "SELECT joined_at FROM onboarding_welcomed WHERE guild_id=? AND user_id=?",
        (member.guild.id, member.id),
    )
    return row is not None and float(row["joined_at"]) == joined


async def mark_welcomed(db, member):
    joined = joined_timestamp(member)
    if joined is not None:
        await db.execute(
            "INSERT INTO onboarding_welcomed (guild_id,user_id,joined_at) VALUES (?,?,?) "
            "ON CONFLICT(guild_id,user_id) DO UPDATE SET joined_at=excluded.joined_at",
            (member.guild.id, member.id, joined),
        )


class Recovery:
    def __init__(self, bot, handle_join, is_active):
        self.bot = bot
        self.handle_join = handle_join
        self.is_active = is_active
        self.task = None
        self.pending = set()
        self.initialized = set()

    async def tick(self):
        if not self.is_active() or not self.bot.is_ready():
            return
        await ensure_schema(self.bot.db)
        for guild in list(self.bot.guilds):
            if not self.is_active() or not self.bot.is_ready():
                return
            try:
                cutoff = time.time()
                row = await self.bot.db.fetchone(
                    "SELECT online_at FROM onboarding_heartbeat WHERE guild_id=?", (guild.id,)
                )
                # Une seule énumération à la reconnexion ; les battements suivants
                # font seulement une écriture, sans scanner tous les membres.
                if row is not None and (guild.id not in self.initialized or guild.id in self.pending):
                    complete = True
                    async for member in guild.fetch_members(limit=None):
                        if not self.is_active() or not self.bot.is_ready():
                            return
                        joined = joined_timestamp(member)
                        if member.bot or joined is None or not float(row["online_at"]) <= joined <= cutoff:
                            continue
                        if await self.handle_join(member) is False:
                            complete = False
                    if not complete:
                        self.pending.add(guild.id)
                        continue
                if not self.is_active() or not self.bot.is_ready():
                    return
                await self.bot.db.execute(
                    "INSERT INTO onboarding_heartbeat (guild_id,online_at) VALUES (?,?) "
                    "ON CONFLICT(guild_id) DO UPDATE SET online_at=excluded.online_at",
                    (guild.id, cutoff),
                )
                self.pending.discard(guild.id)
                self.initialized.add(guild.id)
            except Exception:
                self.pending.add(guild.id)
                logger.exception("Rattrapage des arrivées incomplet guild=%s", guild.id)

    async def run(self):
        while not self.bot.is_closed():
            try:
                await self.bot.wait_until_ready()
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Rattrapage des arrivées indisponible")
            await asyncio.sleep(30)

    async def on_ready(self):
        # READY est aussi émis lorsqu'une session ne peut pas être reprise.
        if self.task is not None and not self.task.done():
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        self.initialized.clear()
        self.task = asyncio.create_task(self.run(), name="sentrix-onboarding-recovery")
