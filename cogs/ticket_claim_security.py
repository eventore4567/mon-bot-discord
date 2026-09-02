"""Sécurise les boutons staff, les claims, les ouvertures et les logs de tickets.

Cette couche est installée directement avec ``cogs.tickets``. Elle constitue donc le bon
endroit pour les correctifs runtime qui doivent être présents sur toutes les ouvertures :
- anti-double ouverture ;
- permissions des boutons staff ;
- suppression de l'ancien bloc « Priorité détectée » ;
- logs ouverture/fermeture exclusivement via ``utils.log_service`` ;
- une panne de log ne peut jamais transformer un ticket déjà créé en erreur utilisateur.
"""
from __future__ import annotations

import asyncio
import logging
import unicodedata

import discord
from discord.ext import commands

from utils import log_service
from utils import sentrix_panels as panels

logger = logging.getLogger("bot.tickets.claim-security")
_INSTALLED = False
_CREATING: set[tuple[int, int, int]] = set()

_STAFF_ONLY_KEYS = {"claim", "unclaim", "add", "remove", "rename", "transfer", "note", "bump"}


def _plain(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return " ".join(text.casefold().replace("⚡", " ").split())


def _priority_only_embed(embed: discord.Embed) -> bool:
    title = _plain(embed.title)
    description = _plain(embed.description)
    return "priorite detectee" in title and description in {"", "normale", "normal"}


def _without_priority_field(embed: discord.Embed) -> tuple[discord.Embed, bool]:
    """Retire uniquement l'ancien champ de priorité sans toucher au reste du ticket."""
    data = embed.to_dict()
    fields = list(data.get("fields") or [])
    kept = [
        field
        for field in fields
        if "priorite detectee" not in _plain(field.get("name"))
    ]
    if len(kept) == len(fields):
        return embed, False
    if kept:
        data["fields"] = kept
    else:
        data.pop("fields", None)
    return discord.Embed.from_dict(data), True


async def _remove_priority_cards(channel: discord.TextChannel, bot_user_id: int | None) -> None:
    """Nettoie les anciens blocs de priorité générés autour de l'ouverture du ticket.

    La priorité continue d'exister en base pour la compatibilité des anciens outils, mais
    elle n'est plus affichée dans le ticket. Le nettoyage est volontairement limité aux
    messages envoyés par SentriX dans CE salon de ticket.
    """
    if not bot_user_id:
        return
    try:
        async for message in channel.history(limit=30, oldest_first=False):
            if message.author.id != bot_user_id or not message.embeds:
                continue

            cleaned: list[discord.Embed] = []
            changed = False
            for embed in message.embeds:
                if _priority_only_embed(embed):
                    changed = True
                    continue
                new_embed, field_changed = _without_priority_field(embed)
                cleaned.append(new_embed)
                changed = changed or field_changed

            if not changed:
                continue

            try:
                # Si le message ne servait qu'à afficher la priorité, on le supprime.
                # Sinon on ne touche qu'aux embeds afin de préserver boutons/contenu.
                if not cleaned and not (message.content or "").strip():
                    await message.delete()
                else:
                    await message.edit(embeds=cleaned)
            except (discord.Forbidden, discord.NotFound, discord.HTTPException):
                logger.debug("Nettoyage du bloc priorité impossible message=%s", message.id, exc_info=True)
    except (discord.Forbidden, discord.HTTPException):
        logger.debug("Lecture du ticket impossible pour nettoyer la priorité.", exc_info=True)


async def _delayed_priority_cleanup(channel: discord.TextChannel, bot_user_id: int | None) -> None:
    # Une ancienne couche peut publier son bloc quelques centaines de ms après le message
    # d'accueil. Un second passage couvre ce cas sans ralentir l'interaction utilisateur.
    await asyncio.sleep(1.5)
    await _remove_priority_cards(channel, bot_user_id)


async def _ticket_type(cog, ticket):
    type_id = ticket["type_id"] if ticket else None
    if not type_id:
        return None
    try:
        return await cog.get_type(type_id)
    except Exception:
        return None


async def _authorized_staff(cog, interaction: discord.Interaction, ticket, key: str) -> bool:
    guild = interaction.guild
    member = interaction.user
    if guild is None or not isinstance(member, discord.Member):
        return False
    if member.id == guild.owner_id or member.guild_permissions.administrator:
        return True

    from . import tickets

    settings = await tickets.get_button_settings(cog.bot, guild.id)
    cfg = settings.get(key, {})
    configured_role_id = cfg.get("role_id")
    if configured_role_id:
        configured_role = guild.get_role(int(configured_role_id))
        return bool(configured_role and configured_role in member.roles)

    ticket_type = await _ticket_type(cog, ticket)
    staff_role_id = ticket_type["staff_role_id"] if ticket_type else None
    if not staff_role_id:
        return False
    staff_role = guild.get_role(int(staff_role_id))
    return bool(staff_role and staff_role in member.roles)


async def _set_staff_role_visibility(cog, channel: discord.TextChannel, ticket, *, visible: bool) -> None:
    ticket_type = await _ticket_type(cog, ticket)
    staff_role_id = ticket_type["staff_role_id"] if ticket_type else None
    if not staff_role_id:
        return
    staff_role = channel.guild.get_role(int(staff_role_id))
    if staff_role is None:
        return

    overwrite = channel.overwrites_for(staff_role)
    overwrite.view_channel = visible
    overwrite.send_messages = visible
    overwrite.read_message_history = visible
    try:
        await channel.set_permissions(
            staff_role,
            overwrite=overwrite,
            reason=("Ticket pris en charge : accès réservé" if not visible else "Prise en charge annulée : accès staff rétabli"),
        )
    except discord.HTTPException:
        logger.exception("Impossible de modifier l'accès du rôle staff au ticket %s.", ticket["id"])


async def _grant_claimant(channel: discord.TextChannel, member: discord.Member) -> None:
    overwrite = channel.overwrites_for(member)
    overwrite.view_channel = True
    overwrite.send_messages = True
    overwrite.read_message_history = True
    overwrite.attach_files = True
    await channel.set_permissions(member, overwrite=overwrite, reason="Ticket pris en charge")


async def _remove_claimant_override(channel: discord.TextChannel, member: discord.Member | None, owner_id: int) -> None:
    if member is None or member.id == owner_id or member.guild_permissions.administrator:
        return
    try:
        await channel.set_permissions(member, overwrite=None, reason="Fin de prise en charge du ticket")
    except discord.HTTPException:
        pass


async def _private_reply(interaction: discord.Interaction, embed: discord.Embed) -> None:
    try:
        if interaction.response.is_done():
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message(embed=embed, ephemeral=True)
    except discord.HTTPException:
        pass


async def _safe_ticket_log(cog, guild: discord.Guild, log_type: str, embed: discord.Embed, **kwargs) -> bool:
    """Journalise sans jamais casser l'action métier qui vient de réussir."""
    try:
        sent = await log_service.send_log(cog.bot, guild, log_type, embed, **kwargs)
        if not sent:
            logger.warning(
                "Log ticket non envoyé guild=%s type=%s : route désactivée/invalide ou transport indisponible.",
                guild.id,
                log_type,
            )
        return bool(sent)
    except Exception:
        logger.exception("Échec du log ticket guild=%s type=%s ; action métier conservée.", guild.id, log_type)
        return False


def install(bot: commands.Bot) -> None:
    del bot
    global _INSTALLED
    if _INSTALLED:
        return

    from . import tickets

    original_handle = tickets.Tickets.handle_control_button
    original_create_ticket = tickets.Tickets.create_ticket

    async def secure_log_action(self, guild: discord.Guild, embed: discord.Embed, log_channel_id=None):
        """Ignore les anciens IDs par type : la route officielle est ``logs-tickets``.

        C'est volontaire : un ancien ``ticket_types.log_channel_id`` pouvait pointer vers
        un salon supprimé ou vers l'ancienne modération. Le nouveau Setup configure la
        catégorie Tickets dans ``log_config`` ; c'est désormais l'unique source de vérité.
        """
        del log_channel_id
        title = _plain(embed.title)
        log_type = "ticket_close" if "ferm" in title else "ticket_open"
        return await _safe_ticket_log(self, guild, log_type, embed)

    async def secure_handle_control_button(self, interaction: discord.Interaction, key: str):
        ticket = await self.get_ticket_by_channel(interaction.channel.id)
        if not ticket:
            return await original_handle(self, interaction, key)

        if key in _STAFF_ONLY_KEYS:
            if not await _authorized_staff(self, interaction, ticket, key):
                return await panels.envoyer(interaction.response, panels.depuis_embed(tickets.embeds.error('Ce bouton est réservé au staff autorisé de ce ticket.')), ephemere=True)
        elif key == "close":
            # Le créateur peut fermer son propre ticket. Pour tous les autres membres,
            # il faut être staff autorisé.
            if interaction.user.id != ticket["user_id"] and not await _authorized_staff(self, interaction, ticket, key):
                return await panels.envoyer(interaction.response, panels.depuis_embed(tickets.embeds.error("Vous n'êtes pas autorisé à fermer ce ticket.")), ephemere=True)

        return await original_handle(self, interaction, key)

    async def secure_create_ticket(self, interaction: discord.Interaction, ticket_type, answers: list):
        """Empêche les doubles tickets et nettoie les éléments visuels obsolètes."""
        guild = interaction.guild
        user = interaction.user
        if guild is None or user is None:
            return await original_create_ticket(self, interaction, ticket_type, answers)

        type_id = int(ticket_type["id"])
        key = (guild.id, user.id, type_id)
        if key in _CREATING:
            return await _private_reply(
                interaction,
                tickets.embeds.warning("Une ouverture de ticket est déjà en cours. Inutile de cliquer plusieurs fois."),
            )

        _CREATING.add(key)
        try:
            # Recontrôle atomique juste avant la création réelle.
            limit = int(ticket_type["max_per_member"] or 1)
            row = await self.bot.db.fetchone(
                "SELECT COUNT(*) c FROM tickets WHERE guild_id = ? AND user_id = ? AND type_id = ? AND status = 'ouvert'",
                (guild.id, user.id, type_id),
            )
            current = int(row["c"] if row else 0)
            if current >= limit:
                return await _private_reply(
                    interaction,
                    tickets.embeds.warning(
                        f"Vous avez déjà **{current}** ticket(s) « {ticket_type['name']} » ouvert(s) (maximum : {limit})."
                    ),
                )

            # ``Tickets.create_ticket`` envoie le succès puis journalise. ``self.log_action``
            # est désormais sans exception : une panne de logs ne peut plus retomber dans
            # start_ticket_flow et produire un faux « Action impossible » après le succès.
            result = await original_create_ticket(self, interaction, ticket_type, answers)

            latest = await self.bot.db.fetchone(
                "SELECT channel_id FROM tickets WHERE guild_id=? AND user_id=? AND type_id=? AND status='ouvert' "
                "ORDER BY id DESC LIMIT 1",
                (guild.id, user.id, type_id),
            )
            if latest:
                channel = guild.get_channel(int(latest["channel_id"]))
                if isinstance(channel, discord.TextChannel):
                    await _remove_priority_cards(channel, getattr(self.bot.user, "id", None))
                    asyncio.create_task(
                        _delayed_priority_cleanup(channel, getattr(self.bot.user, "id", None)),
                        name=f"sentrix-ticket-priority-cleanup-{channel.id}",
                    )
            return result
        finally:
            _CREATING.discard(key)

    async def secure_close_ticket(self, interaction: discord.Interaction, ticket_id: int, reason: str):
        """Ferme le ticket et écrit toujours le journal dans la catégorie Tickets.

        Cette version supprime les anciens ``target_channel.send`` / fallback Modération,
        responsables des logs absents ou placés dans le mauvais salon.
        """
        guild = interaction.guild
        if guild is None:
            return
        ticket = await self.bot.db.fetchone("SELECT * FROM tickets WHERE id = ?", (ticket_id,))
        if not ticket:
            return
        channel = guild.get_channel(int(ticket["channel_id"]))
        if not isinstance(channel, discord.TextChannel):
            return

        conf = await self.bot.db.get_guild_config(guild.id)
        closed_at = tickets.now()
        await self.bot.db.execute(
            "UPDATE tickets SET status='ferme', closed_at=?, locked=1 WHERE id=?",
            (closed_at, ticket_id),
        )

        owner = guild.get_member(int(ticket["user_id"]))
        if owner:
            overwrite = channel.overwrites_for(owner)
            overwrite.send_messages = False
            try:
                await channel.set_permissions(owner, overwrite=overwrite)
            except discord.HTTPException:
                pass

        try:
            transcript_text = await self._fetch_transcript_text(channel)
        except discord.HTTPException:
            transcript_text = "Transcription indisponible (erreur lors de la lecture du salon)."

        delay = (conf["ticket_delete_delay"] if conf else 30) or 30
        asyncio.create_task(self._auto_delete(channel, ticket_id, delay))

        reason_text = (reason or "Non précisée").strip()[:1200]
        try:
            await channel.send(
                embed=tickets.embeds.warning(
                    f"🔒 Ticket fermé par {interaction.user.mention}.\nRaison : {reason_text}\n\n"
                    f"Suppression automatique dans **{tickets.helpers.format_duration(delay)}**."
                ),
                file=self._transcript_file(channel, transcript_text),
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except discord.HTTPException:
            pass

        participants = [
            f"{member.display_name} (`{member.id}`)"
            for member in channel.members
            if not member.bot
        ][:30]
        participant_text = "\n".join(participants) or "Aucun participant disponible."
        member_ref = f"<@{int(ticket['user_id'])}> (`{int(ticket['user_id'])}`)"
        moderator_ref = f"<@{interaction.user.id}> (`{interaction.user.id}`)"
        log_embed = discord.Embed(
            title="🔒 Fermeture du ticket",
            description=(
                f"**Modérateur :** {moderator_ref}\n"
                f"**Membre :** {member_ref}\n"
                f"**Création du ticket :** <t:{int(ticket['created_at'] or closed_at)}:R>\n"
                f"**Raison :** {reason_text}\n\n"
                f"**Participants :**\n{participant_text}"
            )[:3900],
            colour=discord.Colour(0xA05CFF),
            timestamp=discord.utils.utcnow(),
        )
        log_embed.set_footer(text="SentriX")
        event_key = log_service.make_event_key(
            guild.id,
            "ticket_close",
            target_id=int(ticket["user_id"]),
            executor_id=interaction.user.id,
            discriminator=ticket_id,
        )
        await _safe_ticket_log(
            self,
            guild,
            "ticket_close",
            log_embed,
            file=self._transcript_file(channel, transcript_text),
            event_key=event_key,
            identity_name=(owner.display_name if owner else f"Membre {ticket['user_id']}"),
            identity_id=int(ticket["user_id"]),
            identity_icon=(str(owner.display_avatar.url) if owner else None),
        )

        if owner and (not conf or conf["ticket_transcript_dm"]):
            try:
                await owner.send(
                    embed=tickets.embeds.info(f"Voici la transcription de votre ticket sur **{guild.name}**."),
                    file=self._transcript_file(channel, transcript_text),
                )
            except (discord.Forbidden, discord.HTTPException):
                pass
            if not conf or conf["ticket_rating_enabled"]:
                try:
                    await owner.send(
                        content="Pouvez-vous noter le support reçu ?",
                        view=tickets.RatingView(self, ticket_id),
                    )
                except (discord.Forbidden, discord.HTTPException):
                    pass

    async def secure_claim(self, interaction: discord.Interaction, ticket):
        channel = interaction.channel
        guild = interaction.guild
        member = interaction.user
        if not isinstance(channel, discord.TextChannel) or guild is None or not isinstance(member, discord.Member):
            return await panels.envoyer(interaction.response, panels.depuis_embed(tickets.embeds.error('Impossible de prendre en charge ce ticket.')), ephemere=True)

        current_id = ticket["claimed_by"]
        if current_id:
            if int(current_id) == member.id:
                return await panels.envoyer(interaction.response, panels.depuis_embed(tickets.embeds.warning('Vous avez déjà pris en charge ce ticket.')), ephemere=True)
            if not member.guild_permissions.administrator and member.id != guild.owner_id:
                current = guild.get_member(int(current_id))
                return await panels.envoyer(interaction.response, panels.depuis_embed(tickets.embeds.warning(f"Ce ticket est déjà pris en charge par {(current.mention if current else 'un autre membre du staff')}.")), ephemere=True)

        await interaction.response.defer()

        old_member = guild.get_member(int(current_id)) if current_id else None
        if old_member and old_member.id != member.id:
            await _remove_claimant_override(channel, old_member, int(ticket["user_id"]))

        await _set_staff_role_visibility(self, channel, ticket, visible=False)
        try:
            await _grant_claimant(channel, member)
        except discord.Forbidden:
            return await panels.envoyer(interaction.followup, panels.depuis_embed(tickets.embeds.error("SentriX n'a pas la permission de modifier les accès de ce ticket.")), ephemere=True)

        await self.bot.db.execute(
            "UPDATE tickets SET claimed_by = ?, last_activity_at = ? WHERE id = ?",
            (member.id, tickets.now(), ticket["id"]),
        )
        await panels.envoyer(interaction.followup, panels.depuis_embed(tickets.embeds.success(f"{member.mention} a pris en charge ce ticket. L'accès est maintenant réservé au créateur, au membre en charge et aux Administrateurs.")))

    async def secure_unclaim(self, interaction: discord.Interaction, ticket):
        guild = interaction.guild
        channel = interaction.channel
        member = interaction.user
        if guild is None or not isinstance(channel, discord.TextChannel) or not isinstance(member, discord.Member):
            return await panels.envoyer(interaction.response, panels.depuis_embed(tickets.embeds.error('Action impossible.')), ephemere=True)

        current_id = ticket["claimed_by"]
        if not current_id:
            return await panels.envoyer(interaction.response, panels.depuis_embed(tickets.embeds.warning("Ce ticket n'est pas actuellement pris en charge.")), ephemere=True)
        if int(current_id) != member.id and not member.guild_permissions.administrator and member.id != guild.owner_id:
            return await panels.envoyer(interaction.response, panels.depuis_embed(tickets.embeds.error('Seul le membre en charge ou un Administrateur peut abandonner ce ticket.')), ephemere=True)

        await interaction.response.defer()
        claimant = guild.get_member(int(current_id))
        await _remove_claimant_override(channel, claimant, int(ticket["user_id"]))
        await _set_staff_role_visibility(self, channel, ticket, visible=True)
        await self.bot.db.execute(
            "UPDATE tickets SET claimed_by = NULL, last_activity_at = ? WHERE id = ?",
            (tickets.now(), ticket["id"]),
        )
        await panels.envoyer(interaction.followup, panels.depuis_embed(tickets.embeds.success("Prise en charge annulée. L'accès du rôle staff a été rétabli.")))

    # Important : ``create_ticket`` appelle ``self.log_action`` dynamiquement. Installer
    # d'abord le transport sûr suffit donc à empêcher le faux message rouge après succès.
    tickets.Tickets.log_action = secure_log_action
    tickets.Tickets.handle_control_button = secure_handle_control_button
    tickets.Tickets.create_ticket = secure_create_ticket
    tickets.Tickets.close_ticket = secure_close_ticket
    tickets.Tickets.btn_claim = secure_claim
    tickets.Tickets.btn_unclaim = secure_unclaim
    _INSTALLED = True
    logger.info(
        "Sécurité tickets activée : claims, anti-double ouverture, priorité masquée et logs-tickets canoniques."
    )
