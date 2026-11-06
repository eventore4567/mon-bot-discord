"""SentriX final regression runtime.

Loaded by ``cogs.sentrix_regression_fix`` at the very end of Railway startup.
The module intentionally lives outside ``cogs/`` so the compatibility shim remains tiny.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import types
from typing import Any

import discord
from discord.ext import commands

from utils.audit_trail import journaliser
from utils import sentrix_emojis

logger = logging.getLogger("bot.sentrix-regression-runtime")

_ROLE_MENTION_RE = re.compile(r"^<@&(\d+)>$")
_DEFAULT_REACTION_EMOJIS = (
    "✅", "🔔", "⭐", "🎮", "🎁", "🎉", "📢", "🧩", "🛡️", "🎫",
    "💬", "📌", "🏆", "🎵", "🚀", "💎", "🌙", "☀️", "🍀", "🔥",
)

_REACTION_SCHEMA = """
CREATE TABLE IF NOT EXISTS sentrix_reaction_role_panels (
    message_id INTEGER PRIMARY KEY,
    guild_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    mappings_json TEXT NOT NULL,
    created_by INTEGER NOT NULL,
    created_at INTEGER NOT NULL
)
"""

_ROLE_PANEL_SCHEMA = """
CREATE TABLE IF NOT EXISTS sentrix_role_panels (
    message_id INTEGER PRIMARY KEY,
    guild_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    mode TEXT NOT NULL,
    role_ids_json TEXT NOT NULL DEFAULT '[]',
    mappings_json TEXT NOT NULL DEFAULT '[]',
    created_by INTEGER NOT NULL,
    created_at INTEGER NOT NULL
)
"""


def _emoji_key(value: Any) -> str:
    if isinstance(value, discord.PartialEmoji):
        return f"custom:{value.id}" if value.id else f"unicode:{value.name or str(value)}"
    text = str(value or "").strip()
    parsed = discord.PartialEmoji.from_str(text)
    if parsed.id:
        return f"custom:{parsed.id}"
    return f"unicode:{parsed.name or text}"


def _install_dashboard_loader_fix() -> bool:
    """Make the actual HTML served by /app obey the hidden state."""
    try:
        from web import dashboard
        from web import dashboard_oxyde_hotfix as hotfix
    except Exception:
        logger.exception("Dashboard Oxyde unavailable for final loader fix.")
        return False

    rule = "#emptyState.sx-empty-premium.hidden{display:none!important}"
    css = str(getattr(hotfix, "HOTFIX_CSS", "") or "")
    if rule not in css:
        if "</style>" in css:
            css = css.replace("</style>", f"  {rule}\n</style>", 1)
        else:
            css += f"\n<style>{rule}</style>\n"
        hotfix.HOTFIX_CSS = css

    html = str(getattr(dashboard, "INDEX_HTML", "") or "")
    marker = 'id="sentrix-final-loader-guard"'
    if 'id="sentrix-dashboard-unified-v2"' in html:
        return True  # aucun #emptyState hérité dans le programme unique
    if marker not in html:
        guard = (
            '\n<style id="sentrix-final-loader-guard">'
            '#emptyState.sx-empty-premium.hidden{display:none!important}'
            '#emptyState.hidden{display:none!important}'
            '</style>\n'
        )
        html = html.replace("</head>", guard + "</head>", 1) if "</head>" in html else guard + html
        dashboard.INDEX_HTML = html
    return marker in str(getattr(dashboard, "INDEX_HTML", ""))


def _install_setup_invitations(bot: commands.Bot) -> bool:
    try:
        from cogs.setup_invitations import install
        install(bot)
        return True
    except Exception:
        logger.exception("Final invitation setup install failed.")
        return False


def _disable_legacy_role_autocreate(bot: commands.Bot) -> bool:
    """Prevent the historical notification panel from ever creating preset roles."""
    try:
        from cogs import rolepanel_notifications as legacy
    except Exception:
        logger.exception("Legacy role panel module unavailable.")
        return False

    legacy._catalog_role_ids = lambda _guild: []
    cog = bot.get_cog("NotificationRolePanels")
    if cog is not None:
        async def existing_only(_self, _guild: discord.Guild) -> list[discord.Role]:
            return []
        existing_only._sentrix_existing_roles_only = True
        cog._ensure_roles = types.MethodType(existing_only, cog)
    return True


def _role_ids(values: Any) -> list[int]:
    result: list[int] = []
    for value in values or []:
        raw = getattr(value, "id", value)
        try:
            role_id = int(raw)
        except (TypeError, ValueError):
            continue
        if role_id not in result:
            result.append(role_id)
    return result[:20]


def _valid_roles(guild: discord.Guild, role_ids: list[int]) -> tuple[list[discord.Role], list[str]]:
    me = guild.me
    if me is None:
        return [], ["Le membre SentriX est indisponible dans le cache Discord."]
    valid: list[discord.Role] = []
    errors: list[str] = []
    for role_id in role_ids[:20]:
        role = guild.get_role(int(role_id))
        if role is None:
            errors.append(f"Rôle supprimé : `{role_id}`")
            continue
        if role.is_default():
            errors.append("@everyone ne peut pas être utilisé.")
            continue
        if role.managed:
            errors.append(f"{role.name} est géré par une intégration.")
            continue
        if role >= me.top_role:
            errors.append(f"Le rôle de SentriX doit être placé au-dessus de **{role.name}**.")
            continue
        from cogs.economy import _self_assignable_role_error
        error = _self_assignable_role_error(guild, role)
        if error:
            errors.append(error)
            continue
        valid.append(role)
    return valid, errors


def _dropdown_embed(guild: discord.Guild, role_ids: list[int]) -> discord.Embed:
    roles, _ = _valid_roles(guild, role_ids)
    lines = "\n".join(f"• {role.mention}" for role in roles)
    embed = discord.Embed(
        title="Choisissez vos rôles",
        description=(
            "Sélectionnez un ou plusieurs rôles dans le menu ci-dessous.\n"
            "Un rôle absent sera ajouté ; un rôle déjà possédé sera retiré.\n\n"
            + (lines or "Aucun rôle configuré.")
        ),
        colour=0x7658E8,
    )
    embed.set_footer(text="SentriX • Rôles existants uniquement")
    return embed


def _reaction_embed(guild: discord.Guild, mappings: list[dict[str, Any]]) -> discord.Embed:
    lines: list[str] = []
    for item in mappings:
        role = guild.get_role(int(item["role_id"]))
        if role is not None:
            lines.append(f"{item['emoji']}  →  {role.mention}")
    embed = discord.Embed(
        title="Choisissez vos rôles",
        description=(
            "Ajoutez une réaction pour recevoir le rôle correspondant.\n"
            "Retirez la réaction pour retirer automatiquement le rôle.\n\n"
            + ("\n".join(lines) if lines else "Aucun rôle configuré.")
        ),
        colour=0x7658E8,
    )
    embed.set_footer(text="SentriX • Rôles par réactions")
    return embed


async def _save_panel(
    bot: commands.Bot,
    message: discord.Message,
    *,
    mode: str,
    role_ids: list[int],
    mappings: list[dict[str, Any]] | None,
    creator_id: int,
) -> None:
    await bot.db.execute(
        "INSERT INTO sentrix_role_panels "
        "(message_id,guild_id,channel_id,mode,role_ids_json,mappings_json,created_by,created_at) "
        "VALUES (?,?,?,?,?,?,?,?) "
        "ON CONFLICT(message_id) DO UPDATE SET "
        "mode=excluded.mode,role_ids_json=excluded.role_ids_json,"
        "mappings_json=excluded.mappings_json,channel_id=excluded.channel_id",
        (
            message.id,
            message.guild.id,
            message.channel.id,
            mode,
            json.dumps(role_ids[:20], separators=(",", ":")),
            json.dumps(mappings or [], ensure_ascii=False, separators=(",", ":")),
            int(creator_id),
            int(time.time()),
        ),
    )

    if mode == "reaction":
        from utils.reaction_role_options import register_legacy_panel
        await register_legacy_panel(bot, guild_id=message.guild.id, channel_id=message.channel.id,
                                    message_id=message.id, mappings=mappings or [],
                                    creator_id=creator_id, created_at=int(time.time()))


class ExistingRoleSelect(discord.ui.Select):
    def __init__(self, guild: discord.Guild, role_ids: list[int]):
        roles, _ = _valid_roles(guild, role_ids)
        options = [
            discord.SelectOption(label=role.name[:100], value=str(role.id), description="Ajouter ou retirer ce rôle")
            for role in roles[:20]
        ]
        if not options:
            options = [discord.SelectOption(label="Aucun rôle disponible", value="0")]
        super().__init__(
            placeholder="Choisir les rôles à ajouter ou retirer…",
            min_values=1,
            max_values=max(1, len(options)),
            options=options,
            custom_id="sentrix:rolepanel:existing-dropdown",
            disabled=options[0].value == "0",
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            return await interaction.edit_original_response(content="Ce panneau fonctionne uniquement dans un serveur.")
        me = interaction.guild.me
        if me is None or not me.guild_permissions.manage_roles:
            return await interaction.edit_original_response(content="SentriX a besoin de la permission **Gérer les rôles**.")

        selected = [
            interaction.guild.get_role(int(value))
            for value in self.values
            if value.isdigit() and value != "0"
        ]
        roles = [
            role for role in selected
            if role is not None and not role.managed and not role.is_default() and role < me.top_role
        ]
        if not roles:
            return await interaction.edit_original_response(content="Aucun rôle modifiable n'a été sélectionné.")

        current = {role.id for role in interaction.user.roles}
        to_add = [role for role in roles if role.id not in current]
        to_remove = [role for role in roles if role.id in current]
        try:
            if to_add:
                await interaction.user.add_roles(*to_add, reason="SentriX • rolepanel menu déroulant")
            if to_remove:
                await interaction.user.remove_roles(*to_remove, reason="SentriX • rolepanel menu déroulant")
        except discord.Forbidden:
            return await interaction.edit_original_response(content="SentriX ne peut pas modifier un de ces rôles. Vérifiez la hiérarchie des rôles.")
        except discord.HTTPException:
            return await interaction.edit_original_response(content="Discord a refusé la modification. Réessayez dans quelques secondes.")

        parts: list[str] = []
        if to_add:
            parts.append("Ajouté : " + ", ".join(role.name for role in to_add))
        if to_remove:
            parts.append("Retiré : " + ", ".join(role.name for role in to_remove))
        await interaction.edit_original_response(content="\n".join(parts) or "Aucun changement.")


class ExistingDropdownPanel(discord.ui.View):
    def __init__(self, guild: discord.Guild, role_ids: list[int]):
        super().__init__(timeout=None)
        self.add_item(ExistingRoleSelect(guild, role_ids))


#: Modèles prêts à l'emploi (04/11/2026 : « pourquoi ça propose pas de rôles ? »).
#: Les rôles déjà présents (même nom) sont réutilisés ; seuls les manquants sont créés.
ROLE_PRESETS: dict[str, tuple[str, str, tuple[tuple[str, int], ...]]] = {
    "notifications": ("🔔 Notifications", "Annonces, événements, giveaways, sondages", (
        ("🔔 Annonces", 0x5865F2), ("🎉 Événements", 0xEB459E), ("🎁 Giveaways", 0xF1C40F),
        ("📊 Sondages", 0x3BA55D), ("🤝 Partenariats", 0x1ABC9C),
    )),
    "couleurs": ("🎨 Couleurs de pseudo", "Rouge, orange, jaune, vert, bleu, violet, rose", (
        ("🔴 Rouge", 0xED4245), ("🟠 Orange", 0xE67E22), ("🟡 Jaune", 0xF1C40F),
        ("🟢 Vert", 0x57F287), ("🔵 Bleu", 0x3498DB), ("🟣 Violet", 0x9B59B6), ("🌸 Rose", 0xFF73FA),
    )),
    "jeux": ("🎮 Jeux", "Minecraft, Fortnite, Valorant, GTA, LoL, Roblox", (
        ("⛏️ Minecraft", 0x57A64A), ("🪂 Fortnite", 0x9D4DFF), ("🎯 Valorant", 0xFF4655),
        ("🚗 GTA", 0x2ECC71), ("⚔️ League of Legends", 0xC89B3C), ("🧱 Roblox", 0xE2231A),
    )),
    "pronoms": ("💬 Pronoms", "il/lui, elle, iel, tous pronoms", (
        ("il/lui", 0x3498DB), ("elle", 0xEB459E), ("iel", 0x9B59B6), ("tous pronoms", 0x95A5A6),
    )),
}


async def creer_roles_du_modele(guild: discord.Guild, cle: str) -> tuple[list[discord.Role], list[str]]:
    """Rôles du modèle : existants réutilisés, manquants créés. (rôles, erreurs)"""
    _titre, _desc, roles_modele = ROLE_PRESETS[cle]
    obtenus: list[discord.Role] = []
    erreurs: list[str] = []
    for nom, couleur in roles_modele:
        existant = discord.utils.find(lambda r, n=nom: r.name.casefold() == n.casefold(), guild.roles)
        if existant is not None:
            obtenus.append(existant)
            continue
        try:
            obtenus.append(await guild.create_role(
                name=nom, colour=discord.Colour(couleur), mentionable=False,
                reason="SentriX • modèle de panneau de rôles",
            ))
        except discord.Forbidden:
            erreurs.append(f"{nom} : permission « Gérer les rôles » manquante")
            break
        except discord.HTTPException as exc:
            erreurs.append(f"{nom} : refusé par Discord ({getattr(exc, 'status', '?')})")
    return obtenus, erreurs


class BuilderRolePicker(discord.ui.RoleSelect):
    def __init__(self, parent: "RolePanelBuilder"):
        self.parent_builder = parent
        super().__init__(
            placeholder="Choisir des rôles existants…",
            min_values=1,
            max_values=20,
            custom_id=f"sentrix:rolepanel-builder:roles:{parent.owner_id}",
        )

    async def callback(self, interaction: discord.Interaction):
        self.parent_builder.selected_role_ids = _role_ids(self.values)
        await self.parent_builder.refresh(interaction)


class BuilderChannelPicker(discord.ui.ChannelSelect):
    def __init__(self, parent: "RolePanelBuilder"):
        self.parent_builder = parent
        super().__init__(
            placeholder="Salon où publier le panneau…",
            channel_types=[discord.ChannelType.text, discord.ChannelType.news],
            min_values=1, max_values=1,
            default_values=[parent.guild.get_channel(parent.channel_id)] if parent.channel_id and parent.guild.get_channel(parent.channel_id) else [],
            custom_id=f"sentrix:rolepanel-builder:channel:{parent.owner_id}",
        )

    async def callback(self, interaction: discord.Interaction):
        self.parent_builder.channel_id = self.values[0].id
        await self.parent_builder.refresh(interaction)


class BuilderPresetSelect(discord.ui.Select):
    def __init__(self, parent: "RolePanelBuilder"):
        self.parent_builder = parent
        super().__init__(
            placeholder="…ou un modèle prêt à l'emploi",
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(label=titre, value=cle, description=desc[:100])
                for cle, (titre, desc, _roles) in ROLE_PRESETS.items()
            ],
            custom_id=f"sentrix:rolepanel-builder:preset:{parent.owner_id}",
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        roles, erreurs = await creer_roles_du_modele(self.parent_builder.guild, self.values[0])
        ids = list(dict.fromkeys([*self.parent_builder.selected_role_ids, *(r.id for r in roles)]))[:20]
        self.parent_builder.selected_role_ids = ids
        self.parent_builder.erreurs = erreurs
        self.parent_builder.rebuild()
        await interaction.edit_original_response(view=self.parent_builder)


class BuilderModeSelect(discord.ui.Select):
    def __init__(self, parent: "RolePanelBuilder"):
        self.parent_builder = parent
        super().__init__(
            placeholder="Mode du panneau…",
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(label="Menu déroulant", value="dropdown", emoji=sentrix_emojis.partiel("role"), description="Les membres choisissent dans un menu.", default=parent.mode == "dropdown"),
                discord.SelectOption(label="Réactions emoji", value="reaction", emoji=sentrix_emojis.partiel("role"), description="Une réaction ajoute ou retire le rôle.", default=parent.mode == "reaction"),
            ],
            custom_id=f"sentrix:rolepanel-builder:mode:{parent.owner_id}",
        )

    async def callback(self, interaction: discord.Interaction):
        self.parent_builder.mode = self.values[0]
        await self.parent_builder.refresh(interaction)


class RolePanelBuilder(discord.ui.LayoutView):
    """Constructeur de panneau de rôles en carte Components V2 (04/11/2026).

    Avant : un embed + des menus, aplati en texte brut par une couche d'envoi,
    et seulement des rôles existants. Maintenant : une vraie carte, les menus
    dans la carte, et des modèles prêts à l'emploi (rôles manquants créés).
    """

    def __init__(self, bot: commands.Bot, guild: discord.Guild, owner_id: int, *, mode: str = "dropdown", allow_mode_switch: bool = True):
        super().__init__(timeout=300)
        self.bot = bot
        self.guild = guild
        self.owner_id = int(owner_id)
        self.mode = mode if mode in {"dropdown", "reaction"} else "dropdown"
        self.allow_mode_switch = allow_mode_switch
        self.selected_role_ids: list[int] = []
        self.channel_id: int | None = None
        self.erreurs: list[str] = []
        self.message: discord.Message | None = None
        self.rebuild()

    def _texte(self) -> str:
        roles = [self.guild.get_role(role_id) for role_id in self.selected_role_ids]
        roles = [role for role in roles if role is not None]
        selection = "\n".join(f"> {role.mention}" for role in roles) or "> *Aucun rôle pour l'instant.*"
        mode = "Menu déroulant" if self.mode == "dropdown" else "Réactions emoji"
        lignes = [
            "## " + sentrix_emojis.titre("role", "Panneau de rôles"),
            "Choisissez vos **rôles existants**, le **salon de publication** et le mode, puis **Créer le panneau**.",
            "",
            f"**Mode** · {mode}",
            f"**Salon** · {f'<#{self.channel_id}>' if self.channel_id else 'À choisir'}",
            f"**Rôles ({len(roles)})**",
            selection,
        ]
        if self.mode == "reaction":
            lignes.append("-# Chaque rôle reçoit un emoji personnalisé SentriX.")
        if self.erreurs:
            lignes.append("-# " + sentrix_emojis.emoji("warning") + " " + " · ".join(self.erreurs[:3]))
        return "\n".join(lignes)

    def rebuild(self) -> None:
        self.clear_items()
        carte = discord.ui.Container(accent_colour=discord.Colour(0x7658E8))
        carte.add_item(discord.ui.TextDisplay(self._texte()))
        carte.add_item(discord.ui.Separator())
        carte.add_item(discord.ui.ActionRow(BuilderRolePicker(self)))
        carte.add_item(discord.ui.ActionRow(BuilderChannelPicker(self)))
        if self.allow_mode_switch:
            carte.add_item(discord.ui.ActionRow(BuilderModeSelect(self)))
        create = discord.ui.Button(
            label="Créer le panneau", emoji=sentrix_emojis.partiel("success"), style=discord.ButtonStyle.success,
            custom_id=f"sentrix:rolepanel-builder:create:{self.owner_id}",
            disabled=not self.selected_role_ids or not self.channel_id,
        )
        cancel = discord.ui.Button(
            label="Annuler", style=discord.ButtonStyle.secondary,
            custom_id=f"sentrix:rolepanel-builder:cancel:{self.owner_id}",
        )
        create.callback = self.create_panel
        cancel.callback = self.cancel
        carte.add_item(discord.ui.ActionRow(create, cancel))
        carte.add_item(discord.ui.TextDisplay("-# SentriX · réservé à la personne qui a lancé la commande"))
        self.add_item(carte)

    def embed(self) -> discord.Embed:
        """Compatibilité : résumé texte (l'interface réelle est la carte)."""
        return discord.Embed(title="Panneau de rôles", description=self._texte(), colour=0x7658E8)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.owner_id:
            return True
        await interaction.response.send_message("Ce panneau de configuration appartient à son créateur.", ephemeral=True)
        return False

    async def refresh(self, interaction: discord.Interaction) -> None:
        if not interaction.response.is_done():
            await interaction.response.defer()
        self.rebuild()
        await interaction.edit_original_response(view=self)

    def _carte_finale(self, titre: str, texte: str, couleur: int) -> discord.ui.LayoutView:
        vue = discord.ui.LayoutView(timeout=None)
        carte = discord.ui.Container(accent_colour=discord.Colour(couleur))
        carte.add_item(discord.ui.TextDisplay(f"### {titre}\n{texte}"))
        vue.add_item(carte)
        return vue

    async def create_panel(self, interaction: discord.Interaction) -> None:
        if not self.selected_role_ids:
            return await interaction.response.send_message("Sélectionnez au moins un rôle avant de créer le panneau.", ephemeral=True)
        channel = self.guild.get_channel(self.channel_id) if self.channel_id else None
        if not isinstance(channel, discord.TextChannel):
            return await interaction.response.send_message("Choisissez un salon de publication valide.", ephemeral=True)
        actor = self.guild.get_member(interaction.user.id)
        if actor is None or not actor.guild_permissions.administrator:
            return await interaction.response.send_message("Permission Administrateur requise.", ephemeral=True)
        me = self.guild.me
        perms = channel.permissions_for(me) if me else None
        if not perms or not (perms.view_channel and perms.send_messages and perms.embed_links):
            return await interaction.response.send_message("SentriX doit pouvoir voir le salon, y envoyer des messages et intégrer des liens.", ephemeral=True)
        if self.mode == "reaction" and not (perms.add_reactions and perms.read_message_history):
            return await interaction.response.send_message("SentriX doit pouvoir ajouter des réactions et lire l'historique dans ce salon.", ephemeral=True)
        roles, errors = _valid_roles(self.guild, self.selected_role_ids)
        if not roles:
            return await interaction.response.send_message(
                "Aucun rôle sélectionné n'est modifiable par SentriX.\n" + "\n".join(f"• {item}" for item in errors[:6]),
                ephemeral=True,
            )
        reaction_emojis = []
        if self.mode == "reaction":
            names = ("role", "notification", "games", "trophy", "ticket", "cards", "user", "users", "calendar", "voice", "video", "support", "tools", "verified", "info", "coin", "wallet", "staff", "bot", "channel")
            reaction_emojis = [str(icon) for name in names if (icon := sentrix_emojis.partiel(name)) is not None]
            custom = list(getattr(self, "custom_emojis", []) or [])
            if custom:
                if len(custom) != len(roles) or len({_emoji_key(value) for value in custom}) != len(custom):
                    return await interaction.response.send_message("Choisissez un emoji différent par rôle sélectionné.", ephemeral=True)
                reaction_emojis = custom
            if len(reaction_emojis) < len(roles):
                return await interaction.response.send_message("Les emojis personnalisés SentriX ne sont pas encore disponibles en nombre suffisant. Réessayez après leur synchronisation ou choisissez le menu déroulant.", ephemeral=True)
        await interaction.response.defer()
        role_ids = [role.id for role in roles]

        try:
            if self.mode == "dropdown":
                panel = ExistingDropdownPanel(self.guild, role_ids)
                panel_message = await channel.send(embed=_dropdown_embed(self.guild, role_ids), view=panel)
                await _save_panel(self.bot, panel_message, mode="dropdown", role_ids=role_ids, mappings=[], creator_id=self.owner_id)
                self.bot.add_view(ExistingDropdownPanel(self.guild, role_ids), message_id=panel_message.id)
            else:
                mappings = [
                    {"emoji": reaction_emojis[index], "key": _emoji_key(reaction_emojis[index]), "role_id": role.id}
                    for index, role in enumerate(roles)
                ]
                panel_message = await channel.send(embed=_reaction_embed(self.guild, mappings))
                try:
                    for item in mappings:
                        await panel_message.add_reaction(item["emoji"])
                except (discord.Forbidden, discord.HTTPException):
                    try:
                        await panel_message.delete()
                    except discord.HTTPException:
                        pass
                    return await interaction.followup.send("Impossible d'ajouter les réactions au panneau. Vérifiez les permissions de SentriX.", ephemeral=True)
                await _save_panel(self.bot, panel_message, mode="reaction", role_ids=role_ids, mappings=mappings, creator_id=self.owner_id)

            mode = "menu déroulant" if self.mode == "dropdown" else "réactions emoji"
            await interaction.edit_original_response(view=self._carte_finale(
                sentrix_emojis.titre("success", "Panneau créé"), f"**Mode** · {mode}\n**Rôles** · {len(role_ids)}\n**Salon** · {channel.mention}", 0x2FBF71,
            ))
            self.stop()
        except discord.Forbidden:
            await interaction.followup.send("SentriX n'a pas la permission d'envoyer le panneau ou de gérer ces rôles.", ephemeral=True)
        except discord.HTTPException:
            await interaction.followup.send("Discord a refusé la création du panneau. Réessayez dans quelques secondes.", ephemeral=True)

    async def cancel(self, interaction: discord.Interaction) -> None:
        await interaction.response.edit_message(view=self._carte_finale(
            "Configuration annulée", "Aucun panneau n'a été publié.", 0x99AAB5,
        ))
        self.stop()

    async def on_timeout(self) -> None:
        if self.message is None:
            return
        try:
            await self.message.edit(view=self._carte_finale(
                "Configuration expirée", "Relancez `/role menu` pour recommencer.", 0x99AAB5,
            ))
        except discord.HTTPException:
            pass


async def _restore_dropdown_views(bot: commands.Bot) -> None:
    try:
        await bot.wait_until_ready()
        rows = await bot.db.fetchall("SELECT message_id,guild_id,role_ids_json FROM sentrix_role_panels WHERE mode='dropdown'")
    except Exception:
        logger.exception("Role panel persistent view restore failed.")
        return
    restored = 0
    for row in rows:
        try:
            guild_id = int(row["guild_id"])
            message_id = int(row["message_id"])
            role_ids = [int(value) for value in json.loads(row["role_ids_json"] or "[]")]
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            continue
        guild = bot.get_guild(guild_id)
        if guild is None:
            continue
        roles, _ = _valid_roles(guild, role_ids)
        if not roles:
            continue
        try:
            bot.add_view(ExistingDropdownPanel(guild, [role.id for role in roles]), message_id=message_id)
            restored += 1
        except Exception:
            logger.debug("Role panel view restore skipped for %s.", message_id, exc_info=True)
    logger.info("Persistent dropdown role panels restored: %s", restored)


class SentriXRegressionRuntime(commands.Cog, name="SentriXRegressionFix"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._restore_task: asyncio.Task | None = None

    async def cog_load(self) -> None:
        self._restore_task = asyncio.create_task(_restore_dropdown_views(self.bot), name="sentrix-rolepanel-restore")

    def cog_unload(self) -> None:
        if self._restore_task is not None and not self._restore_task.done():
            self._restore_task.cancel()

    @commands.group(name="rolepanel", aliases=["role-panel", "roles-notifs", "notifs-roles"], invoke_without_command=True)
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def rolepanel(self, ctx: commands.Context):
        me = ctx.guild.me
        if me is None or not me.guild_permissions.manage_roles:
            return await ctx.send("SentriX a besoin de la permission **Gérer les rôles**.")
        view = RolePanelBuilder(self.bot, ctx.guild, ctx.author.id)
        message = await ctx.send(view=view)
        view.message = message

    @rolepanel.command(name="dropdown", aliases=["menu", "deroulant", "déroulant", "select"],
                       description="Publier un menu déroulant de rôles à choisir.")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def rolepanel_dropdown(self, ctx: commands.Context, roles: commands.Greedy[discord.Role]):
        role_ids = _role_ids(roles)
        if not role_ids:
            view = RolePanelBuilder(self.bot, ctx.guild, ctx.author.id, mode="dropdown")
            message = await ctx.send(view=view)
            view.message = message
            return
        valid, errors = _valid_roles(ctx.guild, role_ids)
        if not valid:
            return await ctx.send("Aucun rôle n'est modifiable par SentriX.\n" + "\n".join(f"• {item}" for item in errors[:6]))
        ids = [role.id for role in valid]
        view = ExistingDropdownPanel(ctx.guild, ids)
        message = await ctx.send(embed=_dropdown_embed(ctx.guild, ids), view=view)
        await _save_panel(self.bot, message, mode="dropdown", role_ids=ids, mappings=[], creator_id=ctx.author.id)
        # Un panneau de rôles distribue des rôles en libre-service : savoir qui l'a
        # publié, et avec quels rôles, compte autant que de savoir qui a donné un rôle.
        await journaliser(self.bot, ctx, "config_update", "🎛️ Panneau de rôles publié", {
            "🎭 Rôles": ", ".join(r.mention for r in valid)[:1024],
            "💬 Message": f"`{message.id}`",
        })
        self.bot.add_view(ExistingDropdownPanel(ctx.guild, ids), message_id=message.id)

    @rolepanel.command(name="reaction", aliases=["reactions", "emoji", "emojis"],
                       description="Publier un panneau de rôles par réaction.")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def rolepanel_reaction(self, ctx: commands.Context, *, configuration: str = ""):
        if not configuration.strip():
            view = RolePanelBuilder(self.bot, ctx.guild, ctx.author.id, mode="reaction")
            message = await ctx.send(view=view)
            view.message = message
            return
        tokens = configuration.split()
        if len(tokens) % 2 != 0:
            return await ctx.send("Configuration invalide. Utilisez des paires `emoji @Rôle`, par exemple : `+rolepanel reaction ✅ @Membre 🎉 @Events`.")
        if len(tokens) > 40:
            return await ctx.send("Maximum **20 réactions/rôles** par panneau.")
        me = ctx.guild.me
        if me is None or not me.guild_permissions.manage_roles:
            return await ctx.send("SentriX a besoin de la permission **Gérer les rôles**.")

        mappings: list[dict[str, Any]] = []
        seen: set[str] = set()
        role_ids: list[int] = []
        for index in range(0, len(tokens), 2):
            emoji_token, role_token = tokens[index], tokens[index + 1]
            match = _ROLE_MENTION_RE.fullmatch(role_token)
            if not match:
                return await ctx.send(f"`{role_token}` n'est pas une mention de rôle valide.")
            role = ctx.guild.get_role(int(match.group(1)))
            if role is None:
                return await ctx.send(f"Le rôle {role_token} est introuvable.")
            if role.is_default() or role.managed:
                return await ctx.send(f"Le rôle {role.mention} ne peut pas être attribué.")
            if role >= me.top_role:
                return await ctx.send(f"Le rôle de SentriX doit être placé au-dessus de {role.mention}.")
            key = _emoji_key(emoji_token)
            if key in seen:
                return await ctx.send(f"L'emoji `{emoji_token}` est configuré deux fois.")
            seen.add(key)
            role_ids.append(role.id)
            mappings.append({"emoji": emoji_token, "key": key, "role_id": role.id})

        message = await ctx.send(embed=_reaction_embed(ctx.guild, mappings))
        try:
            for item in mappings:
                await message.add_reaction(item["emoji"])
        except (discord.Forbidden, discord.HTTPException):
            try:
                await message.delete()
            except discord.HTTPException:
                pass
            return await ctx.send("Un emoji n'a pas pu être ajouté. Vérifiez sa validité et les permissions de SentriX.")
        await _save_panel(self.bot, message, mode="reaction", role_ids=role_ids, mappings=mappings, creator_id=ctx.author.id)
        await self.bot.db.execute(
            "INSERT INTO sentrix_reaction_role_panels (message_id,guild_id,channel_id,mappings_json,created_by,created_at) VALUES (?,?,?,?,?,?) "
            "ON CONFLICT(message_id) DO UPDATE SET mappings_json=excluded.mappings_json,channel_id=excluded.channel_id",
            (message.id, ctx.guild.id, ctx.channel.id, json.dumps(mappings, ensure_ascii=False, separators=(",", ":")), ctx.author.id, int(time.time())),
        )

    async def _mapping_for(self, message_id: int, emoji: discord.PartialEmoji) -> int | None:
        row = await self.bot.db.fetchone("SELECT mappings_json FROM sentrix_role_panels WHERE message_id=? AND mode='reaction'", (int(message_id),))
        if row is None:
            row = await self.bot.db.fetchone("SELECT mappings_json FROM sentrix_reaction_role_panels WHERE message_id=?", (int(message_id),))
        if row is None:
            return None
        try:
            raw = row["mappings_json"]
        except (KeyError, TypeError):
            raw = row[0]
        try:
            mappings = json.loads(raw or "[]")
        except (TypeError, json.JSONDecodeError):
            return None
        key = _emoji_key(emoji)
        for item in mappings:
            if str(item.get("key")) == key:
                try:
                    return int(item["role_id"])
                except (KeyError, TypeError, ValueError):
                    return None
        return None

    async def _apply_reaction(self, payload: discord.RawReactionActionEvent, *, add: bool) -> None:
        if self.bot.user is None or payload.user_id == self.bot.user.id or payload.guild_id is None:
            return
        canonical = await self.bot.db.fetchone(
            "SELECT message_id FROM reaction_role_panels WHERE guild_id=? AND message_id=?",
            (payload.guild_id,payload.message_id),
        )
        if canonical is not None:
            return  # Le listener Verification applique les options persistantes.
        role_id = await self._mapping_for(payload.message_id, payload.emoji)
        if role_id is None:
            return
        from utils.reaction_role_options import apply_reaction
        await apply_reaction(self.bot, payload, {"role_id":role_id}, adding=add)

    @commands.Cog.listener("on_raw_reaction_add")
    async def reaction_added(self, payload: discord.RawReactionActionEvent):
        await self._apply_reaction(payload, add=True)

    @commands.Cog.listener("on_raw_reaction_remove")
    async def reaction_removed(self, payload: discord.RawReactionActionEvent):
        await self._apply_reaction(payload, add=False)

    # remove_duplicate_welcome (ancien filet de sécurité "envoyer puis nettoyer après
    # coup") a été retiré : il était déjà mort en pratique (mauvaise colonne de config,
    # welcome_channel_id au lieu de welcome_channel) et redondant avec le verrou
    # utils.join_dedup qui empêche maintenant l'envoi en double à la source — voir
    # cogs/setup_v2_completion.py. cogs/bot_tracker.py::_cleanup_presence_duplicates
    # reste l'unique filet de sécurité après coup, branché sur le seul système officiel.

async def setup(bot: commands.Bot) -> None:
    await bot.db.execute(_REACTION_SCHEMA)
    await bot.db.execute(_ROLE_PANEL_SCHEMA)
    dashboard_fixed = _install_dashboard_loader_fix()
    invitations_fixed = _install_setup_invitations(bot)
    legacy_disabled = _disable_legacy_role_autocreate(bot)

    legacy_command = bot.get_command("rolepanel")
    if legacy_command is not None:
        bot.remove_command(legacy_command.name)

    if bot.get_cog("SentriXRegressionFix") is None:
        await bot.add_cog(SentriXRegressionRuntime(bot))

    bot.sentrix_regression_fix_state = {
        "dashboard_loader": dashboard_fixed,
        "setup_invitations": invitations_fixed,
        "rolepanel_existing_roles_only": legacy_disabled,
        "rolepanel_dropdown": True,
        "rolepanel_reactions": True,
        "welcome_dedupe": True,
    }
    logger.info("SentriX regression runtime active: %s", bot.sentrix_regression_fix_state)
