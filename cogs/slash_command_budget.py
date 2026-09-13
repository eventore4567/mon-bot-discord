"""Budget et sélection canonique des commandes slash SentriX."""
from __future__ import annotations

import logging
from types import MethodType

import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger("bot.slash-budget")
GLOBAL_CHAT_INPUT_BUDGET = 100

# Le catalogue historique occupe déjà la limite Discord. Quatre racines directes sont
# actuellement indisponibles à cause de collisions/anciens groupes ; on réserve ces
# emplacements aux quatre entrées réellement utiles du nouveau système de preuve. Les
# actions secondaires restent accessibles en + et via le panneau interactif.
PROOF_SLASH_PREFERRED = frozenset({"proof", "proofsetup", "proofexample", "proofstatus"})


def _preferred_names() -> set[str]:
    from .command_catalog_cleanup import NORMAL_DIRECT_COMMANDS

    return set(NORMAL_DIRECT_COMMANDS) | set(PROOF_SLASH_PREFERRED)


def _excluded_names() -> set[str]:
    from .command_catalog_cleanup import ADMIN_DIRECT_COMMANDS, MERGED_COMMANDS
    return set(ADMIN_DIRECT_COMMANDS) | set(MERGED_COMMANDS)


def _global_roots(tree) -> list:
    try:
        return list(tree.get_commands(guild=None, type=discord.AppCommandType.chat_input))
    except Exception:
        return [
            item for item in tree.get_commands(guild=None)
            if isinstance(item, (app_commands.Command, app_commands.Group))
        ]


async def _ticket_reply(
    interaction: discord.Interaction,
    *,
    title: str,
    description: str,
    success: bool = False,
    warning: bool = False,
    ephemeral: bool = True,
    file: discord.File | None = None,
) -> None:
    """Réponse compacte et fiable pour les sous-commandes /ticket."""
    from utils import embeds

    if success:
        embed = embeds.success(description)
        if title:
            embed.title = title
    elif warning:
        embed = embeds.warning(description)
        if title:
            embed.title = title
    else:
        embed = embeds.error(description)
        if title:
            embed.title = title

    kwargs = {"embed": embed, "ephemeral": ephemeral}
    if file is not None:
        kwargs["file"] = file

    if interaction.response.is_done():
        await interaction.followup.send(**kwargs)
    else:
        await interaction.response.send_message(**kwargs)


async def _ticket_record(bot: commands.Bot, interaction: discord.Interaction):
    cog = bot.get_cog("Tickets")
    if cog is None:
        await _ticket_reply(
            interaction,
            title="Tickets indisponibles",
            description="Le module Tickets n'est pas chargé. Réessayez après le redémarrage de SentriX.",
        )
        return None, None
    if interaction.guild is None or not isinstance(interaction.channel, discord.TextChannel):
        await _ticket_reply(
            interaction,
            title="Commande indisponible ici",
            description="Cette action doit être utilisée dans un salon de ticket sur un serveur.",
        )
        return cog, None
    ticket = await cog.get_ticket_by_channel(interaction.channel.id)
    if not ticket:
        await _ticket_reply(
            interaction,
            title="Ce salon n'est pas un ticket",
            description="Utilisez cette sous-commande directement dans le salon du ticket concerné.",
        )
        return cog, None
    return cog, ticket


async def _ticket_staff_allowed(cog, interaction: discord.Interaction, ticket, key: str) -> bool:
    """Même autorisation que les boutons persistants du ticket."""
    try:
        from .ticket_claim_security import _authorized_staff
        return await _authorized_staff(cog, interaction, ticket, key)
    except Exception:
        logger.exception("Vérification staff /ticket impossible.")
        member = interaction.user
        guild = interaction.guild
        return bool(
            guild
            and isinstance(member, discord.Member)
            and (
                member.id == guild.owner_id
                or member.guild_permissions.administrator
                or member.guild_permissions.manage_channels
            )
        )


