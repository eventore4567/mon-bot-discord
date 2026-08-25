"""SentriX V3.8 — finition, stabilité et sécurité transversale.

Cette couche corrige des risques qui se trouvent entre plusieurs runtimes historiques sans
ajouter de commande ni modifier les fonctionnalités métier :

- le rôle modérateur configuré ne peut plus servir de raccourci pour des permissions
  structurelles comme Gérer les rôles/salons/expressions ;
- une interaction slash refusée ou en erreur libère toujours son verrou de concurrence ;
- les vérifications propriétaire/DB restent fail-closed en cas de panne ;
- la hiérarchie du bot échoue proprement si le membre bot n'est pas encore résolu ;
- les grands panneaux d'information conservent un vrai titre au lieu de finir sur
  « Information », et la marque n'est pas répétée inutilement dans l'auteur.
"""
from __future__ import annotations

import inspect
import logging
import re
from typing import Any

import discord
from discord.ext import commands

from utils import checks
from . import command_hardening_v41, final_interaction_policy, permission_guard

logger = logging.getLogger("bot.sentrix-final-quality-v38")

# Un rôle de modération peut couvrir les actions de modération quotidiennes, mais jamais
# des permissions qui permettent de restructurer le serveur ou d'élever des privilèges.
SAFE_MOD_ROLE_PERMISSIONS = frozenset({
    "ban_members",
    "kick_members",
    "moderate_members",
    "manage_messages",
    "manage_nicknames",
    "move_members",
})

_INSTALLED = False


def mod_role_fallback_allowed(permission: str) -> bool:
    return str(permission or "").strip() in SAFE_MOD_ROLE_PERMISSIONS


def _role_id_set(member: Any) -> set[int]:
    result: set[int] = set()
    for role in getattr(member, "roles", ()) or ():
        try:
            result.add(int(role.id))
        except (TypeError, ValueError, AttributeError):
            continue
    return result


async def _safe_is_mod_or_permission(ctx: commands.Context, permission: str) -> bool:
    author = getattr(ctx, "author", None)
    guild = getattr(ctx, "guild", None)
    if not isinstance(author, discord.Member) or guild is None:
        return False

    perms = getattr(author, "guild_permissions", None)
    if perms is not None and bool(getattr(perms, permission, False)):
        return True

    if not mod_role_fallback_allowed(permission):
        return False

    try:
        conf = await ctx.bot.db.get_guild_config(guild.id)
    except Exception:
        logger.exception("V3.8 : lecture du rôle modérateur impossible pour guild=%s", guild.id)
        return False

    mod_role_id = conf["mod_role"] if conf and conf["mod_role"] else None
    if not mod_role_id:
        return False
    try:
        return int(mod_role_id) in _role_id_set(author)
    except (TypeError, ValueError):
        return False


async def _safe_transversal_mod_permission(
    bot: commands.Bot,
    guild: Any,
    author: Any,
    permission: str,
) -> bool:
    if guild is None or author is None:
        return False

    perms = getattr(author, "guild_permissions", None)
    if perms is not None and bool(getattr(perms, permission, False)):
        return True

    if not mod_role_fallback_allowed(permission):
        return False

    guild_id = getattr(guild, "id", None)
    if guild_id is None:
        return False
    try:
        conf = await bot.db.get_guild_config(int(guild_id))
    except Exception:
        logger.exception("V3.8 : lecture du rôle modérateur impossible pour guild=%s", guild_id)
        return False

    mod_role_id = conf["mod_role"] if conf and conf["mod_role"] else None
    if not mod_role_id:
        return False
    try:
        return int(mod_role_id) in _role_id_set(author)
    except (TypeError, ValueError):
        return False


