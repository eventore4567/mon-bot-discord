"""SentriX V68 — Setup simple, large et help cohérent.

Objectifs UX :
- Permissions n'expose plus de matrice rôle/groupe/commande : un seul bouton ON/OFF ;
- les vraies permissions Discord et les commandes Owner restent toujours protégées ;
- toutes les pages Setup utilisent un bandeau plus large et uniforme ;
- +help et /help utilisent une présentation plus horizontale et expliquent le nouveau Setup.
"""
from __future__ import annotations

import logging
from typing import Any

import discord
from discord.ext import commands

from utils import access_matrix as matrix
from utils import embeds
from . import permission_guard
from . import permission_setup_hardening_v65 as v66
from . import setup_control_center as setup_ui
from . import setup_v2_core as core

logger = logging.getLogger("bot.setup-simple-v68")

RUNTIME_MARKER = "Setup simplifié V68"
SETUP_WIDE_BAR = "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"


def _permissions(author: Any):
    return getattr(author, "guild_permissions", None)


def _is_admin(author: Any) -> bool:
    perms = _permissions(author)
    return bool(perms is not None and getattr(perms, "administrator", False))


def _is_guild_owner(author: Any, guild: Any) -> bool:
    author_id = getattr(author, "id", None)
    owner_id = getattr(guild, "owner_id", None)
    if author_id is None or owner_id is None:
        return False
    try:
        return int(author_id) == int(owner_id)
    except (TypeError, ValueError):
        return False


def _has_native_permission(author: Any, guild: Any, permission: str) -> bool:
    if _is_guild_owner(author, guild) or _is_admin(author):
        return True
    perms = _permissions(author)
    return bool(perms is not None and getattr(perms, permission, False))


def _category_for(name: str) -> str | None:
    for category, names in matrix.CATEGORY_COMMANDS.items():
        if name in names:
            return category
    return None


def _deny(reason: str, policy: str) -> matrix.AccessDecision:
    return matrix.AccessDecision(False, reason, policy)


