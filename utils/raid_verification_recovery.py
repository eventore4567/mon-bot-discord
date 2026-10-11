"""Restauration prudente du niveau de vérification après un raid Discord.

Ne restaure jamais un réglage inconnu. Le niveau précédent est écrit en base
AVANT l'augmentation, afin de survivre aux crashs et bascules HA.

Avant la restauration, vérifier :
- le serveur est toujours au niveau fixé par SentriX ;
- l'audit Discord confirme que SentriX a effectué la hausse ;
- aucune modification manuelle du niveau n'est survenue depuis ;
- les journaux d'audit sont complets et accessibles.

En cas de doute, laisser le réglage intact. Le propriétaire du serveur peut
toujours ajuster le niveau manuellement.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from datetime import datetime, timezone

import discord

logger = logging.getLogger("bot.security.raid-recovery")
RAID_VERIFICATION_HOLD_SECONDS = 15 * 60
RAID_AUDIT_LOOKBACK_LIMIT = 100
SCHEMA = """
CREATE TABLE IF NOT EXISTS sentrix_raid_verification_restore (
    guild_id INTEGER PRIMARY KEY,
    previous_level INTEGER NOT NULL,
    raised_at INTEGER NOT NULL,
    restore_after INTEGER NOT NULL
)
"""


class RaidVerificationRecovery:
    def __init__(self, bot):
        self.bot = bot
        self._locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._schema_ready = False
        # Une seule transition attendue pour ignorer la notification Gateway
        # générée par notre propre guild.edit().
        self._expected_levels: dict[int, tuple[int, float]] = {}

    async def ensure_schema(self):
        if not self._schema_ready:
            await self.bot.db.execute(SCHEMA)
            self._schema_ready = True

    async def _forget(self, guild_id: int):
        await self.bot.db.execute(
            "DELETE FROM sentrix_raid_verification_restore WHERE guild_id = ?",
            (guild_id,),
        )

    def _expect(self, guild_id: int, level: discord.VerificationLevel):
        if len(self._expected_levels) > 4096:
            self._expected_levels.clear()
        self._expected_levels[int(guild_id)] = (int(level), time.monotonic() + 120)

    async def protect(self, guild: discord.Guild, *, now: int | None = None) -> bool:
        """Relever la vérification pour un raid rapide, ou prolonger la protection.

        Renvoie True uniquement si une modification a été appliquée.
        """
        await self.ensure_schema()
        timestamp = int(time.time()) if now is None else int(now)
        async with self._locks[guild.id]:
            row = await self.bot.db.fetchone(
                "SELECT previous_level, raised_at FROM sentrix_raid_verification_restore "
                "WHERE guild_id = ?",
                (guild.id,),
            )
            current = guild.verification_level
            if current == discord.VerificationLevel.highest:
                if row is not None:
                    await self.bot.db.execute(
                        "UPDATE sentrix_raid_verification_restore SET restore_after = ? "
                        "WHERE guild_id = ?",
                        (timestamp + RAID_VERIFICATION_HOLD_SECONDS, guild.id),
                    )
                # Un niveau maximal choisi par l'administrateur n'appartient
                # pas au bot : ne JAMAIS sauvegarder un snapshot fictif.
                return False

            if row is not None:
                # Le niveau a été changé entre-temps : annuler l'ancien
                # snapshot plutôt que restaurer ultérieurement une valeur périmée.
                await self._forget(guild.id)

            await self.bot.db.execute(
                "INSERT OR REPLACE INTO sentrix_raid_verification_restore "
                "(guild_id, previous_level, raised_at, restore_after) VALUES (?, ?, ?, ?)",
                (
                    guild.id, int(current), timestamp,
                    timestamp + RAID_VERIFICATION_HOLD_SECONDS,
                ),
            )
            self._expect(guild.id, discord.VerificationLevel.highest)
            try:
                await guild.edit(
                    verification_level=discord.VerificationLevel.highest,
                    reason="SentriX anti-raid : vérification maximale provisoire (15 min après dernier raid)",
                )
            except (discord.Forbidden, discord.HTTPException):
                self._expected_levels.pop(guild.id, None)
                await self._forget(guild.id)
                logger.warning("Anti-raid : impossible de relever la vérification guild=%s", guild.id)
                return False
            return True

    async def on_guild_level_change(
        self, before: discord.Guild, after: discord.Guild
    ) -> None:
        """Une modification manuelle annule le retour automatique.

        Ne traite pas les edits de salon, nom, icône, etc.
        """
        if before.verification_level == after.verification_level:
            return
        record = self._expected_levels.get(after.id)
        if record is not None:
            expected_level, expires_at = record
            if time.monotonic() <= expires_at and int(after.verification_level) == expected_level:
                self._expected_levels.pop(after.id, None)
                return
            self._expected_levels.pop(after.id, None)
        await self.ensure_schema()
        async with self._locks[after.id]:
            await self._forget(after.id)
        logger.info("Anti-raid : retour automatique annulé (réglage modifié) guild=%s", after.id)

    async def _audit_allows_restore(
        self, guild: discord.Guild, previous_level: int, raised_at: int
    ) -> bool:
        """L'historique prouve l'édition du bot et aucune édition tierce.

        En cas de permission insuffisante ou de pagination possiblement
        tronquée, refuser silencieusement de remplacer un réglage manuel.
        """
        perms = getattr(getattr(guild, "me", None), "guild_permissions", None)
        if not getattr(perms, "view_audit_log", False):
            return False
        bot_id = getattr(getattr(self.bot, "user", None), "id", None)
        if bot_id is None:
            return False
        bot_raised = False
        examined = 0
        since = datetime.fromtimestamp(raised_at - 10, tz=timezone.utc)
        try:
            async for entry in guild.audit_logs(
                limit=RAID_AUDIT_LOOKBACK_LIMIT,
                action=discord.AuditLogAction.guild_update,
                after=since,
            ):
                examined += 1
                actor_id = getattr(getattr(entry, "user", None), "id", None)
                old = getattr(getattr(entry, "before", None), "verification_level", None)
                new = getattr(getattr(entry, "after", None), "verification_level", None)
                if old is None and new is None:
                    continue
                try:
                    old_level = int(old)
                    new_level = int(new)
                except (TypeError, ValueError):
                    return False
                if (
                    actor_id == bot_id
                    and old_level == previous_level
                    and new_level == int(discord.VerificationLevel.highest)
                ):
                    bot_raised = True
                elif actor_id != bot_id:
                    return False
        except (discord.Forbidden, discord.HTTPException):
            return False
        # 100 entrées = recherche possiblement tronquée, donc pas de preuve.
        return bot_raised and examined < RAID_AUDIT_LOOKBACK_LIMIT

    async def restore_due(self, *, now: int | None = None) -> dict[str, int]:
        """Restaurer après 15 minutes et SEULEMENT si l'audit le permet."""
        await self.ensure_schema()
        timestamp = int(time.time()) if now is None else int(now)
        rows = await self.bot.db.fetchall(
            "SELECT guild_id FROM sentrix_raid_verification_restore "
            "WHERE restore_after <= ?",
            (timestamp,),
        )
        results = {"restored": 0, "cancelled": 0, "deferred": 0}
        for row in rows:
            guild_id = int(row["guild_id"])
            guild = self.bot.get_guild(guild_id)
            if guild is None:
                results["deferred"] += 1
                continue
            async with self._locks[guild_id]:
                state = await self.bot.db.fetchone(
                    "SELECT previous_level, raised_at, restore_after "
                    "FROM sentrix_raid_verification_restore WHERE guild_id = ?",
                    (guild_id,),
                )
                if state is None or int(state["restore_after"]) > timestamp:
                    continue
                if guild.verification_level != discord.VerificationLevel.highest:
                    await self._forget(guild_id)
                    results["cancelled"] += 1
                    continue
                previous = int(state["previous_level"])
                if previous < 0 or previous >= int(discord.VerificationLevel.highest):
                    await self._forget(guild_id)
                    results["cancelled"] += 1
                    continue
                if not await self._audit_allows_restore(guild, previous, int(state["raised_at"])):
                    # Ne pas effacer la sauvegarde : une permission Audit Log
                    # peut être donnée plus tard, mais ne jamais écraser le niveau.
                    results["deferred"] += 1
                    continue
                self._expect(guild_id, discord.VerificationLevel(previous))
                try:
                    await guild.edit(
                        verification_level=discord.VerificationLevel(previous),
                        reason="SentriX anti-raid : fin du raid, restauration prudente du niveau antérieur",
                    )
                except (discord.Forbidden, discord.HTTPException):
                    self._expected_levels.pop(guild_id, None)
                    results["deferred"] += 1
                    continue
                await self._forget(guild_id)
                results["restored"] += 1
                logger.info(
                    "Anti-raid : ancien niveau de vérification restauré guild=%s level=%s",
                    guild_id, previous,
                )
        return results


__all__ = ["RaidVerificationRecovery", "RAID_VERIFICATION_HOLD_SECONDS"]
