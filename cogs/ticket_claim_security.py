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

from services import tickets as tickets_service
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
            await panels.envoyer(interaction.followup, panels.depuis_embed(embed), ephemere=True)
        else:
            await panels.envoyer(interaction.response, panels.depuis_embed(embed), ephemere=True)
    except discord.HTTPException:
        pass


#: Titre canonique -> événement, retourné depuis la source unique
#: ``services.tickets.EVENEMENTS_TICKET``. Construit ici une seule fois : une
#: correspondance exacte ne peut pas se tromper, là où un « in » confondait
#: « Ticket fermé » et « Ticket fermé automatiquement ».
_TITRES_CANONIQUES: dict[str, str] = {
    titre: evenement
    for evenement, (titre, _libelle) in tickets_service.EVENEMENTS_TICKET.items()
}


async def _safe_ticket_log(cog, guild: discord.Guild, log_type: str, embed: discord.Embed, **kwargs) -> bool:
    """Journalise sans jamais casser l'action métier qui vient de réussir.

    Voir services/tickets.py::safe_ticket_log() pour le comportement — cette
    fonction reste ici comme adaptateur mince (elle n'a que `cog.bot` à passer).
    """
    return await tickets_service.safe_ticket_log(cog.bot, guild, log_type, embed, **kwargs)


