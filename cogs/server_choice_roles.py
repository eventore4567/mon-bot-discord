"""Panel de choix de rôles configurable pour SentriX.

Le catalogue public ne contient aucun rôle codé en dur : les rôles proposés viennent
exclusivement de ``self_role_items`` et sont configurés depuis ``+setup`` > Rôles.

Ce module installe aussi le contrat final de ``+massrole`` : l'action porte sur TOUS les
membres du serveur et non plus sur une liste de mentions. ``+massrole add @Role`` ajoute
le rôle choisi à tous les membres humains ; ``+massrole del @Role`` le retire partout.
"""
from __future__ import annotations

import logging

import discord
from discord.ext import commands
from utils import checks, sentrix_panels as panels
from utils.owner_access import is_bot_owner_id

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
        message = await panels.envoyer(channel, panels.avec_composants(panels.depuis_embed(build_embed()), view))
    else:
        await panels.editer(message, panels.avec_composants(panels.depuis_embed(build_embed()), view))
    return message


@commands.command(
    name="massrole",
    help="Ajouter ou retirer un rôle à tous les membres du serveur.",
    usage="<add|del> <rôle>",
)
@commands.guild_only()
@checks.is_owner_or_admin()
async def _massrole_all_members(
    _verification_cog,
    ctx: commands.Context,
    action: str,
    role: discord.Role,
):
    """Implémentation finale de +massrole : le rôle choisi est appliqué au serveur entier."""
    guild = ctx.guild
    normalized = str(action or "").strip().casefold()
    if normalized in {"add", "ajout", "ajouter", "ajoute"}:
        mode = "add"
    elif normalized in {"del", "delete", "remove", "retirer", "retire", "supprimer", "supprime"}:
        mode = "remove"
    else:
        return await panels.envoyer(
            ctx,
            panels.depuis_embed(
                discord.Embed(
                    title="Massrole — action invalide",
                    description="Utilisez `+massrole add @Rôle` pour l'ajouter à tout le monde ou `+massrole del @Rôle` pour le retirer à tout le monde.",
                )
            ),
        )

    me = guild.me
    if role.is_default():
        problem = "Le rôle @everyone ne peut pas être ajouté ou retiré."
    elif role.managed:
        problem = "Ce rôle est géré par Discord ou une intégration et ne peut pas être modifié."
    elif me is None:
        problem = "SentriX n'est pas disponible dans le cache de ce serveur."
    elif not me.guild_permissions.manage_roles:
        problem = "SentriX a besoin de la permission **Gérer les rôles**."
    elif role >= me.top_role:
        problem = "Le rôle de SentriX doit être placé au-dessus du rôle à distribuer."
    else:
        problem = None

    if problem:
        return await panels.envoyer(
            ctx,
            panels.depuis_embed(discord.Embed(title="Massrole — impossible", description=problem)),
        )

    progress = await panels.envoyer(
        ctx,
        panels.depuis_embed(
            discord.Embed(
                title="Massrole — traitement en cours",
                description=(
                    f"{'Ajout' if mode == 'add' else 'Retrait'} de {role.mention} sur tous les membres du serveur. "
                    "SentriX traite les membres par lots pour respecter les limites Discord."
                ),
            )
        ),
    )

    added_or_removed = 0
    failed = 0
    skipped = 0
    protected = 0
    processed = 0
    batch_size = 15

    async def apply(member: discord.Member) -> None:
        nonlocal added_or_removed, failed, skipped, protected
        if member.bot:
            skipped += 1
            return
        has_role = role in member.roles
        if mode == "add" and has_role:
            skipped += 1
            return
        if mode == "remove" and not has_role:
            skipped += 1
            return
        # L'immunité propriétaire est aussi appliquée en garde bas niveau sur
        # Member.remove_roles ; on l'évite ici explicitement pour que le compteur final
        # ne prétende jamais qu'un derank protégé a réussi.
        if mode == "remove" and is_bot_owner_id(member.id):
            protected += 1
            return
        try:
            if mode == "add":
                await member.add_roles(role, reason=f"Massrole global par {ctx.author}")
            else:
                await member.remove_roles(role, reason=f"Massrole global par {ctx.author}")
            added_or_removed += 1
        except (discord.Forbidden, discord.HTTPException):
            failed += 1

    batch: list[discord.Member] = []
    try:
        async for member in guild.fetch_members(limit=None):
            batch.append(member)
            if len(batch) < batch_size:
                continue
            await __import__("asyncio").gather(*(apply(member) for member in batch))
            processed += len(batch)
            batch = []
            if processed % 2000 == 0:
                try:
                    await panels.editer(
                        progress,
                        panels.depuis_embed(
                            discord.Embed(
                                title="Massrole — progression",
                                description=f"**{processed}/{guild.member_count or '?'}** membres traités • **{added_or_removed}** modification(s) appliquée(s).",
                            )
                        ),
                    )
                except discord.HTTPException:
                    pass
        if batch:
            await __import__("asyncio").gather(*(apply(member) for member in batch))
            processed += len(batch)
    except (discord.Forbidden, discord.HTTPException):
        # Si Discord refuse l'énumération REST, le cache local est utilisé plutôt que
        # d'abandonner entièrement l'opération. Le résultat indique alors ce qui a été
        # réellement traité, sans inventer de succès.
        remaining = [member for member in guild.members if member not in batch]
        for offset in range(0, len(remaining), batch_size):
            current = remaining[offset:offset + batch_size]
            await __import__("asyncio").gather(*(apply(member) for member in current))
            processed += len(current)

    verb = "ajouté" if mode == "add" else "retiré"
    result = discord.Embed(
        title="Massrole terminé",
        description=f"Rôle {role.mention} **{verb}** pour **{added_or_removed}** membre(s).",
    )
    result.add_field(name="Traités", value=str(processed), inline=True)
    result.add_field(name="Ignorés", value=str(skipped), inline=True)
    result.add_field(name="Échecs", value=str(failed), inline=True)
    if protected:
        result.add_field(
            name="Protégés",
            value=f"{protected} compte(s) propriétaire(s) SentriX conservé(s) intact(s).",
            inline=False,
        )
    await panels.envoyer(ctx, panels.depuis_embed(result))


def _install_massrole_global(bot: commands.Bot) -> None:
    """Remplace l'ancienne variante « liste de mentions » sans laisser deux commandes."""
    verification_cog = bot.get_cog("Verification")
    if verification_cog is None:
        logger.warning("+massrole global non installé : cog Verification absent.")
        return

    current = bot.get_command("massrole")
    if current is _massrole_all_members:
        return
    if current is not None:
        bot.remove_command("massrole")

    # Reproduit le binding d'une commande déclarée dans le cog Verification : Discord.py
    # lui passera le cog puis ctx, et +help continuera de la classer dans les commandes
    # de rôles réservées au staff.
    _massrole_all_members._cog = verification_cog
    bot.add_command(_massrole_all_members)
    logger.info("+massrole global installé : add/del agit sur tous les membres.")


async def install(bot: commands.Bot) -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    bot.add_view(ServerSelfRoleView())
    _install_massrole_global(bot)
    _INSTALLED = True
    logger.info("Choix de rôles configurable et persistant SentriX activé.")