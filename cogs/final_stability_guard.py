"""Dernière garde de stabilité SentriX.

Cette extension reste volontairement petite et non destructive. Elle est chargée après
``cogs.slash_error_completion_guard`` sur Railway et réaffirme quatre invariants qui avaient
encore des chemins historiques concurrents :

- aucune limite locale cooldown/par-minute ne doit bloquer +ai/+chat ;
- l'autorité ``no_cooldown_final`` doit rester active après tous les cogs ;
- un archivage de pièces jointes partiellement téléchargé ne doit jamais associer le
  mauvais fichier à la mauvaise pièce jointe dans les logs ;
- la personnalité IA adaptative doit être installée après tous les wrappers IA historiques.

Elle expose aussi ``+diagnostic`` / ``+diag`` aux administrateurs afin de contrôler en
lecture seule l'état Discord, la base, le stockage durable, les protections finales et les
permissions du bot. Aucune donnée sensible n'est affichée.

Les quotas journaliers IA, permissions, modération de contenu et restrictions de salons/
rôles ne sont pas modifiés. Les réglages cooldown historiques restent en base pour assurer
la compatibilité avec les configurations existantes, mais ils ne throttlent plus le runtime.
"""
from __future__ import annotations

import asyncio
import logging
import types
from typing import Any

import discord
from discord.ext import commands

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
    """Évite le décalage attachment/file lorsqu'un téléchargement Discord échoue.

    ``logs_unified_v6`` construit ensuite sa preview avec ``zip(attachments, files)``. Si
    Discord refuse uniquement le premier fichier, une liste compacte des seuls succès
    décalerait toutes les associations. Le comportement sûr est donc tout-ou-rien : si un
    seul des fichiers demandés manque, le log textuel est conservé mais aucun binaire n'est
    joint. Cela préfère une archive partielle sans fichier à une archive factuellement
    fausse.
    """
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
    """Diagnostic runtime staff, volontairement en lecture seule."""

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

        if essential_missing:
            embed.add_field(
                name=f"❌ Permissions essentielles manquantes ({len(essential_missing)})",
                value="\n".join(f"• {label}" for label in essential_missing)[:1024],
                inline=False,
            )
        else:
            embed.add_field(
                name="Permissions essentielles",
                value="✅ Toutes disponibles dans ce salon.",
                inline=False,
            )

        if module_missing:
            embed.add_field(
                name=f"⚠️ Permissions modules non disponibles ({len(module_missing)})",
                value="\n".join(f"• {label}" for label in module_missing)[:1024],
                inline=False,
            )
        else:
            embed.add_field(
                name="Permissions modules",
                value="✅ Toutes disponibles.",
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
    """Applique les réparations idempotentes et expose leur état pour le diagnostic."""
    zero_cooldown = _reassert_zero_cooldown(bot)
    ai_throttle_disabled = _disable_ai_local_throttle(bot)
    safe_attachment_archive = _install_safe_attachment_archive()
    ai_personality = _install_ai_personality(bot)

    state = _state(bot)
    state.update(
        {
            "installed": True,
            "zero_cooldown": zero_cooldown,
            "ai_local_throttle_disabled": ai_throttle_disabled,
            "safe_attachment_archive": safe_attachment_archive,
            "ai_dynamic_personality": ai_personality,
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

    logger.warning(
        "Garde stabilité finale active : zéro cooldown=%s, throttle IA=%s, fichiers sûrs=%s, personnalité IA=%s.",
        zero_cooldown,
        ai_throttle_disabled,
        safe_attachment_archive,
        ai_personality,
    )
    return state


async def setup(bot: commands.Bot) -> None:
    install(bot)
    command_conflict = bot.get_command("diagnostic") or bot.get_command("diag")
    if bot.get_cog("StabilityDiagnostic") is None and command_conflict is None:
        await bot.add_cog(StabilityDiagnostic(bot))
    elif command_conflict is not None:
        logger.warning(
            "Diagnostic runtime non enregistré : la commande %s existe déjà.",
            command_conflict.qualified_name,
        )


__all__ = [
    "install",
    "StabilityDiagnostic",
    "_disable_ai_local_throttle",
    "_install_safe_attachment_archive",
    "_reassert_zero_cooldown",
    "_install_ai_personality",
    "_missing_permissions",
    "_database_ok",
    "_durable_status",
    "_guard_detail",
    "_latency_text",
]
