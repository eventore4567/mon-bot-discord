"""
Cog UTILITAIRES.
/help /ping /avatar /banner /serverinfo /userinfo /roleinfo /channelinfo
/invite /membercount /emoji-list /poll /remind /reminder-list /reminder-cancel
/say /embed-create /translate /weather /calc /qrcode /suggest /report-bug
/afk /roll /choose /timestamp /snipe
"""

import time
import discord
from discord import app_commands
from discord.ext import commands

from utils import embeds, helpers
from database.db import now

CATEGORY_LABELS = {
    "Moderation": "🛡️ Modération",
    "Automod": "🔒 Sécurité / AutoMod",
    "Tickets": "🎫 Tickets",
    "Configuration": "⚙️ Configuration",
    "Utility": "🧰 Utilitaires",
    "Ai": "🤖 Intelligence Artificielle",
    "Economy": "💰 Économie",
    "Levels": "📈 Niveaux / Communauté",
    "Minigames": "🎮 Mini-jeux",
    "Music": "🎵 Musique",
    "Events": "🎉 Giveaways / Événements",
    "Verification": "✅ Vérification / Rôles",
    "Stats": "📊 Statistiques / Développement",
}


class HelpSelect(discord.ui.Select):
    def __init__(self, bot: commands.Bot, prefix: str):
        self.bot = bot
        self.prefix = prefix
        options = [
            discord.SelectOption(label=label, value=cog_name)
            for cog_name, label in CATEGORY_LABELS.items()
            if bot.get_cog(cog_name)
        ]
        super().__init__(placeholder="Choisissez une catégorie...", options=options)

    async def callback(self, interaction: discord.Interaction):
        cog = self.bot.get_cog(self.values[0])
        label = CATEGORY_LABELS.get(self.values[0], self.values[0])
        slash_names = {c.qualified_name for c in self.bot.tree.get_commands()}

        lines = []
        for cmd in cog.get_commands():
            if cmd.hidden:
                continue
            marker = f"/ ou {self.prefix}" if cmd.qualified_name in slash_names else self.prefix
            lines.append(f"`{marker}{cmd.qualified_name}` — {cmd.description or 'Pas de description.'}")

        if not lines:
            e = embeds.neutral(label, "Aucune commande dans cette catégorie.")
            return await interaction.response.edit_message(embed=e, view=self.view)

        chunks = [lines[i:i + 15] for i in range(0, len(lines), 15)] or [[]]
        embeds_list = []
        for i, chunk in enumerate(chunks):
            e = embeds.neutral(label, "\n".join(chunk))
            e.set_footer(text=f"Page {i + 1}/{len(chunks)} • {len(lines)} commande(s)")
            embeds_list.append(e)

        if len(embeds_list) > 1:
            paginator = helpers.PaginatorView(embeds_list, interaction.user.id)
            await interaction.response.edit_message(embed=embeds_list[0], view=paginator)
        else:
            await interaction.response.edit_message(embed=embeds_list[0], view=self.view)


class HelpView(discord.ui.View):
    def __init__(self, bot: commands.Bot, prefix: str):
        super().__init__(timeout=120)
        self.add_item(HelpSelect(bot, prefix))


