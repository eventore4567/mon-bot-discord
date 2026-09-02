"""SentriX V66 — verrou runtime des permissions et Setup simplifié.

Cette couche conserve le nom de module V65 pour compatibilité avec le chargeur existant,
mais corrige le problème observé en production : une migration SQL ne doit jamais pouvoir
empêcher l'installation de l'interface sécurisée.

Garanties :
- +commande et /commande utilisent la même décision ;
- une règle Setup peut uniquement BLOQUER, jamais accorder une permission ;
- les permissions Discord natives restent obligatoires pour les actions staff ;
- les commandes owner-global ne sont jamais délégables ;
- les commandes publiques restent publiques ;
- Sécurité est préconfigurée et pilotée par un seul bouton Activer / Désactiver ;
- le constructeur de Setup réapplique ce verrou si une ancienne couche UI a été chargée
  après lui.
"""
from __future__ import annotations

import logging
from typing import Any

import discord
from discord.ext import commands

from utils import access_matrix as matrix
from utils import embeds
from . import permission_guard
from . import setup_control_center as setup_ui
from . import setup_v2_core as core

logger = logging.getLogger("bot.permission-setup-v66")

CATEGORY_REQUIRED_PERMISSION: dict[str, str] = {
    "configuration": "manage_guild",
    "tickets": "manage_guild",
    "moderation": "manage_guild",
    "securite": "manage_guild",
    "economie": "manage_guild",
    "ai": "manage_guild",
    "logs": "manage_guild",
    "complete": "administrator",
}

SAFE_SCOPES = (
    "moderation",
    "securite",
    "tickets",
    "economie",
    "ai",
    "notifications",
    "configuration",
    "complete",
    "other",
)

SCOPE_LABELS = {
    "moderation": "Modération",
    "securite": "Sécurité",
    "tickets": "Tickets",
    "economie": "Économie / gestion",
    "ai": "IA",
    "notifications": "Notifications",
    "configuration": "Configuration",
    "complete": "Administration avancée",
    "other": "Autres commandes staff",
}

RUNTIME_MARKER = "Permissions sécurisées V66"


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


async def secure_evaluate(bot, *, command_name: Any, author: Any, guild: Any) -> matrix.AccessDecision:
    """Décision finale commune aux commandes + et /."""
    name = matrix.normalise(command_name)
    # Meme resolution que la matrice : une sous-commande declaree plus stricte que
    # son groupe garde son nom complet, les autres heritent de leur racine.
    name = matrix.resolve_name(name)
    if not name:
        return _deny("Commande impossible à identifier.", "invalid")

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
    # Duplique volontairement depuis utils/access_matrix.py : V65 reimplemente tout le
    # flux. Sans ce bloc, V65 laissait passer un simple Administrateur sur les commandes
    # destructives des qu'il gagnait la course d'installation contre V68.
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

    # Les ACL de rôle ne peuvent jamais couper les fonctions membre publiques.
    if name in matrix.PUBLIC_COMMANDS:
        return matrix.AccessDecision(True, policy="public")

    # Seul deny est pris en compte. Un ancien allow est volontairement ignoré.
    explicit, source = await backend.explicit_rule(guild_id, author, name)
    if explicit is False:
        return _deny(
            "Cette commande a été **bloquée pour votre rôle** dans `Setup > Permissions`.",
            f"setup:{source}:deny",
        )

    required = matrix.DISCORD_PERMISSION_COMMANDS.get(name)
    if required is not None:
        if _has_native_permission(author, guild, required):
            return matrix.AccessDecision(True, policy=f"discord:{required}")
        return _deny(
            f"**Permission Discord requise :** {matrix.permission_label(required)}.\n"
            "Une règle SentriX peut retirer cet accès, mais ne peut jamais créer cette permission.",
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
        native = CATEGORY_REQUIRED_PERMISSION.get(category, "manage_guild")
        if _has_native_permission(author, guild, native):
            return matrix.AccessDecision(True, policy=f"discord:{native}")
        return _deny(
            f"**Permission Discord requise :** {matrix.permission_label(native)}.\n"
            "Une règle SentriX ne peut pas contourner cette permission.",
            f"categorie:{category}",
        )

    if _has_native_permission(author, guild, "administrator"):
        return matrix.AccessDecision(True, policy="fail-closed:administrator")
    return _deny(
        "Cette commande n'a pas encore de niveau d'accès public validé.\n"
        "**Permission Discord requise :** Administrateur.",
        "fail-closed",
    )


def secure_help_requirement(name: str | None) -> str:
    name = matrix.normalise(name)
    if not name:
        return "Sélectionnez une commande"
    if name in matrix.PUBLIC_COMMANDS:
        return "Tout le monde"
    if name in matrix.OWNER_ONLY_COMMANDS:
        return "Propriétaire global SentriX"
    if name in matrix.CUSTOM_PERMISSION_COMMANDS:
        return "Gérer les messages ou Gérer le serveur"
    required = matrix.DISCORD_PERMISSION_COMMANDS.get(name)
    if required:
        return matrix.permission_label(required)
    category = _category_for(name)
    if category:
        return matrix.permission_label(CATEGORY_REQUIRED_PERMISSION.get(category, "manage_guild"))
    return "Administrateur"


def _commands_for_scope(bot, scope: str) -> list[str]:
    names = list(core.commands_for_scope(bot, scope))
    return sorted({
        matrix.normalise(name)
        for name in names
        if matrix.normalise(name)
        and matrix.normalise(name) not in matrix.PUBLIC_COMMANDS
        and matrix.normalise(name) not in matrix.OWNER_ONLY_COMMANDS
    })


def _first_valid_scope(bot) -> str:
    for scope in SAFE_SCOPES:
        if _commands_for_scope(bot, scope):
            return scope
    return "moderation"


class SafePermissionRoleSelect(discord.ui.RoleSelect):
    def __init__(self, owner):
        self.owner = owner
        super().__init__(
            placeholder="1. Rôle à restreindre",
            min_values=1,
            max_values=1,
            row=2,
        )

    async def callback(self, interaction: discord.Interaction):
        self.owner.selected_permission_role = self.values[0].id
        self.owner.selected_permission_command = None
        self.owner.permission_page = 0
        await self.owner.refresh(interaction)


class SafePermissionScopeSelect(discord.ui.Select):
    def __init__(self, owner):
        self.owner = owner
        options = [
            discord.SelectOption(label=SCOPE_LABELS.get(scope, scope.title()), value=scope)
            for scope in SAFE_SCOPES
            if _commands_for_scope(owner.bot, scope)
        ]
        if not options:
            options = [discord.SelectOption(label="Aucune commande staff", value="__none__")]
        super().__init__(
            placeholder="2. Groupe de commandes",
            options=options[:25],
            row=3,
        )

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] != "__none__":
            self.owner.selected_permission_scope = self.values[0]
            self.owner.selected_permission_command = None
            self.owner.permission_page = 0
        await self.owner.refresh(interaction)