def _patch_permission_helpers() -> None:
    if not getattr(checks.is_mod_or_permission, "_sentrix_v38_safe", False):
        _safe_is_mod_or_permission._sentrix_v38_safe = True
        checks.is_mod_or_permission = _safe_is_mod_or_permission

    current = permission_guard._has_discord_or_modrole_permission
    if not getattr(current, "_sentrix_v38_safe", False):
        _safe_transversal_mod_permission._sentrix_v38_safe = True
        permission_guard._has_discord_or_modrole_permission = _safe_transversal_mod_permission

    owner_check = checks.is_verified_bot_owner
    if not getattr(owner_check, "_sentrix_v38_fail_closed", False):
        async def owner_fail_closed(ctx: commands.Context) -> bool:
            try:
                return bool(await owner_check(ctx))
            except Exception:
                logger.exception(
                    "V3.8 : vérification propriétaire impossible pour user=%s ; accès refusé.",
                    getattr(getattr(ctx, "author", None), "id", None),
                )
                return False

        owner_fail_closed._sentrix_v38_fail_closed = True
        owner_fail_closed._sentrix_original = owner_check
        checks.is_verified_bot_owner = owner_fail_closed

    hierarchy = checks.check_bot_hierarchy
    if not getattr(hierarchy, "_sentrix_v38_safe", False):
        def safe_bot_hierarchy(guild: discord.Guild, target: discord.Member) -> str | None:
            me = getattr(guild, "me", None)
            if me is None:
                return "SentriX ne peut pas vérifier sa hiérarchie pour le moment. Réessaie dans quelques secondes."
            try:
                return hierarchy(guild, target)
            except (AttributeError, TypeError):
                logger.exception("V3.8 : vérification de hiérarchie bot impossible.")
                return "SentriX ne peut pas vérifier la hiérarchie des rôles pour cette action."

        safe_bot_hierarchy._sentrix_v38_safe = True
        safe_bot_hierarchy._sentrix_original = hierarchy
        checks.check_bot_hierarchy = safe_bot_hierarchy


def _patch_permission_denial_release() -> None:
    current = permission_guard.evaluate_interaction_access
    if getattr(current, "_sentrix_v38_release", False):
        return

    async def evaluate_and_release(bot: commands.Bot, interaction: discord.Interaction):
        try:
            decision = await current(bot, interaction)
        except Exception:
            command_hardening_v41.release_slash(interaction)
            raise
        if not decision.allowed:
            command_hardening_v41.release_slash(interaction)
        return decision

    evaluate_and_release._sentrix_v38_release = True
    evaluate_and_release._sentrix_original = current
    permission_guard.evaluate_interaction_access = evaluate_and_release


def _patch_tree_error_release(bot: commands.Bot) -> None:
    installer = final_interaction_policy._install_tree_error
    if not getattr(installer, "_sentrix_v38_release", False):
        original_installer = installer

        def install_tree_error_with_release(target_bot: commands.Bot) -> None:
            original_installer(target_bot)
            current_error = target_bot.tree.on_error
            if getattr(current_error, "_sentrix_v38_release", False):
                return

            async def release_then_error(
                interaction: discord.Interaction,
                error: discord.app_commands.AppCommandError,
            ) -> None:
                command_hardening_v41.release_slash(interaction)
                result = current_error(interaction, error)
                if inspect.isawaitable(result):
                    await result

            release_then_error._sentrix_v38_release = True
            release_then_error._sentrix_original = current_error
            target_bot.tree.on_error = release_then_error

        install_tree_error_with_release._sentrix_v38_release = True
        install_tree_error_with_release._sentrix_original = original_installer
        final_interaction_policy._install_tree_error = install_tree_error_with_release

    # Si la politique finale a déjà été installée, réapplique immédiatement le wrapper.
    if getattr(bot, "_sentrix_final_interaction_policy", False):
        final_interaction_policy._install_tree_error(bot)


