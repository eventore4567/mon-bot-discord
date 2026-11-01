"""Controlled bulk role management with explicit human/bot/all selection."""
from __future__ import annotations

import asyncio
import logging
from typing import Literal

import discord
from discord import app_commands
from discord.ext import commands

from . import language_runtime
from utils import sentrix_panels as panels

logger = logging.getLogger("bot.role-mass")
_RUNNING: set[tuple[int, int]] = set()


class TargetSelect(discord.ui.Select):
    def __init__(self, view: "MassRoleView"):
        self.owner = view
        en = view.english
        super().__init__(
            placeholder="Choose members, bots, or everyone" if en else "Membres, bots ou tous",
            min_values=1, max_values=1,
            options=[
                discord.SelectOption(label="Members only" if en else "Membres uniquement", value="members"),
                discord.SelectOption(label="Bots only" if en else "Bots uniquement", value="bots"),
                discord.SelectOption(label="Everyone" if en else "Tous", value="all"),
            ],
        )

    async def callback(self, interaction: discord.Interaction):
        self.owner.target = self.values[0]
        parent = getattr(self.owner, "_sentrix_panel_view", None)
        search = list(parent.children) if parent is not None else list(self.owner.children)
        while search:
            item = search.pop()
            search.extend(getattr(item, "children", ()))
            if isinstance(item, discord.ui.Button) and item.custom_id == "sentrix:mass:confirm":
                item.disabled = False
        label = {"members": "members", "bots": "bots", "all": "everyone"}[self.owner.target]
        desc = (
            f"Target: **{label}**. Click Confirm to {self.owner.action} the role."
            if self.owner.english else
            f"Cible : **{{'members': 'membres', 'bots': 'bots', 'all': 'tous'}[self.owner.target]}**. "
            f"Cliquez sur Confirmer pour {'ajouter' if self.owner.action == 'add' else 'retirer'} le rôle."
        )
        if parent is not None:
            await interaction.response.edit_message(view=parent)
        else:
            await interaction.response.edit_message(content=desc, view=self.owner)