async def secure_evaluate_v68(
    bot,
    *,
    command_name: Any,
    author: Any,
    guild: Any,
) -> matrix.AccessDecision:
    """Même sécurité que V66, avec ACL SentriX commutable sans toucher à Discord."""
    name = matrix.normalise(command_name)
    if not name:
        return _deny("Commande impossible à identifier.", "invalid")
    # Resolution du nom : une sous-commande declaree plus stricte que son groupe garde
    # son nom complet, toutes les autres heritent de leur racine. Fait ici et pas
    # seulement dans le garde, pour que tout appelant direct obtienne la meme decision.
    name = matrix.resolve_name(name)

    backend = matrix.backend_for(bot)
    raw_user_id = getattr(author, "id", None)
    try:
        user_id = int(raw_user_id) if raw_user_id is not None else None
    except (TypeError, ValueError):
        user_id = None

    if user_id is not None:
        reason = await backend.blacklist_reason(user_id)
        if reason is not None and not await backend.is_global_owner(user_id):
            return _deny(
                f"Vous n'êtes pas autorisé à utiliser SentriX. Raison : {reason}",
                "global-blacklist",
            )

    global_owner = user_id is not None and await backend.is_global_owner(user_id)
    if name in matrix.OWNER_ONLY_COMMANDS:
        if global_owner:
            return matrix.AccessDecision(True, policy="owner-global")
        return _deny(
            "Cette commande est réservée au **propriétaire global de SentriX**.",
            "owner-global",
        )
    if global_owner:
        return matrix.AccessDecision(True, policy="owner-global-bypass")

    guild_id = getattr(guild, "id", None)
    if guild_id is None:
        if name in matrix.PUBLIC_COMMANDS:
            return matrix.AccessDecision(True, policy="public-dm")
        return _deny("Cette commande doit être utilisée dans un serveur.", "guild-required")
    guild_id = int(guild_id)

    module = matrix.module_for_command(name)
    if module and not await backend.module_enabled(guild_id, module):
        label = matrix.MODULE_LABELS.get(module, module)
        return _deny(
            f"Le module **{label}** est désactivé sur ce serveur. "
            "Un administrateur peut le réactiver dans `+setup` ou `/setup`.",
            f"module:{module}:off",
        )

    if module == "ai" and name not in matrix.AI_ALWAYS_ALLOWED:
        features = await backend.ai_features(guild_id)
        if name in matrix.AI_IMAGE_COMMANDS and not features["image_generation_enabled"]:
            return _deny(
                "La **génération d'images IA** est désactivée sur ce serveur.",
                "ai:image-off",
            )
        if not features["commands_enabled"]:
            return _deny(
                "Les **commandes IA** sont désactivées sur ce serveur.",
                "ai:commands-off",
            )

    # (4c) NIVEAU 4 — proprietaire du SERVEUR uniquement.
    # Place AVANT les regles Setup, le bypass proprietaire et le bypass Administrateur :
    # un administrateur Discord ne doit pas pouvoir detruire le serveur.
    if name in matrix.GUILD_OWNER_COMMANDS:
        if _is_guild_owner(author, guild):
            return matrix.AccessDecision(True, policy="guild-owner-only")
        return _deny(
            "Cette commande est reservee au **proprietaire du serveur**.\n"
            "Elle detruit des donnees de maniere irreversible : le role Administrateur "
            "ne suffit pas.",
            "guild-owner-only",
        )

    if name == "setup" and _is_guild_owner(author, guild):
        return matrix.AccessDecision(True, policy="guild-owner:setup-recovery")

    # Les commandes membres restent publiques, quel que soit l'état du module ACL.
    if name in matrix.PUBLIC_COMMANDS:
        return matrix.AccessDecision(True, policy="public")

    # V68 : le bouton Permissions active/désactive uniquement les restrictions SentriX
    # enregistrées. Il ne désactive JAMAIS les permissions Discord natives ci-dessous.
    try:
        permissions_enabled = await core.module_enabled(bot, guild_id, "permissions")
    except Exception:
        logger.exception("État du module Permissions illisible ; mode sûr ACTIF conservé.")
        permissions_enabled = True

    if permissions_enabled:
        explicit, source = await backend.explicit_rule(guild_id, author, name)
        if explicit is False:
            return _deny(
                "Cette commande est **bloquée par SentriX** pour votre rôle.",
                f"setup:{source}:deny",
            )

    required = matrix.DISCORD_PERMISSION_COMMANDS.get(name)
    if required is not None:
        if _has_native_permission(author, guild, required):
            return matrix.AccessDecision(True, policy=f"discord:{required}")
        return _deny(
            f"**Permission Discord requise :** {matrix.permission_label(required)}.",
            f"discord:{required}",
        )

    if name in matrix.CUSTOM_PERMISSION_COMMANDS:
        if (
            _has_native_permission(author, guild, "manage_messages")
            or _has_native_permission(author, guild, "manage_guild")
        ):
            return matrix.AccessDecision(True, policy="discord:embed-staff")
        return _deny(
            "**Permission Discord requise :** Gérer les messages ou Gérer le serveur.",
            "discord:embed-staff",
        )

    category = _category_for(name)
    if category is not None:
        native = v66.CATEGORY_REQUIRED_PERMISSION.get(category, "manage_guild")
        if _has_native_permission(author, guild, native):
            return matrix.AccessDecision(True, policy=f"discord:{native}")
        return _deny(
            f"**Permission Discord requise :** {matrix.permission_label(native)}.",
            f"categorie:{category}",
        )

    if _has_native_permission(author, guild, "administrator"):
        return matrix.AccessDecision(True, policy="fail-closed:administrator")
    return _deny(
        "Cette commande n'a pas encore de niveau d'accès public validé.\n"
        "**Permission Discord requise :** Administrateur.",
        "fail-closed",
    )