def _patch_visual_finish(style_module: Any) -> None:
    if style_module is None:
        return

    promote = getattr(style_module, "_promote_real_title", None)
    if callable(promote) and not getattr(promote, "_sentrix_v38_panel_title", False):
        canonical = re.compile(r"^SentriX\s*•\s*(.+)$", re.I)

        def promote_panel_title(embed: discord.Embed, *, kind: str) -> None:
            original_title = str(getattr(embed, "title", "") or "").strip()
            original_description = str(getattr(embed, "description", "") or "").strip()
            original_field_count = len(getattr(embed, "fields", ()) or ())
            promote(embed, kind=kind)

            # Les résultats courts gardent « Information ». Les vrais panneaux riches
            # récupèrent le nom de leur catégorie si aucun titre métier n'a pu être promu.
            if kind != "info" or str(getattr(embed, "title", "") or "").casefold() != "information":
                return
            match = canonical.match(original_title)
            if match is None:
                return
            if original_field_count < 2 and len(original_description) < 240:
                return
            suffix = match.group(1).strip()
            if suffix:
                embed.title = suffix[:64]

        promote_panel_title._sentrix_v38_panel_title = True
        promote_panel_title._sentrix_original = promote
        style_module._promote_real_title = promote_panel_title

    refine = getattr(style_module, "_refine_embed", None)
    if callable(refine) and not getattr(refine, "_sentrix_v38_brand_dedupe", False):
        def refine_without_duplicate_branding(embed: discord.Embed, *args, **kwargs):
            result = refine(embed, *args, **kwargs)
            if not isinstance(result, discord.Embed):
                return result
            category = kwargs.get("category")
            if not category:
                try:
                    from utils import premium_style
                    category = premium_style.infer_category(
                        command=kwargs.get("command"), embed=result, hint=kwargs.get("category")
                    )
                except Exception:
                    category = None
            try:
                from utils import premium_style
                label = str(premium_style.CATEGORY_NAMES.get(str(category), ""))
            except Exception:
                label = ""
            title = str(getattr(result, "title", "") or "").strip()
            author = getattr(result, "author", None)
            author_name = str(getattr(author, "name", "") or "").strip()
            if label and title.casefold() == label.casefold() and author_name.casefold() == f"sentrix • {label}".casefold():
                icon_url = getattr(author, "icon_url", None)
                if icon_url:
                    result.set_author(name="SentriX", icon_url=str(icon_url))
                else:
                    result.set_author(name="SentriX")
            return result

        refine_without_duplicate_branding._sentrix_v38_brand_dedupe = True
        refine_without_duplicate_branding._sentrix_original = refine
        style_module._refine_embed = refine_without_duplicate_branding


def _install_security_audit(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_v38_security_audit_installed", False):
        return

    async def audit_on_ready() -> None:
        try:
            row = await bot.db.fetchone(
                """
                SELECT COUNT(*) AS total
                FROM bot_managers bm
                WHERE NOT EXISTS (
                    SELECT 1 FROM bot_manager_permissions bmp
                    WHERE bmp.guild_id = bm.guild_id AND bmp.user_id = bm.user_id
                )
                """
            )
            total = int(row["total"] if row else 0)
        except Exception:
            logger.debug("V3.8 : audit des gestionnaires legacy indisponible.", exc_info=True)
            return

        bot._sentrix_v38_legacy_full_access_managers = total
        if total:
            logger.warning(
                "V3.8 sécurité : %s gestionnaire(s) legacy sans catégorie explicite conservent l'accès complet par compatibilité.",
                total,
            )

    bot.add_listener(audit_on_ready, "on_ready")
    bot._sentrix_v38_security_audit_installed = True


def install(bot: commands.Bot, *, style_module: Any = None) -> None:
    global _INSTALLED
    _patch_permission_helpers()
    _patch_permission_denial_release()
    _patch_tree_error_release(bot)
    _patch_visual_finish(style_module)
    _install_security_audit(bot)

    bot._sentrix_final_quality_v38 = True
    if not _INSTALLED:
        logger.info(
            "SentriX V3.8 : finition active — permissions mod-role resserrées, verrous slash auto-libérés, style final harmonisé."
        )
        _INSTALLED = True


__all__ = ["SAFE_MOD_ROLE_PERMISSIONS", "mod_role_fallback_allowed", "install"]
