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


def _message_text(message: discord.Message) -> str:
    parts = [message.content or ""]
    for embed in message.embeds:
        parts.extend([str(embed.title or ""), str(embed.description or "")])
        for field in embed.fields:
            parts.extend([str(field.name or ""), str(field.value or "")])
    return "\n".join(parts).casefold()


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


class BuilderRolePicker(discord.ui.RoleSelect):
    def __init__(self, parent: "RolePanelBuilder"):
        self.parent_builder = parent
        super().__init__(
            placeholder="1. Sélectionnez les rôles déjà existants…",
            min_values=1,
            max_values=20,
            custom_id=f"sentrix:rolepanel-builder:roles:{parent.owner_id}",
            row=0,
        )

    async def callback(self, interaction: discord.Interaction):
        self.parent_builder.selected_role_ids = _role_ids(self.values)
        await self.parent_builder.refresh(interaction)


class BuilderModeSelect(discord.ui.Select):
    def __init__(self, parent: "RolePanelBuilder"):
        self.parent_builder = parent
        super().__init__(
            placeholder="2. Sélectionnez le mode du panneau…",
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(label="Menu déroulant", value="dropdown", description="Les membres utilisent un menu.", default=parent.mode == "dropdown"),
                discord.SelectOption(label="Réactions emoji", value="reaction", description="Ajouter/retirer une réaction gère le rôle.", default=parent.mode == "reaction"),
            ],
            custom_id=f"sentrix:rolepanel-builder:mode:{parent.owner_id}",
            row=1,
        )

    async def callback(self, interaction: discord.Interaction):
        self.parent_builder.mode = self.values[0]
        self.parent_builder.rebuild()
        await self.parent_builder.refresh(interaction)


