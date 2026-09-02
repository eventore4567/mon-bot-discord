"""
Cog GIVEAWAYS / ÉVÉNEMENTS.
/giveaway-create (avec rôle requis, niveau requis, rôle exclu et rôle bonus)
/giveaway-end /giveaway-reroll /giveaway-list /giveaway-cancel /giveaway-blacklist
/giveaway-unblacklist /event-create /event-join /event-leave /event-list
/event-cancel /tournament-create /tournament-join /tournament-start
/tournament-list /announce
"""

import random
import discord
from discord import app_commands
from discord.ext import commands, tasks

import config
from utils import embeds, checks, helpers, design_system
from utils import sentrix_panels as panels
from database.db import now


def weighted_draw(pool_with_weight: list[tuple[int, int]], k: int) -> list[int]:
    """
    Tire k gagnants uniques parmi une liste de (user_id, poids), sans remise,
    en respectant les poids (un membre avec un rôle bonus a plus de "tickets"
    mais ne peut jamais gagner deux fois dans le même giveaway).
    """
    remaining = list(pool_with_weight)
    winners = []
    for _ in range(min(k, len(remaining))):
        total = sum(w for _, w in remaining)
        r = random.uniform(0, total)
        upto = 0.0
        for i, (user_id, weight) in enumerate(remaining):
            upto += weight
            if upto >= r:
                winners.append(user_id)
                remaining.pop(i)
                break
    return winners


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
        # Même salon dédié ("logs-serveur") que les autres événements de serveur, avec
        # repli sur le salon de logs général — cohérent avec le reste du bot.
        await helpers.send_log(self.bot, guild, "server", embed)

    # ---------------------------------------------------------------- GIVEAWAYS

    async def enter_giveaway(self, interaction: discord.Interaction):
        giveaway = await self.bot.db.fetchone(
            "SELECT * FROM giveaways WHERE message_id = ? AND status = 'actif'", (interaction.message.id,)
        )
        if not giveaway:
            return await interaction.response.send_message("Ce giveaway n'est plus actif.", ephemeral=True)

        member = interaction.user  # discord.Member dans un salon de serveur

        # 1) Blacklist par membre (liste noire individuelle).
        blacklisted = await self.bot.db.fetchone(
            "SELECT * FROM giveaway_blacklist WHERE guild_id = ? AND user_id = ?",
            (interaction.guild.id, member.id),
        )
        if blacklisted:
            return await interaction.response.send_message("🚫 Vous n'êtes pas autorisé à participer aux giveaways.", ephemeral=True)

        # 2) Blacklist par rôle, définie directement à la création de CE giveaway
        # (paramètre "role_exclu" de /giveaway-create).
        if giveaway["excluded_role_id"]:
            if any(r.id == giveaway["excluded_role_id"] for r in member.roles):
                return await interaction.response.send_message(
                    "🚫 Votre rôle vous empêche de participer à ce giveaway.", ephemeral=True
                )

        # 3) Rôle requis pour participer (optionnel, défini à la création du giveaway).
        if giveaway["required_role_id"]:
            if not any(r.id == giveaway["required_role_id"] for r in member.roles):
                role = interaction.guild.get_role(giveaway["required_role_id"])
                role_name = role.mention if role else "un rôle spécifique"
                return await interaction.response.send_message(
                    f"○ Il faut avoir le rôle {role_name} pour participer à ce giveaway.", ephemeral=True
                )

        # 4) Niveau requis pour participer (optionnel).
        if giveaway["required_level"]:
            level_row = await self.bot.db.get_level(interaction.guild.id, member.id)
            if level_row["level"] < giveaway["required_level"]:
                return await interaction.response.send_message(
                    f"○ Il faut être au moins niveau **{giveaway['required_level']}** pour participer "
                    f"(vous êtes niveau {level_row['level']}).",
                    ephemeral=True,
                )

        existing = await self.bot.db.fetchone(
            "SELECT * FROM giveaway_entries WHERE giveaway_id = ? AND user_id = ?",
            (giveaway["id"], member.id),
        )
        if existing:
            await self.bot.db.execute(
                "DELETE FROM giveaway_entries WHERE giveaway_id = ? AND user_id = ?",
                (giveaway["id"], member.id),
            )
            return await interaction.response.send_message("○ Vous ne participez plus à ce giveaway.", ephemeral=True)

        await self.bot.db.execute(
            "INSERT INTO giveaway_entries (giveaway_id, user_id) VALUES (?, ?)",
            (giveaway["id"], member.id),
        )
        bonus_note = ""
        if giveaway["bonus_role_id"] and any(r.id == giveaway["bonus_role_id"] for r in member.roles):
            bonus_note = f" (votre rôle vous donne **{giveaway['bonus_entries']}x** plus de chances !)"
        await interaction.response.send_message(f"🎉 Vous participez maintenant à ce giveaway !{bonus_note}", ephemeral=True)

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
                    design = await self.bot.db.get_design_settings(giveaway["guild_id"])
                    style = design_system.CATEGORY_STYLES["giveaways"]
                    e = design_system.create_embed(
                        title=f"{style['emoji']} Giveaway terminé",
                        description=f"Le giveaway **{giveaway['prize']}** est terminé, mais personne n'a participé.",
                        colour=design.get("warning_color", design_system.COLORS.warning),
                        footer=design.get("footer"),
                    )
                    await panels.envoyer(channel, panels.depuis_embed(e))
                except discord.HTTPException:
                    pass
            return

        # Construit le tirage pondéré : un membre avec le rôle bonus configuré obtient
        # plusieurs "tickets" dans le tirage, donc plus de chances de gagner, mais ne
        # peut toujours gagner qu'une seule fois grâce au tirage sans remise.
        bonus_role_id = giveaway["bonus_role_id"]
        bonus_entries = giveaway["bonus_entries"] or 2
        pool_with_weight = []
        for entry in entries:
            weight = 1
            if bonus_role_id:
                member = guild.get_member(entry["user_id"])
                if member and any(r.id == bonus_role_id for r in member.roles):
                    weight = bonus_entries
            pool_with_weight.append((entry["user_id"], weight))

        winners = weighted_draw(pool_with_weight, winners_count)
        mentions = ", ".join(f"<@{w}>" for w in winners)

        await self.bot.db.execute(
            "UPDATE giveaways SET winners = ? WHERE id = ?", (",".join(str(w) for w in winners), giveaway_id)
        )

        if channel:
            design = await self.bot.db.get_design_settings(giveaway["guild_id"])
            style = design_system.CATEGORY_STYLES["giveaways"]
            e = design_system.create_embed(
                title=f"{style['emoji']} Félicitations !",
                description=f"{mentions}\n\nVous avez gagné **{giveaway['prize']}** !",
                colour=design.get("success_color", design_system.COLORS.success),
                footer=design.get("footer"),
            )
            try:
                await panels.envoyer(channel, panels.depuis_embed(e))
                original = None
                try:
                    original = await channel.fetch_message(giveaway["message_id"])
                except discord.NotFound:
                    pass
                if original:
                    # On garde le même embed d'origine (titre, champs déjà présents) et on
                    # ajoute seulement le résultat — jamais de nouvel embed reconstruit de
                    # zéro ici, pour ne perdre aucune information déjà affichée.
                    ended_embed = original.embeds[0] if original.embeds else design_system.create_embed(title=f"{style['emoji']} Giveaway terminé", colour=style["colour"])
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
        image="(Optionnel) URL d'une image à afficher sur le giveaway",
        role_requis="(Optionnel) Rôle obligatoire pour participer",
        niveau_requis="(Optionnel) Niveau minimum requis pour participer",
        role_exclu="(Optionnel) Rôle interdit de participation (liste noire pour ce giveaway)",
        role_bonus="(Optionnel) Rôle qui donne plus de chances de gagner",
        entrees_bonus="(Optionnel) Multiplicateur de chances pour le rôle bonus (défaut 2 = double chance)",
    )
    @checks.is_owner_or_admin()
    async def giveaway_create(
        self,
        ctx: commands.Context,
        prix: str,
        duree: str,
        gagnants: int = 1,
        image: str = None,
        role_requis: discord.Role = None,
        niveau_requis: int = None,
        role_exclu: discord.Role = None,
        role_bonus: discord.Role = None,
        entrees_bonus: int = 2,
    ):
        seconds = helpers.parse_duration(duree)
        if not seconds:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Durée invalide. Exemple : `10m`, `1h`, `1j`.')))
        if gagnants < 1:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Le nombre de gagnants doit être au moins 1.')))
        if entrees_bonus < 1:
            entrees_bonus = 2

        # Une pièce jointe envoyée AVEC la commande (uniquement possible en préfixe, +) est
        # acceptée comme alternative à une URL — pratique pour ne pas avoir à héberger
        # l'image ailleurs avant de créer le giveaway.
        if not image and ctx.message and ctx.message.attachments:
            image = ctx.message.attachments[0].url
        if image and not (image.startswith("http://") or image.startswith("https://")):
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error("L'URL de l'image doit commencer par `http://` ou `https://`.")))

        end_at = now() + seconds
        design = await self.bot.db.get_design_settings(ctx.guild.id)
        style = design_system.CATEGORY_STYLES["giveaways"]
        e = design_system.create_embed(
            title=f"{style['emoji']} GIVEAWAY",
            description=f"**Prix :** {prix}\n\nCliquez sur le bouton ci-dessous pour participer !",
            colour=design.get("primary_color", style["colour"]),
            footer=design.get("footer"),
        )
        e.add_field(name="Se termine", value=f"<t:{end_at}:R>", inline=True)
        e.add_field(name="Gagnants", value=str(gagnants), inline=True)
        e.add_field(name="Organisé par", value=ctx.author.mention, inline=True)
        if role_requis:
            e.add_field(name="Rôle requis", value=role_requis.mention, inline=True)
        if niveau_requis:
            e.add_field(name="Niveau requis", value=str(niveau_requis), inline=True)
        if role_exclu:
            e.add_field(name="Rôle exclu", value=role_exclu.mention, inline=True)
        if role_bonus:
            e.add_field(name="Bonus de chances", value=f"{role_bonus.mention} ({entrees_bonus}x)", inline=True)
        if image:
            e.set_image(url=image)

        msg = await panels.envoyer(ctx, panels.avec_composants(panels.depuis_embed(e), GiveawayView()))
        await self.bot.db.execute(
            "INSERT INTO giveaways "
            "(guild_id, channel_id, message_id, prize, winners_count, status, end_at, "
            "required_role_id, required_level, excluded_role_id, bonus_role_id, bonus_entries, created_by, created_at, image_url) "
            "VALUES (?, ?, ?, ?, ?, 'actif', ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                ctx.guild.id, ctx.channel.id, msg.id, prix, gagnants, end_at,
                role_requis.id if role_requis else None,
                niveau_requis,
                role_exclu.id if role_exclu else None,
                role_bonus.id if role_bonus else None,
                entrees_bonus,
                ctx.author.id, now(), image,
            ),
        )
        if ctx.interaction:
            await panels.envoyer(ctx, panels.depuis_embed(embeds.success('Giveaway créé !')), ephemere=True)
        await self.log_action(ctx.guild, embeds.log_entry(
            "🎉 Giveaway créé", config.COLOR_SUCCESS, acteur=ctx.author, acteur_label="🛠️ Organisé par",
            extra={"🎁 Prix": prix, "🏆 Gagnants": str(gagnants), "⏱️ Se termine": f"<t:{end_at}:R>"},
        ))

    @commands.hybrid_command(name="giveaway-end", description="Terminer un giveaway immédiatement.")
    @app_commands.describe(message_id="L'identifiant du message du giveaway")
    @checks.is_owner_or_admin()
    async def giveaway_end(self, ctx: commands.Context, message_id: str):
        try:
            mid = int(message_id)
        except ValueError:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Identifiant de message invalide.')))
        giveaway = await self.bot.db.fetchone("SELECT * FROM giveaways WHERE message_id = ?", (mid,))
        if not giveaway:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Giveaway introuvable.')))
        await self.end_giveaway(giveaway["id"])
        await panels.envoyer(ctx, panels.depuis_embed(embeds.success('Le giveaway a été terminé.')))

    @commands.hybrid_command(name="giveaway-reroll", description="Retirer un nouveau gagnant pour un giveaway terminé.")
    @app_commands.describe(message_id="L'identifiant du message du giveaway")
    @checks.is_owner_or_admin()
    async def giveaway_reroll(self, ctx: commands.Context, message_id: str):
        try:
            mid = int(message_id)
        except ValueError:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Identifiant de message invalide.')))
        giveaway = await self.bot.db.fetchone("SELECT * FROM giveaways WHERE message_id = ?", (mid,))
        if not giveaway or giveaway["status"] != "termine":
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error("Ce giveaway n'existe pas ou n'est pas terminé.")))
        entries = await self.bot.db.fetchall("SELECT * FROM giveaway_entries WHERE giveaway_id = ?", (giveaway["id"],))
        if not entries:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.warning('Aucun participant à ce giveaway.')))
        winner = random.choice(entries)["user_id"]
        await panels.envoyer(ctx, panels.depuis_embed(embeds.success(f"🎉 Nouveau gagnant : <@{winner}> pour **{giveaway['prize']}** !")))

    @commands.hybrid_command(name="giveaway-list", description="Lister les giveaways actifs.")
    async def giveaway_list(self, ctx: commands.Context):
        rows = await self.bot.db.fetchall(
            "SELECT * FROM giveaways WHERE guild_id = ? AND status = 'actif' ORDER BY end_at ASC", (ctx.guild.id,)
        )
        if not rows:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.info("Aucun giveaway actif pour l'instant.")))
        lines = [f"**{r['prize']}** — se termine <t:{r['end_at']}:R> (msg `{r['message_id']}`)" for r in rows]
        await panels.envoyer(ctx, panels.depuis_embed(embeds.neutral('🎉 Giveaways actifs', '\n'.join(lines))))

    @commands.hybrid_command(name="giveaway-cancel", description="Annuler un giveaway sans désigner de gagnant.", with_app_command=False)
    @app_commands.describe(message_id="L'identifiant du message du giveaway")
    @checks.is_owner_or_admin()
    async def giveaway_cancel(self, ctx: commands.Context, message_id: str):
        try:
            mid = int(message_id)
        except ValueError:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Identifiant de message invalide.')))
        giveaway = await self.bot.db.fetchone("SELECT * FROM giveaways WHERE message_id = ?", (mid,))
        if not giveaway:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Giveaway introuvable.')))
        await self.bot.db.execute("UPDATE giveaways SET status = 'annule' WHERE id = ?", (giveaway["id"],))
        channel = ctx.guild.get_channel(giveaway["channel_id"])
        if channel:
            try:
                msg = await channel.fetch_message(mid)
                await msg.edit(embed=embeds.error(f"🚫 Giveaway annulé : {giveaway['prize']}"), view=None)
            except discord.NotFound:
                pass
        await panels.envoyer(ctx, panels.depuis_embed(embeds.success('Giveaway annulé.')))
        await self.log_action(ctx.guild, embeds.log_entry(
            "🚫 Giveaway annulé", config.COLOR_WARNING, acteur=ctx.author, acteur_label="🛠️ Annulé par",
            extra={"🎁 Prix": giveaway["prize"]},
        ))

    @commands.hybrid_command(name="giveaway-blacklist", description="Empêcher un membre de participer aux giveaways.", with_app_command=False)
    @app_commands.describe(membre="Le membre à mettre sur liste noire")
    @checks.is_owner_or_admin()
    async def giveaway_blacklist(self, ctx: commands.Context, membre: discord.Member):
        await self.bot.db.execute(
            "INSERT OR IGNORE INTO giveaway_blacklist (guild_id, user_id) VALUES (?, ?)", (ctx.guild.id, membre.id)
        )
        await panels.envoyer(ctx, panels.depuis_embed(embeds.success(f'{membre.mention} ne peut plus participer aux giveaways.')))

    @commands.hybrid_command(name="giveaway-unblacklist", description="Autoriser à nouveau un membre à participer aux giveaways.", with_app_command=False)
    @app_commands.describe(membre="Le membre à retirer de la liste noire")
    @checks.is_owner_or_admin()
    async def giveaway_unblacklist(self, ctx: commands.Context, membre: discord.Member):
        await self.bot.db.execute(
            "DELETE FROM giveaway_blacklist WHERE guild_id = ? AND user_id = ?", (ctx.guild.id, membre.id)
        )
        await panels.envoyer(ctx, panels.depuis_embed(embeds.success(f'{membre.mention} peut à nouveau participer aux giveaways.')))

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
                        await panels.envoyer(channel, panels.depuis_embed(embeds.success(f"📅 L'événement **{row['name']}** commence maintenant !")))
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
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Durée invalide. Exemple : `1h`, `1j`.')))
        start_at = now() + seconds
        await self.bot.db.execute(
            "INSERT INTO events (guild_id, channel_id, name, start_at, status, created_by, created_at) "
            "VALUES (?, ?, ?, ?, 'planifie', ?, ?)",
            (ctx.guild.id, ctx.channel.id, nom, start_at, ctx.author.id, now()),
        )
        await panels.envoyer(ctx, panels.depuis_embed(embeds.success(f'📅 Événement **{nom}** créé, il commence <t:{start_at}:R>. Utilisez `/event-join` pour vous inscrire.')))
        await self.log_action(ctx.guild, embeds.log_entry(
            "📅 Événement créé", config.COLOR_SUCCESS, acteur=ctx.author, acteur_label="🛠️ Organisé par",
            extra={"🏷️ Nom": nom, "⏱️ Débute": f"<t:{start_at}:R>"},
        ))

    @commands.hybrid_command(name="event-join", description="Rejoindre un événement.")
    @app_commands.describe(nom="Le nom de l'événement")
    async def event_join(self, ctx: commands.Context, *, nom: str):
        event = await self.bot.db.fetchone(
            "SELECT * FROM events WHERE guild_id = ? AND name = ? AND status != 'termine'", (ctx.guild.id, nom)
        )
        if not event:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Événement introuvable.')))
        await self.bot.db.execute(
            "INSERT OR IGNORE INTO event_participants (event_id, user_id) VALUES (?, ?)", (event["id"], ctx.author.id)
        )
        await panels.envoyer(ctx, panels.depuis_embed(embeds.success(f'● Vous participez à **{nom}** !')))

    @commands.hybrid_command(name="event-leave", description="Quitter un événement.", with_app_command=False)
    @app_commands.describe(nom="Le nom de l'événement")
    async def event_leave(self, ctx: commands.Context, *, nom: str):
        event = await self.bot.db.fetchone("SELECT * FROM events WHERE guild_id = ? AND name = ?", (ctx.guild.id, nom))
        if not event:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Événement introuvable.')))
        await self.bot.db.execute(
            "DELETE FROM event_participants WHERE event_id = ? AND user_id = ?", (event["id"], ctx.author.id)
        )
        await panels.envoyer(ctx, panels.depuis_embed(embeds.success(f'Vous ne participez plus à **{nom}**.')))

    @commands.hybrid_command(name="event-list", description="Lister les événements à venir.")
    async def event_list(self, ctx: commands.Context):
        rows = await self.bot.db.fetchall(
            "SELECT * FROM events WHERE guild_id = ? AND status != 'termine' ORDER BY start_at ASC", (ctx.guild.id,)
        )
        if not rows:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.info('Aucun événement à venir.')))
        lines = [f"**{r['name']}** — <t:{r['start_at']}:R>" for r in rows]
        await panels.envoyer(ctx, panels.depuis_embed(embeds.neutral('📅 Événements à venir', '\n'.join(lines))))

    @commands.hybrid_command(name="event-cancel", description="Annuler un événement.", with_app_command=False)
    @app_commands.describe(nom="Le nom de l'événement")
    @checks.is_owner_or_admin()
    async def event_cancel(self, ctx: commands.Context, *, nom: str):
        event = await self.bot.db.fetchone("SELECT * FROM events WHERE guild_id = ? AND name = ?", (ctx.guild.id, nom))
        if not event:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Événement introuvable.')))
        await self.bot.db.execute("UPDATE events SET status = 'annule' WHERE id = ?", (event["id"],))
        await panels.envoyer(ctx, panels.depuis_embed(embeds.success(f'Événement **{nom}** annulé.')))

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
        await panels.envoyer(ctx, panels.depuis_embed(embeds.success(f'🏆 Tournoi **{nom}** créé ! Inscriptions ouvertes (`/tournament-join`).')))

    @commands.hybrid_command(name="tournament-join", description="Rejoindre un tournoi.", with_app_command=False)
    @app_commands.describe(nom="Le nom du tournoi")
    async def tournament_join(self, ctx: commands.Context, *, nom: str):
        t = await self.bot.db.fetchone(
            "SELECT * FROM tournaments WHERE guild_id = ? AND name = ? AND status = 'inscriptions'", (ctx.guild.id, nom)
        )
        if not t:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Tournoi introuvable ou inscriptions fermées.')))
        count = await self.bot.db.fetchone(
            "SELECT COUNT(*) c FROM tournament_participants WHERE tournament_id = ?", (t["id"],)
        )
        if count["c"] >= t["max_participants"]:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Le tournoi est complet.')))
        await self.bot.db.execute(
            "INSERT OR IGNORE INTO tournament_participants (tournament_id, user_id) VALUES (?, ?)", (t["id"], ctx.author.id)
        )
        await panels.envoyer(ctx, panels.depuis_embed(embeds.success(f'● Vous êtes inscrit au tournoi **{nom}** !')))

    @commands.hybrid_command(name="tournament-start", description="Démarrer un tournoi (ferme les inscriptions).", with_app_command=False)
    @app_commands.describe(nom="Le nom du tournoi")
    @checks.is_owner_or_admin()
    async def tournament_start(self, ctx: commands.Context, *, nom: str):
        t = await self.bot.db.fetchone("SELECT * FROM tournaments WHERE guild_id = ? AND name = ?", (ctx.guild.id, nom))
        if not t:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Tournoi introuvable.')))
        await self.bot.db.execute("UPDATE tournaments SET status = 'en_cours' WHERE id = ?", (t["id"],))
        participants = await self.bot.db.fetchall("SELECT * FROM tournament_participants WHERE tournament_id = ?", (t["id"],))
        mentions = ", ".join(f"<@{p['user_id']}>" for p in participants) or "Aucun participant"
        await panels.envoyer(ctx, panels.depuis_embed(embeds.success(f'🏆 Le tournoi **{nom}** commence !\nParticipants : {mentions}')))

    @commands.hybrid_command(name="tournament-list", description="Lister les tournois en cours.", with_app_command=False)
    async def tournament_list(self, ctx: commands.Context):
        rows = await self.bot.db.fetchall(
            "SELECT * FROM tournaments WHERE guild_id = ? AND status != 'termine' ORDER BY created_at DESC", (ctx.guild.id,)
        )
        if not rows:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.info('Aucun tournoi en cours.')))
        lines = [f"**{r['name']}** — {r['status']}" for r in rows]
        await panels.envoyer(ctx, panels.depuis_embed(embeds.neutral('🏆 Tournois', '\n'.join(lines))))

    @commands.hybrid_command(name="announce", description="Faire une annonce dans le salon configuré.", with_app_command=False)
    @app_commands.describe(texte="Le contenu de l'annonce")
    @checks.is_owner_or_admin()
    async def announce(self, ctx: commands.Context, *, texte: str):
        conf = await self.bot.db.get_guild_config(ctx.guild.id)
        channel = ctx.guild.get_channel(conf["announce_channel"]) if conf and conf["announce_channel"] else ctx.channel
        e = embeds.neutral("📢 Annonce", texte)
        e.set_footer(text=f"Par {ctx.author}")
        await panels.envoyer(channel, panels.depuis_embed(e))
        if channel != ctx.channel:
            await panels.envoyer(ctx, panels.depuis_embed(embeds.success(f'Annonce envoyée dans {channel.mention}.')))


async def setup(bot: commands.Bot):
    await bot.add_cog(Events(bot))
