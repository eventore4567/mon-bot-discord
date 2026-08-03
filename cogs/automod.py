"""
Cog SÉCURITÉ ET AUTOMOD.
/blacklist-add /blacklist-remove /blacklist-list /blacklist-user /unblacklist-user
/blacklist-users /antispam /antilink /antiinvite /antimention /anticaps /antiemoji
/antiraid /antibot /antiaccount /antiscam /automod-status /whitelist-domain
/unwhitelist-domain /security-level

Un seul écouteur on_message applique tous les filtres actifs.
Aucune adresse IP n'est collectée : seuls les identifiants Discord sont utilisés.
"""

import re
import time
import discord
from discord import app_commands
from discord.ext import commands

from utils import embeds, checks

INVITE_RE = re.compile(r"(discord\.gg|discord(?:app)?\.com/invite)/\S+", re.IGNORECASE)
LINK_RE = re.compile(r"https?://\S+", re.IGNORECASE)
SCAM_KEYWORDS = ["free nitro", "nitro gratuit", "steamcommunity", "airdrop gratuit", "crypto giveaway"]

TOGGLE_FIELDS = [
    "antispam", "antilink", "antiinvite", "antimention", "anticaps",
    "antiemoji", "antiraid", "antibot", "antiaccount", "antiscam",
]

TOGGLE_CHOICES = [
    app_commands.Choice(name="Activer", value="on"),
    app_commands.Choice(name="Désactiver", value="off"),
]


