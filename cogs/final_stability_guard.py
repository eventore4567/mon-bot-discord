"""Dernière garde de stabilité SentriX.

Cette extension est chargée en fin de démarrage Railway. Elle réaffirme les protections
runtime qui doivent rester autoritaires après tous les anciens wrappers et corrige les
conflits qui ne doivent jamais atteindre l'utilisateur.

Principes :
- aucune limite locale cooldown/par-minute ne bloque +ai/+chat ;
- ``no_cooldown_final`` reste l'autorité finale ;
- les pièces jointes de logs restent correctement associées ;
- la personnalité IA adaptative est réinstallée après les wrappers historiques ;
- ``+diagnostic`` ne produit qu'un seul rapport lorsque V17 est disponible ;
- le superviseur de boucles ne redémarre que les tâches réellement en échec, jamais une
  boucle annulée proprement.

Les quotas journaliers, permissions, règles AutoMod et données métier ne sont pas modifiés.
"""
from __future__ import annotations

import asyncio
import logging
import time
import types
from typing import Any

import discord
from discord.ext import commands, tasks

from utils import checks

logger = logging.getLogger("bot.final-stability-guard")
_MARKER = "_sentrix_final_stability_guard"

_ESSENTIAL_PERMISSIONS = (
    ("view_channel", "Voir le salon"),
    ("send_messages", "Envoyer des messages"),
    ("embed_links", "Intégrer des liens"),
    ("attach_files", "Joindre des fichiers"),
)

_MODULE_PERMISSIONS = (
    ("manage_messages", "Gérer les messages"),
    ("manage_roles", "Gérer les rôles"),
    ("manage_channels", "Gérer les salons"),
    ("kick_members", "Expulser des membres"),
    ("ban_members", "Bannir des membres"),
    ("moderate_members", "Exclure temporairement des membres"),
    ("view_audit_log", "Voir les logs d’audit"),
)


def _disable_ai_local_throttle(bot: commands.Bot) -> bool:
    """Neutralise les deux limites mémoire propres au cog Ai, sans toucher aux quotas DB."""
    cog = bot.get_cog("Ai")
    if cog is None:
        return False

    def no_local_cooldown(_self, _guild_id: int, _user_id: int, _seconds: int):
        return None

    def no_minute_limit(_self, _guild_id: int, _user_id: int, _limit: int) -> bool:
        return False

    no_local_cooldown._sentrix_zero_ai_throttle = True
    no_minute_limit._sentrix_zero_ai_throttle = True
    cog._check_cooldown = types.MethodType(no_local_cooldown, cog)
    cog._check_minute_limit = types.MethodType(no_minute_limit, cog)

    last_used = getattr(cog, "_last_used", None)
    if isinstance(last_used, dict):
        last_used.clear()
    minute_bucket = getattr(cog, "_minute_bucket", None)
    if isinstance(minute_bucket, dict):
        minute_bucket.clear()
    return True


