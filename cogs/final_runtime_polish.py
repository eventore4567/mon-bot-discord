"""Correctifs finaux SentriX pour +help, le Canary et la surface de commandes.

Cette couche est réappliquée après les autres finaliseurs à chaque chargement d'extension.
Elle garantit donc aussi que +help reste public et que la politique permissions/catalogue
est la dernière décision appliquée au runtime.
"""
from __future__ import annotations

import json
import logging
import os
from collections import OrderedDict

import discord
from discord.ext import commands

logger = logging.getLogger("bot.final-runtime-polish")


def _truthy(name: str) -> bool:
    return os.getenv(name, "").strip().casefold() in {"1", "true", "yes", "on", "oui"}


def _patch_help(bot: commands.Bot) -> None:
    command = bot.get_command("help")
    if command is None:
        return

    from . import help_clean_style, language_runtime

    original_home = getattr(help_clean_style, "_sentrix_root_only_original_home", None)
    if original_home is None:
        original_home = help_clean_style._help_home
        help_clean_style._sentrix_root_only_original_home = original_home

    def root_only_home(bot_obj, guild, prefix: str, is_staff: bool, language: str):
        embed = original_home(bot_obj, guild, prefix, is_staff, language)
        navigation = (
            "Use the category menu below to browse every command.\n"
            "Search opens a keyword search when you need it.\n"
            "No command name is required after +help."
            if language == "en"
            else
            "Utilise le menu de catégories ci-dessous pour parcourir toutes les commandes.\n"
            "Rechercher ouvre une recherche seulement si tu en as besoin.\n"
            "Aucun nom de commande n'est demandé après +help."
        )
        for index, field in enumerate(embed.fields):
            if str(field.name).upper() == "NAVIGATION":
                embed.set_field_at(index, name="NAVIGATION", value=navigation, inline=False)
                break
        return embed

    root_only_home._sentrix_help_root_only = True
    help_clean_style._help_home = root_only_home
    language_runtime._help_home = root_only_home

    async def root_only_callback(cog, ctx: commands.Context):
        return await help_clean_style._clean_help_callback(cog, ctx)

    root_only_callback._sentrix_help_clean_v8 = True
    root_only_callback._sentrix_help_root_only = True
    command.callback = root_only_callback
    command.params = OrderedDict()
    command.usage = ""
    command._sentrix_help_root_only = True

    # Invariant de sécurité/UX : l'aide est une commande membre, jamais staff-only.
    command.hidden = False
    local_checks = getattr(command, "checks", None)
    if isinstance(local_checks, list):
        local_checks.clear()
    app = getattr(command, "app_command", None)
    app_checks = getattr(app, "checks", None)
    if isinstance(app_checks, list):
        app_checks.clear()


def _patch_canary_readiness(bot: commands.Bot) -> None:
    from . import production_readiness_runtime as prod

    if not getattr(prod, "_sentrix_external_canary_audit_patch", False):
        original_audit = prod.audit_guild_configuration

        async def audit_without_local_canary_penalty(bot_obj, guild):
            result = await original_audit(bot_obj, guild)
            if _truthy("SENTRIX_CANARY_MODE"):
                return result

            findings = [
                item for item in result.get("findings", [])
                if str(item.get("title", "")).casefold() != "canary"
            ]
            if len(findings) == len(result.get("findings", [])):
                return result

            score = max(0, 100 - sum(int(item.get("deduction", 0) or 0) for item in findings))
            result = dict(result)
            result["findings"] = findings
            result["score"] = score
            result.setdefault("infra", {})["canary_external"] = True

            try:
                await bot_obj.db.execute(
                    "UPDATE guild_readiness_audits SET score=?, findings_json=? "
                    "WHERE id=(SELECT id FROM guild_readiness_audits WHERE guild_id=? ORDER BY created_at DESC,id DESC LIMIT 1)",
                    (score, json.dumps(findings, ensure_ascii=False), guild.id),
                )
            except Exception:
                logger.debug("Impossible de corriger l'historique readiness Canary.", exc_info=True)
            return result

        audit_without_local_canary_penalty._sentrix_external_canary = True
        prod.audit_guild_configuration = audit_without_local_canary_penalty
        prod._sentrix_external_canary_audit_patch = True

    root = bot.get_command("security")
    infra_command = root.get_command("infra") if isinstance(root, commands.Group) else None
    if infra_command is not None and not getattr(infra_command, "_sentrix_external_canary", False):
        async def infra_external_callback(ctx: commands.Context):
            if not await prod._require_admin(ctx):
                return
            state = await prod._infra_health(ctx.bot)
            durable = state.get("durable", {})
            if _truthy("SENTRIX_CANARY_MODE"):
                canary_line = f"Serveur canary : {state.get('canary_guild_id') or 'NON CONFIGURÉ'}"
            else:
                canary_line = "Canary : SERVICE EXTERNE SÉPARÉ"
            lines = [
                f"Base locale SQLite : {'OK' if durable.get('local_sqlite_ok') else 'ERREUR'}",
                f"PostgreSQL durable : {'OK' if durable.get('postgres_online') else ('CONFIGURÉ MAIS HORS LIGNE' if durable.get('configured') else 'NON CONFIGURÉ')}",
                f"Redis : {'OK' if state.get('redis_online') else ('CONFIGURÉ MAIS HORS LIGNE' if state.get('redis_configured') else 'NON CONFIGURÉ')}",
                f"Sauvegarde S3 : {'CONFIGURÉE' if state.get('s3_configured') else 'NON CONFIGURÉE'}",
                f"Sauvegarde externe utilisable : {'OUI' if state.get('external_backup_ready') else 'NON'}",
                canary_line,
            ]
            if durable.get("last_snapshot_at"):
                lines.append(f"Dernier snapshot PostgreSQL : <t:{int(durable['last_snapshot_at'])}:R>")
            await ctx.send(
                embed=discord.Embed(
                    title="Infrastructure SentriX",
                    description="\n".join(lines),
                    color=0x5865F2,
                )
            )

        infra_external_callback._sentrix_external_canary = True
        infra_command.callback = infra_external_callback
        infra_command._sentrix_external_canary = True


def _install_command_surface(bot: commands.Bot) -> None:
    """Réapplique toujours en dernier les décisions catalogue et permissions."""
    from . import (
        command_access_policy_v2,
        command_catalog_cleanup,
        command_centers_v2,
        command_direct_aliases_v2,
        slash_command_budget,
    )

    # Le budget est installé avant les nouveaux centres/alias pour que leur ajout ne puisse
    # jamais dépasser la limite Discord.
    slash_command_budget.install(bot)
    command_centers_v2.install(bot)
    command_direct_aliases_v2.install(bot)
    command_catalog_cleanup.install(bot)
    command_access_policy_v2.install(bot)
    slash_command_budget.finalize(bot)


def install(bot: commands.Bot) -> None:
    _patch_help(bot)
    _patch_canary_readiness(bot)
    _install_command_surface(bot)