class AutoMod(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.spam_tracker: dict[tuple[int, int], list[float]] = {}
        self.join_tracker: dict[int, list[float]] = {}

    async def log_action(self, guild: discord.Guild, embed: discord.Embed):
        conf = await self.bot.db.get_guild_config(guild.id)
        if conf and conf["log_channel"]:
            channel = guild.get_channel(conf["log_channel"])
            if channel:
                try:
                    await channel.send(embed=embed)
                except discord.HTTPException:
                    pass

    async def toggle(self, ctx: commands.Context, field: str, etat: str):
        value = 1 if etat == "on" else 0
        await self.bot.db.set_automod(ctx.guild.id, field, value)
        state_text = "activé ✅" if value else "désactivé ❌"
        await ctx.send(embed=embeds.success(f"Le filtre **{field}** est maintenant {state_text}."))

    # ---------------------------------------------------------------- TOGGLES (10 commandes explicites)

    @commands.hybrid_command(name="antispam", description="Activer/désactiver la protection anti-spam.")
    @app_commands.describe(etat="Activer ou désactiver ce filtre")
    @app_commands.choices(etat=TOGGLE_CHOICES)
    @checks.is_owner_or_admin()
    async def antispam(self, ctx: commands.Context, etat: str):
        await self.toggle(ctx, "antispam", etat)

    @commands.hybrid_command(name="antilink", description="Activer/désactiver le blocage des liens.", with_app_command=False)
    @app_commands.describe(etat="Activer ou désactiver ce filtre")
    @app_commands.choices(etat=TOGGLE_CHOICES)
    @checks.is_owner_or_admin()
    async def antilink(self, ctx: commands.Context, etat: str):
        await self.toggle(ctx, "antilink", etat)

    @commands.hybrid_command(name="antiinvite", description="Activer/désactiver le blocage des invitations Discord.", with_app_command=False)
    @app_commands.describe(etat="Activer ou désactiver ce filtre")
    @app_commands.choices(etat=TOGGLE_CHOICES)
    @checks.is_owner_or_admin()
    async def antiinvite(self, ctx: commands.Context, etat: str):
        await self.toggle(ctx, "antiinvite", etat)

    @commands.hybrid_command(name="antimention", description="Activer/désactiver la protection anti-mention massive.", with_app_command=False)
    @app_commands.describe(etat="Activer ou désactiver ce filtre")
    @app_commands.choices(etat=TOGGLE_CHOICES)
    @checks.is_owner_or_admin()
    async def antimention(self, ctx: commands.Context, etat: str):
        await self.toggle(ctx, "antimention", etat)

    @commands.hybrid_command(name="anticaps", description="Activer/désactiver le filtre anti-majuscules.", with_app_command=False)
    @app_commands.describe(etat="Activer ou désactiver ce filtre")
    @app_commands.choices(etat=TOGGLE_CHOICES)
    @checks.is_owner_or_admin()
    async def anticaps(self, ctx: commands.Context, etat: str):
        await self.toggle(ctx, "anticaps", etat)

    @commands.hybrid_command(name="antiemoji", description="Activer/désactiver le filtre anti-spam d'émojis.", with_app_command=False)
    @app_commands.describe(etat="Activer ou désactiver ce filtre")
    @app_commands.choices(etat=TOGGLE_CHOICES)
    @checks.is_owner_or_admin()
    async def antiemoji(self, ctx: commands.Context, etat: str):
        await self.toggle(ctx, "antiemoji", etat)

    @commands.hybrid_command(name="antiraid", description="Activer/désactiver la protection anti-raid.", with_app_command=False)
    @app_commands.describe(etat="Activer ou désactiver ce filtre")
    @app_commands.choices(etat=TOGGLE_CHOICES)
    @checks.is_owner_or_admin()
    async def antiraid(self, ctx: commands.Context, etat: str):
        await self.toggle(ctx, "antiraid", etat)

    @commands.hybrid_command(name="antibot", description="Activer/désactiver le blocage automatique des bots non autorisés.", with_app_command=False)
    @app_commands.describe(etat="Activer ou désactiver ce filtre")
    @app_commands.choices(etat=TOGGLE_CHOICES)
    @checks.is_owner_or_admin()
    async def antibot(self, ctx: commands.Context, etat: str):
        await self.toggle(ctx, "antibot", etat)

    @commands.hybrid_command(name="antiaccount", description="Activer/désactiver le filtre anti-comptes récents.", with_app_command=False)
    @app_commands.describe(etat="Activer ou désactiver ce filtre")
    @app_commands.choices(etat=TOGGLE_CHOICES)
    @checks.is_owner_or_admin()
    async def antiaccount(self, ctx: commands.Context, etat: str):
        await self.toggle(ctx, "antiaccount", etat)

    @commands.hybrid_command(name="antiscam", description="Activer/désactiver la détection de liens/messages d'arnaque.", with_app_command=False)
    @app_commands.describe(etat="Activer ou désactiver ce filtre")
    @app_commands.choices(etat=TOGGLE_CHOICES)
    @checks.is_owner_or_admin()
    async def antiscam(self, ctx: commands.Context, etat: str):
        await self.toggle(ctx, "antiscam", etat)

    @commands.hybrid_command(name="automod-status", description="Afficher l'état de tous les filtres automod.")
    async def automod_status(self, ctx: commands.Context):
        conf = await self.bot.db.get_automod(ctx.guild.id)
        e = embeds.neutral("🛡️ État de l'AutoMod")
        for field in TOGGLE_FIELDS:
            value = conf[field] if conf else 0
            e.add_field(name=field, value="✅ Activé" if value else "❌ Désactivé", inline=True)
        await ctx.send(embed=e)

    @commands.hybrid_command(name="security-level", description="Définir le niveau de sécurité global du serveur.")
    @app_commands.describe(niveau="Niveau de sécurité")
    @app_commands.choices(niveau=[
        app_commands.Choice(name="Faible", value="faible"),
        app_commands.Choice(name="Moyen", value="moyen"),
        app_commands.Choice(name="Élevé", value="eleve"),
    ])
    @checks.is_owner_or_admin()
    async def security_level(self, ctx: commands.Context, niveau: str):
        await self.bot.db.set_guild_config(ctx.guild.id, "security_level", niveau)
        presets = {
            "faible": {"antispam": 0, "antilink": 0, "antiinvite": 0, "antiraid": 0, "antiscam": 1},
            "moyen": {"antispam": 1, "antilink": 0, "antiinvite": 1, "antiraid": 1, "antiscam": 1},
            "eleve": {"antispam": 1, "antilink": 1, "antiinvite": 1, "antiraid": 1, "antiscam": 1, "antimention": 1, "antiaccount": 1},
        }
        for field, value in presets.get(niveau, {}).items():
            await self.bot.db.set_automod(ctx.guild.id, field, value)
        await ctx.send(embed=embeds.success(f"Niveau de sécurité réglé sur **{niveau}**. Les filtres associés ont été ajustés."))

    # ---------------------------------------------------------------- BLACKLIST MOTS

    @commands.hybrid_command(name="blacklist-add", description="Ajouter un mot à la liste noire.")
    @app_commands.describe(mot="Le mot ou l'expression à interdire")
    @checks.is_owner_or_admin()
    async def blacklist_add(self, ctx: commands.Context, *, mot: str):
        await self.bot.db.execute(
            "INSERT INTO blacklist_words (guild_id, word) VALUES (?, ?)", (ctx.guild.id, mot.lower())
        )
        await ctx.send(embed=embeds.success(f"Le mot `{mot}` a été ajouté à la liste noire."))

    @commands.hybrid_command(name="blacklist-remove", description="Retirer un mot de la liste noire.", with_app_command=False)
    @app_commands.describe(mot="Le mot à retirer")
    @checks.is_owner_or_admin()
    async def blacklist_remove(self, ctx: commands.Context, *, mot: str):
        await self.bot.db.execute(
            "DELETE FROM blacklist_words WHERE guild_id = ? AND word = ?", (ctx.guild.id, mot.lower())
        )
        await ctx.send(embed=embeds.success(f"Le mot `{mot}` a été retiré de la liste noire."))

    @commands.hybrid_command(name="blacklist-list", description="Afficher la liste des mots interdits.")
    @checks.is_owner_or_admin()
    async def blacklist_list(self, ctx: commands.Context):
        rows = await self.bot.db.fetchall("SELECT word FROM blacklist_words WHERE guild_id = ?", (ctx.guild.id,))
        if not rows:
            return await ctx.send(embed=embeds.info("Aucun mot interdit configuré."))
        words = ", ".join(f"`{r['word']}`" for r in rows)
        await ctx.send(embed=embeds.neutral("🚫 Mots interdits", words))

    # ---------------------------------------------------------------- BLACKLIST UTILISATEURS

    @commands.hybrid_command(name="blacklist-user", description="Ajouter un utilisateur à la liste noire du serveur.", with_app_command=False)
    @app_commands.describe(membre="Le membre à mettre en liste noire", raison="La raison")
    @checks.is_owner_or_admin()
    async def blacklist_user(self, ctx: commands.Context, membre: discord.Member, *, raison: str = "Aucune raison fournie"):
        err = checks.check_hierarchy(ctx.author, membre)
        if err:
            return await ctx.send(embed=embeds.error(err))
        await self.bot.db.execute(
            "INSERT OR REPLACE INTO blacklist_users (guild_id, user_id, reason) VALUES (?, ?, ?)",
            (ctx.guild.id, membre.id, raison),
        )
        await ctx.send(embed=embeds.success(f"{membre.mention} a été ajouté à la liste noire.\nRaison : {raison}"))

    @commands.hybrid_command(name="unblacklist-user", description="Retirer un utilisateur de la liste noire.", with_app_command=False)
    @app_commands.describe(membre="Le membre à retirer de la liste noire")
    @checks.is_owner_or_admin()
    async def unblacklist_user(self, ctx: commands.Context, membre: discord.Member):
        await self.bot.db.execute(
            "DELETE FROM blacklist_users WHERE guild_id = ? AND user_id = ?", (ctx.guild.id, membre.id)
        )
        await ctx.send(embed=embeds.success(f"{membre.mention} a été retiré de la liste noire."))

    @commands.hybrid_command(name="blacklist-users", description="Afficher tous les utilisateurs en liste noire.", with_app_command=False)
    @checks.is_owner_or_admin()
    async def blacklist_users(self, ctx: commands.Context):
        rows = await self.bot.db.fetchall("SELECT * FROM blacklist_users WHERE guild_id = ?", (ctx.guild.id,))
        if not rows:
            return await ctx.send(embed=embeds.info("Aucun utilisateur en liste noire."))
        e = embeds.neutral("🚫 Utilisateurs en liste noire")
        for row in rows[:20]:
            e.add_field(name=f"ID: {row['user_id']}", value=row["reason"] or "Aucune raison", inline=False)
        await ctx.send(embed=e)

    # ---------------------------------------------------------------- WHITELIST DOMAINES

    @commands.hybrid_command(name="whitelist-domain", description="Autoriser un nom de domaine malgré l'antilink.", with_app_command=False)
    @app_commands.describe(domaine="Le domaine à autoriser (ex: youtube.com)")
    @checks.is_owner_or_admin()
    async def whitelist_domain(self, ctx: commands.Context, domaine: str):
        await self.bot.db.execute(
            "INSERT OR IGNORE INTO whitelist_domains (guild_id, domain) VALUES (?, ?)",
            (ctx.guild.id, domaine.lower()),
        )
        await ctx.send(embed=embeds.success(f"Le domaine `{domaine}` est maintenant autorisé."))

    @commands.hybrid_command(name="unwhitelist-domain", description="Retirer un domaine de la liste blanche.", with_app_command=False)
    @app_commands.describe(domaine="Le domaine à retirer")
    @checks.is_owner_or_admin()
    async def unwhitelist_domain(self, ctx: commands.Context, domaine: str):
        await self.bot.db.execute(
            "DELETE FROM whitelist_domains WHERE guild_id = ? AND domain = ?", (ctx.guild.id, domaine.lower())
        )
        await ctx.send(embed=embeds.success(f"Le domaine `{domaine}` a été retiré de la liste blanche."))

    # ---------------------------------------------------------------- ÉCOUTEURS

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        if isinstance(message.author, discord.Member) and message.author.guild_permissions.administrator:
            return

        conf = await self.bot.db.get_automod(message.guild.id)
        if not conf:
            return

        blacklisted = await self.bot.db.fetchone(
            "SELECT 1 FROM blacklist_users WHERE guild_id = ? AND user_id = ?",
            (message.guild.id, message.author.id),
        )
        if blacklisted:
            try:
                await message.delete()
            except discord.HTTPException:
                pass
            return

        content_lower = message.content.lower()

        words = await self.bot.db.fetchall("SELECT word FROM blacklist_words WHERE guild_id = ?", (message.guild.id,))
        for row in words:
            if row["word"] in content_lower:
                return await self._delete_and_warn(message, "Mot interdit détecté.")

        if conf["antiscam"] and any(k in content_lower for k in SCAM_KEYWORDS):
            return await self._delete_and_warn(message, "Message d'arnaque potentiel détecté.")

        if conf["antiinvite"] and INVITE_RE.search(message.content):
            return await self._delete_and_warn(message, "Lien d'invitation Discord non autorisé.")

        if conf["antilink"] and LINK_RE.search(message.content):
            whitelisted_domains = await self.bot.db.fetchall(
                "SELECT domain FROM whitelist_domains WHERE guild_id = ?", (message.guild.id,)
            )
            allowed = [d["domain"] for d in whitelisted_domains]
            if not any(domain in content_lower for domain in allowed):
                return await self._delete_and_warn(message, "Lien non autorisé.")

        if conf["antimention"] and len(message.mentions) >= 5:
            return await self._delete_and_warn(message, "Mention massive détectée.")

        if conf["anticaps"] and len(message.content) >= 10:
            letters = [c for c in message.content if c.isalpha()]
            if letters and sum(1 for c in letters if c.isupper()) / len(letters) > 0.7:
                return await self._delete_and_warn(message, "Trop de majuscules (SPAM CAPS).")

        if conf["antiemoji"]:
            emoji_count = len(re.findall(r"<a?:\w+:\d+>|[\U0001F300-\U0001FAFF]", message.content))
            if emoji_count > 10:
                return await self._delete_and_warn(message, "Spam d'émojis détecté.")

        if conf["antispam"]:
            key = (message.guild.id, message.author.id)
            timestamps = self.spam_tracker.setdefault(key, [])
            t = time.time()
            timestamps.append(t)
            self.spam_tracker[key] = [x for x in timestamps if t - x < 6]
            if len(self.spam_tracker[key]) >= 5:
                self.spam_tracker[key] = []
                return await self._delete_and_warn(message, "Spam de messages détecté.")

    async def _delete_and_warn(self, message: discord.Message, reason: str):
        try:
            await message.delete()
        except discord.HTTPException:
            pass
        try:
            note = await message.channel.send(
                embed=embeds.warning(f"{message.author.mention}, votre message a été supprimé.\nRaison : {reason}")
            )
            await note.delete(delay=6)
        except discord.HTTPException:
            pass
        e = embeds.neutral("🛡️ Action AutoMod", f"**Membre :** {message.author.mention}\n**Raison :** {reason}\n**Salon :** {message.channel.mention}")
        await self.log_action(message.guild, e)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        conf = await self.bot.db.get_automod(member.guild.id)
        if not conf:
            return

        if conf["antibot"] and member.bot:
            try:
                await member.kick(reason="AutoMod : bot non autorisé")
                e = embeds.neutral("🛡️ AutoMod - Antibot", f"Le bot {member.mention} a été expulsé automatiquement.")
                await self.log_action(member.guild, e)
            except discord.HTTPException:
                pass
            return

        if conf["antiaccount"]:
            account_age = (discord.utils.utcnow() - member.created_at).days
            if account_age < 7:
                try:
                    await member.kick(reason="AutoMod : compte créé il y a moins de 7 jours")
                    e = embeds.neutral("🛡️ AutoMod - Antiaccount", f"{member.mention} a été expulsé (compte trop récent : {account_age} jour(s)).")
                    await self.log_action(member.guild, e)
                except discord.HTTPException:
                    pass
                return

        if conf["antiraid"]:
            joins = self.join_tracker.setdefault(member.guild.id, [])
            t = time.time()
            joins.append(t)
            self.join_tracker[member.guild.id] = [x for x in joins if t - x < 10]
            if len(self.join_tracker[member.guild.id]) >= 8:
                e = embeds.warning("🚨 Raid potentiel détecté ! Un afflux massif de nouveaux membres a été observé. Vérifiez les nouveaux arrivants.")
                await self.log_action(member.guild, e)


async def setup(bot: commands.Bot):
    await bot.add_cog(AutoMod(bot))
