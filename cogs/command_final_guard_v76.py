"""Dernier garde-fou du registre préfixé SentriX.

Certaines couches d'interface historiques réenveloppent encore des callbacks après les passes
V18/V41. Discord.py met alors en cache les paramètres du wrapper et peut exposer ``ctx``,
``args`` ou ``kwargs`` à l'utilisateur. V76 vérifie LA commande réellement invoquée juste
avant ``Command.invoke`` et ne relance la réparation globale que si cette commande est sale.

Le module remplace aussi l'ancien ``+verify-setup <role>`` par un point d'entrée sans argument
vers le nouvel éditeur « Vérification & règlement » du dashboard et retire ``verify-panel`` :
la publication fait maintenant partie de l'enregistrement du Setup.
"""
from __future__ import annotations

import inspect
import logging
from types import MethodType

import discord
from discord.ext import commands

import config
from utils import sentrix_panels as panels
from .command_runtime_hardening_v18 import repair_wrapped_signatures

logger = logging.getLogger("bot.command-final-guard-v76")

_INTERNAL_PARAMS = {
    "self", "ctx", "context", "interaction", "bot", "_bot", "cog", "_ctx",
    "original", "__original", "name", "__name", "kwargs", "args",
}


def _needs_repair(command: commands.Command | None) -> bool:
    if command is None:
        return False
    try:
        names = {str(name).casefold().lstrip("_") for name in command.clean_params}
    except Exception:
        return True
    reserved = {name.casefold().lstrip("_") for name in _INTERNAL_PARAMS}
    return bool(names & reserved)


def _repair_command_fallback(command: commands.Command | None) -> bool:
    """Reconstruit le cache des paramètres sans retirer le wrapper exécuté.

    V18 couvre normalement ce cas. Ce fallback final utilise une Command temporaire bâtie
    sur le callback métier pour les rares wrappers auxquels discord.py laisse encore
    ``args``/``kwargs`` dans ``Command.params`` après une affectation tardive.
    """
    if command is None or not _needs_repair(command):
        return False
    wrapper = getattr(command, "callback", None)
    original = getattr(wrapper, "_sentrix_original", None) or getattr(wrapper, "__wrapped__", None)
    if not callable(original):
        return False
    try:
        probe = commands.Command(original, name=f"{getattr(command, 'name', 'sentrix')}-signature-probe")
        command.params = dict(getattr(probe, "params", {}) or {})
        try:
            wrapper.__signature__ = inspect.signature(original)
        except (AttributeError, TypeError, ValueError):
            pass
        return not _needs_repair(command)
    except Exception:
        logger.exception(
            "V76 : fallback de signature impossible pour +%s.",
            getattr(command, "qualified_name", getattr(command, "name", "?")),
        )
        return False


def _repair_dirty_commands(bot: commands.Bot) -> int:
    repaired = repair_wrapped_signatures(bot)
    for command in list(bot.walk_commands()):
        if _needs_repair(command) and _repair_command_fallback(command):
            repaired += 1
    return repaired


def _dashboard_url(guild_id: int) -> str | None:
    base = str(getattr(config, "DASHBOARD_PUBLIC_URL", "") or "").strip().rstrip("/")
    if not base:
        return None
    return f"{base}/app?tab=verification&guild={int(guild_id)}"


def _remove_old_verification_commands(bot: commands.Bot) -> None:
    # Prefixe : l'ancien callback attendait obligatoirement un rôle et verify-panel publiait
    # un second panneau séparé. Les deux comportements sont maintenant remplacés.
    bot.remove_command("verify-setup")
    bot.remove_command("verify-panel")
    try:
        bot.tree.remove_command("verify-setup", type=discord.AppCommandType.chat_input)
    except Exception:
        pass
    try:
        bot.tree.remove_command("verify-panel", type=discord.AppCommandType.chat_input)
    except Exception:
        pass

    async def verify_setup(ctx: commands.Context):
        if ctx.guild is None:
            return await ctx.send("Cette commande doit être utilisée sur un serveur.")
        if not (ctx.author.id == ctx.guild.owner_id or ctx.author.guild_permissions.administrator):
            return await ctx.send("Cette configuration est réservée au propriétaire ou aux administrateurs du serveur.")
        url = _dashboard_url(ctx.guild.id)
        embed = discord.Embed(
            title="Vérification & règlement",
            description=(
                "Configurez le **salon**, le **rôle Vérifié**, votre **propre règlement**, "
                "l'**image** et le **CAPTCHA**, puis utilisez **Enregistrer et publier**.\n\n"
                "La commande `+verify-panel` n'est plus nécessaire."
            ),
            colour=discord.Colour(0x4DA3FF),
        )
        view = None
        if url:
            view = discord.ui.View(timeout=120)
            view.add_item(discord.ui.Button(label="Configurer la vérification", url=url))
        panneau = panels.depuis_embed(embed, kind="configuration")
        if view is not None:
            panneau = panels.avec_composants(panneau, view)
        await panels.envoyer(ctx, panneau)

    command = commands.Command(
        verify_setup,
        name="verify-setup",
        help="Configurer le règlement, le rôle, le salon, l'image et le CAPTCHA depuis SentriX.",
        description="Ouvrir la configuration complète Vérification & règlement.",
    )
    bot.add_command(command)


def install(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_command_final_guard_v76", False):
        return

    # Première réparation maintenant, puis une réparation ciblée juste avant chaque commande
    # si une couche tardive a de nouveau contaminé ses paramètres.
    _repair_dirty_commands(bot)
    current_invoke = bot.invoke

    async def invoke_v76(_bot: commands.Bot, ctx: commands.Context):
        if _needs_repair(getattr(ctx, "command", None)):
            repaired = _repair_dirty_commands(_bot)
            logger.warning(
                "V76 : signature préfixée réparée juste avant +%s (%s commande(s) réparée(s)).",
                getattr(getattr(ctx, "command", None), "qualified_name", "?"),
                repaired,
            )
        return await current_invoke(ctx)

    invoke_v76._sentrix_command_final_guard_v76 = True
    invoke_v76._sentrix_original = getattr(current_invoke, "__func__", current_invoke)
    bot.invoke = MethodType(invoke_v76, bot)

    _remove_old_verification_commands(bot)
    bot._sentrix_command_final_guard_v76 = True
    logger.info("V76 actif : signatures + réparées à l'invocation, verify-setup simplifié, verify-panel retiré.")


class CommandFinalGuardV76(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        # on_ready se produit après les derniers hooks de boot : cette passe constitue aussi
        # un audit/rattrapage de tout le registre vivant.
        repaired = _repair_dirty_commands(self.bot)
        if repaired:
            logger.info("V76 on_ready : %s signature(s) finale(s) restaurée(s).", repaired)


async def setup(bot: commands.Bot):
    install(bot)
    await bot.add_cog(CommandFinalGuardV76(bot))


__all__ = ["install", "_needs_repair"]
