"""Correctifs finaux SentriX pour +help, le Canary, l'accessibilité et l'UX intelligente.

Cette couche est réappliquée après les autres finaliseurs à chaque chargement d'extension.
Elle garantit donc aussi que +help reste public et que la politique permissions/catalogue
est la dernière décision appliquée au runtime.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from collections import OrderedDict

import discord

from utils import sentrix_panels as panels
from discord.ext import commands

from . import bot_experience_v5, bot_experience_v6

logger = logging.getLogger("bot.final-runtime-polish")


def _truthy(name: str) -> bool:
    return os.getenv(name, "").strip().casefold() in {"1", "true", "yes", "on", "oui"}


def _install_odboug_account_username(bot: commands.Bot) -> None:
    """Renomme uniquement le compte Discord de l'instance Bot'Odboug."""
    if getattr(bot, "_sentrix_odboug_account_username_installed", False):
        return

    from utils.instance_identity import is_odboug_instance

    if not is_odboug_instance():
        return

    desired = (os.getenv("BOT_ACCOUNT_USERNAME") or "Odboug bot").strip()[:32]
    if not desired:
        return

    async def apply_odboug_account_username():
        user = bot.user
        if user is None or user.name == desired:
            return
        try:
            edited = await user.edit(username=desired)
            logger.info(
                "Username global de l'instance Odboug appliqué : %s.",
                getattr(edited, "name", desired),
            )
        except discord.HTTPException:
            logger.exception(
                "Discord a refusé le changement du username global vers %r. "
                "Le pseudo serveur reste néanmoins indépendant.",
                desired,
            )

    bot.add_listener(apply_odboug_account_username, "on_ready")
    bot._sentrix_odboug_account_username_installed = True


async def _bootstrap_community_growth(bot: commands.Bot) -> None:
    """Installe une seule fois les fonctions communautaires et leur dashboard."""
    if getattr(bot, "_sentrix_community_growth_ready", False):
        return
    try:
        from . import community_growth
        await community_growth.setup(bot)

        from web import dashboard
        from web import community_card_polish
        from web import community_growth as community_dashboard
        from web import dashboard_instance_runtime
        from web import instance_dashboard_branding

        community_dashboard.install(dashboard)
        community_card_polish.install(dashboard)
        dashboard_instance_runtime.install(dashboard)
        instance_dashboard_branding.install(dashboard, community_dashboard)
        bot._sentrix_community_growth_ready = True
        logger.info("Community Growth V2 branché au runtime et au dashboard.")
    except Exception:
        logger.exception("Impossible d'installer Community Growth V2.")


def _schedule_community_growth(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_community_growth_scheduled", False):
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    bot._sentrix_community_growth_scheduled = True
    bot._sentrix_community_growth_task = loop.create_task(_bootstrap_community_growth(bot))


async def _bootstrap_sentrix_v2(bot: commands.Bot) -> None:
    """Branche V2/V2.1/V2.2/V2.3 accessibilité et le dashboard live.

    V2.2/V2.3 n'ajoutent aucune commande : elles améliorent les commandes déjà chargées.
    """
    if getattr(bot, "_sentrix_v2_ready", False) and getattr(bot, "_sentrix_accessibility_ready", False):
        return
    try:
        from .sentrix_v2 import SentriXV2
        from .sentrix_v21 import SentriXV21
        from .sentrix_v22 import SentriXV22
        from .sentrix_accessibility import SentriXAccessibility

        if bot.get_cog("SentriXV2") is None:
            await bot.add_cog(SentriXV2(bot))
        if bot.get_cog("SentriXV21") is None:
            await bot.add_cog(SentriXV21(bot))
        if bot.get_cog("SentriXV22") is None:
            await bot.add_cog(SentriXV22(bot))
        if bot.get_cog("SentriXAccessibility") is None:
            await bot.add_cog(SentriXAccessibility(bot))

        from web import dashboard, dashboard_v2_home, dashboard_v21, dashboard_accessibility
        dashboard_v2_home.install(dashboard)
        dashboard_v21.install(dashboard)
        dashboard_accessibility.install(dashboard)

        bot._sentrix_v2_ready = True
        bot._sentrix_v21_ready = True
        bot._sentrix_v22_ready = True
        bot._sentrix_accessibility_ready = True
        logger.info(
            "SentriX V2.3 branché : accessibilité, tolérance aux fautes, mobile et clavier, sans nouvelle commande."
        )
    except Exception:
        logger.exception("Impossible d'installer SentriX V2/V2.1/V2.2/V2.3 accessibilité.")


def _schedule_sentrix_v2(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_v2_scheduled", False):
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    bot._sentrix_v2_scheduled = True
    bot._sentrix_v2_task = loop.create_task(_bootstrap_sentrix_v2(bot))


def _patch_help(bot: commands.Bot) -> None:
    command = bot.get_command("help")
    if command is None:
        return

    # cogs.help est l'unique propriétaire de +help et /help. L'entrée préfixée finale
    # peut être volontairement enregistrée hors Cog ; dans ce cas command.cog == None.
    # Les marqueurs posés par le bootstrap final sont donc l'autorité principale : une
    # ancienne couche V8/V9 ne doit jamais remplacer son callback par root_only_callback.
    cog = getattr(command, "cog", None)
    cog_name = getattr(cog, "qualified_name", "") or getattr(cog, "__cog_name__", "")
    is_official_help = bool(
        getattr(command, "_sentrix_official_help_owner", False)
        or getattr(command, "_sentrix_context_is_internal", False)
        or cog_name == "SentriXHelp"
        or (cog is not None and cog.__class__.__name__ == "OfficialHelp")
    )
    if is_official_help:
        command.hidden = False
        local_checks = getattr(command, "checks", None)
        if isinstance(local_checks, list):
            local_checks.clear()
        app = getattr(command, "app_command", None)
        app_checks = getattr(app, "checks", None)
        if isinstance(app_checks, list):
            app_checks.clear()
        command._sentrix_official_help_owner = True
        command._sentrix_context_is_internal = True
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
            await panels.envoyer(ctx, panels.depuis_embed(discord.Embed(title='Infrastructure SentriX', description='\n'.join(lines), color=5793266)))

        infra_external_callback._sentrix_external_canary = True
        infra_command.callback = infra_external_callback
        infra_command._sentrix_external_canary = True


def _install_intelligent_ux(bot: commands.Bot) -> None:
    """Branche V2.4 après V6, sans modifier le catalogue de commandes."""
    try:
        from . import sentrix_intelligent_ux
        sentrix_intelligent_ux.install(bot)

        from web import dashboard, dashboard_intelligent_ux
        dashboard_intelligent_ux.install(dashboard)
        bot._sentrix_intelligent_ux_ready = bool(
            getattr(bot, "_sentrix_intelligent_router_ready", False)
            or getattr(bot, "_sentrix_intelligent_tickets_ready", False)
        )
    except Exception:
        logger.exception("Impossible d'installer SentriX V2.4 Intelligent UX.")


def _install_command_surface(bot: commands.Bot) -> None:
    """Réapplique toujours en dernier les décisions catalogue et permissions.

    command_access_policy_v2, command_centers_v2 et command_direct_aliases_v2 ont été
    supprimés (commit 2a130d7, "groupe mort des correctifs de logs") : le détecteur de
    code mort de cette passe n'a pas vu que cet import différé (dans le corps de fonction,
    donc invisible à une analyse statique du graphe d'imports) les rendait encore
    atteignables depuis ce module, lui bien vivant. Résultat : ce `from . import (...)`
    levait une ImportError sur le premier nom manquant à CHAQUE démarrage, empêchant même
    les trois modules restants (toujours présents, toujours voulus) de s'exécuter —
    silencieusement avalé par le try/except de help_v8_final_guard.install(). Leur rôle
    (command_access_policy_v2 dupliquait une politique de permissions slash déjà remplacée
    par utils/access_matrix.py ; command_centers_v2/command_direct_aliases_v2 n'ajoutaient
    que des alias slash cosmétiques) confirme qu'ils sont sans remplacement à prévoir.
    """
    from . import (
        command_catalog_cleanup,
        command_hybrid_slash_restore_v3,
        slash_command_budget,
    )

    slash_command_budget.install(bot)
    command_catalog_cleanup.install(bot)
    command_hybrid_slash_restore_v3.install(bot)
    slash_command_budget.finalize(bot)


def install(bot: commands.Bot) -> None:
    _install_odboug_account_username(bot)
    bot_experience_v5._install_reply_and_dm_conversations(bot)
    bot_experience_v5._install_ai_pipeline_upgrade(bot)
    bot_experience_v6.install(bot)
    _install_intelligent_ux(bot)
    _schedule_community_growth(bot)
    _schedule_sentrix_v2(bot)
    _patch_help(bot)
    _patch_canary_readiness(bot)
    _install_command_surface(bot)
