"""Panel de choix de rôles configurable pour SentriX.

Le catalogue public ne contient aucun rôle codé en dur : les rôles proposés viennent
exclusivement de ``self_role_items`` et sont configurés depuis ``+setup`` > Rôles.
"""
from __future__ import annotations

import logging

import discord
from discord.ext import commands

logger = logging.getLogger("bot.server-choice-roles")
_INSTALLED = False

MARKER = "SentriX • Choix rôles automatique v2"
LEGACY_MARKER = "SentriX • Choix rôles automatique v1"


async def _configured_roles(
    bot: commands.Bot,
    guild: discord.Guild,
    panel_message_id: int = 0,
) -> list[discord.Role]:
    """Retourne uniquement les rôles explicitement configurés pour ce serveur."""
    rows = await bot.db.fetchall(
        "SELECT role_id FROM self_role_items "
        "WHERE guild_id=? AND panel_message_id=? ORDER BY role_id",
        (guild.id, int(panel_message_id or 0)),
    )
    if not rows and panel_message_id:
        rows = await bot.db.fetchall(
            "SELECT role_id FROM self_role_items "
            "WHERE guild_id=? AND panel_message_id=0 ORDER BY role_id",
            (guild.id,),
        )

    me = guild.me
    if me is None:
        return []

    roles: list[discord.Role] = []
    seen: set[int] = set()
    for row in rows:
        try:
            role_id = int(row["role_id"])
        except (KeyError, TypeError, ValueError):
            continue
        if role_id in seen:
            continue
        role = guild.get_role(role_id)
        if role is None or role.is_default() or role.managed or role >= me.top_role:
            continue
        seen.add(role_id)
        roles.append(role)
    return roles[:25]


class ConfiguredRoleSelect(discord.ui.Select):
    def __init__(
        self,
        roles: list[discord.Role],
        member: discord.Member,
        *,
        mode: str,
        row: int,
    ):
        member_ids = {role.id for role in member.roles}
        if mode == "add":
            choices = [role for role in roles if role.id not in member_ids]
            placeholder = "Ajouter des rôles…"
        else:
            choices = [role for role in roles if role.id in member_ids]
            placeholder = "Retirer des rôles…"

        options = [
            discord.SelectOption(label=role.name[:100], value=str(role.id))
            for role in choices[:25]
        ]
        if not options:
            options = [discord.SelectOption(label="Aucun rôle disponible", value="0")]

        super().__init__(
            placeholder=placeholder,
            min_values=1,
            max_values=max(1, len(options)),
            options=options,
            disabled=options[0].value == "0",
            custom_id=f"sentrix:selfroles:configured:{mode}",
            row=row,
        )
        self.mode = mode

    async def callback(self, interaction: discord.Interaction):
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("Serveur introuvable.", ephemeral=True)

        guild = interaction.guild
        member = interaction.user
        me = guild.me
        if me is None or not me.guild_permissions.manage_roles:
            return await interaction.response.edit_message(
                content="SentriX a besoin de **Gérer les rôles**.",
                view=None,
            )

        configured = {
            role.id: role
            for role in await _configured_roles(interaction.client, guild)
        }
        selected: list[discord.Role] = []
        for raw in self.values:
            if not raw.isdigit() or raw == "0":
                continue
            role = configured.get(int(raw))
            if role is not None:
                selected.append(role)

        member_ids = {role.id for role in member.roles}
        if self.mode == "add":
            roles = [role for role in selected if role.id not in member_ids]
        else:
            roles = [role for role in selected if role.id in member_ids]

        try:
            if self.mode == "add" and roles:
                await member.add_roles(*roles, reason="Choix de rôles SentriX")
                status = "Ajouté : " + ", ".join(role.name for role in roles)
            elif self.mode == "remove" and roles:
                await member.remove_roles(*roles, reason="Choix de rôles SentriX")
                status = "Retiré : " + ", ".join(role.name for role in roles)
            else:
                status = "Aucun rôle modifiable sélectionné."
        except discord.Forbidden:
            return await interaction.response.edit_message(
                content="SentriX ne peut pas gérer ces rôles. Placez son rôle plus haut.",
                view=None,
            )
        except discord.HTTPException:
            refreshed = await _private_view(interaction.client, guild, member)
            return await interaction.response.edit_message(
                content='Discord a refusé la modification. Réessayez dans quelques secondes.',
                view=refreshed,
            )

        fresh_member = member
        try:
            fresh_member = await guild.fetch_member(member.id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass

        await interaction.response.edit_message(
            content=f"✅ {status}",
            view=await _private_view(interaction.client, guild, fresh_member),
        )


async def _private_view(
    bot: commands.Bot,
    guild: discord.Guild,
    member: discord.Member,
) -> discord.ui.View:
    view = discord.ui.View(timeout=180)
    roles = await _configured_roles(bot, guild)
    view.add_item(ConfiguredRoleSelect(roles, member, mode="add", row=0))
    view.add_item(ConfiguredRoleSelect(roles, member, mode="remove", row=1))
    return view


class ServerSelfRoleView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Choisir mes rôles",
        style=discord.ButtonStyle.primary,
        custom_id="sentrix:selfroles:open:configured",
    )
    async def open_roles(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ):
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("Serveur introuvable.", ephemeral=True)

        roles = await _configured_roles(interaction.client, interaction.guild)
        if not roles:
            return await interaction.response.send_message(
                "Aucun rôle n'est configuré dans ce panel. "
                "Un administrateur peut les définir dans **+setup → Rôles → Panel de choix**.",
                ephemeral=True,
            )

        member = interaction.user
        try:
            member = await interaction.guild.fetch_member(interaction.user.id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass

        await interaction.response.send_message(
            '**Choix des rôles** — ajoute ou retirez uniquement les rôles que vous voulez.',
            view=await _private_view(interaction.client, interaction.guild, member),
            ephemeral=True,
        )


def build_embed() -> discord.Embed:
    embed = discord.Embed(
        title="Choix des rôles",
        description=(
            "Choisissez les rôles que le staff a configurés pour ce serveur.\n\nLe menu est **privé** : les autres membres ne voient pas vos choix. Un rôle déjà pris disparaît automatiquement de la liste d'ajout."
        ),
        color=0x7C6CFF,
    )
    embed.add_field(
        name="Rôles disponibles",
        value="La liste est synchronisée avec **+setup → Rôles → Panel de choix**.",
        inline=False,
    )
    embed.set_footer(text=MARKER)
    return embed


async def publish_or_refresh(
    bot: commands.Bot,
    channel: discord.TextChannel,
) -> discord.Message:
    message = None
    me = channel.guild.me
    if me is not None:
        try:
            async for candidate in channel.history(limit=50):
                if candidate.author.id != me.id or not candidate.embeds:
                    continue
                footer = candidate.embeds[0].footer.text
                if footer in {MARKER, LEGACY_MARKER}:
                    message = candidate
                    break
        except discord.HTTPException:
            pass

    view = ServerSelfRoleView()
    if message is None:
        message = await channel.send(embed=build_embed(), view=view)
    else:
        await message.edit(embed=build_embed(), view=view)
    return message


async def install(bot: commands.Bot) -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    bot.add_view(ServerSelfRoleView())
    _INSTALLED = True
    logger.info("Choix de rôles configurable et persistant SentriX activé.")
