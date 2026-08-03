"""
Cog TICKETS.
/ticket /ticket-close /ticket-reopen /ticket-claim /ticket-unclaim
/ticket-add /ticket-remove /ticket-rename /ticket-priority /ticket-category
/ticket-transcript /ticket-transfer /ticket-note /ticket-info /ticket-panel
/ticket-stats /ticket-rating /ticket-remind /ticket-archive

Fermer un ticket (bouton "Fermer", sans commande) programme automatiquement sa
suppression après un court délai — plus besoin de commande dédiée pour supprimer.
"""

import asyncio
import io
import discord
from discord import app_commands
from discord.ext import commands

from utils import embeds, checks
from database.db import now

PRIORITIES = ["basse", "normale", "haute", "urgente"]
TICKET_AUTO_DELETE_DELAY = 20  # secondes avant suppression automatique après fermeture


TICKET_CATEGORIES = [
    ("support", "🛠️", "Support technique", "Un bug ou un souci technique"),
    ("facturation", "💳", "Facturation", "Une question sur un paiement / achat"),
    ("signalement", "🚨", "Signalement", "Signaler un membre ou un problème"),
    ("partenariat", "🤝", "Partenariat", "Une proposition de partenariat"),
    ("autre", "❓", "Autre demande", "Tout ce qui ne rentre pas ailleurs"),
]


class TicketDetailsModal(discord.ui.Modal, title="🎫 Détails du ticket"):
    """Formulaire affiché juste après le choix de la catégorie : on demande la priorité et une
    description, pour que le staff ait tout de suite le contexte au lieu de devoir le redemander."""

    priorite = discord.ui.TextInput(
        label="Priorité (basse / normale / haute / urgente)",
        placeholder="normale",
        required=False,
        max_length=10,
    )
    description = discord.ui.TextInput(
        label="Décrivez votre problème en détail",
        style=discord.TextStyle.paragraph,
        placeholder="Expliquez votre demande le plus précisément possible...",
        required=True,
        max_length=1000,
    )

    def __init__(self, category: str):
        super().__init__()
        self.category = category

    async def on_submit(self, interaction: discord.Interaction):
        cog: "Tickets" = interaction.client.get_cog("Tickets")
        priority = (self.priorite.value or "normale").strip().lower()
        if priority not in PRIORITIES:
            priority = "normale"
        await cog.create_ticket(
            interaction,
            category=self.category,
            description=self.description.value.strip(),
            priority=priority,
        )