async def _ticket_open(bot: commands.Bot, interaction: discord.Interaction) -> None:
    """Ouvre le même sélecteur que l'ancienne commande slash /ticket."""
    from . import tickets as ticket_runtime
    from utils import embeds

    cog = bot.get_cog("Tickets")
    if cog is None or interaction.guild is None:
        return await _ticket_reply(
            interaction,
            title="Tickets indisponibles",
            description="Le système de tickets n'est pas disponible sur ce serveur.",
        )

    # Respecte le switch ON/OFF du module lorsque le Setup V2 est présent.
    try:
        from . import setup_v2_core as core
        if not await core.module_enabled(bot, interaction.guild.id, "tickets"):
            return await _ticket_reply(
                interaction,
                title="Tickets désactivés",
                description="Le système de tickets est actuellement désactivé sur ce serveur.",
                warning=True,
            )
    except Exception:
        logger.debug("État du module Tickets impossible à lire pour /ticket open.", exc_info=True)

    panels = await bot.db.fetchall(
        "SELECT * FROM ticket_panels_v2 WHERE guild_id = ? AND enabled = 1",
        (interaction.guild.id,),
    )
    available = []
    for panel in panels:
        types = await cog.get_panel_types(panel["id"])
        if types:
            available.append((panel, types))

    if not available:
        return await _ticket_reply(
            interaction,
            title="Aucun panel configuré",
            description="Un administrateur doit d'abord configurer les tickets dans `/setup` → **Tickets**.",
            warning=True,
        )

    if len(available) == 1:
        panel, types = available[0]
        return await interaction.response.send_message(
            embed=cog.build_panel_embed(panel),
            view=ticket_runtime.TicketPanelView(panel, types),
            ephemeral=True,
        )

    view = discord.ui.View(timeout=180)
    options = [
        discord.SelectOption(
            label=str(panel["name"])[:100],
            value=str(panel["id"]),
            description=(str(panel["description"] or "")[:100] or None),
        )
        for panel, _types in available[:25]
    ]
    select = discord.ui.Select(
        placeholder="Choisissez le type de support",
        min_values=1,
        max_values=1,
        options=options,
    )

    async def on_pick(sub_interaction: discord.Interaction):
        panel_id = int(select.values[0])
        panel, types = next(
            (candidate, candidate_types)
            for candidate, candidate_types in available
            if int(candidate["id"]) == panel_id
        )
        await sub_interaction.response.edit_message(
            embed=cog.build_panel_embed(panel),
            view=ticket_runtime.TicketPanelView(panel, types),
        )

    select.callback = on_pick
    view.add_item(select)
    await interaction.response.send_message(
        embed=embeds.neutral(
            "🎫 Ouvrir un ticket",
            "Sélectionnez la catégorie correspondant à votre demande.",
        ),
        view=view,
        ephemeral=True,
    )


