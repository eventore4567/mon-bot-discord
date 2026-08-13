"""Bot V11 — commandes personnalisées: les métriques ne bloquent jamais l'exécution."""
from __future__ import annotations

import logging
import time

import discord
from discord.ext import commands, tasks

from database.db import now

logger = logging.getLogger("bot.custom-command-failsafe-v11")
_LOG_THROTTLE_SECONDS = 60.0


def install(bot: commands.Bot, owner: "CustomCommandFailsafeV11 | None" = None) -> bool:
    v10 = bot.get_cog("BotV10")
    if v10 is None:
        return False

    listeners = bot.extra_events.get("on_message", [])
    for index, listener in enumerate(listeners):
        if not getattr(listener, "_sentrix_custom_commands_v10", False):
            continue
        if getattr(listener, "_sentrix_custom_commands_usage_failsafe_v11", False):
            return True

        defaults = getattr(listener, "__defaults__", ()) or ()
        original = defaults[-1] if defaults else None
        if not callable(original):
            logger.warning("V11: listener custom V10 détecté mais handler original inaccessible.")
            return False

        try:
            from .bot_v10 import CUSTOM_COMMAND_COOLDOWN
            cooldown_seconds = float(CUSTOM_COMMAND_COOLDOWN)
        except Exception:
            cooldown_seconds = 3.0

        async def guarded_failsafe(
            message: discord.Message,
            _original=original,
            _v10=v10,
            _cooldown=cooldown_seconds,
        ):
            if message.guild and not message.author.bot:
                try:
                    conf = await bot.db.get_guild_config(message.guild.id)
                    prefix = str(conf["prefix"] or "+") if conf else "+"
                except Exception:
                    prefix = "+"

                if (message.content or "").startswith(prefix):
                    raw_name = (message.content[len(prefix):].split(maxsplit=1) or [""])[0].casefold()
                    try:
                        row = (
                            await bot.db.fetchone(
                                "SELECT id FROM platform_custom_commands "
                                "WHERE guild_id=? AND name=? AND enabled=1",
                                (message.guild.id, raw_name),
                            )
                            if raw_name
                            else None
                        )
                    except Exception:
                        row = None

                    if row:
                        key = (message.guild.id, message.author.id, raw_name)
                        current_t = time.monotonic()
                        previous = _v10._custom_cooldowns.get(key, 0.0)
                        if _cooldown - (current_t - previous) > 0:
                            return
                        _v10._custom_cooldowns[key] = current_t
                        try:
                            await bot.db.execute(
                                "INSERT INTO v10_custom_command_usage "
                                "(guild_id,command_name,uses,last_used_at) VALUES (?,?,1,?) "
                                "ON CONFLICT(guild_id,command_name) DO UPDATE SET "
                                "uses=uses+1,last_used_at=excluded.last_used_at",
                                (message.guild.id, raw_name, now()),
                            )
                        except Exception:
                            current_log_t = time.monotonic()
                            last_log_t = getattr(owner, "_last_metric_error", 0.0) if owner else 0.0
                            if current_log_t - last_log_t >= _LOG_THROTTLE_SECONDS:
                                if owner:
                                    owner._last_metric_error = current_log_t
                                logger.warning(
                                    "V11: métrique custom-command ignorée; la commande continue.",
                                    exc_info=True,
                                )

            return await _original(message)

        guarded_failsafe._sentrix_custom_commands_v10 = True
        guarded_failsafe._sentrix_custom_commands_usage_failsafe_v11 = True
        listeners[index] = guarded_failsafe
        logger.info("V11: métriques des commandes personnalisées passées en fail-soft.")
        return True

    return False


class CustomCommandFailsafeV11(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._last_metric_error = 0.0

    async def cog_load(self) -> None:
        install(self.bot, self)
        if not self.repair_loop.is_running():
            self.repair_loop.start()

    def cog_unload(self) -> None:
        self.repair_loop.cancel()

    @tasks.loop(seconds=30)
    async def repair_loop(self) -> None:
        try:
            install(self.bot, self)
        except Exception:
            logger.warning("V11: vérification custom-command impossible; nouveau cycle prévu.", exc_info=True)

    @repair_loop.before_loop
    async def before_repair_loop(self) -> None:
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        install(self.bot, self)


async def setup(bot: commands.Bot) -> None:
    if bot.get_cog("CustomCommandFailsafeV11") is None:
        await bot.add_cog(CustomCommandFailsafeV11(bot))
