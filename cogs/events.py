"""
Cog GIVEAWAYS / ÉVÉNEMENTS.
/giveaway-create /giveaway-end /giveaway-reroll /giveaway-list /giveaway-cancel
/giveaway-blacklist /giveaway-unblacklist /event-create /event-join /event-leave
/event-list /event-cancel /tournament-create /tournament-join /tournament-start
/tournament-list /announce
"""

import random
import discord
from discord import app_commands
from discord.ext import commands, tasks

from utils import embeds, checks, helpers
from database.db import now


class GiveawayView(discord.ui.View):
    """Vue persistante affichée sur le message d'un giveaway (bouton Participer)."""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🎉 Participer", style=discord.ButtonStyle.primary, custom_id="giveaway_enter_btn")
    async def enter(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog: "Events" = interaction.client.get_cog("Events")
        await cog.enter_giveaway(interaction)


class Events(commands.Cog, name="Events"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.check_giveaways.start()
        self.check_events.start()

    def cog_unload(self):
        self.check_giveaways.cancel()
        self.check_events.cancel()

    async def log_action(self, guild: discord.Guild, embed: discord.Embed):
        conf = await self.bot.db.get_guild_config(guild.id)
        channel_id = conf["log_channel"] if conf else None
        if channel_id:
            channel = guild.get_channel(channel_id)
            if channel:
                try:
                    await channel.send(embed=embed)
                except discord.HTTPException:
                    pass

    # ---------------------------------------------------------------- GIVEAWAYS

    async def enter_giveaway(self, interaction: discord.Interaction):
        giveaway = await self.bot.db.fetchone(
            "SELECT * FROM giveaways WHERE message_id = ? AND status = 'actif'", (interaction.message.id,)
        )
        if not giveaway:
            return await interaction.response.send_message("Ce giveaway n'est plus actif.", ephemeral=True)

        blacklisted = await self.bot.db.fetchone(
            "SELECT * FROM giveaway_blacklist WHERE guild_id = ? AND user_id = ?",
            (interaction.guild.id, interaction.user.id),
        )
        if blacklisted:
            return await interaction.response.send_message("Vous n'êtes pas autorisé à participer aux giveaways.", ephemeral=True)

        existing = await self.bot.db.fetchone(
            "SELECT * FROM giveaway_entries WHERE giveaway_id = ? AND user_id = ?",
            (giveaway["id"], interaction.user.id),
        )
        if existing:
            await self.bot.db.execute(
                "DELETE FROM giveaway_entries WHERE giveaway_id = ? AND user_id = ?",
                (giveaway["id"], interaction.user.id),
            )
            return await interaction.response.send_message("❌ Vous ne participez plus à ce giveaway.", ephemeral=True)

        await self.bot.db.execute(
            "INSERT INTO giveaway_entries (giveaway_id, user_id) VALUES (?, ?)",
            (giveaway["id"], interaction.user.id),
        )
        await interaction.response.send_message("🎉 Vous participez maintenant à ce giveaway !", ephemeral=True)

    async def end_giveaway(self, giveaway_id: int):
        giveaway = await self.bot.db.fetchone("SELECT * FROM giveaways WHERE id = ?", (giveaway_id,))
        if not giveaway or giveaway["status"] != "actif":
            return
        guild = self.bot.get_guild(giveaway["guild_id"])
        if not guild:
            return
        channel = guild.get_channel(giveaway["channel_id"])
        entries = await self.bot.db.fetchall("SELECT * FROM giveaway_entries WHERE giveaway_id = ?", (giveaway_id,))
        winners_count = giveaway["winners_count"]

        await self.bot.db.execute("UPDATE giveaways SET status = 'termine' WHERE id = ?", (giveaway_id,))

        if not entries:
            if channel:
                try:
                    await channel.send(embed=embeds.warning(f"🎉 Le giveaway **{giveaway['prize']}** est terminé, mais personne n'a participé."))
                except discord.HTTPException:
                    pass
            return

        pool = [e["user_id"] for e in entries]
        winners = random.sample(pool, min(winners_count, len(pool)))
        mentions = ", ".join(f"<@{w}>" for w in winners)

        await self.bot.db.execute(
            "UPDATE giveaways SET winners = ? WHERE id = ?", (",".join(str(w) for w in winners), giveaway_id)
        )

        if channel:
            e = embeds.success(f"🎉 Félicitations {mentions} ! Vous avez gagné **{giveaway['prize']}** !")
            try:
                await channel.send(embed=e)
                original = None
                try:
                    original = await channel.fetch_message(giveaway["message_id"])
                except discord.NotFound:
                    pass
                if original:
                    ended_embed = original.embeds[0] if original.embeds else embeds.neutral("🎉 Giveaway terminé")
                    ended_embed.description = f"**Gagnant(s) :** {mentions}\n\n*Ce giveaway est terminé.*"
                    ended_embed.color = discord.Color.dark_grey()
                    await original.edit(embed=ended_embed, view=None)
            except discord.HTTPException:
                pass

    @tasks.loop(seconds=20)
    async def check_giveaways(self):
        rows = await self.bot.db.fetchall(
            "SELECT * FROM giveaways WHERE status = 'actif' AND end_at <= ?", (now(),)
        )
        for row in rows:
            await self.end_giveaway(row["id"])

    @check_giveaways.before_loop
    async def before_check_giveaways(self):
        await self.bot.wait_until_ready()

    @commands.hybrid_command(name="giveaway-create", description="Créer un giveaway.")
    @app_commands.describe(
        prix="Le prix à gagner",
        duree="Durée du giveaway (ex: 10m, 1h, 1j)",
        gagnants="Nombre de gagnants (défaut 1)",
    )
    @checks.is_owner_or_admin()
    async def giveaway_create(self, ctx: commands.Context, prix: str, duree: str, gagnants: int = 1):
        seconds = helpers.parse_duration(duree)
        if not seconds:
            return await ctx.send(embed=embeds.error("Durée invalide. Exemple : `10m`, `1h`, `1j`."))
        if gagnants < 1:
            return await ctx.send(embed=embeds.error("Le nombre de gagnants doit être au moins 1."))

        end_at = now() + seconds
        e = embeds.neutral("🎉 GIVEAWAY 🎉", f"**Prix :** {prix}\n\nCliquez sur le bouton ci-dessous pour participer !")
        e.add_field(name="Se termine", value=f"<t:{end_at}:R>", inline=True)
        e.add_field(name="Gagnants", value=str(gagnants), inline=True)
        e.add_field(name="Organisé par", value=ctx.author.mention, inline=True)

        msg = await ctx.send(embed=e, view=GiveawayView())
        await self.bot.db.execute(
            "INSERT INTO giveaways (guild_id, channel_id, message_id, prize, winners_count, status, end_at, created_by, created_at) "
            "VALUES (?, ?, ?, ?, ?, 'actif', ?, ?, ?)",
            (ctx.guild.id, ctx.channel.id, msg.id, prix, gagnants, end_at, ctx.author.id, now()),
        )
        if ctx.interaction:
            await ctx.send(embed=embeds.success("Giveaway créé !"), ephemeral=True)

    @commands.hybrid_command(name="giveaway-end", description="Terminer un giveaway immédiatement.")
    @app_commands.describe(message_id="L'identifiant du message du giveaway")
    @checks.is_owner_or_admin()
    async def giveaway_end(self, ctx: commands.Context, message_id: str):
        try:
            mid = int(message_id)
        except ValueError:
            return await ctx.send(embed=embeds.error("Identifiant de message invalide."))
        giveaway = await self.bot.db.fetchone("SELECT * FROM giveaways WHERE message_id = ?", (mid,))
        if not giveaway:
            return await ctx.send(embed=embeds.error("Giveaway introuvable."))
        await self.end_giveaway(giveaway["id"])
        await ctx.send(embed=embeds.success("Le giveaway a été terminé."))

    @commands.hybrid_command(name="giveaway-reroll", description="Retirer un nouveau gagnant pour un giveaway terminé.")
    @app_commands.describe(message_id="L'identifiant du message du giveaway")
    @checks.is_owner_or_admin()
    async def giveaway_reroll(self, ctx: commands.Context, message_id: str):
        try:
            mid = int(message_id)
        except ValueError:
            return await ctx.send(embed=embeds.error("Identifiant de message invalide."))
        giveaway = await self.bot.db.fetchone("SELECT * FROM giveaways WHERE message_id = ?", (mid,))
        if not giveaway or giveaway["status"] != "termine":
            return await ctx.send(embed=embeds.error("Ce giveaway n'existe pas ou n'est pas terminé."))
        entries = await self.bot.db.fetchall("SELECT * FROM giveaway_entries WHERE giveaway_id = ?", (giveaway["id"],))
        if not entries:
            return await ctx.send(embed=embeds.warning("Aucun participant à ce giveaway."))
        winner = random.choice(entries)["user_id"]
        await ctx.send(embed=embeds.success(f"🎉 Nouveau gagnant : <@{winner}> pour **{giveaway['prize']}** !"))

    @commands.hybrid_command(name="giveaway-list", description="Lister les giveaways actifs.")
    async def giveaway_list(self, ctx: commands.Context):
        rows = await self.bot.db.fetchall(
            "SELECT * FROM giveaways WHERE guild_id = ? AND status = 'actif' ORDER BY end_at ASC", (ctx.guild.id,)
        )
        if not rows:
            return await ctx.send(embed=embeds.info("Aucun giveaway actif pour l'instant."))
        lines = [f"**{r['prize']}** — se termine <t:{r['end_at']}:R> (msg `{r['message_id']}`)" for r in rows]
        await ctx.send(embed=embeds.neutral("🎉 Giveaways actifs", "\n".join(lines)))

    @commands.hybrid_command(name="giveaway-cancel", description="Annuler un giveaway sans désigner de gagnant.", with_app_command=False)
    @app_commands.describe(message_id="L'identifiant du message du giveaway")
    @checks.is_owner_or_admin()
    async def giveaway_cancel(self, ctx: commands.Context, message_id: str):
        try:
            mid = int(message_id)
        except ValueError:
            return await ctx.send(embed=embeds.error("Identifiant de message invalide."))
        giveaway = await self.bot.db.fetchone("SELECT * FROM giveaways WHERE message_id = ?", (mid,))
        if not giveaway:
            return await ctx.send(embed=embeds.error("Giveaway introuvable."))
        await self.bot.db.execute("UPDATE giveaways SET status = 'annule' WHERE id = ?", (giveaway["id"],))
        channel = ctx.guild.get_channel(giveaway["channel_id"])
        if channel:
            try:
                msg = await channel.fetch_message(mid)
                await msg.edit(embed=embeds.error(f"🚫 Giveaway annulé : {giveaway['prize']}"), view=None)
            except discord.NotFound:
                pass
        await ctx.send(embed=embeds.success("Giveaway annulé."))

    @commands.hybrid_command(name="giveaway-blacklist", description="Empêcher un membre de participer aux giveaways.", with_app_command=False)
    @app_commands.describe(membre="Le membre à mettre sur liste noire")
    @checks.is_owner_or_admin()
    async def giveaway_blacklist(self, ctx: commands.Context, membre: discord.Member):
        await self.bot.db.execute(
            "INSERT OR IGNORE INTO giveaway_blacklist (guild_id, user_id) VALUES (?, ?)", (ctx.guild.id, membre.id)
        )
        await ctx.send(embed=embeds.success(f"{membre.mention} ne peut plus participer aux giveaways."))

    @commands.hybrid_command(name="giveaway-unblacklist", description="Autoriser à nouveau un membre à participer aux giveaways.", with_app_command=False)
    @app_commands.describe(membre="Le membre à retirer de la liste noire")
    @checks.is_owner_or_admin()
    async def giveaway_unblacklist(self, ctx: commands.Context, membre: discord.Member):
        await self.bot.db.execute(
            "DELETE FROM giveaway_blacklist WHERE guild_id = ? AND user_id = ?", (ctx.guild.id, membre.id)
        )
        await ctx.send(embed=embeds.success(f"{membre.mention} peut à nouveau participer aux giveaways."))

    # ---------------------------------------------------------------- ÉVÉNEMENTS

    @tasks.loop(minutes=1)
    async def check_events(self):
        rows = await self.bot.db.fetchall(
            "SELECT * FROM events WHERE status = 'planifie' AND start_at <= ?", (now(),)
        )
        for row in rows:
            await self.bot.db.execute("UPDATE events SET status = 'en_cours' WHERE id = ?", (row["id"],))
            guild = self.bot.get_guild(row["guild_id"])
            if guild:
                channel = guild.get_channel(row["channel_id"])
                if channel:
                    try:
                        await channel.send(embed=embeds.success(f"📅 L'événement **{row['name']}** commence maintenant !"))
                    except discord.HTTPException:
                        pass

    @check_events.before_loop
    async def before_check_events(self):
        await self.bot.wait_until_ready()

    @commands.hybrid_command(name="event-create", description="Créer un événement communautaire.")
    @app_commands.describe(nom="Le nom de l'événement", duree="Dans combien de temps il commence (ex: 1h, 1j)")
    @checks.is_owner_or_admin()
    async def event_create(self, ctx: commands.Context, nom: str, duree: str):
        seconds = helpers.parse_duration(duree)
        if not seconds:
            return await ctx.send(embed=embeds.error("Durée invalide. Exemple : `1h`, `1j`."))
        start_at = now() + seconds
        await self.bot.db.execute(
            "INSERT INTO events (guild_id, channel_id, name, start_at, status, created_by, created_at) "
            "VALUES (?, ?, ?, ?, 'planifie', ?, ?)",
            (ctx.guild.id, ctx.channel.id, nom, start_at, ctx.author.id, now()),
        )
        await ctx.send(embed=embeds.success(f"📅 Événement **{nom}** créé, il commence <t:{start_at}:R>. Utilisez `/event-join` pour vous inscrire."))

    @commands.hybrid_command(name="event-join", description="Rejoindre un événement.")
    @app_commands.describe(nom="Le nom de l'événement")
    async def event_join(self, ctx: commands.Context, *, nom: str):
        event = await self.bot.db.fetchone(
            "SELECT * FROM events WHERE guild_id = ? AND name = ? AND status != 'termine'", (ctx.guild.id, nom)
        )
        if not event:
            return await ctx.send(embed=embeds.error("Événement introuvable."))
        await self.bot.db.execute(
            "INSERT OR IGNORE INTO event_participants (event_id, user_id) VALUES (?, ?)", (event["id"], ctx.author.id)
        )
        await ctx.send(embed=embeds.success(f"✅ Vous participez à **{nom}** !"))

    @commands.hybrid_command(name="event-leave", description="Quitter un événement.", with_app_command=False)
    @app_commands.describe(nom="Le nom de l'événement")
    async def event_leave(self, ctx: commands.Context, *, nom: str):
        event = await self.bot.db.fetchone("SELECT * FROM events WHERE guild_id = ? AND name = ?", (ctx.guild.id, nom))
        if not event:
            return await ctx.send(embed=embeds.error("Événement introuvable."))
        await self.bot.db.execute(
            "DELETE FROM event_participants WHERE event_id = ? AND user_id = ?", (event["id"], ctx.author.id)
        )
        await ctx.send(embed=embeds.success(f"Vous ne participez plus à **{nom}**."))

    @commands.hybrid_command(name="event-list", description="Lister les événements à venir.")
    async def event_list(self, ctx: commands.Context):
        rows = await self.bot.db.fetchall(
            "SELECT * FROM events WHERE guild_id = ? AND status != 'termine' ORDER BY start_at ASC", (ctx.guild.id,)
        )
        if not rows:
            return await ctx.send(embed=embeds.info("Aucun événement à venir."))
        lines = [f"**{r['name']}** — <t:{r['start_at']}:R>" for r in rows]
        await ctx.send(embed=embeds.neutral("📅 Événements à venir", "\n".join(lines)))

    @commands.hybrid_command(name="event-cancel", description="Annuler un événement.", with_app_command=False)
    @app_commands.describe(nom="Le nom de l'événement")
    @checks.is_owner_or_admin()
    async def event_cancel(self, ctx: commands.Context, *, nom: str):
        event = await self.bot.db.fetchone("SELECT * FROM events WHERE guild_id = ? AND name = ?", (ctx.guild.id, nom))
        if not event:
            return await ctx.send(embed=embeds.error("Événement introuvable."))
        await self.bot.db.execute("UPDATE events SET status = 'annule' WHERE id = ?", (event["id"],))
        await ctx.send(embed=embeds.success(f"Événement **{nom}** annulé."))

    # ---------------------------------------------------------------- TOURNOIS

    @commands.hybrid_command(name="tournament-create", description="Créer un tournoi.", with_app_command=False)
    @app_commands.describe(nom="Le nom du tournoi", max_participants="Nombre maximum de participants")
    @checks.is_owner_or_admin()
    async def tournament_create(self, ctx: commands.Context, nom: str, max_participants: int = 16):
        await self.bot.db.execute(
            "INSERT INTO tournaments (guild_id, name, max_participants, status, created_by, created_at) "
            "VALUES (?, ?, ?, 'inscriptions', ?, ?)",
            (ctx.guild.id, nom, max_participants, ctx.author.id, now()),
        )
        await ctx.send(embed=embeds.success(f"🏆 Tournoi **{nom}** créé ! Inscriptions ouvertes (`/tournament-join`)."))

    @commands.hybrid_command(name="tournament-join", description="Rejoindre un tournoi.", with_app_command=False)
    @app_commands.describe(nom="Le nom du tournoi")
    async def tournament_join(self, ctx: commands.Context, *, nom: str):
        t = await self.bot.db.fetchone(
            "SELECT * FROM tournaments WHERE guild_id = ? AND name = ? AND status = 'inscriptions'", (ctx.guild.id, nom)
        )
        if not t:
            return await ctx.send(embed=embeds.error("Tournoi introuvable ou inscriptions fermées."))
        count = await self.bot.db.fetchone(
            "SELECT COUNT(*) c FROM tournament_participants WHERE tournament_id = ?", (t["id"],)
        )
        if count["c"] >= t["max_participants"]:
            return await ctx.send(embed=embeds.error("Le tournoi est complet."))
        await self.bot.db.execute(
            "INSERT OR IGNORE INTO tournament_participants (tournament_id, user_id) VALUES (?, ?)", (t["id"], ctx.author.id)
        )
        await ctx.send(embed=embeds.success(f"✅ Vous êtes inscrit au tournoi **{nom}** !"))

    @commands.hybrid_command(name="tournament-start", description="Démarrer un tournoi (ferme les inscriptions).", with_app_command=False)
    @app_commands.describe(nom="Le nom du tournoi")
    @checks.is_owner_or_admin()
    async def tournament_start(self, ctx: commands.Context, *, nom: str):
        t = await self.bot.db.fetchone("SELECT * FROM tournaments WHERE guild_id = ? AND name = ?", (ctx.guild.id, nom))
        if not t:
            return await ctx.send(embed=embeds.error("Tournoi introuvable."))
        await self.bot.db.execute("UPDATE tournaments SET status = 'en_cours' WHERE id = ?", (t["id"],))
        participants = await self.bot.db.fetchall("SELECT * FROM tournament_participants WHERE tournament_id = ?", (t["id"],))
        mentions = ", ".join(f"<@{p['user_id']}>" for p in participants) or "Aucun participant"
        await ctx.send(embed=embeds.success(f"🏆 Le tournoi **{nom}** commence !\nParticipants : {mentions}"))

    @commands.hybrid_command(name="tournament-list", description="Lister les tournois en cours.", with_app_command=False)
    async def tournament_list(self, ctx: commands.Context):
        rows = await self.bot.db.fetchall(
            "SELECT * FROM tournaments WHERE guild_id = ? AND status != 'termine' ORDER BY created_at DESC", (ctx.guild.id,)
        )
        if not rows:
            return await ctx.send(embed=embeds.info("Aucun tournoi en cours."))
        lines = [f"**{r['name']}** — {r['status']}" for r in rows]
        await ctx.send(embed=embeds.neutral("🏆 Tournois", "\n".join(lines)))

    @commands.hybrid_command(name="announce", description="Faire une annonce dans le salon configuré.", with_app_command=False)
    @app_commands.describe(texte="Le contenu de l'annonce")
    @checks.is_owner_or_admin()
    async def announce(self, ctx: commands.Context, *, texte: str):
        conf = await self.bot.db.get_guild_config(ctx.guild.id)
        channel = ctx.guild.get_channel(conf["announce_channel"]) if conf and conf["announce_channel"] else ctx.channel
        e = embeds.neutral("📢 Annonce", texte)
        e.set_footer(text=f"Par {ctx.author}")
        await channel.send(embed=e)
        if channel != ctx.channel:
            await ctx.send(embed=embeds.success(f"Annonce envoyée dans {channel.mention}."))


async def setup(bot: commands.Bot):
    await bot.add_cog(Events(bot))