def _install_ticket_group(bot: commands.Bot) -> bool:
    """Remplace l'ancienne racine slash /ticket par un vrai groupe de sous-commandes.

    Les commandes préfixées (+ticket, +ticketsetup, etc.) ne sont jamais retirées.
    """
    get_cog = getattr(bot, "get_cog", None)
    cog = get_cog("Tickets") if callable(get_cog) else None
    # Les tests du budget utilisent des Mock génériques : ne jamais installer un faux
    # groupe /ticket tant qu'un vrai Cog discord.py Tickets n'est pas présent.
    if not isinstance(cog, commands.Cog):
        return False
    if getattr(bot, "_sentrix_ticket_slash_group_v2", False):
        return True

    tree = bot.tree
    try:
        existing = tree.get_command("ticket", type=discord.AppCommandType.chat_input)
    except TypeError:
        existing = tree.get_command("ticket")
    if isinstance(existing, app_commands.Group) and {
        "open", "close", "reopen", "claim", "unclaim", "add", "remove", "rename", "transcript"
    }.issubset({command.name for command in existing.commands}):
        bot._sentrix_ticket_slash_group_v2 = True
        return True

    group = app_commands.Group(
        name="ticket",
        description="Ouvrir et gérer les tickets SentriX.",
    )

    @group.command(name="open", description="Ouvrir un ticket de support.")
    async def ticket_open(interaction: discord.Interaction):
        await _ticket_open(bot, interaction)

    async def control(interaction: discord.Interaction, key: str) -> None:
        cog, ticket = await _ticket_record(bot, interaction)
        if ticket is None:
            return
        await cog.handle_control_button(interaction, key)

    @group.command(name="close", description="Fermer ce ticket.")
    async def ticket_close(interaction: discord.Interaction):
        await control(interaction, "close")

    @group.command(name="claim", description="Prendre ce ticket en charge.")
    async def ticket_claim(interaction: discord.Interaction):
        await control(interaction, "claim")

    @group.command(name="unclaim", description="Abandonner la prise en charge de ce ticket.")
    async def ticket_unclaim(interaction: discord.Interaction):
        await control(interaction, "unclaim")

    @group.command(name="add", description="Ajouter un membre à ce ticket.")
    async def ticket_add(interaction: discord.Interaction):
        await control(interaction, "add")

    @group.command(name="remove", description="Retirer un membre de ce ticket.")
    async def ticket_remove(interaction: discord.Interaction):
        await control(interaction, "remove")

    @group.command(name="rename", description="Renommer ce salon de ticket.")
    async def ticket_rename(interaction: discord.Interaction):
        await control(interaction, "rename")

    @group.command(name="reopen", description="Rouvrir ce ticket avant sa suppression.")
    async def ticket_reopen(interaction: discord.Interaction):
        cog, ticket = await _ticket_record(bot, interaction)
        if ticket is None:
            return
        if ticket["status"] != "ferme":
            return await _ticket_reply(
                interaction,
                title="Ticket déjà ouvert",
                description="Ce ticket n'est pas fermé.",
                warning=True,
            )
        if not await _ticket_staff_allowed(cog, interaction, ticket, "claim"):
            return await _ticket_reply(
                interaction,
                title="Permission refusée",
                description="Cette action est réservée au staff autorisé du ticket.",
            )

        await bot.db.execute(
            "UPDATE tickets SET status='ouvert', closed_at=NULL, locked=0, last_activity_at=? WHERE id=?",
            (int(discord.utils.utcnow().timestamp()), ticket["id"]),
        )
        owner = interaction.guild.get_member(int(ticket["user_id"]))
        if owner:
            overwrite = interaction.channel.overwrites_for(owner)
            overwrite.view_channel = True
            overwrite.send_messages = True
            overwrite.read_message_history = True
            try:
                await interaction.channel.set_permissions(
                    owner,
                    overwrite=overwrite,
                    reason=f"Ticket rouvert par {interaction.user}",
                )
            except discord.HTTPException:
                logger.exception("Impossible de rétablir les permissions du créateur du ticket %s.", ticket["id"])

        await _ticket_reply(
            interaction,
            title="Ticket rouvert",
            description=f"{interaction.user.mention} a rouvert ce ticket.",
            success=True,
            ephemeral=False,
        )

    @group.command(name="transcript", description="Générer la transcription de ce ticket.")
    async def ticket_transcript(interaction: discord.Interaction):
        cog, ticket = await _ticket_record(bot, interaction)
        if ticket is None:
            return
        if not await _ticket_staff_allowed(cog, interaction, ticket, "claim"):
            return await _ticket_reply(
                interaction,
                title="Permission refusée",
                description="La transcription est réservée au staff autorisé du ticket.",
            )

        await interaction.response.defer(ephemeral=True)
        try:
            transcript = await cog.generate_transcript(interaction.channel)
        except discord.HTTPException:
            return await _ticket_reply(
                interaction,
                title="Transcript impossible",
                description="Discord n'a pas permis de lire l'historique complet de ce ticket.",
            )
        await interaction.followup.send(
            content=f"Transcription du ticket **#{ticket['id']}**.",
            file=transcript,
            ephemeral=True,
        )

    @group.command(name="setup", description="Ouvrir la configuration complète des tickets.")
    @app_commands.default_permissions(administrator=True)
    async def ticket_setup(interaction: discord.Interaction):
        from . import tickets as ticket_runtime
        from utils import embeds
        from utils import sentrix_panels as panels_ui

        member = interaction.user
        if (
            interaction.guild is None
            or not isinstance(member, discord.Member)
            or not (
                member.id == interaction.guild.owner_id
                or member.guild_permissions.administrator
            )
        ):
            return await _ticket_reply(
                interaction,
                title="Permission refusée",
                description="Vous devez avoir la permission **Administrateur** pour configurer les tickets.",
            )
        cog = bot.get_cog("Tickets")
        if cog is None:
            return await _ticket_reply(
                interaction,
                title="Tickets indisponibles",
                description="Le module Tickets n'est pas chargé.",
            )
        embed = embeds.brand(
            "🎫 Configuration des tickets",
            "Gérez les panels, les types de tickets, le rôle support, les catégories, les formulaires et les boutons.",
        )
        await panels_ui.envoyer(
            interaction.response,
            panels_ui.avec_composants(
                panels_ui.depuis_embed(embed),
                ticket_runtime.TicketSetupHubView(cog, interaction.user.id),
            ),
            ephemere=True,
        )

    # override=True remplace l'ancienne commande slash /ticket SANS libérer puis
    # réallouer une racine. On ne crée donc aucun trou temporaire dans le budget de 100.
    tree.add_command(group, override=True)
    try:
        installed = tree.get_command("ticket", type=discord.AppCommandType.chat_input)
    except TypeError:
        installed = tree.get_command("ticket")
    if not isinstance(installed, app_commands.Group):
        logger.error("Le groupe /ticket n'a pas pu être enregistré ; ancienne surface conservée si disponible.")
        return False

    bot._sentrix_ticket_slash_group_v2 = True
    logger.info(
        "Slash Tickets V2 actif : /ticket open|close|reopen|claim|unclaim|add|remove|rename|transcript|setup."
    )
    return True


