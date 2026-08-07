"""Choix de rôles automatique pour les serveurs créés par SentriX."""
from __future__ import annotations

import logging

import discord
from discord.ext import commands

logger = logging.getLogger("bot.server-choice-roles")
_INSTALLED = False
MARKER = "SentriX • Choix rôles automatique v1"

ROLE_GROUPS = {
    "games": (
        "Jeux et plateformes",
        ("PC", "PlayStation", "Xbox", "Nintendo", "Mobile", "Roblox", "Minecraft", "Fortnite", "Valorant", "GTA", "Rocket League"),
    ),
    "languages": (
        "Langues et régions",
        ("Français", "English", "العربية", "Europe", "Afrique", "Amérique"),
    ),
    "colors": (
        "Couleurs",
        ("Rouge", "Orange", "Jaune", "Vert", "Bleu", "Violet", "Rose", "Cyan", "Blanc", "Noir"),
    ),
}


def _manageable_roles(guild: discord.Guild, names: tuple[str, ...]) -> list[discord.Role]:
    me = guild.me
    if me is None:
        return []
    result = []
    for name in names:
        role = discord.utils.get(guild.roles, name=name)
        if role is None or role.managed or role >= me.top_role:
            continue
        result.append(role)
    return result


class GroupRoleSelect(discord.ui.Select):
    def __init__(self, guild: discord.Guild, member: discord.Member, group_key: str, mode: str, row: int):
        _label, names = ROLE_GROUPS[group_key]
        roles = _manageable_roles(guild, names)
        member_ids = {role.id for role in member.roles}
        if mode == "add":
            roles = [role for role in roles if role.id not in member_ids]
            placeholder = "Ajouter des rôles…"
        else:
            roles = [role for role in roles if role.id in member_ids]
            placeholder = "Retirer des rôles…"

        options = [discord.SelectOption(label=role.name[:100], value=str(role.id)) for role in roles[:25]]
        if not options:
            options = [discord.SelectOption(label="Aucun rôle disponible", value="0")]
        super().__init__(
            placeholder=placeholder,
            min_values=1,
            max_values=max(1, len(options)),
            options=options,
            disabled=options[0].value == "0",
            custom_id=f"sentrix:selfroles:{group_key}:{mode}",
            row=row,
        )
        self.group_key = group_key
        self.mode = mode

    async def callback(self, interaction: discord.Interaction):
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("Serveur introuvable.", ephemeral=True)
        guild = interaction.guild
        member = interaction.user
        me = guild.me
        if me is None or not me.guild_permissions.manage_roles:
            return await interaction.response.edit_message(content="SentriX a besoin de **Gérer les rôles**.", view=None)

        roles = []
        for raw in self.values:
            if not raw.isdigit() or raw == "0":
                continue
            role = guild.get_role(int(raw))
            if role is not None and not role.managed and role < me.top_role:
                roles.append(role)
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
                content="SentriX ne peut pas gérer ces rôles. Place son rôle plus haut.",
                view=None,
            )
        except discord.HTTPException:
            return await interaction.response.edit_message(
                content="Discord a refusé la modification. Réessaie dans quelques secondes.",
                view=GroupPrivateView(guild, member, self.group_key),
            )

        # Force une lecture Discord fraîche : le rôle ajouté/retiré disparaît immédiatement
        # du bon menu au lieu d'attendre l'événement de cache on_member_update.
        fresh_member = member
        try:
            fresh_member = await guild.fetch_member(member.id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass

        await interaction.response.edit_message(
            content=f"✅ {status}",
            view=GroupPrivateView(guild, fresh_member, self.group_key),
        )


class GroupPrivateView(discord.ui.View):
    def __init__(self, guild: discord.Guild, member: discord.Member, group_key: str):
        super().__init__(timeout=180)
        self.add_item(GroupRoleSelect(guild, member, group_key, "add", 0))
        self.add_item(GroupRoleSelect(guild, member, group_key, "remove", 1))


class ServerSelfRoleView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def _open(self, interaction: discord.Interaction, group_key: str):
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("Serveur introuvable.", ephemeral=True)
        label, _names = ROLE_GROUPS[group_key]
        member = interaction.user
        try:
            member = await interaction.guild.fetch_member(interaction.user.id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass
        await interaction.response.send_message(
            f"**{label}** — ajoute ou retire uniquement les rôles que tu veux.",
            view=GroupPrivateView(interaction.guild, member, group_key),
            ephemeral=True,
        )

    @discord.ui.button(label="Jeux et plateformes", style=discord.ButtonStyle.primary, custom_id="sentrix:selfroles:open:games")
    async def games(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await self._open(interaction, "games")

    @discord.ui.button(label="Langues et régions", style=discord.ButtonStyle.secondary, custom_id="sentrix:selfroles:open:languages")
    async def languages(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await self._open(interaction, "languages")

    @discord.ui.button(label="Couleurs", style=discord.ButtonStyle.secondary, custom_id="sentrix:selfroles:open:colors")
    async def colors(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await self._open(interaction, "colors")


def build_embed() -> discord.Embed:
    e = discord.Embed(
        title="Choix des rôles",
        description=(
            "Personnalise ton profil avec les boutons ci-dessous.\n\n"
            "Les menus sont **privés** : les autres membres ne voient pas tes choix. "
            "Un rôle déjà pris disparaît automatiquement de la liste d'ajout."
        ),
        color=0x7C6CFF,
    )
    e.add_field(name="Jeux et plateformes", value="PC, consoles, mobile et jeux principaux.", inline=False)
    e.add_field(name="Langues et régions", value="Langue principale et région.", inline=False)
    e.add_field(name="Couleurs", value="Choisis une couleur de profil parmi les rôles disponibles.", inline=False)
    e.set_footer(text=MARKER)
    return e


async def publish_or_refresh(bot: commands.Bot, channel: discord.TextChannel) -> discord.Message:
    message = None
    try:
        async for candidate in channel.history(limit=50):
            if candidate.author.id != channel.guild.me.id or not candidate.embeds:
                continue
            if candidate.embeds[0].footer.text == MARKER:
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
    logger.info("Choix de rôles persistant SentriX activé.")