def _wide_embed(panel: discord.Embed) -> discord.Embed:
    """Force une empreinte horizontale cohérente sans ajouter de hauteur inutile."""
    description = str(panel.description or "").strip()
    lines = description.splitlines()
    if lines and lines[0].strip() and set(lines[0].strip()) <= {"━", "—", "-", "_"}:
        lines[0] = SETUP_WIDE_BAR
        panel.description = "\n".join(lines)
    else:
        panel.description = f"{SETUP_WIDE_BAR}\n{description}" if description else SETUP_WIDE_BAR
    return panel


def _remove_controls_except_navigation(view) -> None:
    for child in list(view.children):
        if getattr(child, "row", None) != 0:
            view.remove_item(child)


def _patch_setup_surface() -> None:
    cls = setup_ui.SetupView
    if (
        getattr(cls.render, "_sentrix_setup_simple_v68", False)
        and getattr(cls.build_embed, "_sentrix_setup_simple_v68", False)
    ):
        return

    previous_render = cls.render
    previous_build_embed = cls.build_embed

    def render_v68(self) -> None:
        previous_render(self)
        if self.category != "permissions":
            return

        _remove_controls_except_navigation(self)
        toggle = discord.ui.Button(
            label="Activer / Désactiver",
            style=discord.ButtonStyle.primary,
            row=1,
        )

        async def permissions_toggle_cb(interaction: discord.Interaction):
            current = await core.module_enabled(self.bot, self.guild.id, "permissions")
            new_value = not current
            await core.set_module_enabled(
                self.bot,
                self.guild.id,
                "permissions",
                new_value,
                actor_id=interaction.user.id,
            )
            await self.audit(
                interaction.user.id,
                "module:permissions",
                "on" if new_value else "off",
            )
            await self.refresh(interaction)

        toggle.callback = permissions_toggle_cb
        self.add_item(toggle)

    async def build_embed_v68(self) -> discord.Embed:
        if self.category == "permissions":
            enabled = await core.module_enabled(self.bot, self.guild.id, "permissions")
            panel = embeds.brand(
                "SentriX — Permissions",
                "Activez ou désactivez simplement les restrictions supplémentaires de SentriX.",
            )
            panel.add_field(
                name="État",
                value="**ACTIF**" if enabled else "**INACTIF**",
                inline=True,
            )
            panel.add_field(
                name="Protection Discord",
                value="**TOUJOURS ACTIVE**",
                inline=True,
            )
            panel.add_field(
                name="Fonctionnement",
                value=(
                    "Le bouton contrôle uniquement les restrictions SentriX enregistrées. "
                    "Les permissions Discord réelles restent obligatoires pour Ban, Kick, Mute, "
                    "Clear, rôles, salons et toutes les actions staff."
                ),
                inline=False,
            )
            panel.add_field(
                name="Owner",
                value="Les commandes Owner restent réservées au propriétaire global, même si ce module est désactivé.",
                inline=False,
            )
            panel.set_footer(text=f"SentriX • {RUNTIME_MARKER}")
            return _wide_embed(panel)

        panel = await previous_build_embed(self)
        return _wide_embed(panel)

    # V66 vérifie ses marqueurs lors de chaque construction. On les conserve pour éviter
    # qu'il ne réinstalle son ancienne matrice après V68.
    render_v68._sentrix_permissions_v66 = True
    build_embed_v68._sentrix_permissions_v66 = True
    render_v68._sentrix_setup_simple_v68 = True
    build_embed_v68._sentrix_setup_simple_v68 = True
    render_v68._sentrix_previous = previous_render
    build_embed_v68._sentrix_previous = previous_build_embed
    cls.render = render_v68
    cls.build_embed = build_embed_v68
    cls._sentrix_permissions_v66 = True
    cls._sentrix_setup_simple_v68 = True


