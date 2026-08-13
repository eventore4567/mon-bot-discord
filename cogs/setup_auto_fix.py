"""Routage fiable de ``+setup auto <profil>`` avant le parsing de /setup.

La commande historique ``setup`` n'accepte aucun argument. discord.py ignore donc les
mots supplémentaires d'une commande préfixée par défaut : ``+setup auto community``
ouvrait simplement le panneau interactif. Ce correctif intercepte uniquement la forme
préfixée ``setup auto`` avant ``Command.prepare()`` ; ``+setup`` et ``/setup`` gardent
strictement leur comportement historique.
"""
from __future__ import annotations

import asyncio
import logging
from types import MethodType

from discord.ext import commands

from utils import embeds

logger = logging.getLogger("bot.setup-auto-fix")
VALID_PROFILES = frozenset({"community", "gaming", "support", "creator"})


def parse_setup_auto_profile(content: str, prefix: str = "+", invoked_with: str = "setup") -> str | None:
    """Retourne le profil demandé, ou ``None`` si le message n'est pas ``setup auto``.

    Le parsing est volontairement indépendant de la casse et du préfixe du serveur afin
    que le routeur fonctionne aussi si un serveur remplace ``+`` par ``!`` ou ``?``.
    ``+setup auto`` utilise ``community`` par défaut.
    """
    raw = str(content or "").strip()
    head = f"{prefix or ''}{invoked_with or 'setup'}"
    if not raw.casefold().startswith(head.casefold()):
        return None
    # Évite de confondre +setupfoo avec +setup.
    if len(raw) > len(head) and not raw[len(head)].isspace():
        return None
    rest = raw[len(head):].strip()
    if not rest:
        return None
    parts = rest.split()
    if not parts or parts[0].casefold() != "auto":
        return None
    return parts[1].casefold() if len(parts) > 1 else "community"


async def _fallback_auto_setup(bot: commands.Bot, ctx: commands.Context, profile: str) -> None:
    """Exécute Platform V4 directement si BotV10 n'est pas encore disponible."""
    platform = bot.get_cog("PlatformV4")
    # Platform V4 est normalement prêt avant Discord sur Railway. Ce court délai couvre
    # néanmoins un redémarrage où le dashboard termine encore son initialisation.
    if platform is None:
        for _ in range(12):
            await asyncio.sleep(0.25)
            platform = bot.get_cog("PlatformV4")
            if platform is not None:
                break
    if platform is None or not hasattr(platform, "quick_setup"):
        await ctx.send(embed=embeds.error("La configuration automatique se charge encore. Réessayez dans quelques secondes."))
        return

    try:
        result = await platform.quick_setup(ctx.guild, ctx.author.id, profile)
    except Exception as exc:
        logger.exception("Échec du setup automatique %s", profile)
        # Les erreurs attendues de permissions sont déjà formulées clairement par
        # PlatformV4. On n'expose jamais de trace technique dans Discord.
        message = str(exc).strip() or "La configuration automatique a échoué."
        await ctx.send(embed=embeds.error(message[:900]))
        return

    created = result.get("created_channels", []) if isinstance(result, dict) else []
    created_count = len(created) if isinstance(created, (list, tuple, set)) else int(created or 0)
    missing = result.get("missing_permissions", []) if isinstance(result, dict) else []
    text = f"Configuration automatique **{profile}** terminée.\n**{created_count}** salon(s) créé(s)."
    if missing:
        text += "\nPermissions à vérifier : " + ", ".join(str(item) for item in missing[:6])
    await ctx.send(embed=embeds.success(text))


async def _run_auto_setup(bot: commands.Bot, ctx: commands.Context, profile: str) -> None:
    if profile not in VALID_PROFILES:
        await ctx.send(embed=embeds.error(
            "Profil inconnu. Utilisez `community`, `gaming`, `support` ou `creator`."
        ))
        return

    runtime = bot.get_cog("BotV10")
    if runtime is not None and hasattr(runtime, "run_auto_setup"):
        await runtime.run_auto_setup(ctx, profile)
        return
    await _fallback_auto_setup(bot, ctx, profile)


def install(bot: commands.Bot) -> bool:
    """Intercepte l'invocation de +setup avant que discord.py n'ignore ses arguments."""
    command = bot.get_command("setup")
    if command is None:
        logger.warning("Commande setup introuvable : routeur auto non installé.")
        return False
    if getattr(command, "_sentrix_setup_auto_invoke_fix", False):
        return True

    original_invoke = command.invoke

    async def invoke_with_auto(command_self, ctx: commands.Context):
        if ctx.interaction is not None or getattr(ctx, "message", None) is None:
            return await original_invoke(ctx)

        profile = parse_setup_auto_profile(
            ctx.message.content,
            str(getattr(ctx, "prefix", "") or ""),
            str(getattr(ctx, "invoked_with", "setup") or "setup"),
        )
        if profile is None:
            return await original_invoke(ctx)

        # Nous interceptons avant Command.prepare(), donc nous rejouons explicitement les
        # checks de +setup. En cas de refus, on laisse l'invocation historique produire le
        # même message d'erreur/permission qu'avant au lieu de contourner les contrôles.
        try:
            allowed = await command_self.can_run(ctx)
        except commands.CommandError:
            return await original_invoke(ctx)
        if not allowed:
            return await original_invoke(ctx)

        await _run_auto_setup(bot, ctx, profile)

    command.invoke = MethodType(invoke_with_auto, command)
    command._sentrix_setup_auto_invoke_fix = True
    logger.info("Routeur +setup auto installé sur la commande setup.")
    return True


class SetupAutoFix(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        install(self.bot)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SetupAutoFix(bot))