def finalize(bot: commands.Bot) -> None:
    """Écarte les racines fusionnées/admin et garantit au maximum 100 racines /."""
    tree = bot.tree
    preferred = _preferred_names()
    excluded = _excluded_names()

    # Quand le Cog Tickets est déjà chargé, /ticket devient une seule racine avec
    # plusieurs sous-commandes. Cela économise le budget global sans supprimer d'actions.
    _install_ticket_group(bot)

    for item in list(_global_roots(tree)):
        name = str(getattr(item, "name", "") or "").casefold()
        if name in excluded:
            try:
                tree.remove_command(name, type=discord.AppCommandType.chat_input)
            except TypeError:
                tree.remove_command(name)

    roots = _global_roots(tree)
    if len(roots) <= GLOBAL_CHAT_INPUT_BUDGET:
        return

    keep: set[str] = set()
    for item in roots:
        name = str(getattr(item, "name", "") or "").casefold()
        if name in preferred and len(keep) < GLOBAL_CHAT_INPUT_BUDGET:
            keep.add(name)
    for item in roots:
        name = str(getattr(item, "name", "") or "").casefold()
        if name not in keep and len(keep) < GLOBAL_CHAT_INPUT_BUDGET:
            keep.add(name)

    for item in list(roots):
        name = str(getattr(item, "name", "") or "").casefold()
        if name not in keep:
            try:
                tree.remove_command(name, type=discord.AppCommandType.chat_input)
            except TypeError:
                tree.remove_command(name)


def install(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_slash_budget_installed", False):
        _install_ticket_group(bot)
        finalize(bot)
        return
    bot._sentrix_slash_budget_installed = True

    tree = bot.tree
    original_add = tree.add_command
    skipped: list[str] = []
    bot._sentrix_skipped_global_slash = skipped

    def _call_original(command, *, guild=None, guilds=None, override: bool = False):
        kwargs = {"override": override}
        if guild is not None:
            kwargs["guild"] = guild
        if guilds is not None:
            kwargs["guilds"] = guilds
        try:
            return original_add(command, **kwargs)
        except app_commands.CommandLimitReached:
            name = str(getattr(command, "name", "") or "").casefold()
            skipped.append(name)
            logger.warning(
                "Budget slash : « %s » écartée après échec réel de discord.py "
                "(limite 100 déjà atteinte malgré le comptage local).",
                name,
            )
            return None

    def budgeted_add(
        _tree,
        command,
        *,
        guild=None,
        guilds=None,
        override: bool = False,
    ):
        if guild is not None or guilds is not None:
            return _call_original(command, guild=guild, guilds=guilds, override=override)

        if isinstance(command, (app_commands.Command, app_commands.Group)):
            name = str(getattr(command, "name", "") or "").casefold()
            if name in _excluded_names():
                skipped.append(name)
                return None

            roots = _global_roots(tree)
            existing = next(
                (item for item in roots if str(getattr(item, "name", "")).casefold() == name),
                None,
            )
            if existing is None and len(roots) >= GLOBAL_CHAT_INPUT_BUDGET:
                preferred = _preferred_names()
                if name in preferred:
                    victim = next(
                        (
                            item for item in roots
                            if str(getattr(item, "name", "")).casefold() not in preferred
                        ),
                        None,
                    )
                    if victim is not None:
                        victim_name = str(getattr(victim, "name", "")).casefold()
                        try:
                            tree.remove_command(victim_name, type=discord.AppCommandType.chat_input)
                        except TypeError:
                            tree.remove_command(victim_name)
                    else:
                        skipped.append(name)
                        return None
                else:
                    skipped.append(name)
                    return None

        return _call_original(command, override=override)

    tree.add_command = MethodType(budgeted_add, tree)
    finalize(bot)
    logger.info(
        "Budget slash SentriX actif : maximum %s racines, proof essentiel réservé=%s.",
        GLOBAL_CHAT_INPUT_BUDGET,
        ",".join(sorted(PROOF_SLASH_PREFERRED)),
    )