class SafePermissionCommandSelect(discord.ui.Select):
    PAGE_SIZE = 24

    def __init__(self, owner):
        self.owner = owner
        scope = getattr(owner, "selected_permission_scope", _first_valid_scope(owner.bot))
        commands_list = _commands_for_scope(owner.bot, scope)
        page_count = max(1, (len(commands_list) + self.PAGE_SIZE - 1) // self.PAGE_SIZE)
        page = max(0, int(getattr(owner, "permission_page", 0))) % page_count
        owner.permission_page = page
        start = page * self.PAGE_SIZE
        chunk = commands_list[start:start + self.PAGE_SIZE]
        options = [
            discord.SelectOption(
                label=name[:100],
                value=name,
                description=secure_help_requirement(name)[:100],
            )
            for name in chunk
        ]
        if page_count > 1:
            options.append(
                discord.SelectOption(
                    label=f"Page suivante ({page + 1}/{page_count})",
                    value="__next__",
                )
            )
        if not options:
            options = [discord.SelectOption(label="Aucune commande staff", value="__none__")]
        super().__init__(
            placeholder="3. Commande à restreindre",
            options=options[:25],
            row=4,
        )

    async def callback(self, interaction: discord.Interaction):
        value = self.values[0]
        if value == "__next__":
            self.owner.permission_page = int(getattr(self.owner, "permission_page", 0)) + 1
            self.owner.selected_permission_command = None
        elif value != "__none__":
            self.owner.selected_permission_command = value
        await self.owner.refresh(interaction)


async def _permission_decision(view) -> str | None:
    name = matrix.normalise(getattr(view, "selected_permission_command", None))
    if not name:
        return None
    role_id = int(getattr(view, "selected_permission_role", view.guild.default_role.id))
    row = await view.bot.db.fetchone(
        "SELECT decision FROM command_role_permissions "
        "WHERE guild_id=? AND role_id=? AND command_name=?",
        (view.guild.id, role_id, name),
    )
    return "deny" if row and str(row["decision"]).casefold() == "deny" else None


async def _set_restrictive_decision(
    bot,
    guild_id: int,
    role_id: int,
    command_name: str,
    decision: str | None,
    *,
    actor_id: int | None = None,
) -> None:
    await core.ensure_schema(bot)
    name = matrix.normalise(command_name)
    if not name:
        raise ValueError("command_name vide")

    value = None if decision is None else str(decision).casefold()
    if value in {None, "default", "allow", "inherit"}:
        await bot.db.execute(
            "DELETE FROM command_role_permissions WHERE guild_id=? AND role_id=? AND command_name=?",
            (int(guild_id), int(role_id), name),
        )
        return
    if value != "deny":
        raise ValueError("Seuls deny et héritage sont autorisés")

    await bot.db.execute(
        "INSERT INTO command_role_permissions "
        "(guild_id,role_id,command_name,decision,updated_by,updated_at) "
        "VALUES (?,?,?,'deny',?,strftime('%s','now')) "
        "ON CONFLICT(guild_id,role_id,command_name) DO UPDATE SET "
        "decision='deny',updated_by=excluded.updated_by,updated_at=excluded.updated_at",
        (int(guild_id), int(role_id), name, actor_id),
    )


def _category_select(owner):
    try:
        from . import control_center_v3
        return control_center_v3.V3CategorySelect(owner)
    except Exception:
        return setup_ui.CategorySelect(owner)


def _remove_all_but_navigation(view) -> None:
    for child in list(view.children):
        row = getattr(child, "row", None)
        if row is None or row != 0:
            view.remove_item(child)


async def _apply_recommended_security(view, *, enabled: bool, actor_id: int) -> None:
    """Le profil est fixe : à l'activation, toutes les protections supportées sont ON.

    À la désactivation on coupe le module sans effacer les réglages, afin qu'une
    réactivation retrouve immédiatement le profil SentriX.
    """
    if enabled:
        await view.bot.db.execute(
            "INSERT INTO automod_settings (guild_id) VALUES (?) ON CONFLICT(guild_id) DO NOTHING",
            (view.guild.id,),
        )
        fields = [field for field, _label in setup_ui.AUTOMOD]
        if fields:
            assignments = ", ".join(f"{field}=?" for field in fields)
            await view.bot.db.execute(
                f"UPDATE automod_settings SET {assignments} WHERE guild_id=?",
                (*([1] * len(fields)), view.guild.id),
            )
    await core.set_module_enabled(
        view.bot,
        view.guild.id,
        "security",
        enabled,
        actor_id=actor_id,
    )


def _patch_setup_surface() -> None:
    """Pose V66 sur la méthode actuellement finale.

    On vérifie le marqueur de LA MÉTHODE et non un marqueur de classe. Si V2/V3 a
    remplacé render après nous, la prochaine construction de Setup repose V66.
    """
    cls = setup_ui.SetupView
    if (
        getattr(cls.render, "_sentrix_permissions_v66", False)
        and getattr(cls.build_embed, "_sentrix_permissions_v66", False)
    ):
        return

    previous_render = cls.render
    previous_build_embed = cls.build_embed

    def render_v66(self) -> None:
        if self.category == "permissions":
            self.clear_items()
            self.add_item(_category_select(self))

            if not hasattr(self, "selected_permission_role"):
                self.selected_permission_role = self.guild.default_role.id
            scope = getattr(self, "selected_permission_scope", None)
            if scope not in SAFE_SCOPES or not _commands_for_scope(self.bot, scope):
                self.selected_permission_scope = _first_valid_scope(self.bot)
                self.selected_permission_command = None
            if not hasattr(self, "permission_page"):
                self.permission_page = 0
            if not hasattr(self, "selected_permission_command"):
                self.selected_permission_command = None

            everyone = discord.ui.Button(
                label="Cible : @everyone",
                style=discord.ButtonStyle.secondary,
                row=1,
            )
            restrict = discord.ui.Button(
                label="Bloquer / rétablir",
                style=discord.ButtonStyle.danger,
                row=1,
            )

            async def everyone_cb(interaction: discord.Interaction):
                self.selected_permission_role = self.guild.default_role.id
                self.selected_permission_command = None
                self.permission_page = 0
                await self.refresh(interaction)

            async def restrict_cb(interaction: discord.Interaction):
                name = getattr(self, "selected_permission_command", None)
                if not name:
                    return await interaction.response.send_message(
                        "Choisissez d'abord une commande.", ephemeral=True
                    )
                current = await _permission_decision(self)
                next_value = None if current == "deny" else "deny"
                await _set_restrictive_decision(
                    self.bot,
                    self.guild.id,
                    int(self.selected_permission_role),
                    name,
                    next_value,
                    actor_id=interaction.user.id,
                )
                await self.audit(
                    interaction.user.id,
                    f"permission:{matrix.normalise(name)}",
                    "inherit" if next_value is None else "deny",
                )
                await self.refresh(interaction)

            everyone.callback = everyone_cb
            restrict.callback = restrict_cb
            self.add_item(everyone)
            self.add_item(restrict)
            self.add_item(SafePermissionRoleSelect(self))
            self.add_item(SafePermissionScopeSelect(self))
            self.add_item(SafePermissionCommandSelect(self))
            return

        if self.category == "security":
            # On laisse les anciennes couches préparer leur état interne puis on retire
            # tous leurs contrôles détaillés. L'utilisateur n'a plus qu'un seul bouton.
            previous_render(self)
            _remove_all_but_navigation(self)
            toggle = discord.ui.Button(
                label="Activer / Désactiver",
                style=discord.ButtonStyle.primary,
                row=1,
            )

            async def security_toggle_cb(interaction: discord.Interaction):
                current = await core.module_enabled(self.bot, self.guild.id, "security")
                new_value = not current
                await _apply_recommended_security(
                    self,
                    enabled=new_value,
                    actor_id=interaction.user.id,
                )
                await self.audit(
                    interaction.user.id,
                    "module:security",
                    "on" if new_value else "off",
                )
                await self.refresh(interaction)

            toggle.callback = security_toggle_cb
            self.add_item(toggle)
            return

        previous_render(self)

    async def build_embed_v66(self) -> discord.Embed:
        if self.category == "permissions":
            try:
                await core.ensure_schema(self.bot)
            except Exception:
                logger.exception("Schéma permissions indisponible pendant le rendu ; affichage conservé.")

            role_id = int(getattr(self, "selected_permission_role", self.guild.default_role.id))
            role = self.guild.get_role(role_id)
            name = matrix.normalise(getattr(self, "selected_permission_command", None)) or None
            scope = getattr(self, "selected_permission_scope", _first_valid_scope(self.bot))
            try:
                decision = await _permission_decision(self)
            except Exception:
                decision = None

            target = "`@everyone` — membres du serveur" if role_id == self.guild.default_role.id else (
                role.mention if role else f"Rôle introuvable `{role_id}`"
            )
            count = 0
            try:
                row = await self.bot.db.fetchone(
                    "SELECT COUNT(*) AS n FROM command_role_permissions "
                    "WHERE guild_id=? AND decision='deny'",
                    (self.guild.id,),
                )
                count = int(row["n"] if row else 0)
            except Exception:
                pass

            panel = embeds.brand(
                "SentriX — Permissions",
                "Permissions simples et sûres : SentriX peut **retirer** un accès, jamais créer un droit Discord.",
            )
            panel.add_field(name="Mode", value=f"**{RUNTIME_MARKER}**", inline=False)
            panel.add_field(name="Cible", value=target, inline=True)
            panel.add_field(name="Groupe", value=SCOPE_LABELS.get(scope, scope.title()), inline=True)
            panel.add_field(
                name="Commande",
                value=f"`+{name}` / `/{name}`" if name else "Choisissez une commande",
                inline=True,
            )
            panel.add_field(
                name="Accès SentriX",
                value="**BLOQUÉ**" if decision == "deny" else "**HÉRITÉ DE DISCORD**",
                inline=True,
            )
            panel.add_field(
                name="Permission Discord requise",
                value=secure_help_requirement(name),
                inline=True,
            )
            panel.add_field(name="Blocages personnalisés", value=str(count), inline=True)
            panel.add_field(
                name="Fonctionnement",
                value=(
                    '**1.** Choisissez un rôle.\n**2.** Choisissez le groupe puis la commande.\n**3.** Utilisez **Bloquer / rétablir**.\n\nLes commandes `+` et `/` partagent exactement la même règle.'
                ),
                inline=False,
            )
            panel.add_field(
                name="Sécurité",
                value=(
                    "`Ban`, `Kick`, `Mute`, `Clear`, gestion des rôles/salons et autres actions staff "
                    "exigent toujours la **permission Discord réelle** correspondante.\n"
                    "Les commandes Owner ne sont jamais configurables ici. Les commandes membre "
                    "(jeux, argent, classements, invitations, niveaux...) restent publiques."
                ),
                inline=False,
            )
            return panel

        if self.category == "security":
            enabled = await core.module_enabled(self.bot, self.guild.id, "security")
            protection_names = [str(label) for _field, label in setup_ui.AUTOMOD]
            preview = " • ".join(protection_names[:10])
            if len(protection_names) > 10:
                preview += f" • +{len(protection_names) - 10} autres"
            panel = embeds.brand(
                "SentriX — Sécurité",
                "Protection automatique préconfigurée par SentriX. Aucun réglage compliqué à faire.",
            )
            panel.add_field(
                name="État",
                value="**ACTIF**" if enabled else "**INACTIF**",
                inline=True,
            )
            panel.add_field(
                name="Profil",
                value=f"**{len(protection_names)} protections** configurées automatiquement",
                inline=True,
            )
            panel.add_field(
                name="Protections",
                value=preview or "Profil automatique SentriX",
                inline=False,
            )
            panel.add_field(
                name="Utilisation",
                value=(
                    "Utilisez uniquement **Activer / Désactiver**. À l'activation, SentriX applique son profil recommandé. À la désactivation, les réglages sont conservés."
                ),
                inline=False,
            )
            panel.add_field(
                name="Permissions des commandes",
                value=(
                    "Ce bouton ne donne **aucun droit** aux membres. Les commandes de modération, "
                    "administration et Owner restent protégées même si Sécurité est désactivée. "
                    "Les commandes publiques restent utilisables normalement."
                ),
                inline=False,
            )
            panel.add_field(name="Version du panneau", value=f"**{RUNTIME_MARKER}**", inline=False)
            return panel

        return await previous_build_embed(self)

    render_v66._sentrix_permissions_v66 = True
    render_v66._sentrix_previous = previous_render
    build_embed_v66._sentrix_permissions_v66 = True
    build_embed_v66._sentrix_previous = previous_build_embed
    cls.render = render_v66
    cls.build_embed = build_embed_v66
    cls._sentrix_permissions_v65 = True
    cls._sentrix_permissions_v66 = True


def _install_setup_constructor_guard() -> None:
    """Réapplique V66 juste avant chaque nouvelle vue Setup.

    C'est le filet de sécurité contre une ancienne couche chargée après ce module.
    """
    cls = setup_ui.SetupView
    current = cls.__init__
    if getattr(current, "_sentrix_permissions_v66_constructor", False):
        return

    def guarded_init(self, *args, **kwargs):
        _patch_setup_surface()
        return current(self, *args, **kwargs)

    guarded_init._sentrix_permissions_v66_constructor = True
    guarded_init._sentrix_previous = current
    cls.__init__ = guarded_init


def _apply_runtime_patches() -> None:
    # Toujours poser la sécurité AVANT toute migration/lecture de base susceptible d'échouer.
    matrix.evaluate = secure_evaluate
    matrix.help_requirement = secure_help_requirement
    permission_guard.evaluate = secure_evaluate
    permission_guard.access_matrix.evaluate = secure_evaluate
    core.set_role_command_decision = _set_restrictive_decision

    setup_ui.CATEGORIES["permissions"] = (
        "Permissions",
        "Bloquer des commandes staff par rôle sans contourner les permissions Discord.",
    )
    order = list(setup_ui.CATEGORY_ORDER)
    if "permissions" not in order:
        insert_at = order.index("moderation") + 1 if "moderation" in order else 0
        order.insert(insert_at, "permissions")
        setup_ui.CATEGORY_ORDER = tuple(order)

    _patch_setup_surface()
    _install_setup_constructor_guard()


async def install(bot: commands.Bot) -> None:
    # IMPORTANT : ne jamais mettre une requête SQL avant ces patches.
    _apply_runtime_patches()

    # La migration est utile mais non bloquante. Même avec SQLite verrouillée ou une
    # migration incomplète, l'UI et la décision runtime sont déjà sécurisées.
    try:
        await core.ensure_schema(bot)
        await bot.db.execute("DELETE FROM command_role_permissions WHERE decision='allow'")
    except Exception:
        logger.exception(
            "Migration des anciennes règles allow impossible ; elles restent ignorées par V66."
        )

    bot._sentrix_permission_setup_v65 = True
    bot._sentrix_permission_setup_v66 = True
    logger.info(
        "Permissions V66 actives : UI verrouillée, ACL deny-only, permissions Discord natives "
        "et sécurité préconfigurée à bouton unique."
    )


# Le constructeur est protégé dès l'import. Cela ne change pas la matrice globale pendant
# les tests unitaires ; secure_evaluate n'est branchée qu'au moment de install(bot).
_install_setup_constructor_guard()


__all__ = [
    "CATEGORY_REQUIRED_PERMISSION",
    "SAFE_SCOPES",
    "RUNTIME_MARKER",
    "secure_evaluate",
    "secure_help_requirement",
    "install",
]
