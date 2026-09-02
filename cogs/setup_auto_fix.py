"""Routage fiable de ``+setup auto <profil>`` avant le parsing de /setup.

La commande historique ``setup`` n'accepte aucun argument. discord.py ignore donc les
mots supplémentaires d'une commande préfixée par défaut : ``+setup auto community``
ouvrait simplement le panneau interactif. Ce correctif intercepte uniquement la forme
préfixée ``setup auto`` avant ``Command.prepare()`` ; ``+setup`` et ``/setup`` gardent
strictement leur comportement historique.

Ce module répare aussi les doublons exacts des salons de logs SentriX au démarrage. La
réparation est volontairement non destructive : le salon configuré est conservé, la base
est rattachée à un salon existant quand son ID a disparu, et les doublons sont renommés en
archives au lieu d'être supprimés avec leur historique. Le créateur de salons de logs est
également entouré par ce garde-fou afin qu'une perte d'ID en base ne recrée plus de doublon
pendant que le bot tourne.
"""
from __future__ import annotations

import asyncio
import logging
import unicodedata
from types import MethodType

import discord
from discord.ext import commands

from utils import embeds
from utils import sentrix_panels as panels

logger = logging.getLogger("bot.setup-auto-fix")
VALID_PROFILES = frozenset({"community", "gaming", "support", "creator"})

# Même mapping que cogs.configuration.LOG_CHANNEL_DEFINITIONS, dupliqué ici afin que ce
# garde-fou reste petit et indépendant de l'énorme UI /setup.
_LOG_CHANNELS = (
    ("log_server", "logs-serveur"),
    ("log_messages", "logs-messages"),
    ("log_members", "logs-membre"),
    ("log_voice", "logs-vocal"),
    ("log_roles", "logs-roles"),
    ("log_moderation", "logs-moderation"),
    ("log_automod", "logs-securite"),
)


def _normalise_channel_name(value: str) -> str:
    """Compare aussi les anciens noms accentués : modération/sécurité, etc."""
    folded = unicodedata.normalize("NFKD", str(value or "").casefold())
    ascii_name = "".join(char for char in folded if not unicodedata.combining(char))
    return ascii_name.replace("_", "-").strip("- ")


def _is_sentrix_log_category(channel: discord.TextChannel) -> bool:
    category = channel.category
    if category is None:
        return False
    name = _normalise_channel_name(category.name)
    return "sentrix" in name and "log" in name


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
        await panels.envoyer(ctx, panels.depuis_embed(embeds.error('La configuration automatique se charge encore. Réessayez dans quelques secondes.')))
        return

    try:
        result = await platform.quick_setup(ctx.guild, ctx.author.id, profile)
    except Exception as exc:
        logger.exception("Échec du setup automatique %s", profile)
        # Les erreurs attendues de permissions sont déjà formulées clairement par
        # PlatformV4. On n'expose jamais de trace technique dans Discord.
        message = str(exc).strip() or "La configuration automatique a échoué."
        await panels.envoyer(ctx, panels.depuis_embed(embeds.error(message[:900])))
        return

    created = result.get("created_channels", []) if isinstance(result, dict) else []
    created_count = len(created) if isinstance(created, (list, tuple, set)) else int(created or 0)
    missing = result.get("missing_permissions", []) if isinstance(result, dict) else []
    text = f"Configuration automatique **{profile}** terminée.\n**{created_count}** salon(s) créé(s)."
    if missing:
        text += "\nPermissions à vérifier : " + ", ".join(str(item) for item in missing[:6])
    await panels.envoyer(ctx, panels.depuis_embed(embeds.success(text)))


async def _run_auto_setup(bot: commands.Bot, ctx: commands.Context, profile: str) -> None:
    if profile not in VALID_PROFILES:
        await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Profil inconnu. Utilisez `community`, `gaming`, `support` ou `creator`.')))
        return

    runtime = bot.get_cog("BotV10")
    if runtime is not None and hasattr(runtime, "run_auto_setup"):
        await runtime.run_auto_setup(ctx, profile)
        return
    await _fallback_auto_setup(bot, ctx, profile)