class MassRoleView(discord.ui.View):
    def __init__(self, bot: commands.Bot, guild_id: int, author_id: int, role_id: int,
                 action: str, english: bool):
        super().__init__(timeout=300)
        self.bot = bot
        self.guild_id = guild_id
        self.author_id = author_id
        self.role_id = role_id
        self.action = action
        self.target = None
        self.english = english
        self.add_item(TargetSelect(self))
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                if item.label == "Confirm":
                    item.label = "Confirm" if english else "Confirmer"
                    item.custom_id = "sentrix:mass:confirm"
                elif item.label == "Cancel":
                    item.label = "Cancel" if english else "Annuler"

    async def interaction_check(self, interaction: discord.Interaction):
        member = interaction.user
        guild = interaction.guild
        if (guild is None or guild.id != self.guild_id or member.id != self.author_id
                or not isinstance(member, discord.Member)
                or not member.guild_permissions.manage_roles):
            await interaction.response.send_message(
                "You cannot manage this role operation." if self.english else
                "Vous ne pouvez pas modifier cette opération.", ephemeral=True)
            return False
        role = guild.get_role(self.role_id)
        bot_member = guild.me
        if (role is None or bot_member is None or role.is_default() or role.managed
                or role >= bot_member.top_role
                or (member.id != guild.owner_id and role >= member.top_role)):
            await interaction.response.send_message(
                "This role can no longer be managed." if self.english else
                "Ce rôle ne peut plus être géré.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.danger, disabled=True)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.target not in {"members", "bots", "all"}:
            return await interaction.response.send_message("Select a target first.", ephemeral=True)
        key = (self.guild_id, self.role_id)
        if key in _RUNNING:
            return await interaction.response.send_message(
                "A bulk operation for this role is already running.", ephemeral=True
            )
        _RUNNING.add(key)
        self.stop()
        parent = getattr(self, "_sentrix_panel_view", None)
        pending = list(parent.children) if parent is not None else list(self.children)
        while pending:
            item = pending.pop()
            pending.extend(getattr(item, "children", ()))
            if isinstance(item, (discord.ui.Button, discord.ui.Select)):
                item.disabled = True
        if parent is not None:
            await interaction.response.edit_message(view=parent)
            await interaction.followup.send(
                "Opération démarrée. Le résultat sera envoyé en MP.",
                ephemeral=True,
            )
        else:
            await interaction.response.edit_message(
                content="Opération démarrée. Le résultat sera envoyé en MP.", view=self
            )
        # The job can outlast an interaction token on large servers.
        # Keep it independent and report through the original channel.
        asyncio.create_task(self._apply(interaction.guild, interaction.channel, self.author_id, key))

    async def _apply(self, guild: discord.Guild, channel, actor_id: int, key: tuple[int, int]):
        processed = changed = skipped = failed = 0
        try:
            role = guild.get_role(self.role_id)
            me = guild.me
            if role is None or me is None or role >= me.top_role:
                return
            try:
                members = [member async for member in guild.fetch_members(limit=None)]
            except (discord.Forbidden, discord.HTTPException):
                # Do not silently apply to a partial member cache.
                await self._notify_actor(guild, actor_id, "Liste complète des membres indisponible ; aucun rôle modifié.")
                return
            for member in members:
                if self.target == "members" and member.bot:
                    continue
                if self.target == "bots" and not member.bot:
                    continue
                processed += 1
                # Managed and hierarchy checks are enforced by Discord as well.
                if self.action == "add" and role in member.roles:
                    skipped += 1
                    continue
                if self.action == "remove" and role not in member.roles:
                    skipped += 1
                    continue
                try:
                    if self.action == "add":
                        await member.add_roles(role, reason=f"Bulk role requested by {actor_id}")
                    else:
                        await member.remove_roles(role, reason=f"Bulk role requested by {actor_id}")
                    changed += 1
                except (discord.Forbidden, discord.HTTPException):
                    failed += 1
                await asyncio.sleep(0)
            await self._notify_actor(
                guild, actor_id,
                f"Opération terminée : {changed} modifiés, {skipped} ignorés et {failed} échecs.",
            )
        except Exception:
            logger.exception("Mass role failed: guild=%s, role=%s, processed=%s",
                             guild.id, self.role_id, processed)
            await self._notify_actor(guild, actor_id, "L'opération sur les rôles a été interrompue.")
        finally:
            _RUNNING.discard(key)

    async def _notify_actor(self, guild: discord.Guild, actor_id: int, message: str) -> None:
        try:
            actor = guild.get_member(actor_id) or await guild.fetch_member(actor_id)
            await actor.send(message, allowed_mentions=discord.AllowedMentions.none())
        except (discord.Forbidden, discord.NotFound, discord.HTTPException):
            logger.warning("Récapitulatif de rôle impossible à envoyer en MP (guild=%s).", guild.id)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        await interaction.response.edit_message(view=None)


class MassRole(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.hybrid_group(name="role", invoke_without_command=True,
                           description="Manage roles.")
    @commands.guild_only()
    async def role(self, ctx: commands.Context):
        await ctx.send("Use `/role mass` or `+role mass @role add`.")

    @role.command(name="mass", description="Ajouter ou retirer un rôle en masse.")
    @commands.has_guild_permissions(manage_roles=True)
    @app_commands.describe(
        role="Rôle à modifier",
        action="Ajouter ou retirer le rôle",
        cible="Choisir les membres, les bots ou tout le monde",
    )
    @app_commands.choices(
        action=[
            app_commands.Choice(name="Ajouter", value="add"),
            app_commands.Choice(name="Retirer", value="remove"),
        ],
        cible=[
            app_commands.Choice(name="Membres (sans bots)", value="members"),
            app_commands.Choice(name="Bots uniquement", value="bots"),
            app_commands.Choice(name="Tous", value="all"),
        ],
    )
    async def mass(
        self, ctx: commands.Context, role: discord.Role,
        action: str = "add", cible: str = "members",
    ):
        # Acknowledge slash commands immediately; Discord otherwise times out
        # before the permission checks, localization and target panel complete.
        if ctx.interaction:
            await ctx.defer(ephemeral=True)
        guild = ctx.guild
        actor = ctx.author
        me = guild.me
        if (me is None or not me.guild_permissions.manage_roles
                or role.is_default() or role.managed or role >= me.top_role
                or (actor.id != guild.owner_id and role >= actor.top_role)):
            return await ctx.send("Ce rôle ne peut pas être modifié (permissions ou hiérarchie Discord).", ephemeral=bool(ctx.interaction))
        english = await language_runtime.get_language(self.bot, guild.id) == language_runtime.LANG_EN
        if action not in {"add", "remove"} or cible not in {"members", "bots", "all"}:
            return await ctx.send("Choisissez une action et une cible valides.", ephemeral=bool(ctx.interaction))
        view = MassRoleView(self.bot, guild.id, actor.id, role.id, action, english)
        view.target = cible
        for item in view.children:
            if isinstance(item, TargetSelect):
                for option in item.options:
                    option.default = option.value == cible
                item.placeholder = {
                    "members": "Cible : membres",
                    "bots": "Cible : bots",
                    "all": "Cible : tous",
                }[cible]
            elif isinstance(item, discord.ui.Button) and item.custom_id == "sentrix:mass:confirm":
                item.disabled = False
        description = (
            f"Role: {role.mention} · Action: **{action}**. Choose who should be affected."
            if english else
            f"Rôle : {role.mention} · Action : **{'ajouter' if action == 'add' else 'retirer'}**. "
            f"Cible : **{'membres' if cible == 'members' else 'bots' if cible == 'bots' else 'tous'}**."
        )
        panneau = panels.Panneau(
            titre="Gestion des rôles en masse" if not english else "Bulk role management",
            sous_titre=description,
            kind="moderation",
            banniere=True,
            sections=[panels.Section(
                "Sélection" if not english else "Selection",
                texte="Choisissez membres, bots ou tous, puis confirmez. Aucune modification sans confirmation."
                if not english else "Choose members, bots or everyone, then confirm.",
            )],
        )
        panneau = panels.avec_composants(panneau, view)
        await panels.envoyer(ctx, panneau, ephemere=bool(ctx.interaction))


async def setup(bot: commands.Bot):
    await bot.add_cog(MassRole(bot))