class TicketCategorySelect(discord.ui.Select):
    """Menu déroulant du panneau de tickets : on choisit d'abord la catégorie, puis un
    formulaire (priorité + description) s'ouvre pour compléter la demande."""

    def __init__(self):
        options = [
            discord.SelectOption(label=label, value=value, emoji=emoji, description=desc)
            for value, emoji, label, desc in TICKET_CATEGORIES
        ]
        super().__init__(
            placeholder="📂 Choisissez une catégorie pour ouvrir un ticket...",
            options=options,
            custom_id="ticket_panel_select",
            min_values=1,
            max_values=1,
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(TicketDetailsModal(category=self.values[0]))


class TicketPanelView(discord.ui.View):
    """Vue persistante affichée dans le panel (/ticket-panel) pour créer un ticket."""

    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(TicketCategorySelect())


class TicketControlView(discord.ui.View):
    """Vue persistante affichée dans chaque salon de ticket (fermer / claim / transcript).
    Fermer ne demande aucune commande : le bouton suffit, et programme la suppression automatique."""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Fermer", style=discord.ButtonStyle.danger, emoji="🔒", custom_id="ticket_close_btn", row=0)
    async def close_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog: "Tickets" = interaction.client.get_cog("Tickets")
        await cog.close_ticket(interaction, interaction.channel)

    @discord.ui.button(label="Prendre en charge", style=discord.ButtonStyle.secondary, emoji="🙋", custom_id="ticket_claim_btn", row=0)
    async def claim_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog: "Tickets" = interaction.client.get_cog("Tickets")
        await cog.claim_ticket(interaction, interaction.channel, interaction.user)

    @discord.ui.button(label="Transcript", style=discord.ButtonStyle.secondary, emoji="📄", custom_id="ticket_transcript_btn", row=0)
    async def transcript_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog: "Tickets" = interaction.client.get_cog("Tickets")
        await cog.send_transcript(interaction, interaction.channel)


class Tickets(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def log_action(self, guild: discord.Guild, embed: discord.Embed):
        conf = await self.bot.db.get_guild_config(guild.id)
        channel_id = conf["ticket_log_channel"] if conf else None
        if not channel_id:
            channel_id = conf["log_channel"] if conf else None
        if channel_id:
            channel = guild.get_channel(channel_id)
            if channel:
                try:
                    await channel.send(embed=embed)
                except discord.HTTPException:
                    pass

    async def get_ticket_by_channel(self, channel_id: int):
        return await self.bot.db.fetchone("SELECT * FROM tickets WHERE channel_id = ?", (channel_id,))

    # ---------------------------------------------------------------- CRÉATION

    async def create_ticket(
        self,
        interaction: discord.Interaction,
        category: str = "general",
        description: str | None = None,
        priority: str = "normale",
    ):
        guild = interaction.guild
        user = interaction.user
        await interaction.response.defer(ephemeral=True)

        existing = await self.bot.db.fetchone(
            "SELECT * FROM tickets WHERE guild_id = ? AND user_id = ? AND status = 'ouvert'",
            (guild.id, user.id),
        )
        if existing:
            channel = guild.get_channel(existing["channel_id"])
            if channel:
                return await interaction.followup.send(
                    embed=embeds.warning(f"Vous avez déjà un ticket ouvert : {channel.mention}"), ephemeral=True
                )

        conf = await self.bot.db.get_guild_config(guild.id)
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True),
        }
        if conf and conf["mod_role"]:
            role = guild.get_role(conf["mod_role"])
            if role:
                overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True)

        parent = guild.get_channel(conf["ticket_category"]) if conf and conf["ticket_category"] else None
        channel_name = f"ticket-{user.name}".lower().replace(" ", "-")[:90]
        channel = await guild.create_text_channel(
            channel_name, overwrites=overwrites, category=parent if isinstance(parent, discord.CategoryChannel) else None,
            reason=f"Ticket ouvert par {user}",
        )

        await self.bot.db.execute(
            "INSERT INTO tickets (guild_id, channel_id, user_id, status, category, priority, created_at) VALUES (?, ?, ?, 'ouvert', ?, ?, ?)",
            (guild.id, channel.id, user.id, category, priority, now()),
        )

        e = embeds.brand("🎫 Nouveau ticket", f"Bonjour {user.mention}, un membre du staff vous répondra bientôt.")
        e.add_field(name="📂 Catégorie", value=category, inline=True)
        e.add_field(name="🚦 Priorité", value=priority, inline=True)
        if description:
            e.add_field(name="📝 Description", value=description[:1000], inline=False)
        await channel.send(content=user.mention, embed=e, view=TicketControlView())

        await interaction.followup.send(embed=embeds.success(f"Votre ticket a été créé : {channel.mention}"), ephemeral=True)

        log_e = embeds.neutral("🎫 Ticket ouvert", f"**Membre :** {user.mention}\n**Salon :** {channel.mention}\n**Catégorie :** {category}\n**Priorité :** {priority}")
        await self.log_action(guild, log_e)

    @commands.hybrid_command(name="ticket", description="Créer un nouveau ticket de support.")
    @app_commands.describe(categorie="Catégorie du ticket (ex: support, facturation, signalement)")
    async def ticket(self, ctx: commands.Context, categorie: str = "general"):
        if ctx.interaction:
            await self.create_ticket(ctx.interaction, category=categorie)
        else:
            guild = ctx.guild
            conf = await self.bot.db.get_guild_config(guild.id)
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(view_channel=False),
                ctx.author: discord.PermissionOverwrite(view_channel=True, send_messages=True),
                guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True),
            }
            channel = await guild.create_text_channel(f"ticket-{ctx.author.name}".lower()[:90], overwrites=overwrites)
            await self.bot.db.execute(
                "INSERT INTO tickets (guild_id, channel_id, user_id, status, category, priority, created_at) VALUES (?, ?, ?, 'ouvert', ?, 'normale', ?)",
                (guild.id, channel.id, ctx.author.id, categorie, now()),
            )
            await channel.send(content=ctx.author.mention, embed=embeds.neutral("🎫 Nouveau ticket", "Un membre du staff vous répondra bientôt."), view=TicketControlView())
            await ctx.send(embed=embeds.success(f"Ticket créé : {channel.mention}"))

    @commands.hybrid_command(name="ticket-panel", description="Poster le panneau de création de tickets dans ce salon.")
    @checks.is_owner_or_admin()
    async def ticket_panel(self, ctx: commands.Context):
        e = embeds.brand(
            "🎫 Support — Ouvrir un ticket",
            "Choisissez une catégorie dans le menu ci-dessous pour ouvrir un ticket privé avec l'équipe "
            "de support. Un court formulaire vous demandera ensuite la priorité et une description, pour "
            "que le staff ait tout de suite le contexte.",
        )
        categories_list = "\n".join(f"{emoji} **{label}** — {desc}" for _, emoji, label, desc in TICKET_CATEGORIES)
        e.add_field(name="📂 Catégories disponibles", value=categories_list, inline=False)
        msg = await ctx.send(embed=e, view=TicketPanelView())
        await self.bot.db.execute(
            "INSERT INTO ticket_panels (guild_id, channel_id, message_id) VALUES (?, ?, ?)",
            (ctx.guild.id, ctx.channel.id, msg.id),
        )

    # ---------------------------------------------------------------- GESTION

    async def close_ticket(self, interaction_or_ctx, channel: discord.TextChannel):
        ticket = await self.get_ticket_by_channel(channel.id)
        if not ticket:
            return await self._reply(interaction_or_ctx, embeds.error("Ce salon n'est pas un ticket."))
        await self.bot.db.execute("UPDATE tickets SET status = 'ferme', closed_at = ? WHERE id = ?", (now(), ticket["id"]))
        owner = channel.guild.get_member(ticket["user_id"])
        if owner:
            overwrite = channel.overwrites_for(owner)
            overwrite.send_messages = False
            await channel.set_permissions(owner, overwrite=overwrite)
        await self._reply(
            interaction_or_ctx,
            embeds.success(
                f"🔒 Le ticket a été fermé. Il sera supprimé automatiquement dans **{TICKET_AUTO_DELETE_DELAY} secondes** — "
                "utilisez `+ticket-reopen` avant ça si vous changez d'avis."
            ),
        )
        e = embeds.neutral("🔒 Ticket fermé", f"Salon : {channel.mention} (suppression automatique programmée)")
        await self.log_action(channel.guild, e)
        # Suppression automatique : plus besoin de commande dédiée pour supprimer un ticket fermé.
        asyncio.create_task(self._auto_delete(channel, ticket["id"]))

    async def _auto_delete(self, channel: discord.TextChannel, ticket_id: int):
        await asyncio.sleep(TICKET_AUTO_DELETE_DELAY)
        current = await self.bot.db.fetchone("SELECT * FROM tickets WHERE id = ?", (ticket_id,))
        if not current or current["status"] != "ferme":
            return  # rouvert ou déjà supprimé entre-temps, on annule
        await self.bot.db.execute("UPDATE tickets SET status = 'supprime' WHERE id = ?", (ticket_id,))
        try:
            await channel.delete(reason="Ticket fermé : suppression automatique.")
        except discord.HTTPException:
            pass

    async def claim_ticket(self, interaction_or_ctx, channel: discord.TextChannel, staff: discord.Member):
        ticket = await self.get_ticket_by_channel(channel.id)
        if not ticket:
            return await self._reply(interaction_or_ctx, embeds.error("Ce salon n'est pas un ticket."))
        await self.bot.db.execute("UPDATE tickets SET claimed_by = ? WHERE id = ?", (staff.id, ticket["id"]))
        await self._reply(interaction_or_ctx, embeds.success(f"🙋 {staff.mention} a pris en charge ce ticket."))

    async def send_transcript(self, interaction_or_ctx, channel: discord.TextChannel):
        """Génère et envoie la transcription du salon. Utilisé à la fois par /ticket-transcript
        et par le bouton "Transcript" du panneau de contrôle, pour ne pas dupliquer la logique."""
        is_interaction = isinstance(interaction_or_ctx, discord.Interaction)
        if is_interaction:
            await interaction_or_ctx.response.defer()
        lines = []
        async for msg in channel.history(limit=1000, oldest_first=True):
            lines.append(f"[{msg.created_at:%Y-%m-%d %H:%M}] {msg.author}: {msg.content}")
        content = "\n".join(lines) or "Aucun message."
        buffer = io.BytesIO(content.encode("utf-8"))
        file = discord.File(buffer, filename=f"transcript-{channel.name}.txt")
        embed = embeds.success("📄 Transcription générée.")
        if is_interaction:
            await interaction_or_ctx.followup.send(embed=embed, file=file)
        else:
            await interaction_or_ctx.send(embed=embed, file=file)

    async def _reply(self, target, embed: discord.Embed):
        if isinstance(target, discord.Interaction):
            if target.response.is_done():
                await target.followup.send(embed=embed)
            else:
                await target.response.send_message(embed=embed)
        else:
            await target.send(embed=embed)

    @commands.hybrid_command(name="ticket-close", description="Fermer le ticket en cours.")
    @checks.has_permission_or_modrole("manage_channels")
    async def ticket_close(self, ctx: commands.Context):
        await self.close_ticket(ctx, ctx.channel)

    @commands.hybrid_command(name="ticket-reopen", description="Rouvrir un ticket fermé.", with_app_command=False)
    @checks.has_permission_or_modrole("manage_channels")
    async def ticket_reopen(self, ctx: commands.Context):
        ticket = await self.get_ticket_by_channel(ctx.channel.id)
        if not ticket:
            return await ctx.send(embed=embeds.error("Ce salon n'est pas un ticket."))
        await self.bot.db.execute("UPDATE tickets SET status = 'ouvert', closed_at = NULL WHERE id = ?", (ticket["id"],))
        owner = ctx.guild.get_member(ticket["user_id"])
        if owner:
            overwrite = ctx.channel.overwrites_for(owner)
            overwrite.send_messages = True
            await ctx.channel.set_permissions(owner, overwrite=overwrite)
        await ctx.send(embed=embeds.success("🔓 Le ticket a été rouvert."))

    @commands.hybrid_command(name="ticket-claim", description="Prendre en charge ce ticket.")
    @checks.has_permission_or_modrole("manage_channels")
    async def ticket_claim(self, ctx: commands.Context):
        await self.claim_ticket(ctx, ctx.channel, ctx.author)

    @commands.hybrid_command(name="ticket-unclaim", description="Annuler la prise en charge du ticket.", with_app_command=False)
    @checks.has_permission_or_modrole("manage_channels")
    async def ticket_unclaim(self, ctx: commands.Context):
        ticket = await self.get_ticket_by_channel(ctx.channel.id)
        if not ticket:
            return await ctx.send(embed=embeds.error("Ce salon n'est pas un ticket."))
        await self.bot.db.execute("UPDATE tickets SET claimed_by = NULL WHERE id = ?", (ticket["id"],))
        await ctx.send(embed=embeds.success("La prise en charge a été annulée."))

    @commands.hybrid_command(name="ticket-add", description="Ajouter un membre au ticket.")
    @app_commands.describe(membre="Le membre à ajouter")
    @checks.has_permission_or_modrole("manage_channels")
    async def ticket_add(self, ctx: commands.Context, membre: discord.Member):
        await ctx.channel.set_permissions(membre, view_channel=True, send_messages=True, read_message_history=True)
        await ctx.send(embed=embeds.success(f"{membre.mention} a été ajouté au ticket."))

    @commands.hybrid_command(name="ticket-remove", description="Retirer un membre du ticket.", with_app_command=False)
    @app_commands.describe(membre="Le membre à retirer")
    @checks.has_permission_or_modrole("manage_channels")
    async def ticket_remove(self, ctx: commands.Context, membre: discord.Member):
        await ctx.channel.set_permissions(membre, overwrite=None)
        await ctx.send(embed=embeds.success(f"{membre.mention} a été retiré du ticket."))

    @commands.hybrid_command(name="ticket-rename", description="Renommer ce ticket.", with_app_command=False)
    @app_commands.describe(nom="Le nouveau nom du salon")
    @checks.has_permission_or_modrole("manage_channels")
    async def ticket_rename(self, ctx: commands.Context, *, nom: str):
        await ctx.channel.edit(name=nom[:90])
        await ctx.send(embed=embeds.success(f"Le ticket a été renommé en **{nom[:90]}**."))

    @commands.hybrid_command(name="ticket-priority", description="Définir la priorité du ticket.", with_app_command=False)
    @app_commands.describe(priorite="Niveau de priorité")
    @app_commands.choices(priorite=[app_commands.Choice(name=p, value=p) for p in PRIORITIES])
    @checks.has_permission_or_modrole("manage_channels")
    async def ticket_priority(self, ctx: commands.Context, priorite: str):
        ticket = await self.get_ticket_by_channel(ctx.channel.id)
        if not ticket:
            return await ctx.send(embed=embeds.error("Ce salon n'est pas un ticket."))
        await self.bot.db.execute("UPDATE tickets SET priority = ? WHERE id = ?", (priorite, ticket["id"]))
        await ctx.send(embed=embeds.success(f"Priorité définie sur **{priorite}**."))

    @commands.hybrid_command(name="ticket-category", description="Définir la catégorie (label) du ticket.", with_app_command=False)
    @app_commands.describe(categorie="Nom de la catégorie")
    @checks.has_permission_or_modrole("manage_channels")
    async def ticket_category(self, ctx: commands.Context, *, categorie: str):
        ticket = await self.get_ticket_by_channel(ctx.channel.id)
        if not ticket:
            return await ctx.send(embed=embeds.error("Ce salon n'est pas un ticket."))
        await self.bot.db.execute("UPDATE tickets SET category = ? WHERE id = ?", (categorie, ticket["id"]))
        await ctx.send(embed=embeds.success(f"Catégorie définie sur **{categorie}**."))

    @commands.hybrid_command(name="ticket-transcript", description="Générer une transcription texte du ticket.")
    @checks.has_permission_or_modrole("manage_channels")
    async def ticket_transcript(self, ctx: commands.Context):
        await self.send_transcript(ctx, ctx.channel)

    @commands.hybrid_command(name="ticket-transfer", description="Transférer le ticket à un autre membre du staff.", with_app_command=False)
    @app_commands.describe(membre="Le nouveau membre du staff responsable")
    @checks.has_permission_or_modrole("manage_channels")
    async def ticket_transfer(self, ctx: commands.Context, membre: discord.Member):
        ticket = await self.get_ticket_by_channel(ctx.channel.id)
        if not ticket:
            return await ctx.send(embed=embeds.error("Ce salon n'est pas un ticket."))
        await self.bot.db.execute("UPDATE tickets SET claimed_by = ? WHERE id = ?", (membre.id, ticket["id"]))
        await ctx.channel.set_permissions(membre, view_channel=True, send_messages=True)
        await ctx.send(embed=embeds.success(f"Le ticket a été transféré à {membre.mention}."))

    @commands.hybrid_command(name="ticket-note", description="Ajouter une note interne (invisible pour l'utilisateur).", with_app_command=False)
    @app_commands.describe(note="Le contenu de la note")
    @checks.has_permission_or_modrole("manage_channels")
    async def ticket_note(self, ctx: commands.Context, *, note: str):
        ticket = await self.get_ticket_by_channel(ctx.channel.id)
        if not ticket:
            return await ctx.send(embed=embeds.error("Ce salon n'est pas un ticket."))
        await self.bot.db.execute(
            "INSERT INTO ticket_notes (ticket_id, author_id, note, timestamp) VALUES (?, ?, ?, ?)",
            (ticket["id"], ctx.author.id, note, now()),
        )
        await ctx.send(embed=embeds.success("📝 Note interne enregistrée."), ephemeral=True)

    @commands.hybrid_command(name="ticket-info", description="Afficher les informations de ce ticket.")
    @checks.has_permission_or_modrole("manage_channels")
    async def ticket_info(self, ctx: commands.Context):
        ticket = await self.get_ticket_by_channel(ctx.channel.id)
        if not ticket:
            return await ctx.send(embed=embeds.error("Ce salon n'est pas un ticket."))
        owner = ctx.guild.get_member(ticket["user_id"])
        claimed = ctx.guild.get_member(ticket["claimed_by"]) if ticket["claimed_by"] else None
        e = embeds.neutral(f"🎫 Ticket #{ticket['id']}")
        e.add_field(name="Ouvert par", value=owner.mention if owner else "Inconnu", inline=True)
        e.add_field(name="Statut", value=ticket["status"], inline=True)
        e.add_field(name="Priorité", value=ticket["priority"], inline=True)
        e.add_field(name="Catégorie", value=ticket["category"], inline=True)
        e.add_field(name="Pris en charge par", value=claimed.mention if claimed else "Personne", inline=True)
        e.add_field(name="Créé", value=f"<t:{ticket['created_at']}:R>", inline=True)
        notes = await self.bot.db.fetchall("SELECT * FROM ticket_notes WHERE ticket_id = ? ORDER BY timestamp DESC LIMIT 5", (ticket["id"],))
        if notes:
            e.add_field(name="Dernières notes", value="\n".join(f"- {n['note']}" for n in notes), inline=False)
        await ctx.send(embed=e)

    @commands.hybrid_command(name="ticket-stats", description="Afficher les statistiques des tickets du serveur.", with_app_command=False)
    @checks.has_permission_or_modrole("manage_channels")
    async def ticket_stats(self, ctx: commands.Context):
        total = await self.bot.db.fetchone("SELECT COUNT(*) c FROM tickets WHERE guild_id = ?", (ctx.guild.id,))
        open_ = await self.bot.db.fetchone("SELECT COUNT(*) c FROM tickets WHERE guild_id = ? AND status = 'ouvert'", (ctx.guild.id,))
        closed = await self.bot.db.fetchone("SELECT COUNT(*) c FROM tickets WHERE guild_id = ? AND status = 'ferme'", (ctx.guild.id,))
        avg_rating = await self.bot.db.fetchone("SELECT AVG(rating) a FROM tickets WHERE guild_id = ? AND rating IS NOT NULL", (ctx.guild.id,))
        e = embeds.neutral("📊 Statistiques des tickets")
        e.add_field(name="Total", value=total["c"], inline=True)
        e.add_field(name="Ouverts", value=open_["c"], inline=True)
        e.add_field(name="Fermés", value=closed["c"], inline=True)
        e.add_field(name="Note moyenne", value=f"{avg_rating['a']:.1f}/5" if avg_rating["a"] else "N/A", inline=True)
        await ctx.send(embed=e)

    @commands.hybrid_command(name="ticket-rating", description="Noter le support reçu dans ce ticket (1 à 5).", with_app_command=False)
    @app_commands.describe(note="Note de 1 à 5")
    async def ticket_rating(self, ctx: commands.Context, note: app_commands.Range[int, 1, 5]):
        ticket = await self.get_ticket_by_channel(ctx.channel.id)
        if not ticket:
            return await ctx.send(embed=embeds.error("Ce salon n'est pas un ticket."))
        await self.bot.db.execute("UPDATE tickets SET rating = ? WHERE id = ?", (note, ticket["id"]))
        await ctx.send(embed=embeds.success(f"Merci pour votre note : {'⭐' * note}"))

    @commands.hybrid_command(name="ticket-remind", description="Envoyer un rappel à l'utilisateur du ticket.", with_app_command=False)
    @checks.has_permission_or_modrole("manage_channels")
    async def ticket_remind(self, ctx: commands.Context):
        ticket = await self.get_ticket_by_channel(ctx.channel.id)
        if not ticket:
            return await ctx.send(embed=embeds.error("Ce salon n'est pas un ticket."))
        owner = ctx.guild.get_member(ticket["user_id"])
        await ctx.send(f"⏰ {owner.mention if owner else ''}, rappel : nous attendons votre réponse sur ce ticket.")

    @commands.hybrid_command(name="ticket-archive", description="Archiver ce ticket (lecture seule, conservé).", with_app_command=False)
    @checks.has_permission_or_modrole("manage_channels")
    async def ticket_archive(self, ctx: commands.Context):
        ticket = await self.get_ticket_by_channel(ctx.channel.id)
        if not ticket:
            return await ctx.send(embed=embeds.error("Ce salon n'est pas un ticket."))
        await self.bot.db.execute("UPDATE tickets SET status = 'archive' WHERE id = ?", (ticket["id"],))
        overwrite = ctx.channel.overwrites_for(ctx.guild.default_role)
        await ctx.channel.set_permissions(ctx.guild.default_role, overwrite=overwrite)
        owner = ctx.guild.get_member(ticket["user_id"])
        if owner:
            ow = ctx.channel.overwrites_for(owner)
            ow.send_messages = False
            ow.view_channel = False
            await ctx.channel.set_permissions(owner, overwrite=ow)
        await ctx.send(embed=embeds.success("📦 Ticket archivé."))


async def setup(bot: commands.Bot):
    await bot.add_cog(Tickets(bot))