class RolePanelBuilder(discord.ui.View):
    def __init__(self, bot: commands.Bot, guild: discord.Guild, owner_id: int, *, mode: str = "dropdown"):
        super().__init__(timeout=300)
        self.bot = bot
        self.guild = guild
        self.owner_id = int(owner_id)
        self.mode = mode if mode in {"dropdown", "reaction"} else "dropdown"
        self.selected_role_ids: list[int] = []
        self.message: discord.Message | None = None
        self.rebuild()

    def rebuild(self) -> None:
        self.clear_items()
        self.add_item(BuilderRolePicker(self))
        self.add_item(BuilderModeSelect(self))
        create = discord.ui.Button(label="Créer le panneau", style=discord.ButtonStyle.success, custom_id=f"sentrix:rolepanel-builder:create:{self.owner_id}", row=2)
        cancel = discord.ui.Button(label="Annuler", style=discord.ButtonStyle.secondary, custom_id=f"sentrix:rolepanel-builder:cancel:{self.owner_id}", row=2)
        create.callback = self.create_panel
        cancel.callback = self.cancel
        self.add_item(create)
        self.add_item(cancel)

    def embed(self) -> discord.Embed:
        roles = [self.guild.get_role(role_id) for role_id in self.selected_role_ids]
        roles = [role for role in roles if role is not None]
        selected = "\n".join(f"• {role.mention}" for role in roles) or "Aucun rôle sélectionné."
        mode_name = "Menu déroulant" if self.mode == "dropdown" else "Réactions emoji"
        embed = discord.Embed(
            title="Configuration du panneau de rôles",
            description=(
                "**SentriX ne créera aucun rôle.**\n"
                "Sélectionnez uniquement des rôles déjà présents sur le serveur, puis choisissez le mode.\n\n"
                f"**Mode :** {mode_name}\n**Rôles sélectionnés :**\n{selected}"
            ),
            colour=0x7658E8,
        )
        if self.mode == "reaction":
            embed.add_field(
                name="Emojis",
                value=(
                    "Le builder attribue automatiquement des emojis uniques. "
                    "Pour définir vos propres emojis : `+rolepanel reaction ✅ @Rôle 🎉 @AutreRôle`."
                ),
                inline=False,
            )
        embed.set_footer(text="SentriX • Rôles existants uniquement")
        return embed

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.owner_id:
            return True
        await interaction.response.send_message("Ce panneau de configuration appartient à son créateur.", ephemeral=True)
        return False

    async def refresh(self, interaction: discord.Interaction) -> None:
        await interaction.response.edit_message(embed=self.embed(), view=self)

    async def create_panel(self, interaction: discord.Interaction) -> None:
        if not self.selected_role_ids:
            return await interaction.response.send_message("Sélectionnez au moins un rôle existant avant de créer le panneau.", ephemeral=True)
        roles, errors = _valid_roles(self.guild, self.selected_role_ids)
        if not roles:
            return await interaction.response.send_message(
                "Aucun rôle sélectionné n'est modifiable par SentriX.\n" + "\n".join(f"• {item}" for item in errors[:6]),
                ephemeral=True,
            )
        await interaction.response.defer()
        role_ids = [role.id for role in roles]

        try:
            if self.mode == "dropdown":
                panel = ExistingDropdownPanel(self.guild, role_ids)
                panel_message = await interaction.channel.send(embed=_dropdown_embed(self.guild, role_ids), view=panel)
                await _save_panel(self.bot, panel_message, mode="dropdown", role_ids=role_ids, mappings=[], creator_id=self.owner_id)
                self.bot.add_view(ExistingDropdownPanel(self.guild, role_ids), message_id=panel_message.id)
            else:
                mappings = [
                    {"emoji": _DEFAULT_REACTION_EMOJIS[index], "key": _emoji_key(_DEFAULT_REACTION_EMOJIS[index]), "role_id": role.id}
                    for index, role in enumerate(roles[: len(_DEFAULT_REACTION_EMOJIS)])
                ]
                panel_message = await interaction.channel.send(embed=_reaction_embed(self.guild, mappings))
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

            success = discord.Embed(
                title="Panneau créé",
                description=(
                    f"Mode : **{'menu déroulant' if self.mode == 'dropdown' else 'réactions emoji'}**\n"
                    f"Rôles : **{len(role_ids)}**\n\nSentriX n'a créé aucun nouveau rôle."
                ),
                colour=0x2FBF71,
            )
            await interaction.message.edit(embed=success, view=None)
            self.stop()
        except discord.Forbidden:
            await interaction.followup.send("SentriX n'a pas la permission d'envoyer le panneau ou de gérer ces rôles.", ephemeral=True)
        except discord.HTTPException:
            await interaction.followup.send("Discord a refusé la création du panneau. Réessayez dans quelques secondes.", ephemeral=True)

    async def cancel(self, interaction: discord.Interaction) -> None:
        await interaction.response.edit_message(
            embed=discord.Embed(title="Configuration annulée", description="Aucun rôle n'a été créé ni modifié.", colour=0x99AAB5),
            view=None,
        )
        self.stop()

    async def on_timeout(self) -> None:
        if self.message is None:
            return
        try:
            await self.message.edit(view=None)
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
        message = await ctx.send(embed=view.embed(), view=view)
        view.message = message

    @rolepanel.command(name="dropdown", aliases=["menu", "deroulant", "déroulant", "select"])
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def rolepanel_dropdown(self, ctx: commands.Context, roles: commands.Greedy[discord.Role]):
        role_ids = _role_ids(roles)
        if not role_ids:
            view = RolePanelBuilder(self.bot, ctx.guild, ctx.author.id, mode="dropdown")
            message = await ctx.send(embed=view.embed(), view=view)
            view.message = message
            return
        valid, errors = _valid_roles(ctx.guild, role_ids)
        if not valid:
            return await ctx.send("Aucun rôle n'est modifiable par SentriX.\n" + "\n".join(f"• {item}" for item in errors[:6]))
        ids = [role.id for role in valid]
        view = ExistingDropdownPanel(ctx.guild, ids)
        message = await ctx.send(embed=_dropdown_embed(ctx.guild, ids), view=view)
        await _save_panel(self.bot, message, mode="dropdown", role_ids=ids, mappings=[], creator_id=ctx.author.id)
        self.bot.add_view(ExistingDropdownPanel(ctx.guild, ids), message_id=message.id)

    @rolepanel.command(name="reaction", aliases=["reactions", "emoji", "emojis"])
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def rolepanel_reaction(self, ctx: commands.Context, *, configuration: str = ""):
        if not configuration.strip():
            view = RolePanelBuilder(self.bot, ctx.guild, ctx.author.id, mode="reaction")
            message = await ctx.send(embed=view.embed(), view=view)
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
        role_id = await self._mapping_for(payload.message_id, payload.emoji)
        if role_id is None:
            return
        guild = self.bot.get_guild(int(payload.guild_id))
        if guild is None:
            return
        role = guild.get_role(role_id)
        if role is None:
            return
        member = payload.member if add else guild.get_member(payload.user_id)
        if member is None:
            try:
                member = await guild.fetch_member(payload.user_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                return
        me = guild.me
        if member.bot or me is None or role.managed or role >= me.top_role:
            return
        try:
            if add and role not in member.roles:
                await member.add_roles(role, reason="SentriX • rôle par réaction")
            elif not add and role in member.roles:
                await member.remove_roles(role, reason="SentriX • retrait réaction")
        except (discord.Forbidden, discord.HTTPException):
            logger.warning("Reaction role failed guild=%s user=%s role=%s", guild.id, member.id, role.id)

    @commands.Cog.listener("on_raw_reaction_add")
    async def reaction_added(self, payload: discord.RawReactionActionEvent):
        await self._apply_reaction(payload, add=True)

    @commands.Cog.listener("on_raw_reaction_remove")
    async def reaction_removed(self, payload: discord.RawReactionActionEvent):
        await self._apply_reaction(payload, add=False)

    @commands.Cog.listener("on_member_join")
    async def remove_duplicate_welcome(self, member: discord.Member):
        await asyncio.sleep(4.0)
        try:
            conf = await self.bot.db.get_guild_config(member.guild.id)
            channel_id = int(conf["welcome_channel_id"] or 0) if conf else 0
        except Exception:
            return
        channel = member.guild.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel) or self.bot.user is None:
            return
        now = discord.utils.utcnow()
        recent: list[discord.Message] = []
        try:
            async for message in channel.history(limit=20):
                if message.author.id == self.bot.user.id and abs((now - message.created_at).total_seconds()) <= 15:
                    recent.append(message)
        except (discord.Forbidden, discord.HTTPException):
            return
        identity = {member.mention.casefold(), member.name.casefold(), member.display_name.casefold()}
        direct = [msg for msg in recent if any(value and value in _message_text(msg) for value in identity)]
        if not direct:
            return
        anchor = min(direct, key=lambda msg: msg.created_at)
        related = [
            msg for msg in recent
            if abs((msg.created_at - anchor.created_at).total_seconds()) <= 6
            and (any(value and value in _message_text(msg) for value in identity) or "bienvenue" in _message_text(msg))
        ]
        if len(related) < 2:
            return
        keep = max(related, key=lambda msg: (int(bool(msg.embeds)) * 4 + int(any(getattr(embed.image, "url", None) for embed in msg.embeds)) * 3, -msg.created_at.timestamp()))
        for msg in related:
            if msg.id == keep.id:
                continue
            try:
                await msg.delete()
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass


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
