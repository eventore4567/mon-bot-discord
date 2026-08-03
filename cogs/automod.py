"""
Cog SÉCURITÉ ET AUTOMOD.
/blacklist-add /blacklist-remove /blacklist-list /blacklist-user /unblacklist-user
/blacklist-users /antispam /antilink /antiinvite /antimention /anticaps /antiemoji
/antiraid /antibot /antiaccount /antiscam /antinuke /automod-status /whitelist-domain
/unwhitelist-domain /security-level /antinuke-whitelist-add /antinuke-whitelist-remove
/antinuke-whitelist-list /lockdown-server /unlock-server

Un seul écouteur on_message applique tous les filtres actifs.
Aucune adresse IP n'est collectée : seuls les identifiants Discord sont utilisés.

L'anti-nuke (/antinuke) protège contre un compte compromis (staff ou même le bot)
qui tenterait de détruire le serveur : suppression massive de salons/rôles ou
bannissements en rafale. Si le seuil est dépassé, le responsable est immédiatement
privé de ses rôles dangereux et expulsé, et le propriétaire du serveur est alerté.
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
    "antiemoji", "antiraid", "antibot", "antiaccount", "antiscam", "antinuke",
]

TOGGLE_CHOICES = [
    app_commands.Choice(name="Activer", value="on"),
    app_commands.Choice(name="Désactiver", value="off"),
]

DANGEROUS_PERMS = ["administrator", "manage_guild", "manage_roles", "manage_channels", "ban_members", "kick_members"]
NUKE_ACTION_WINDOW = 30  # secondes
NUKE_ACTION_THRESHOLD = 3  # actions destructrices avant déclenchement


class AutoMod(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.spam_tracker: dict[tuple[int, int], list[float]] = {}
        self.join_tracker: dict[int, list[float]] = {}
        self.nuke_tracker: dict[tuple[int, int], list[float]] = {}
        # Caches mémoire : évitent des allers-retours en base de données à CHAQUE
        # message (ce qui ralentissait le bot sur un salon actif). Invalidés dès
        # qu'une commande change un réglage.
        self.automod_cache: dict[int, dict] = {}
        self.blacklist_words_cache: dict[int, list[str]] = {}
        self.blacklist_users_cache: dict[int, set[int]] = {}
        self.whitelist_domains_cache: dict[int, list[str]] = {}

    async def log_action(self, guild: discord.Guild, embed: discord.Embed):
        conf = await self.bot.db.get_guild_config(guild.id)
        if conf and conf["log_channel"]:
            channel = guild.get_channel(conf["log_channel"])
            if channel:
                try:
                    await channel.send(embed=embed)
                except discord.HTTPException:
                    pass

    # ---------------------------------------------------------------- CACHES

    async def get_automod_cached(self, guild_id: int) -> dict:
        if guild_id not in self.automod_cache:
            conf = await self.bot.db.get_automod(guild_id)
            self.automod_cache[guild_id] = dict(conf) if conf else {}
        return self.automod_cache[guild_id]

    async def get_blacklist_words_cached(self, guild_id: int) -> list[str]:
        if guild_id not in self.blacklist_words_cache:
            rows = await self.bot.db.fetchall("SELECT word FROM blacklist_words WHERE guild_id = ?", (guild_id,))
            self.blacklist_words_cache[guild_id] = [r["word"] for r in rows]
        return self.blacklist_words_cache[guild_id]

    async def get_blacklist_users_cached(self, guild_id: int) -> set:
        if guild_id not in self.blacklist_users_cache:
            rows = await self.bot.db.fetchall("SELECT user_id FROM blacklist_users WHERE guild_id = ?", (guild_id,))
            self.blacklist_users_cache[guild_id] = {r["user_id"] for r in rows}
        return self.blacklist_users_cache[guild_id]

    async def get_whitelist_domains_cached(self, guild_id: int) -> list[str]:
        if guild_id not in self.whitelist_domains_cache:
            rows = await self.bot.db.fetchall("SELECT domain FROM whitelist_domains WHERE guild_id = ?", (guild_id,))
            self.whitelist_domains_cache[guild_id] = [r["domain"] for r in rows]
        return self.whitelist_domains_cache[guild_id]

    async def toggle(self, ctx: commands.Context, field: str, etat: str):
        value = 1 if etat == "on" else 0
        await self.bot.db.set_automod(ctx.guild.id, field, value)
        self.automod_cache.pop(ctx.guild.id, None)
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

    @commands.hybrid_command(name="antinuke", description="Activer/désactiver la protection anti-nuke (compte compromis).")
    @app_commands.describe(etat="Activer ou désactiver cette protection")
    @app_commands.choices(etat=TOGGLE_CHOICES)
    @checks.is_owner_or_admin()
    async def antinuke(self, ctx: commands.Context, etat: str):
        await self.toggle(ctx, "antinuke", etat)

    @commands.hybrid_command(name="antinuke-whitelist-add", description="Exempter un membre de confiance de l'anti-nuke.", with_app_command=False)
    @app_commands.describe(membre="Le membre à exempter")
    @checks.is_owner_or_admin()
    async def antinuke_whitelist_add(self, ctx: commands.Context, membre: discord.Member):
        await self.bot.db.execute(
            "INSERT OR IGNORE INTO antinuke_whitelist (guild_id, user_id) VALUES (?, ?)", (ctx.guild.id, membre.id)
        )
        await ctx.send(embed=embeds.success(f"{membre.mention} est maintenant exempté de l'anti-nuke."))

    @commands.hybrid_command(name="antinuke-whitelist-remove", description="Retirer un membre de la liste blanche anti-nuke.", with_app_command=False)
    @app_commands.describe(membre="Le membre à retirer")
    @checks.is_owner_or_admin()
    async def antinuke_whitelist_remove(self, ctx: commands.Context, membre: discord.Member):
        await self.bot.db.execute(
            "DELETE FROM antinuke_whitelist WHERE guild_id = ? AND user_id = ?", (ctx.guild.id, membre.id)
        )
        await ctx.send(embed=embeds.success(f"{membre.mention} a été retiré de la liste blanche anti-nuke."))

    @commands.hybrid_command(name="antinuke-whitelist-list", description="Afficher les membres exemptés de l'anti-nuke.", with_app_command=False)
    @checks.is_owner_or_admin()
    async def antinuke_whitelist_list(self, ctx: commands.Context):
        rows = await self.bot.db.fetchall("SELECT * FROM antinuke_whitelist WHERE guild_id = ?", (ctx.guild.id,))
        if not rows:
            return await ctx.send(embed=embeds.info("Aucun membre exempté (seul le propriétaire du serveur est protégé par défaut)."))
        lines = [f"<@{r['user_id']}>" for r in rows]
        await ctx.send(embed=embeds.neutral("🛡️ Liste blanche anti-nuke", "\n".join(lines)))

    @commands.hybrid_command(name="lockdown-server", description="[Sécurité] Verrouiller tous les salons textuels du serveur.")
    @checks.is_owner_or_admin()
    async def lockdown_server(self, ctx: commands.Context):
        await ctx.send(embed=embeds.warning("🔒 Verrouillage de tous les salons en cours, merci de patienter..."))
        count = 0
        for channel in ctx.guild.text_channels:
            try:
                await channel.set_permissions(
                    ctx.guild.default_role, send_messages=False, reason=f"Verrouillage du serveur par {ctx.author}"
                )
                count += 1
            except discord.Forbidden:
                pass
        e = embeds.error(f"🔒 Serveur verrouillé par {ctx.author.mention} ({count} salon(s)).")
        await self.log_action(ctx.guild, e)
        await ctx.send(embed=embeds.success(f"🔒 {count} salon(s) verrouillé(s). Utilisez `/unlock-server` pour déverrouiller."))

    @commands.hybrid_command(name="unlock-server", description="[Sécurité] Déverrouiller tous les salons textuels du serveur.")
    @checks.is_owner_or_admin()
    async def unlock_server(self, ctx: commands.Context):
        await ctx.send(embed=embeds.info("🔓 Déverrouillage en cours, merci de patienter..."))
        count = 0
        for channel in ctx.guild.text_channels:
            try:
                await channel.set_permissions(
                    ctx.guild.default_role, send_messages=None, reason=f"Déverrouillage du serveur par {ctx.author}"
                )
                count += 1
            except discord.Forbidden:
                pass
        e = embeds.success(f"🔓 Serveur déverrouillé par {ctx.author.mention} ({count} salon(s)).")
        await self.log_action(ctx.guild, e)
        await ctx.send(embed=embeds.success(f"🔓 {count} salon(s) déverrouillé(s)."))

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
            "faible": {"antispam": 0, "antilink": 0, "antiinvite": 0, "antiraid": 0, "antiscam": 1, "antinuke": 1},
            "moyen": {"antispam": 1, "antilink": 0, "antiinvite": 1, "antiraid": 1, "antiscam": 1, "antinuke": 1},
            "eleve": {
                "antispam": 1, "antilink": 1, "antiinvite": 1, "antiraid": 1, "antiscam": 1,
                "antimention": 1, "antiaccount": 1, "antinuke": 1,
            },
        }
        for field, value in presets.get(niveau, {}).items():
            await self.bot.db.set_automod(ctx.guild.id, field, value)
        self.automod_cache.pop(ctx.guild.id, None)
        await ctx.send(embed=embeds.success(f"Niveau de sécurité réglé sur **{niveau}**. Les filtres associés ont été ajustés."))

    # ---------------------------------------------------------------- BLACKLIST MOTS

    @commands.hybrid_command(name="blacklist-add", description="Ajouter un mot à la liste noire.")
    @app_commands.describe(mot="Le mot ou l'expression à interdire")
    @checks.is_owner_or_admin()
    async def blacklist_add(self, ctx: commands.Context, *, mot: str):
        await self.bot.db.execute(
            "INSERT INTO blacklist_words (guild_id, word) VALUES (?, ?)", (ctx.guild.id, mot.lower())
        )
        self.blacklist_words_cache.pop(ctx.guild.id, None)
        await ctx.send(embed=embeds.success(f"Le mot `{mot}` a été ajouté à la liste noire."))

    @commands.hybrid_command(name="blacklist-remove", description="Retirer un mot de la liste noire.", with_app_command=False)
    @app_commands.describe(mot="Le mot à retirer")
    @checks.is_owner_or_admin()
    async def blacklist_remove(self, ctx: commands.Context, *, mot: str):
        await self.bot.db.execute(
            "DELETE FROM blacklist_words WHERE guild_id = ? AND word = ?", (ctx.guild.id, mot.lower())
        )
        self.blacklist_words_cache.pop(ctx.guild.id, None)
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
        self.blacklist_users_cache.pop(ctx.guild.id, None)
        await ctx.send(embed=embeds.success(f"{membre.mention} a été ajouté à la liste noire.\nRaison : {raison}"))

    @commands.hybrid_command(name="unblacklist-user", description="Retirer un utilisateur de la liste noire.", with_app_command=False)
    @app_commands.describe(membre="Le membre à retirer de la liste noire")
    @checks.is_owner_or_admin()
    async def unblacklist_user(self, ctx: commands.Context, membre: discord.Member):
        await self.bot.db.execute(
            "DELETE FROM blacklist_users WHERE guild_id = ? AND user_id = ?", (ctx.guild.id, membre.id)
        )
        self.blacklist_users_cache.pop(ctx.guild.id, None)
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
        self.whitelist_domains_cache.pop(ctx.guild.id, None)
        await ctx.send(embed=embeds.success(f"Le domaine `{domaine}` est maintenant autorisé."))

    @commands.hybrid_command(name="unwhitelist-domain", description="Retirer un domaine de la liste blanche.", with_app_command=False)
    @app_commands.describe(domaine="Le domaine à retirer")
    @checks.is_owner_or_admin()
    async def unwhitelist_domain(self, ctx: commands.Context, domaine: str):
        await self.bot.db.execute(
            "DELETE FROM whitelist_domains WHERE guild_id = ? AND domain = ?", (ctx.guild.id, domaine.lower())
        )
        self.whitelist_domains_cache.pop(ctx.guild.id, None)
        await ctx.send(embed=embeds.success(f"Le domaine `{domaine}` a été retiré de la liste blanche."))

    # ---------------------------------------------------------------- ÉCOUTEURS

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        if isinstance(message.author, discord.Member) and message.author.guild_permissions.administrator:
            return

        conf = await self.get_automod_cached(message.guild.id)
        if not conf:
            return

        blacklisted_users = await self.get_blacklist_users_cached(message.guild.id)
        if message.author.id in blacklisted_users:
            try:
                await message.delete()
            except discord.HTTPException:
                pass
            return

        content_lower = message.content.lower()

        words = await self.get_blacklist_words_cached(message.guild.id)
        for word in words:
            if word in content_lower:
                return await self._delete_and_warn(message, "Mot interdit détecté.")

        if conf["antiscam"] and any(k in content_lower for k in SCAM_KEYWORDS):
            return await self._delete_and_warn(message, "Message d'arnaque potentiel détecté.")

        if conf["antiinvite"] and INVITE_RE.search(message.content):
            return await self._delete_and_warn(message, "Lien d'invitation Discord non autorisé.")

        if conf["antilink"] and LINK_RE.search(message.content):
            allowed = await self.get_whitelist_domains_cached(message.guild.id)
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
        conf = await self.get_automod_cached(member.guild.id)
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
                e = embeds.warning("🚨 Raid potentiel détecté ! Un afflux massif de nouveaux membres a été observé.")
                await self.log_action(member.guild, e)
                # Réponse automatique : relever le niveau de vérification du serveur
                # freine immédiatement les faux comptes fraîchement créés, sans avoir
                # à verrouiller manuellement tous les salons.
                try:
                    if member.guild.verification_level != discord.VerificationLevel.highest:
                        await member.guild.edit(
                            verification_level=discord.VerificationLevel.highest,
                            reason="AutoMod : raid détecté, niveau de vérification relevé automatiquement",
                        )
                        await self.log_action(
                            member.guild,
                            embeds.warning("🔒 Niveau de vérification du serveur relevé automatiquement suite au raid détecté."),
                        )
                except discord.Forbidden:
                    pass
                # Évite de redéclencher la même alerte à chaque nouvel arrivant tant que le raid dure.
                self.join_tracker[member.guild.id] = []

    # ---------------------------------------------------------------- ANTI-NUKE

    async def record_nuke_action(self, guild: discord.Guild, actor_id: int) -> bool:
        """Retourne True si le seuil d'actions destructrices est dépassé pour cet auteur."""
        key = (guild.id, actor_id)
        t = time.time()
        actions = self.nuke_tracker.setdefault(key, [])
        actions.append(t)
        self.nuke_tracker[key] = [x for x in actions if t - x < NUKE_ACTION_WINDOW]
        return len(self.nuke_tracker[key]) >= NUKE_ACTION_THRESHOLD

    async def get_audit_actor(self, guild: discord.Guild, action: discord.AuditLogAction, target_id: int = None):
        """Retrouve l'auteur d'une action récente via les logs d'audit (nécessite la permission adéquate)."""
        try:
            async for entry in guild.audit_logs(limit=5, action=action):
                if (discord.utils.utcnow() - entry.created_at).total_seconds() > 15:
                    continue
                if target_id is None or (entry.target and getattr(entry.target, "id", None) == target_id):
                    return entry.user
        except discord.Forbidden:
            return None
        return None

    async def is_antinuke_exempt(self, guild: discord.Guild, actor: discord.abc.User) -> bool:
        if actor is None or actor.bot:
            return True
        if actor.id == guild.owner_id:
            return True
        row = await self.bot.db.fetchone(
            "SELECT 1 FROM antinuke_whitelist WHERE guild_id = ? AND user_id = ?", (guild.id, actor.id)
        )
        return row is not None

    async def punish_nuker(self, guild: discord.Guild, actor_id: int, reason: str):
        member = guild.get_member(actor_id)
        e = embeds.error(
            f"🚨 **ANTI-NUKE DÉCLENCHÉ**\n**Membre :** <@{actor_id}> (`{actor_id}`)\n**Raison :** {reason}\n"
            f"Ses rôles à risque ont été retirés et il a été expulsé du serveur si possible."
        )
        if member:
            dangerous_roles = [
                r for r in member.roles
                if r != guild.default_role and any(getattr(r.permissions, p, False) for p in DANGEROUS_PERMS)
            ]
            try:
                if dangerous_roles:
                    await member.remove_roles(*dangerous_roles, reason=f"AutoMod anti-nuke : {reason}")
            except discord.Forbidden:
                pass
            try:
                await member.kick(reason=f"AutoMod anti-nuke : {reason}")
            except discord.Forbidden:
                pass
        await self.log_action(guild, e)
        try:
            owner = guild.owner or await guild.fetch_member(guild.owner_id)
            if owner:
                await owner.send(embed=e)
        except (discord.Forbidden, discord.HTTPException, AttributeError):
            pass

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel):
        conf = await self.bot.db.get_automod(channel.guild.id)
        if not conf or not conf["antinuke"]:
            return
        actor = await self.get_audit_actor(channel.guild, discord.AuditLogAction.channel_delete, channel.id)
        if await self.is_antinuke_exempt(channel.guild, actor):
            return
        if await self.record_nuke_action(channel.guild, actor.id):
            await self.punish_nuker(channel.guild, actor.id, "Suppression massive de salons")

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role):
        conf = await self.bot.db.get_automod(role.guild.id)
        if not conf or not conf["antinuke"]:
            return
        actor = await self.get_audit_actor(role.guild, discord.AuditLogAction.role_delete, role.id)
        if await self.is_antinuke_exempt(role.guild, actor):
            return
        if await self.record_nuke_action(role.guild, actor.id):
            await self.punish_nuker(role.guild, actor.id, "Suppression massive de rôles")

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User):
        conf = await self.bot.db.get_automod(guild.id)
        if not conf or not conf["antinuke"]:
            return
        actor = await self.get_audit_actor(guild, discord.AuditLogAction.ban, user.id)
        if await self.is_antinuke_exempt(guild, actor):
            return
        if await self.record_nuke_action(guild, actor.id):
            await self.punish_nuker(guild, actor.id, "Bannissements massifs")


async def setup(bot: commands.Bot):
    await bot.add_cog(AutoMod(bot))