def _install_safe_attachment_archive() -> bool:
    """Évite le décalage attachment/file lorsqu'un téléchargement Discord échoue."""
    try:
        from . import logs_unified_v6 as logs_v6
    except Exception:
        logger.exception("Impossible d'importer logs_unified_v6 pour la garde fichiers.")
        return False

    current = logs_v6._best_effort_files
    if getattr(current, _MARKER, False):
        return True

    async def all_or_none_files(attachments):
        selected = list(attachments or [])[:10]
        files = list(await current(selected))
        if len(files) == len(selected):
            return files

        for file in files:
            close = getattr(file, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass
        logger.warning(
            "Archive fichiers partielle ignorée pour éviter une mauvaise association (%s/%s).",
            len(files),
            len(selected),
        )
        return []

    setattr(all_or_none_files, _MARKER, True)
    all_or_none_files._sentrix_original = current
    logs_v6._best_effort_files = all_or_none_files
    return True


def _reassert_zero_cooldown(bot: commands.Bot) -> bool:
    """Réinstalle l'autorité finale après tous les autres wrappers runtime."""
    try:
        from . import no_cooldown_final

        no_cooldown_final.install(bot)
        return bool(getattr(bot, "no_cooldown_final_state", {}).get("installed"))
    except Exception:
        logger.exception("Réaffirmation zéro cooldown impossible.")
        return False


def _install_ai_personality(bot: commands.Bot) -> bool:
    """Installe la personnalité adaptative après les anciens wrappers IA."""
    try:
        from . import ai_personality_final

        return bool(ai_personality_final.install(bot))
    except Exception:
        logger.exception("Installation de la personnalité IA dynamique impossible.")
        return False


def _loop_really_failed(loop: Any, task: Any) -> bool:
    """Vrai uniquement lorsqu'une Loop s'est terminée à cause d'une erreur.

    ``task.done()`` seul n'est pas suffisant : une tâche annulée lors d'un unload/reload est
    aussi ``done`` et ne doit surtout pas être ressuscitée par le superviseur global.
    """
    if task is None or not task.done() or task.cancelled():
        return False
    try:
        return bool(loop.failed())
    except Exception:
        try:
            return task.exception() is not None
        except Exception:
            return False


def _install_failed_loop_only_supervisor() -> bool:
    """Corrige le superviseur Excellence qui redémarrait aussi les boucles annulées."""
    try:
        from . import bot_excellence_runtime as excellence
    except Exception:
        logger.exception("Superviseur Excellence indisponible pour le correctif final.")
        return False

    current = getattr(excellence, "_restart_failed_loops", None)
    if not callable(current):
        return False
    if getattr(current, "_sentrix_failed_loop_only", False):
        return True

    async def restart_failed_loops(bot: commands.Bot) -> int:
        restarted = 0
        for cog_name, cog in list(bot.cogs.items()):
            for attr_name in dir(cog):
                try:
                    value = getattr(cog, attr_name)
                except Exception:
                    continue
                if not isinstance(value, tasks.Loop):
                    continue
                task = value.get_task()
                if bot.is_closed() or not _loop_really_failed(value, task):
                    continue

                # BotV12Machine possède déjà sa propre maintenance de reprise. Le laisser
                # au superviseur générique créait deux autorités concurrentes.
                if cog_name == "BotV12Machine" and attr_name == "ticket_watch_loop":
                    continue

                try:
                    value.start()
                    restarted += 1
                    record = getattr(excellence, "_record_incident", None)
                    if callable(record):
                        await record(
                            bot,
                            "background_loop_restart",
                            f"{cog_name}.{attr_name} redémarrée après une erreur réelle",
                        )
                except Exception as exc:
                    record = getattr(excellence, "_record_incident", None)
                    if callable(record):
                        await record(
                            bot,
                            "background_loop_restart_failed",
                            f"{cog_name}.{attr_name}: {type(exc).__name__}: {exc}",
                        )
        return restarted

    restart_failed_loops._sentrix_failed_loop_only = True
    restart_failed_loops._sentrix_original = current
    excellence._restart_failed_loops = restart_failed_loops
    return True


def _install_single_v17_diagnostic(bot: commands.Bot) -> bool:
    """Remplace la chaîne ancien diagnostic -> V17 par un unique rapport V17."""
    command = (
        bot.get_command("diagnostic")
        or bot.get_command("diagnose")
        or bot.get_command("diag")
    )
    health = bot.get_cog("V17Health")
    if command is None or health is None:
        return False

    current = command.callback
    if getattr(current, "_sentrix_single_diagnostic", False):
        return True

    async def diagnostic_single(*args, **kwargs):
        ctx = next(
            (value for value in args if isinstance(value, commands.Context)),
            kwargs.get("ctx"),
        )
        cog = bot.get_cog("V17Health")
        if isinstance(ctx, commands.Context) and cog is not None and ctx.guild is not None:
            return await cog.send_report(ctx)
        return await current(*args, **kwargs)

    diagnostic_single._sentrix_single_diagnostic = True
    # Empêche v17_health de remettre ensuite son ancien wrapper "original + V17".
    diagnostic_single._sentrix_v17_diagnostic = True
    diagnostic_single._sentrix_original = current
    command.callback = diagnostic_single
    return True


async def _clear_false_ticket_restart_incidents(bot: commands.Bot) -> None:
    """Retire uniquement les faux positifs générés par l'ancien superviseur."""
    db = getattr(bot, "db", None)
    if db is None:
        return
    try:
        await db.execute(
            "DELETE FROM runtime_incidents "
            "WHERE source='background_loop_restart' "
            "AND detail LIKE 'BotV12Machine.ticket_watch_loop redémarrée automatiquement%'"
        )
    except Exception:
        # La table n'existe pas sur tous les runtimes/tests et ce nettoyage n'est pas vital.
        logger.debug("Nettoyage des faux incidents V12 indisponible.", exc_info=True)


def _state(bot: commands.Bot) -> dict[str, Any]:
    value = getattr(bot, "final_stability_guard_state", None)
    if isinstance(value, dict):
        return value
    value = {}
    bot.final_stability_guard_state = value
    return value


def _missing_permissions(perms: Any, required: tuple[tuple[str, str], ...]) -> list[str]:
    """Retourne uniquement les permissions absentes, sans jamais lever d'exception."""
    if perms is None:
        return [label for _, label in required]
    if bool(getattr(perms, "administrator", False)):
        return []
    return [
        label
        for attr, label in required
        if not bool(getattr(perms, attr, False))
    ]


async def _database_ok(bot: commands.Bot) -> bool:
    """Effectue une vraie lecture DB, bornée à trois secondes."""
    db = getattr(bot, "db", None)
    if db is None:
        return False
    try:
        row = await asyncio.wait_for(db.fetchone("SELECT 1 AS ok"), timeout=3.0)
        if row is None:
            return False
        try:
            return int(row["ok"]) == 1
        except (KeyError, TypeError, ValueError):
            return True
    except Exception:
        return False


def _durable_status(bot: commands.Bot) -> str:
    """Décrit le stockage sans considérer SQLite comme une panne."""
    durable = getattr(bot, "sentrix_durable_store", None)
    if durable is None:
        return "⚠️ état non détecté"
    if bool(getattr(durable, "configured", False)):
        return "✅ PostgreSQL configuré"
    return "ℹ️ SQLite local"


def _guard_detail(state: dict[str, Any]) -> str:
    checks_state = (
        ("Zéro cooldown", "zero_cooldown"),
        ("Throttle IA local neutralisé", "ai_local_throttle_disabled"),
        ("Archives pièces jointes sûres", "safe_attachment_archive"),
        ("Personnalité IA dynamique", "ai_dynamic_personality"),
        ("Superviseur boucles", "failed_loop_only_supervisor"),
        ("Diagnostic unique", "single_v17_diagnostic"),
    )
    return "\n".join(
        f"{'✅' if bool(state.get(key)) else '⚠️'} {label}"
        for label, key in checks_state
    )


def _latency_text(bot: commands.Bot) -> str:
    try:
        value = float(getattr(bot, "latency", 0.0)) * 1000
        if value < 0 or value != value:
            raise ValueError
        return f"{round(value)} ms"
    except (TypeError, ValueError, OverflowError):
        return "indisponible"


class StabilityDiagnostic(commands.Cog, name="StabilityDiagnostic"):
    """Diagnostic runtime staff de secours si aucun diagnostic canonique n'existe."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(name="diagnostic", aliases=["diag"])
    @commands.guild_only()
    @checks.is_owner_or_admin_for("configuration")
    async def diagnostic(self, ctx: commands.Context):
        db_ok = await _database_ok(self.bot)
        discord_ready = bool(self.bot.is_ready() and not self.bot.is_closed())

        me = ctx.guild.me
        if me is None and getattr(self.bot, "user", None) is not None:
            me = ctx.guild.get_member(self.bot.user.id)

        channel_perms = None
        guild_perms = None
        if me is not None:
            guild_perms = me.guild_permissions
            try:
                channel_perms = ctx.channel.permissions_for(me)
            except Exception:
                channel_perms = None

        essential_missing = _missing_permissions(channel_perms, _ESSENTIAL_PERMISSIONS)
        module_missing = _missing_permissions(guild_perms, _MODULE_PERMISSIONS)

        state = getattr(self.bot, "final_stability_guard_state", {}) or {}
        guard_installed = bool(state.get("installed"))
        core_ok = discord_ready and db_ok and guard_installed and not essential_missing

        colour = (
            0x2FBF71 if core_ok and not module_missing
            else 0xF0B232 if core_ok
            else 0xED4245
        )
        embed = discord.Embed(
            title="🩺 Diagnostic SentriX",
            description="Contrôle en direct des éléments essentiels de ce serveur.",
            colour=discord.Colour(colour),
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(
            name="Services",
            value=(
                f"Discord : {'✅ prêt' if discord_ready else '❌ indisponible'}\n"
                f"Base de données : {'✅ opérationnelle' if db_ok else '❌ indisponible'}\n"
                f"Latence : **{_latency_text(self.bot)}**"
            ),
            inline=True,
        )
        embed.add_field(
            name="Runtime",
            value=(
                f"Stability guard : {'✅ actif' if guard_installed else '❌ inactif'}\n"
                f"Stockage : {_durable_status(self.bot)}\n"
                f"Cogs : **{len(self.bot.cogs)}** • Commandes : **{len(self.bot.commands)}**"
            ),
            inline=True,
        )
        embed.add_field(name="Protections finales", value=_guard_detail(state), inline=False)
        embed.add_field(
            name="Permissions essentielles",
            value=(
                "✅ Toutes disponibles dans ce salon."
                if not essential_missing
                else "❌ " + "\n• ".join(essential_missing)
            )[:1024],
            inline=False,
        )
        embed.add_field(
            name="Permissions modules",
            value=(
                "✅ Toutes disponibles."
                if not module_missing
                else "⚠️ " + "\n• ".join(module_missing)
            )[:1024],
            inline=False,
        )
        if core_ok and not module_missing:
            summary = "✅ Aucun problème détecté."
        elif core_ok:
            summary = "⚠️ Le cœur du bot fonctionne, mais certains modules ont des permissions limitées."
        else:
            summary = "❌ Un élément essentiel demande une correction."
        embed.add_field(name="Résultat", value=summary, inline=False)
        embed.set_footer(text="SentriX • Diagnostic staff • aucune donnée sensible affichée")
        await ctx.send(embed=embed)


def install(bot: commands.Bot) -> dict[str, Any]:
    """Applique les réparations idempotentes et expose leur état."""
    zero_cooldown = _reassert_zero_cooldown(bot)
    ai_throttle_disabled = _disable_ai_local_throttle(bot)
    safe_attachment_archive = _install_safe_attachment_archive()
    ai_personality = _install_ai_personality(bot)
    failed_loop_only = _install_failed_loop_only_supervisor()
    single_diagnostic = _install_single_v17_diagnostic(bot)

    state = _state(bot)
    state.update(
        {
            "installed": True,
            "zero_cooldown": zero_cooldown,
            "ai_local_throttle_disabled": ai_throttle_disabled,
            "safe_attachment_archive": safe_attachment_archive,
            "ai_dynamic_personality": ai_personality,
            "failed_loop_only_supervisor": failed_loop_only,
            "single_v17_diagnostic": single_diagnostic,
        }
    )
    setattr(bot, _MARKER, True)

    if not zero_cooldown:
        logger.error("Garde finale active mais l'autorité zéro cooldown n'a pas pu être confirmée.")
    if not ai_throttle_disabled:
        logger.warning("Garde finale : cog Ai absent au moment de l'installation.")
    if not safe_attachment_archive:
        logger.warning("Garde finale : protection archive fichiers non installée.")
    if not ai_personality:
        logger.warning("Garde finale : personnalité IA dynamique non installée.")
    if not failed_loop_only:
        logger.warning("Garde finale : superviseur de boucles non corrigé.")

    logger.warning(
        "Garde stabilité finale active : zéro cooldown=%s, throttle IA=%s, fichiers sûrs=%s, "
        "personnalité IA=%s, boucles failed-only=%s, diagnostic unique=%s.",
        zero_cooldown,
        ai_throttle_disabled,
        safe_attachment_archive,
        ai_personality,
        failed_loop_only,
        single_diagnostic,
    )
    return state


async def setup(bot: commands.Bot) -> None:
    install(bot)

    command_conflict = (
        bot.get_command("diagnostic")
        or bot.get_command("diagnose")
        or bot.get_command("diag")
    )
    if bot.get_cog("StabilityDiagnostic") is None and command_conflict is None:
        await bot.add_cog(StabilityDiagnostic(bot))

    # Repasser après l'éventuel fallback garantit que V17 reste l'unique sortie.
    state = _state(bot)
    state["single_v17_diagnostic"] = _install_single_v17_diagnostic(bot)
    await _clear_false_ticket_restart_incidents(bot)


__all__ = [
    "install",
    "StabilityDiagnostic",
    "_disable_ai_local_throttle",
    "_install_safe_attachment_archive",
    "_reassert_zero_cooldown",
    "_install_ai_personality",
    "_loop_really_failed",
    "_install_failed_loop_only_supervisor",
    "_install_single_v17_diagnostic",
    "_clear_false_ticket_restart_incidents",
    "_missing_permissions",
    "_database_ok",
    "_durable_status",
    "_guard_detail",
    "_latency_text",
]