async def _repair_log_channels(bot: commands.Bot, guild: discord.Guild) -> tuple[int, int]:
    """Réconcilie la config et les noms de logs sans effacer aucun historique.

    Retourne ``(configs_repaired, duplicates_archived)``.
    """
    try:
        conf = await bot.db.get_guild_config(guild.id)
    except Exception:
        logger.exception("Impossible de lire la configuration logs de %s", guild.id)
        return 0, 0

    configs_repaired = 0
    duplicates_archived = 0
    me = guild.me
    can_manage = bool(me and me.guild_permissions.manage_channels)

    for db_column, canonical_name in _LOG_CHANNELS:
        wanted = _normalise_channel_name(canonical_name)
        candidates = [
            channel
            for channel in guild.text_channels
            if _normalise_channel_name(channel.name) == wanted
        ]
        if not candidates:
            continue

        configured_id = None
        try:
            configured_id = int(conf[db_column] or 0) if conf is not None else 0
        except (KeyError, TypeError, ValueError, IndexError):
            configured_id = 0

        configured = guild.get_channel(configured_id) if configured_id else None
        if isinstance(configured, discord.TextChannel) and configured in candidates:
            winner = configured
        else:
            # Priorité au vrai bloc SentriX — Logs, puis au salon le plus ancien afin de
            # préserver l'historique si l'ID de base a été perdu.
            winner = min(
                candidates,
                key=lambda channel: (0 if _is_sentrix_log_category(channel) else 1, channel.id),
            )

        if configured_id != winner.id:
            try:
                await bot.db.set_guild_config(guild.id, db_column, winner.id)
                configs_repaired += 1
            except Exception:
                logger.exception(
                    "Impossible de rattacher %s au salon %s sur %s",
                    db_column,
                    winner.id,
                    guild.id,
                )

        if len(candidates) <= 1 or not can_manage:
            continue

        for duplicate in candidates:
            if duplicate.id == winner.id:
                continue
            archive_name = f"{canonical_name}-archive-{str(duplicate.id)[-4:]}"[:100]
            try:
                if duplicate.name != archive_name:
                    await duplicate.edit(
                        name=archive_name,
                        reason="SentriX : archivage non destructif d'un doublon de salon de logs",
                    )
                    duplicates_archived += 1
            except (discord.Forbidden, discord.HTTPException):
                logger.warning(
                    "Doublon logs non renommé faute de permission/API : guild=%s channel=%s",
                    guild.id,
                    duplicate.id,
                )

    return configs_repaired, duplicates_archived


def _install_log_creation_guard(bot: commands.Bot) -> bool:
    """Répare les IDs juste avant /create-logs ou la page Logs de /setup.

    Ainsi, même après un reset partiel de configuration pendant que le bot reste en ligne,
    un salon existant est réutilisé au lieu d'en créer un deuxième.
    """
    configuration = bot.get_cog("Configuration")
    if configuration is None or not hasattr(configuration, "create_log_channels"):
        logger.warning("Cog Configuration introuvable : garde anti-doublon logs non installé.")
        return False
    if getattr(configuration, "_sentrix_log_creation_guard", False):
        return True

    original_create = configuration.create_log_channels

    async def guarded_create(_self, guild: discord.Guild, author: discord.Member):
        await _repair_log_channels(bot, guild)
        return await original_create(guild, author)

    configuration.create_log_channels = MethodType(guarded_create, configuration)
    configuration._sentrix_log_creation_guard = True
    logger.info("Garde anti-doublon installée sur create_log_channels.")
    return True


def install(bot: commands.Bot) -> bool:
    """Intercepte l'invocation de +setup avant que discord.py n'ignore ses arguments."""
    command = bot.get_command("setup")
    if command is None:
        logger.warning("Commande setup introuvable : routeur auto non installé.")
        return False
    if getattr(command, "_sentrix_setup_auto_invoke_fix", False):
        _install_log_creation_guard(bot)
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
    _install_log_creation_guard(bot)
    logger.info("Routeur +setup auto installé sur la commande setup.")
    return True


class SetupAutoFix(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._repaired_guilds: set[int] = set()

    async def cog_load(self):
        install(self.bot)

    @commands.Cog.listener()
    async def on_ready(self):
        total_configs = 0
        total_archived = 0
        for guild in self.bot.guilds:
            if guild.id in self._repaired_guilds:
                continue
            configs, archived = await _repair_log_channels(self.bot, guild)
            total_configs += configs
            total_archived += archived
            self._repaired_guilds.add(guild.id)
        if total_configs or total_archived:
            logger.info(
                "Réparation logs terminée : %s configuration(s) rattachée(s), %s doublon(s) archivé(s).",
                total_configs,
                total_archived,
            )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SetupAutoFix(bot))