class Utility(commands.Cog, name="Utility"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.afk_users: dict[int, str] = {}
        self.snipes: dict[int, dict] = {}

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if message.author.bot:
            return
        self.snipes[message.channel.id] = {
            "content": message.content,
            "author": str(message.author),
            "avatar": message.author.display_avatar.url,
            "time": now(),
        }

    @commands.hybrid_command(name="help", description="Afficher la liste des commandes du bot.")
    @app_commands.describe(commande="Nom d'une commande précise (optionnel)")
    async def help_cmd(self, ctx: commands.Context, *, commande: str = None):
        prefix = self.bot.command_prefix
        if callable(prefix):
            conf = await self.bot.db.get_guild_config(ctx.guild.id) if ctx.guild else None
            prefix = conf["prefix"] if conf and conf["prefix"] else "+"

        if commande:
            cmd = self.bot.get_command(commande)
            if not cmd:
                return await ctx.send(embed=embeds.error(f"Commande `{commande}` introuvable."))
            slash_names = {c.qualified_name for c in self.bot.tree.get_commands()}
            marker = f"/ ou {prefix}" if cmd.qualified_name in slash_names else prefix
            e = embeds.neutral(f"{marker}{cmd.qualified_name}", cmd.description or "Pas de description.")
            if isinstance(cmd, commands.HybridCommand) and cmd.clean_params:
                params = ", ".join(cmd.clean_params.keys())
                e.add_field(name="Paramètres", value=params)
            return await ctx.send(embed=e)

        total = sum(1 for _ in self.bot.commands)
        e = embeds.neutral(
            "📖 Menu d'aide",
            f"Ce bot possède **{total} commandes** au total, réparties en catégories ci-dessous.\n\n"
            f"⚠️ Discord limite les commandes `/` à 100 par bot. Pour ne rien manquer, "
            f"**toutes les commandes fonctionnent aussi avec le préfixe `{prefix}`**, sans exception.\n\n"
            f"Utilisez le menu déroulant pour choisir une catégorie."
        )
        await ctx.send(embed=e, view=HelpView(self.bot, prefix))

    @commands.hybrid_command(name="ping", description="Afficher la latence du bot.")
    async def ping(self, ctx: commands.Context):
        await ctx.send(embed=embeds.info(f"🏓 Pong ! Latence : **{round(self.bot.latency * 1000)}ms**"))

    @commands.hybrid_command(name="avatar", description="Afficher l'avatar d'un membre.")
    @app_commands.describe(membre="Le membre visé (optionnel)")
    async def avatar(self, ctx: commands.Context, membre: discord.Member = None):
        membre = membre or ctx.author
        e = embeds.neutral(f"Avatar de {membre}")
        e.set_image(url=membre.display_avatar.url)
        await ctx.send(embed=e)

    @commands.hybrid_command(name="banner", description="Afficher la bannière d'un membre.", with_app_command=False)
    @app_commands.describe(membre="Le membre visé (optionnel)")
    async def banner(self, ctx: commands.Context, membre: discord.Member = None):
        membre = membre or ctx.author
        user = await self.bot.fetch_user(membre.id)
        if not user.banner:
            return await ctx.send(embed=embeds.warning("Ce membre n'a pas de bannière."))
        e = embeds.neutral(f"Bannière de {membre}")
        e.set_image(url=user.banner.url)
        await ctx.send(embed=e)

    @commands.hybrid_command(name="serverinfo", description="Afficher les informations du serveur.")
    async def serverinfo(self, ctx: commands.Context):
        guild = ctx.guild
        e = embeds.neutral(f"📊 {guild.name}")
        if guild.icon:
            e.set_thumbnail(url=guild.icon.url)
        e.add_field(name="Propriétaire", value=f"<@{guild.owner_id}>", inline=True)
        e.add_field(name="Membres", value=guild.member_count, inline=True)
        e.add_field(name="Créé le", value=f"<t:{int(guild.created_at.timestamp())}:D>", inline=True)
        e.add_field(name="Salons textuels", value=len(guild.text_channels), inline=True)
        e.add_field(name="Salons vocaux", value=len(guild.voice_channels), inline=True)
        e.add_field(name="Rôles", value=len(guild.roles), inline=True)
        e.add_field(name="Boosts", value=guild.premium_subscription_count, inline=True)
        await ctx.send(embed=e)

    @commands.hybrid_command(name="userinfo", description="Afficher les informations d'un membre.")
    @app_commands.describe(membre="Le membre visé (optionnel)")
    async def userinfo(self, ctx: commands.Context, membre: discord.Member = None):
        membre = membre or ctx.author
        e = embeds.neutral(f"👤 {membre}")
        e.set_thumbnail(url=membre.display_avatar.url)
        e.add_field(name="ID", value=membre.id, inline=True)
        e.add_field(name="Compte créé", value=f"<t:{int(membre.created_at.timestamp())}:D>", inline=True)
        e.add_field(name="A rejoint le", value=f"<t:{int(membre.joined_at.timestamp())}:D>" if membre.joined_at else "Inconnu", inline=True)
        roles = [r.mention for r in membre.roles if r.name != "@everyone"]
        e.add_field(name=f"Rôles ({len(roles)})", value=", ".join(roles) if roles else "Aucun", inline=False)
        await ctx.send(embed=e)

    @commands.hybrid_command(name="roleinfo", description="Afficher les informations d'un rôle.", with_app_command=False)
    @app_commands.describe(role="Le rôle visé")
    async def roleinfo(self, ctx: commands.Context, role: discord.Role):
        e = embeds.neutral(f"🎭 {role.name}")
        e.color = role.color if role.color.value else e.color
        e.add_field(name="ID", value=role.id, inline=True)
        e.add_field(name="Couleur", value=str(role.color), inline=True)
        e.add_field(name="Membres", value=len(role.members), inline=True)
        e.add_field(name="Position", value=role.position, inline=True)
        e.add_field(name="Mentionnable", value="Oui" if role.mentionable else "Non", inline=True)
        await ctx.send(embed=e)

    @commands.hybrid_command(name="channelinfo", description="Afficher les informations d'un salon.", with_app_command=False)
    @app_commands.describe(salon="Le salon visé (optionnel)")
    async def channelinfo(self, ctx: commands.Context, salon: discord.abc.GuildChannel = None):
        salon = salon or ctx.channel
        e = embeds.neutral(f"📺 #{salon.name}")
        e.add_field(name="ID", value=salon.id, inline=True)
        e.add_field(name="Type", value=str(salon.type), inline=True)
        e.add_field(name="Créé le", value=f"<t:{int(salon.created_at.timestamp())}:D>", inline=True)
        await ctx.send(embed=e)

    @commands.hybrid_command(name="invite", description="Obtenir le lien d'invitation du bot.")
    async def invite(self, ctx: commands.Context):
        link = discord.utils.oauth_url(self.bot.user.id, permissions=discord.Permissions(administrator=True))
        await ctx.send(embed=embeds.info(f"[Cliquez ici pour m'inviter]({link})"))

    @commands.hybrid_command(name="membercount", description="Afficher le nombre de membres du serveur.", with_app_command=False)
    async def membercount(self, ctx: commands.Context):
        guild = ctx.guild
        humans = sum(1 for m in guild.members if not m.bot)
        bots = sum(1 for m in guild.members if m.bot)
        e = embeds.neutral("👥 Membres du serveur")
        e.add_field(name="Total", value=guild.member_count, inline=True)
        e.add_field(name="Humains", value=humans, inline=True)
        e.add_field(name="Bots", value=bots, inline=True)
        await ctx.send(embed=e)

    @commands.hybrid_command(name="emoji-list", description="Lister les emojis du serveur.", with_app_command=False)
    async def emoji_list(self, ctx: commands.Context):
        if not ctx.guild.emojis:
            return await ctx.send(embed=embeds.warning("Ce serveur n'a aucun emoji personnalisé."))
        text = " ".join(str(e) for e in ctx.guild.emojis)[:4000]
        await ctx.send(embed=embeds.neutral(f"😀 Emojis ({len(ctx.guild.emojis)})", text))

    @commands.hybrid_command(name="poll", description="Créer un sondage rapide (réactions 👍/👎).")
    @app_commands.describe(question="La question du sondage")
    async def poll(self, ctx: commands.Context, *, question: str):
        e = embeds.neutral("📊 Sondage", question)
        e.set_footer(text=f"Créé par {ctx.author}")
        msg = await ctx.send(embed=e)
        await msg.add_reaction("👍")
        await msg.add_reaction("👎")

    @commands.hybrid_command(name="remind", description="Définir un rappel personnel.")
    @app_commands.describe(duree="Durée (ex: 10m, 2h, 1j)", texte="Le texte du rappel")
    async def remind(self, ctx: commands.Context, duree: str, *, texte: str):
        seconds = helpers.parse_duration(duree)
        if not seconds:
            return await ctx.send(embed=embeds.error("Durée invalide. Exemple : `10m`, `2h`, `1j`."))
        trigger_at = now() + seconds
        await self.bot.db.execute(
            "INSERT INTO reminders (user_id, channel_id, guild_id, text, trigger_at, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (ctx.author.id, ctx.channel.id, ctx.guild.id if ctx.guild else None, texte, trigger_at, now()),
        )
        await ctx.send(embed=embeds.success(f"⏰ Rappel défini dans {helpers.format_duration(seconds)}."))

    @commands.hybrid_command(name="reminder-list", description="Lister vos rappels en cours.", with_app_command=False)
    async def reminder_list(self, ctx: commands.Context):
        rows = await self.bot.db.fetchall("SELECT * FROM reminders WHERE user_id = ? ORDER BY trigger_at ASC", (ctx.author.id,))
        if not rows:
            return await ctx.send(embed=embeds.info("Vous n'avez aucun rappel en cours."))
        lines = [f"`#{r['id']}` <t:{r['trigger_at']}:R> — {r['text'][:50]}" for r in rows[:15]]
        await ctx.send(embed=embeds.neutral("⏰ Vos rappels", "\n".join(lines)))

    @commands.hybrid_command(name="reminder-cancel", description="Annuler un rappel.", with_app_command=False)
    @app_commands.describe(id="L'identifiant du rappel (voir /reminder-list)")
    async def reminder_cancel(self, ctx: commands.Context, id: int):
        row = await self.bot.db.fetchone("SELECT * FROM reminders WHERE id = ? AND user_id = ?", (id, ctx.author.id))
        if not row:
            return await ctx.send(embed=embeds.error("Rappel introuvable."))
        await self.bot.db.execute("DELETE FROM reminders WHERE id = ?", (id,))
        await ctx.send(embed=embeds.success("Rappel annulé."))

    @commands.hybrid_command(name="say", description="Faire répéter un message par le bot.", with_app_command=False)
    @app_commands.describe(texte="Le texte à faire répéter")
    @commands.has_permissions(manage_messages=True)
    async def say(self, ctx: commands.Context, *, texte: str):
        if ctx.interaction:
            await ctx.interaction.response.send_message("Message envoyé.", ephemeral=True)
        else:
            await ctx.message.delete()
        await ctx.channel.send(texte)

    @commands.hybrid_command(name="embed-create", description="Créer un embed personnalisé.", with_app_command=False)
    @app_commands.describe(titre="Titre de l'embed", description="Contenu de l'embed")
    @commands.has_permissions(manage_messages=True)
    async def embed_create(self, ctx: commands.Context, titre: str, *, description: str):
        e = embeds.neutral(titre, description)
        await ctx.send(embed=e)

    @commands.hybrid_command(name="translate", description="Traduire un texte vers une autre langue.")
    @app_commands.describe(langue="Code langue cible (ex: en, es, de)", texte="Le texte à traduire")
    async def translate(self, ctx: commands.Context, langue: str, *, texte: str):
        try:
            from deep_translator import GoogleTranslator
            result = GoogleTranslator(source="auto", target=langue).translate(texte)
            await ctx.send(embed=embeds.neutral(f"🌐 Traduction ({langue})", result))
        except Exception:
            await ctx.send(embed=embeds.error("La traduction a échoué. Vérifiez le code de langue."))

    @commands.hybrid_command(name="weather", description="Afficher la météo d'une ville.")
    @app_commands.describe(ville="Le nom de la ville")
    async def weather(self, ctx: commands.Context, *, ville: str):
        import config
        if not config.WEATHER_API_KEY:
            return await ctx.send(embed=embeds.error("Aucune clé météo n'est configurée sur ce bot."))
        import aiohttp
        url = f"https://api.openweathermap.org/data/2.5/weather?q={ville}&appid={config.WEATHER_API_KEY}&units=metric&lang=fr"
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return await ctx.send(embed=embeds.error(f"Ville `{ville}` introuvable."))
                data = await resp.json()
        e = embeds.neutral(f"🌤️ Météo à {data['name']}")
        e.add_field(name="Température", value=f"{data['main']['temp']}°C", inline=True)
        e.add_field(name="Ressenti", value=f"{data['main']['feels_like']}°C", inline=True)
        e.add_field(name="Condition", value=data["weather"][0]["description"], inline=True)
        await ctx.send(embed=e)

    @commands.hybrid_command(name="calc", description="Calculer une expression mathématique simple.")
    @app_commands.describe(expression="L'expression à calculer (ex: 2+2*3)")
    async def calc(self, ctx: commands.Context, *, expression: str):
        allowed = set("0123456789+-*/(). ")
        if not set(expression) <= allowed:
            return await ctx.send(embed=embeds.error("Expression invalide. Utilisez uniquement des chiffres et + - * / ( )."))
        try:
            result = eval(expression, {"__builtins__": {}}, {})
        except Exception:
            return await ctx.send(embed=embeds.error("Impossible de calculer cette expression."))
        await ctx.send(embed=embeds.info(f"🧮 `{expression}` = **{result}**"))

    @commands.hybrid_command(name="qrcode", description="Générer un QR code à partir d'un texte.", with_app_command=False)
    @app_commands.describe(texte="Le texte ou lien à encoder")
    async def qrcode(self, ctx: commands.Context, *, texte: str):
        url = f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data={discord.utils.escape_markdown(texte)}"
        e = embeds.neutral("🔳 QR Code généré")
        e.set_image(url=url)
        await ctx.send(embed=e)

    @commands.hybrid_command(name="suggest", description="Faire une suggestion pour le serveur.")
    @app_commands.describe(texte="Votre suggestion")
    async def suggest(self, ctx: commands.Context, *, texte: str):
        conf = await self.bot.db.get_guild_config(ctx.guild.id)
        channel = ctx.guild.get_channel(conf["suggest_channel"]) if conf and conf["suggest_channel"] else ctx.channel
        e = embeds.neutral("💡 Nouvelle suggestion", texte)
        e.set_footer(text=f"Proposé par {ctx.author}")
        msg = await channel.send(embed=e)
        await msg.add_reaction("👍")
        await msg.add_reaction("👎")
        await self.bot.db.execute(
            "INSERT INTO suggestions (guild_id, user_id, message_id, content, created_at) VALUES (?, ?, ?, ?, ?)",
            (ctx.guild.id, ctx.author.id, msg.id, texte, now()),
        )
        if channel != ctx.channel:
            await ctx.send(embed=embeds.success(f"Suggestion envoyée dans {channel.mention} !"))

    @commands.hybrid_command(name="report-bug", description="Signaler un bug du bot aux développeurs.", with_app_command=False)
    @app_commands.describe(texte="Description du bug")
    async def report_bug(self, ctx: commands.Context, *, texte: str):
        await self.bot.db.execute(
            "INSERT INTO bug_reports (guild_id, user_id, content, created_at) VALUES (?, ?, ?, ?)",
            (ctx.guild.id if ctx.guild else None, ctx.author.id, texte, now()),
        )
        await ctx.send(embed=embeds.success("🐛 Merci, votre signalement a été enregistré."))

    @commands.hybrid_command(name="afk", description="Se mettre en mode AFK (absent).")
    @app_commands.describe(raison="La raison de votre absence (optionnel)")
    async def afk(self, ctx: commands.Context, *, raison: str = "Absent"):
        self.afk_users[ctx.author.id] = raison
        await ctx.send(embed=embeds.info(f"😴 {ctx.author.mention} est maintenant AFK : {raison}"))

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        if message.author.id in self.afk_users:
            del self.afk_users[message.author.id]
            try:
                await message.channel.send(embed=embeds.info(f"👋 Bon retour {message.author.mention}, votre statut AFK a été retiré."), delete_after=5)
            except discord.HTTPException:
                pass
        for mention in message.mentions:
            if mention.id in self.afk_users:
                try:
                    await message.channel.send(embed=embeds.info(f"💤 {mention.display_name} est AFK : {self.afk_users[mention.id]}"), delete_after=5)
                except discord.HTTPException:
                    pass

    @commands.hybrid_command(name="roll", description="Lancer un dé (par défaut 1-100).")
    @app_commands.describe(max="Valeur maximale (optionnel, défaut 100)")
    async def roll(self, ctx: commands.Context, max: int = 100):
        import random
        result = random.randint(1, max)
        await ctx.send(embed=embeds.info(f"🎲 Vous avez obtenu : **{result}** (sur {max})"))

    @commands.hybrid_command(name="choose", description="Faire choisir le bot parmi plusieurs options.")
    @app_commands.describe(options="Options séparées par des virgules")
    async def choose(self, ctx: commands.Context, *, options: str):
        import random
        choices = [c.strip() for c in options.split(",") if c.strip()]
        if len(choices) < 2:
            return await ctx.send(embed=embeds.error("Donnez au moins deux options séparées par des virgules."))
        await ctx.send(embed=embeds.info(f"🤔 Je choisis : **{random.choice(choices)}**"))

    @commands.hybrid_command(name="timestamp", description="Générer un timestamp Discord à partir d'une durée.", with_app_command=False)
    @app_commands.describe(duree="Durée depuis maintenant (ex: 1h, 2j)")
    async def timestamp(self, ctx: commands.Context, duree: str):
        seconds = helpers.parse_duration(duree)
        if not seconds:
            return await ctx.send(embed=embeds.error("Durée invalide."))
        ts = int(time.time()) + seconds
        await ctx.send(embed=embeds.info(f"`<t:{ts}:F>` → <t:{ts}:F> (<t:{ts}:R>)"))

    @commands.hybrid_command(name="snipe", description="Afficher le dernier message supprimé dans ce salon.", with_app_command=False)
    async def snipe(self, ctx: commands.Context):
        data = self.snipes.get(ctx.channel.id)
        if not data:
            return await ctx.send(embed=embeds.warning("Aucun message supprimé récemment dans ce salon."))
        e = embeds.neutral("🗑️ Message supprimé", data["content"] or "*[contenu vide/média]*")
        e.set_footer(text=f"Par {data['author']}")
        await ctx.send(embed=e)


async def setup(bot: commands.Bot):
    await bot.add_cog(Utility(bot))