def _patch_help(bot: commands.Bot) -> None:
    try:
        from . import help as help_mod
    except Exception:
        logger.exception("Help officiel indisponible pendant l'installation V68.")
        return

    if getattr(help_mod, "_sentrix_help_v68", False):
        return

    original_decorate = help_mod._decorate

    def decorate_v68(panel: discord.Embed, current_bot: commands.Bot) -> discord.Embed:
        # Pas de miniature : toute la largeur reste disponible pour le contenu.
        panel.set_thumbnail(url=None)
        return _wide_embed(panel)

    def home_v68(current_bot: commands.Bot, member=None) -> discord.Embed:
        grouped = help_mod._ordered_categories(current_bot, member)
        panel = embeds.help_embed(
            "SentriX — Aide",
            "Toutes les commandes de SentriX au même endroit, avec leur permission réelle.",
        )
        for category, count in grouped.items():
            description = help_mod.CATEGORY_DESCRIPTIONS.get(category, "Commandes SentriX.")
            panel.add_field(
                name=category,
                value=f"{description}\n**{count} commande(s)**",
                inline=True,
            )
        panel.add_field(
            name="Navigation",
            value="Choisissez une catégorie, utilisez **Rechercher**, ou tapez `+help <commande>`.",
            inline=False,
        )
        panel.add_field(
            name="Setup",
            value=(
                "`+setup` et `/setup` centralisent la configuration. Les pages **Permissions** "
                "et **Sécurité** utilisent maintenant un simple bouton **Activer / Désactiver**."
            ),
            inline=False,
        )
        panel.add_field(
            name="Accès",
            value=(
                "Les commandes staff restent visibles dans l'aide mais exigent toujours la "
                "permission Discord indiquée. Les commandes Owner restent privées."
            ),
            inline=False,
        )
        panel.set_footer(text=f"SentriX • Aide V68 • Préfixe {getattr(current_bot, 'command_prefix', '+') if not callable(getattr(current_bot, 'command_prefix', None)) else '+'}")
        return decorate_v68(panel, current_bot)

    def pages_v68(
        current_bot: commands.Bot,
        command_rows: list[commands.Command],
        prefix: str,
        title: str,
    ) -> list[discord.Embed]:
        page_size = 6
        chunks = [command_rows[i:i + page_size] for i in range(0, len(command_rows), page_size)] or [[]]
        pages: list[discord.Embed] = []
        for page_index, chunk in enumerate(chunks, start=1):
            panel = embeds.help_embed(
                f"SentriX — {title}",
                "Choisissez une commande pour voir sa syntaxe et sa permission.",
            )
            if not chunk:
                panel.add_field(name="Aucun résultat", value="Aucune commande trouvée.", inline=False)
            else:
                for command in chunk:
                    panel.add_field(
                        name=help_mod._command_label(current_bot, command, prefix),
                        value=(
                            f"{help_mod._description(command)}\n"
                            f"**Permission :** {help_mod.command_requirement(command)}"
                        ),
                        inline=True,
                    )
            panel.set_footer(text=f"SentriX • Page {page_index}/{len(chunks)}")
            pages.append(decorate_v68(panel, current_bot))
        return pages

    decorate_v68._sentrix_help_v68 = True
    home_v68._sentrix_help_v68 = True
    pages_v68._sentrix_help_v68 = True
    decorate_v68._sentrix_previous = original_decorate
    help_mod._decorate = decorate_v68
    help_mod._home = home_v68
    help_mod._pages = pages_v68
    help_mod._sentrix_help_v68 = True


def _install_permission_runtime() -> None:
    matrix.evaluate = secure_evaluate_v68
    permission_guard.evaluate = secure_evaluate_v68
    permission_guard.access_matrix.evaluate = secure_evaluate_v68


def install(bot: commands.Bot) -> None:
    """Dernière autorité Setup/help, volontairement appelée après V66."""
    _install_permission_runtime()
    setup_ui.CATEGORIES["permissions"] = (
        "Permissions",
        "Activer ou désactiver les restrictions SentriX.",
    )
    _patch_setup_surface()
    _patch_help(bot)
    bot._sentrix_setup_simple_v68 = True
    bot._sentrix_help_v68 = True
    logger.info(
        "V68 actif : Permissions à bouton unique, Setup large, help V68 et permissions Discord natives conservées."
    )


__all__ = ["RUNTIME_MARKER", "SETUP_WIDE_BAR", "secure_evaluate_v68", "install"]
