"""SentriX V65 — permissions Discord natives + Setup ACL restrictif.

Cette couche est installée en dernier, après les anciennes surfaces Setup. Elle ne crée
pas un second système d'autorisation : elle remplace la décision runtime utilisée par
``permission_guard`` et ``utils.access_matrix`` par une politique plus stricte.

Principes :
- +commande et /commande passent par la même fonction ``secure_evaluate`` ;
- les permissions Discord natives restent obligatoires pour toute action privilégiée ;
- Setup > Permissions peut uniquement BLOQUER une commande, jamais accorder un droit ;
- les anciennes règles ``allow`` sont supprimées et traitées comme « hériter » ;
- le rôle staff configuré ne remplace jamais kick/ban/moderate/manage_* ;
- les commandes owner-global restent impossibles à déléguer ;
- les commandes membres restent publiques, sauf arrêt explicite de leur module ;
- les pages Permissions et Sécurité du Setup sont simplifiées et plus explicites.
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

logger = logging.getLogger("bot.permission-setup-v65")

# Les commandes déjà classées dans DISCORD_PERMISSION_COMMANDS gardent leur permission
# exacte. Les centres de configuration restants demandent Gérer le serveur ; les
# opérations « complete » restent Administrateur uniquement.
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
    "economy",
    "economie",
    "levels",
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
    "economy": "Économie membres",
    "economie": "Économie / gestion",
    "levels": "Niveaux",
    "ai": "IA",
    "notifications": "Notifications",
    "configuration": "Configuration",
    "complete": "Administration avancée",
    "other": "Autres commandes staff",
}


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
    """Permission effective Discord, avec owner/admin comme super-utilisateurs natifs."""
    if _is_guild_owner(author, guild) or _is_admin(author):
        return True
    perms = _permissions(author)
    return bool(perms is not None and getattr(perms, permission, False))


def _category_for(name: str) -> str | None:
    for category, commands_in_category in matrix.CATEGORY_COMMANDS.items():
        if name in commands_in_category:
            return category
    return None


def _deny(reason: str, policy: str) -> matrix.AccessDecision:
    return matrix.AccessDecision(False, reason, policy)


async def secure_evaluate(bot, *, command_name: Any, author: Any, guild: Any) -> matrix.AccessDecision:
    """Décision finale V65, commune aux commandes préfixées et slash."""
    name = matrix.normalise(command_name)
    if not name:
        return _deny("Commande impossible à identifier.", "invalid")

    backend = matrix.backend_for(bot)
    raw_user_id = getattr(author, "id", None)
    try:
        user_id = int(raw_user_id) if raw_user_id is not None else None
    except (TypeError, ValueError):
        user_id = None

    # Blacklist globale. Le propriétaire global conserve le chemin de récupération.
    if user_id is not None:
        reason = await backend.blacklist_reason(user_id)
        if reason is not None and not await backend.is_global_owner(user_id):
            return _deny(
                f"Vous n'êtes pas autorisé à utiliser SentriX. Raison : {reason}",
                "global-blacklist",
            )

    global_owner = user_id is not None and await backend.is_global_owner(user_id)

    # Aucun rôle de serveur, Administrateur Discord ou règle Setup ne peut ouvrir ces
    # commandes. C'est le verrou le plus important de la matrice.
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

    # Un module coupé coupe ses commandes, y compris les commandes publiques du module.
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

    # Le propriétaire du serveur ne peut jamais se verrouiller hors du Setup.
    if name == "setup" and _is_guild_owner(author, guild):
        return matrix.AccessDecision(True, policy="guild-owner:setup-recovery")

    # Les commandes membres ne deviennent pas privées à cause d'une règle de rôle.
    # Les modules (IA, économie, tickets...) restent toutefois désactivables plus haut.
    if name in matrix.PUBLIC_COMMANDS:
        return matrix.AccessDecision(True, policy="public")

    # Setup est désormais une ACL de RESTRICTION uniquement. Une ancienne règle allow
    # est volontairement ignorée : elle ne peut plus créer une permission inexistante.
    explicit, source = await backend.explicit_rule(guild_id, author, name)
    if explicit is False:
        return _deny(
            "Cette commande a été **bloquée pour votre rôle** dans "
            "`Setup > Permissions`.",
            f"setup:{source}:deny",
        )

    # Commandes qui possèdent une permission Discord précise.
    required = matrix.DISCORD_PERMISSION_COMMANDS.get(name)
    if required is not None:
        if _has_native_permission(author, guild, required):
            return matrix.AccessDecision(True, policy=f"discord:{required}")
        return _deny(
            f"**Permission Discord requise :** {matrix.permission_label(required)}.\n"
            "Les rôles configurés dans SentriX peuvent bloquer cette commande, "
            "mais ils ne peuvent pas accorder cette permission Discord.",
            f"discord:{required}",
        )

    # +embed conserve deux permissions natives possibles, mais aucune whitelist interne
    # ne peut désormais remplacer ces permissions.
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

    # Toute nouvelle commande non classée reste fermée aux membres. Un administrateur
    # Discord peut l'utiliser, ce qui garde le comportement fail-closed historique.
    if _has_native_permission(author, guild, "administrator"):
        return matrix.AccessDecision(True, policy="fail-closed:administrator")
    return _deny(
        "Cette commande n'a pas encore de niveau d'accès public validé.\n"
        "**Permission Discord requise :** Administrateur.",
        "fail-closed",
    )


def secure_help_requirement(name: str) -> str:
    name = matrix.normalise(name)
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
    return sorted(
        {
            matrix.normalise(name)
            for name in names
            if matrix.normalise(name)
            and matrix.normalise(name) not in matrix.PUBLIC_COMMANDS
            and matrix.normalise(name) not in matrix.OWNER_ONLY_COMMANDS
        }
    )


class SafePermissionRoleSelect(discord.ui.RoleSelect):
    def __init__(self, owner):
        self.owner = owner
        super().__init__(
            placeholder="1. Choisir le rôle à restreindre",
            min_values=1,
            max_values=1,
            row=2,
        )

    async def callback(self, interaction: discord.Interaction):
        role = self.values[0]
        self.owner.selected_permission_role = role.id
        self.owner.selected_permission_command = None
        self.owner.permission_page = 0
        await self.owner.refresh(interaction)


class SafePermissionScopeSelect(discord.ui.Select):
    def __init__(self, owner):
        self.owner = owner
        options = []
        for scope in SAFE_SCOPES:
            if _commands_for_scope(owner.bot, scope):
                options.append(
                    discord.SelectOption(
                        label=SCOPE_LABELS.get(scope, scope.title()),
                        value=scope,
                    )
                )
        super().__init__(
            placeholder="2. Choisir un groupe de commandes",
            options=options[:25],
            row=3,
        )

    async def callback(self, interaction: discord.Interaction):
        self.owner.selected_permission_scope = self.values[0]
        self.owner.selected_permission_command = None
        self.owner.permission_page = 0
        await self.owner.refresh(interaction)


class SafePermissionCommandSelect(discord.ui.Select):
    PAGE_SIZE = 24

    def __init__(self, owner):
        self.owner = owner
        scope = getattr(owner, "selected_permission_scope", "moderation")
        commands_list = _commands_for_scope(owner.bot, scope)
        page_count = max(1, (len(commands_list) + self.PAGE_SIZE - 1) // self.PAGE_SIZE)
        page = max(0, int(getattr(owner, "permission_page", 0))) % page_count
        owner.permission_page = page
        start = page * self.PAGE_SIZE
        chunk = commands_list[start:start + self.PAGE_SIZE]
        options = [
            discord.SelectOption(
                label=f"{name}",
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
            placeholder="3. Choisir la commande",
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
    command_name = getattr(view, "selected_permission_command", None)
    if not command_name:
        return None
    role_id = int(getattr(view, "selected_permission_role", view.guild.default_role.id))
    row = await view.bot.db.fetchone(
        "SELECT decision FROM command_role_permissions "
        "WHERE guild_id=? AND role_id=? AND command_name=?",
        (view.guild.id, role_id, matrix.normalise(command_name)),
    )
    # « allow » n'est plus un état de sécurité valide : il équivaut à hériter.
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
    """Écriture ACL V65 : uniquement deny ou héritage.

    ``allow`` est accepté en entrée pour la compatibilité avec un ancien callback mais
    converti en héritage. Ainsi aucun ancien chemin UI ne peut réintroduire l'élévation.
    """
    await core.ensure_schema(bot)
    name = matrix.normalise(command_name)
    if not name:
        raise ValueError("command_name vide")
    if decision is None or str(decision).casefold() in {"default", "allow", "inherit"}:
        await bot.db.execute(
            "DELETE FROM command_role_permissions WHERE guild_id=? AND role_id=? AND command_name=?",
            (int(guild_id), int(role_id), name),
        )
        return
    if str(decision).casefold() != "deny":
        raise ValueError("V65 accepte uniquement deny ou héritage")
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


def _patch_setup_surface() -> None:
    cls = setup_ui.SetupView
    if getattr(cls, "_sentrix_permissions_v65", False):
        return

    previous_render = cls.render
    previous_build_embed = cls.build_embed

    def render_v65(self) -> None:
        if self.category != "permissions":
            previous_render(self)
            if self.category == "security":
                # Une sélection détaillée reste disponible, plus deux raccourcis ON/OFF.
                for child in self.children:
                    if isinstance(child, setup_ui.AutomodSelect):
                        child.placeholder = "Choisir les protections actives (sélection = ON)"

                all_on = discord.ui.Button(
                    label="Tout activer",
                    style=discord.ButtonStyle.success,
                    row=3,
                )
                all_off = discord.ui.Button(
                    label="Tout désactiver",
                    style=discord.ButtonStyle.secondary,
                    row=3,
                )

                async def set_all(interaction: discord.Interaction, enabled: bool):
                    await self.bot.db.execute(
                        "INSERT INTO automod_settings (guild_id) VALUES (?) "
                        "ON CONFLICT(guild_id) DO NOTHING",
                        (self.guild.id,),
                    )
                    columns = ", ".join(f"{field}=?" for field, _ in setup_ui.AUTOMOD)
                    values = tuple(1 if enabled else 0 for _ in setup_ui.AUTOMOD)
                    await self.bot.db.execute(
                        f"UPDATE automod_settings SET {columns} WHERE guild_id=?",
                        (*values, self.guild.id),
                    )
                    await self.audit(
                        interaction.user.id,
                        "protections",
                        "all_on" if enabled else "all_off",
                    )
                    await self.refresh(interaction)

                async def on_cb(interaction: discord.Interaction):
                    await set_all(interaction, True)

                async def off_cb(interaction: discord.Interaction):
                    await set_all(interaction, False)

                all_on.callback = on_cb
                all_off.callback = off_cb
                # Discord limite une vue à 5 lignes ; row=3 reste libre dans la page
                # sécurité V3 standard.
                self.add_item(all_on)
                self.add_item(all_off)
            return

        self.clear_items()
        self.add_item(_category_select(self))
        if not hasattr(self, "selected_permission_role"):
            self.selected_permission_role = self.guild.default_role.id
        if getattr(self, "selected_permission_scope", "public") not in SAFE_SCOPES:
            self.selected_permission_scope = "moderation"
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
            label="Bloquer / rétablir la commande",
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

    async def build_embed_v65(self) -> discord.Embed:
        if self.category != "permissions":
            panel = await previous_build_embed(self)
            if self.category is None and len(panel.fields) < 24:
                panel.add_field(
                    name="Permissions sûres",
                    value=(
                        "Les droits sensibles utilisent les permissions Discord natives. "
                        "La page **Permissions** sert uniquement à retirer un accès."
                    ),
                    inline=False,
                )
            if self.category == "security" and len(panel.fields) < 24:
                panel.add_field(
                    name="Utilisation rapide",
                    value=(
                        "Dans le menu, une protection sélectionnée = **ON**. "
                        "Utilisez **Tout activer** ou **Tout désactiver** pour appliquer "
                        "un profil complet en un clic."
                    ),
                    inline=False,
                )
            return panel

        await core.ensure_schema(self.bot)
        role_id = int(getattr(self, "selected_permission_role", self.guild.default_role.id))
        role = self.guild.get_role(role_id)
        target = role.mention if role else "@everyone"
        scope = getattr(self, "selected_permission_scope", "moderation")
        name = getattr(self, "selected_permission_command", None)
        decision = await _permission_decision(self)
        row = await self.bot.db.fetchone(
            "SELECT COUNT(*) AS n FROM command_role_permissions "
            "WHERE guild_id=? AND decision='deny'",
            (self.guild.id,),
        )
        count = int(row["n"] if row else 0)

        panel = embeds.brand(
            "SentriX — Permissions",
            "Contrôlez les commandes staff sans pouvoir contourner les permissions Discord.",
        )
        panel.add_field(name="Cible", value=target, inline=True)
        panel.add_field(
            name="Groupe",
            value=SCOPE_LABELS.get(scope, scope.title()),
            inline=True,
        )
        panel.add_field(
            name="Commande",
            value=f"`+{name}` / `/{name}`" if name else "Aucune sélectionnée",
            inline=True,
        )
        panel.add_field(
            name="Accès SentriX",
            value="**BLOQUÉ**" if decision == "deny" else "**HÉRITÉ DE DISCORD**",
            inline=True,
        )
        panel.add_field(
            name="Permission Discord requise",
            value=secure_help_requirement(name) if name else "Sélectionnez une commande",
            inline=True,
        )
        panel.add_field(
            name="Règles personnalisées",
            value=f"**{count}** blocage(s) configuré(s)",
            inline=True,
        )
        panel.add_field(
            name="Règle de sécurité",
            value=(
                "Un rôle SentriX peut **retirer** l'accès à une commande, mais ne peut jamais "
                "donner `Ban`, `Kick`, `Modérer`, `Gérer les messages`, `Gérer les rôles`, "
                "`Gérer le serveur` ou `Administrateur` si Discord ne les accorde pas déjà.\n"
                "Les commandes réservées au propriétaire global ne sont jamais configurables ici."
            ),
            inline=False,
        )
        panel.add_field(
            name="Comment l'utiliser",
            value=(
                "**1.** Choisissez le rôle à restreindre.\n"
                "**2.** Choisissez le groupe.\n"
                "**3.** Choisissez la commande.\n"
                "**4.** Cliquez sur **Bloquer / rétablir la commande**.\n\n"
                "La même règle s'applique automatiquement à `+commande` et `/commande`."
            ),
            inline=False,
        )
        return panel

    cls.render = render_v65
    cls.build_embed = build_embed_v65
    cls._sentrix_permissions_v65 = True


async def install(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_permission_setup_v65", False):
        return

    await core.ensure_schema(bot)

    # Migration sûre et idempotente : une ancienne autorisation explicite redevient
    # l'héritage Discord. Les refus existants sont conservés.
    await bot.db.execute("DELETE FROM command_role_permissions WHERE decision='allow'")

    # Même fonction pour les imports historiques et pour les deux transports actifs.
    matrix.evaluate = secure_evaluate
    matrix.help_requirement = secure_help_requirement
    permission_guard.evaluate = secure_evaluate
    permission_guard.access_matrix.evaluate = secure_evaluate
    core.set_role_command_decision = _set_restrictive_decision

    # La page existe même si une ancienne couche Setup n'a pas été chargée.
    setup_ui.CATEGORIES["permissions"] = (
        "Permissions",
        "Restreindre les commandes staff par rôle sans contourner les droits Discord.",
    )
    order = list(setup_ui.CATEGORY_ORDER)
    if "permissions" not in order:
        insert_at = order.index("moderation") + 1 if "moderation" in order else 0
        order.insert(insert_at, "permissions")
        setup_ui.CATEGORY_ORDER = tuple(order)

    _patch_setup_surface()

    bot._sentrix_permission_setup_v65 = True
    logger.info(
        "Permissions V65 actives : droits Discord obligatoires, ACL Setup deny-only, "
        "owner-global non délégable et UI Permissions/Sécurité simplifiée."
    )


__all__ = [
    "CATEGORY_REQUIRED_PERMISSION",
    "SAFE_SCOPES",
    "secure_evaluate",
    "secure_help_requirement",
    "install",
]