def install(bot: commands.Bot) -> None:
    del bot
    global _INSTALLED
    if _INSTALLED:
        return

    from . import tickets

    original_handle = tickets.Tickets.handle_control_button
    original_create_ticket = tickets.Tickets.create_ticket

    async def secure_log_action(self, guild: discord.Guild, embed: discord.Embed,
                                log_channel_id=None, *, log_type: str | None = None):
        """Ignore les anciens IDs par type : la route officielle est ``logs-tickets``.

        C'est volontaire : un ancien ``ticket_types.log_channel_id`` pouvait pointer vers
        un salon supprimé ou vers l'ancienne modération. Le nouveau Setup configure la
        catégorie Tickets dans ``log_config`` ; c'est désormais l'unique source de vérité.

        **Le classement du type d'événement a changé.** Il était :

            log_type = "ticket_close" if "ferm" in title else "ticket_open"

        Deux événements seulement, décidés sur un bout de texte. Tout ce qui
        n'était pas une fermeture — prise en charge, renommage, transfert,
        ajout de membre — arrivait donc dans le journal étiqueté « ouverture de
        ticket », et la fermeture automatique par inactivité était
        indistinguable d'une fermeture décidée par un humain.

        Trois niveaux maintenant, du plus sûr au moins sûr :

        1. ``log_type`` passé explicitement par l'appelant — la seule voie
           correcte, et celle que ``services.tickets.journaliser_evenement``
           emprunte pour les quatorze événements ;
        2. correspondance EXACTE du titre avec un titre canonique
           (``EVENEMENTS_TICKET``), pour un appelant historique qui reprend un
           de ces titres au mot près ;
        3. l'ancienne heuristique, conservée pour ne rien casser d'un appelant
           tiers inconnu, mais qui ne décide plus rien dans le bot.
        """
        del log_channel_id
        title = _plain(embed.title)
        if log_type is None:
            log_type = _TITRES_CANONIQUES.get(title.strip())
        if log_type is None:
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
            # Recontrôle atomique juste avant la création réelle. Utilise le même
            # comptage "auto-réparant" que start_ticket_flow (voir sa docstring) :
            # un salon supprimé manuellement ne doit jamais bloquer indéfiniment.
            limit = int(ticket_type["max_per_member"] or 1)
            current = await tickets.count_genuinely_open_tickets(self.bot, guild, user.id, type_id)
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
            return await _private_reply(
                interaction,
                tickets.embeds.error("Un ticket ne peut être fermé que depuis son serveur."),
            )
        ticket = await self.bot.db.fetchone("SELECT * FROM tickets WHERE id = ?", (ticket_id,))
        if not ticket:
            # Trois `return` nus vivaient ici. Le membre cliquait « Fermer »,
            # remplissait le formulaire de raison, et STRICTEMENT rien ne se
            # passait : sans réponse à l'interaction, Discord affiche « L'appli-
            # cation n'a pas répondu » et le ticket reste ouvert. Un bouton qui
            # ne fait rien est le pire état possible, parce que rien n'indique
            # quoi faire ensuite.
            return await _private_reply(
                interaction,
                tickets.embeds.error(
                    "Ce ticket n'existe plus en base. Le salon peut être supprimé "
                    "manuellement sans risque."
                ),
            )
        channel = guild.get_channel(int(ticket["channel_id"]))
        if not isinstance(channel, discord.TextChannel):
            # Salon supprimé à la main alors que la ligne dit « ouvert » : le
            # ticket était bloqué dans cet état pour toujours — impossible à
            # fermer, et il continuait de compter dans la limite par membre.
            # On solde la ligne ici, c'est le seul endroit qui le peut.
            await self.bot.db.execute(
                "UPDATE tickets SET status='supprime', closed_at=? WHERE id=? AND status<>'supprime'",
                (tickets.now(), ticket_id),
            )
            await tickets_service.journaliser_evenement(
                self.bot, guild, "ticket_delete",
                ticket_id=ticket_id,
                cible=guild.get_member(int(ticket["user_id"])),
                acteur=interaction.user,
                raison="Salon supprimé manuellement ; ticket soldé à la fermeture.",
                avec_bouton=False,
            )
            return await _private_reply(
                interaction,
                tickets.embeds.warning(
                    "Le salon de ce ticket n'existe plus. Le ticket a été marqué comme "
                    "clos — il ne compte plus dans votre limite."
                ),
            )

        conf = await self.bot.db.get_guild_config(guild.id)
        closed_at = tickets.now()
        close_cursor = await self.bot.db.execute(
            "UPDATE tickets SET status='ferme', closed_at=?, locked=1 "
            "WHERE id=? AND status='ouvert'",
            (closed_at, ticket_id),
        )
        if getattr(close_cursor, "rowcount", 0) != 1:
            return await _private_reply(
                interaction,
                tickets.embeds.warning("Ce ticket est déjà fermé ou n'est plus disponible."),
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

        # Fermer n'est plus forcément supprimer. `ticket_delete_delay` à 0 veut
        # dire « le staff décide » — ce qui était impossible à exprimer avant,
        # parce que les six lecteurs de ce réglage écrivaient tous
        # `(...) or 30`, et `0 or 30` rend 30.
        delay = tickets_service.delai_de_suppression(conf)
        duree = tickets_service.duree_du_ticket(ticket, fin=closed_at)

        reason_text = (reason or "Non précisée").strip()[:1200]
        if delay is None:
            suite = (
                "Le salon reste ouvert à la relecture. "
                "Un membre du staff le supprimera avec le bouton ci-dessous."
            )
            vue_fermeture = tickets_service.vue_supprimer_ticket(ticket_id)
        else:
            asyncio.create_task(self._auto_delete(channel, ticket_id, delay))
            suite = f"Suppression automatique dans **{tickets.helpers.format_duration(delay)}**."
            # Le bouton est proposé même avec un délai : il sert à supprimer
            # tout de suite, sans attendre.
            vue_fermeture = tickets_service.vue_supprimer_ticket(ticket_id)

        ligne_duree = f"\nOuvert pendant : **{duree}**" if duree else ""
        try:
            await panels.envoyer(
                channel,
                panels.avec_composants(
                    panels.depuis_embed(tickets.embeds.warning(
                        f'🔒 Ticket fermé par {interaction.user.mention}.'
                        f'\nRaison : {reason_text}{ligne_duree}\n\n{suite}'
                    )),
                    vue_fermeture,
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
        # Ligne d'audit + référence citable. Cet embed-ci est construit à la main
        # plutôt que par journaliser_evenement() parce qu'il porte des champs que
        # lui seul a : les participants et la date de création. Les perdre pour
        # uniformiser serait une régression — on lui ajoute donc ce qui manque
        # au lieu de le remplacer.
        ligne_id = await tickets_service.enregistrer_evenement(
            self.bot, guild.id, "ticket_close",
            ticket_id=ticket_id, channel_id=channel.id,
            actor_id=interaction.user.id, target_id=int(ticket["user_id"]),
            details=reason_text,
        )
        reference = tickets_service.reference_incident(ticket_id, ligne_id)
        if duree:
            # Demandé par Jayden : combien de temps le ticket est resté ouvert.
            # Deux horodatages qu'il faut soustraire de tête ne disent rien ;
            # « 2 h 14 min » se lit d'un coup d'œil et montre ce qui a traîné.
            log_embed.add_field(name="⏳ Ouvert pendant", value=f"**{duree}**", inline=True)
        log_embed.add_field(name="🔖 Référence", value=f"`{reference}`", inline=False)
        event_key = log_service.make_event_key(
            guild.id,
            "ticket_close",
            target_id=int(ticket["user_id"]),
            executor_id=interaction.user.id,
            discriminator=reference,
        )
        await _safe_ticket_log(
            self,
            guild,
            "ticket_close",
            log_embed,
            file=self._transcript_file(channel, transcript_text),
            view=tickets_service.vue_voir_le_ticket(guild.id, channel.id),
            event_key=event_key,
            identity_name=(owner.display_name if owner else f"Membre {ticket['user_id']}"),
            identity_id=int(ticket["user_id"]),
            identity_icon=(str(owner.display_avatar.url) if owner else None),
        )

        if owner and (not conf or conf["ticket_transcript_dm"]):
            try:
                await panels.envoyer(owner, panels.depuis_embed(tickets.embeds.info(f'Voici la transcription de votre ticket sur **{guild.name}**.')), file=self._transcript_file(channel, transcript_text))
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
        decision = tickets_service.claim_decision(
            current_claimant_id=int(current_id) if current_id else None,
            member_id=member.id,
            is_admin=member.guild_permissions.administrator,
            is_owner=member.id == guild.owner_id,
        )
        if decision == "self_already":
            return await panels.envoyer(interaction.response, panels.depuis_embed(tickets.embeds.warning('Vous avez déjà pris en charge ce ticket.')), ephemere=True)
        if decision == "taken":
            current = guild.get_member(int(current_id))
            return await panels.envoyer(interaction.response, panels.depuis_embed(tickets.embeds.warning(f"Ce ticket est déjà pris en charge par {(current.mention if current else 'un autre membre du staff')}.")), ephemere=True)

        await interaction.response.defer()

        # Réservation compare-and-set AVANT de toucher aux permissions Discord : deux
        # clics simultanés ne peuvent plus se voler la prise en charge.
        if current_id:
            claim_cursor = await self.bot.db.execute(
                "UPDATE tickets SET claimed_by = ?, last_activity_at = ? "
                "WHERE id = ? AND status = 'ouvert' AND claimed_by = ?",
                (member.id, tickets.now(), ticket["id"], int(current_id)),
            )
        else:
            claim_cursor = await self.bot.db.execute(
                "UPDATE tickets SET claimed_by = ?, last_activity_at = ? "
                "WHERE id = ? AND status = 'ouvert' AND claimed_by IS NULL",
                (member.id, tickets.now(), ticket["id"]),
            )

        if getattr(claim_cursor, "rowcount", 0) != 1:
            latest = await self.bot.db.fetchone(
                "SELECT claimed_by, status FROM tickets WHERE id = ?",
                (ticket["id"],),
            )
            if not latest or latest["status"] != "ouvert":
                message = "Ce ticket n'est plus ouvert."
            elif latest["claimed_by"]:
                message = f"Ce ticket vient d'être pris en charge par <@{int(latest['claimed_by'])}>."
            else:
                message = "La prise en charge a changé. Réessayez."
            return await panels.envoyer(
                interaction.followup,
                panels.depuis_embed(tickets.embeds.warning(message)),
                ephemere=True,
            )

        old_member = guild.get_member(int(current_id)) if current_id else None
        if old_member and old_member.id != member.id:
            await _remove_claimant_override(channel, old_member, int(ticket["user_id"]))

        await _set_staff_role_visibility(self, channel, ticket, visible=False)
        try:
            await _grant_claimant(channel, member)
        except discord.Forbidden:
            # Revenir à l'état DB précédent si Discord refuse les permissions.
            if current_id:
                await self.bot.db.execute(
                    "UPDATE tickets SET claimed_by = ? WHERE id = ? AND claimed_by = ?",
                    (int(current_id), ticket["id"], member.id),
                )
            else:
                await self.bot.db.execute(
                    "UPDATE tickets SET claimed_by = NULL WHERE id = ? AND claimed_by = ?",
                    (ticket["id"], member.id),
                )
            await _set_staff_role_visibility(self, channel, ticket, visible=True)
            return await panels.envoyer(
                interaction.followup,
                panels.depuis_embed(
                    tickets.embeds.error("SentriX n'a pas la permission de modifier les accès de ce ticket.")
                ),
                ephemere=True,
            )

        # Journalisé après le compare-and-set ET après l'octroi des permissions :
        # un claim qui échoue sur Forbidden a déjà rendu la base à son état
        # précédent plus haut, il ne doit donc rien laisser dans le journal.
        ancien = guild.get_member(int(current_id)) if current_id else None
        reference = await tickets_service.journaliser_evenement(
            self.bot, guild, "ticket_claim",
            ticket_id=ticket["id"], channel=channel,
            acteur=member,
            cible=guild.get_member(int(ticket["user_id"])),
            extra=({"↩️ Reprise sur": ancien.mention} if ancien and ancien.id != member.id else None),
        )
        await panels.envoyer(
            interaction.followup,
            panels.depuis_embed(
                tickets.embeds.success(
                    f"{member.mention} a pris en charge ce ticket. "
                    "L'accès est maintenant réservé au créateur, au membre en charge et aux Administrateurs.\n"
                    f"Référence : `{reference}`"
                )
            ),
        )

    async def secure_unclaim(self, interaction: discord.Interaction, ticket):
        guild = interaction.guild
        channel = interaction.channel
        member = interaction.user
        if guild is None or not isinstance(channel, discord.TextChannel) or not isinstance(member, discord.Member):
            return await panels.envoyer(interaction.response, panels.depuis_embed(tickets.embeds.error('Action impossible.')), ephemere=True)

        current_id = ticket["claimed_by"]
        decision = tickets_service.unclaim_decision(
            current_claimant_id=int(current_id) if current_id else None,
            member_id=member.id,
            is_admin=member.guild_permissions.administrator,
            is_owner=member.id == guild.owner_id,
        )
        if decision == "not_claimed":
            return await panels.envoyer(interaction.response, panels.depuis_embed(tickets.embeds.warning("Ce ticket n'est pas actuellement pris en charge.")), ephemere=True)
        if decision == "forbidden":
            return await panels.envoyer(interaction.response, panels.depuis_embed(tickets.embeds.error('Seul le membre en charge ou un Administrateur peut abandonner ce ticket.')), ephemere=True)

        await interaction.response.defer()

        unclaim_cursor = await self.bot.db.execute(
            "UPDATE tickets SET claimed_by = NULL, last_activity_at = ? "
            "WHERE id = ? AND status = 'ouvert' AND claimed_by = ?",
            (tickets.now(), ticket["id"], int(current_id)),
        )
        if getattr(unclaim_cursor, "rowcount", 0) != 1:
            return await panels.envoyer(
                interaction.followup,
                panels.depuis_embed(
                    tickets.embeds.warning("La prise en charge a déjà changé. Actualisez le ticket.")
                ),
                ephemere=True,
            )

        claimant = guild.get_member(int(current_id))
        await _remove_claimant_override(channel, claimant, int(ticket["user_id"]))
        await _set_staff_role_visibility(self, channel, ticket, visible=True)
        reference = await tickets_service.journaliser_evenement(
            self.bot, guild, "ticket_unclaim",
            ticket_id=ticket["id"], channel=channel,
            acteur=member,
            cible=guild.get_member(int(ticket["user_id"])),
            # Un administrateur peut abandonner la charge d'un AUTRE : sans ce
            # champ, le journal laisserait croire que le titulaire s'est retiré
            # lui-même.
            extra=({"🙋 Titulaire retiré": claimant.mention} if claimant and claimant.id != member.id else None),
        )
        await panels.envoyer(
            interaction.followup,
            panels.depuis_embed(
                tickets.embeds.success(
                    "Prise en charge annulée. L'accès du rôle staff a été rétabli.\n"
                    f"Référence : `{reference}`"
                )
            ),
        )

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


async def setup(bot: commands.Bot) -> None:
    """Extension à part entière : sans elle, des boutons staff sont ouverts.

    Le module n'avait qu'``install()``, appelé par l'enveloppe de chargement de
    ``cogs/__init__`` — posée sur une classe que la production n'instancie plus
    depuis que ``railway_boot`` remplace ``commands.Bot``. Mesuré le 2026-09-26
    sur la chaîne v8 : le module n'était pas installé.

    Ce que son absence laissait passer : ``Tickets.handle_control_button`` ne
    vérifie une autorisation que si un ``role_id`` est configuré pour ce bouton
    précis. Sans configuration, aucun contrôle — le créateur du ticket pouvait
    donc utiliser claim, add, remove, rename et transfer, dont ``add`` qui fait
    entrer d'autres membres dans son salon privé. Ce module impose le contrôle
    staff quelle que soit la configuration, et réserve la fermeture au créateur
    ou au staff.

    ``install()`` est idempotent : il garde un drapeau de module.
    """
    install(bot)

