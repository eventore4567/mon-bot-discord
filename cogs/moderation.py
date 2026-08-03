"""
Cog MODÉRATION.
/ban /tempban /unban /kick /mute /unmute /warn /unwarn /warnings /clearwarnings
/clear /slowmode /lock /unlock /hide /show /nickname /resetnick /move /disconnect

Toutes les commandes existent en slash ET en commande préfixée (+), vérifient les
permissions, respectent la hiérarchie des rôles et journalisent dans le salon de logs.
"""

import discord
from discord import app_commands
from discord.ext import commands, tasks

import config
from utils import embeds, checks, helpers
from database.db import now


class Moderation(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.check_tempactions.start()

    def cog_unload(self):
        self.check_tempactions.cancel()

    @tasks.loop(minutes=1)
    async def check_tempactions(self):
        rows = await self.bot.db.fetchall("SELECT * FROM tempactions WHERE expires_at <= ?", (now(),))
        for row in rows:
            guild = self.bot.get_guild(row["guild_id"])
            if not guild:
                await self.bot.db.execute("DELETE FROM tempactions WHERE id = ?", (row["id"],))
                continue
            if row["action"] == "ban":
                try:
                    await guild.unban(discord.Object(id=row["user_id"]), reason="Fin du bannissement temporaire")
                    e = embeds.log_entry(
                        "⏰ Fin de sanction temporaire", config.COLOR_INFO,
                        extra={"👤 Utilisateur": f"<@{row['user_id']}>\n`ID: {row['user_id']}`", "📄 Détail": "Débanni automatiquement (fin du tempban)"},
                    )
                    await self.log_action(guild, e)
                except discord.HTTPException:
                    pass
            await self.bot.db.execute("DELETE FROM tempactions WHERE id = ?", (row["id"],))

    @check_tempactions.before_loop
    async def before_check_tempactions(self):
        await self.bot.wait_until_ready()

    async def log_action(self, guild: discord.Guild, embed: discord.Embed):
        # Utilise le salon "logs-moderation" dédié s'il existe (via /create-logs), sinon
        # retombe sur le salon de logs général — jamais de log perdu.
        await helpers.send_log(self.bot, guild, "moderation", embed)

    SANCTION_COLORS = {
        "Bannissement": None, "Bannissement temporaire": None, "Expulsion": None,
        "Mute (timeout)": None, "Débannissement": "success", "Unmute": "success", "Avertissement": "warning",
    }

    def sanction_embed(self, action: str, target: discord.abc.User, moderator: discord.abc.User, reason: str, extra: str = "") -> discord.Embed:
        kind = self.SANCTION_COLORS.get(action)
        color = config.COLOR_SUCCESS if kind == "success" else config.COLOR_WARNING if kind == "warning" else config.COLOR_ERROR
        return embeds.log_entry(
            f"🔨 Sanction : {action}",
            color,
            cible=target,
            cible_label="👤 Membre",
            acteur=moderator,
            raison=reason,
            extra={"📌 Détails": extra} if extra else None,
        )

    async def check_targetable(self, ctx: commands.Context, membre: discord.Member) -> bool:
        err = checks.check_hierarchy(ctx.author, membre)
        if err:
            await ctx.send(embed=embeds.error(err))
            return False
        err = checks.check_bot_hierarchy(ctx.guild, membre)
        if err:
            await ctx.send(embed=embeds.error(err))
            return False
        return True

    # ---------------------------------------------------------------- BAN

    @commands.hybrid_command(name="ban", description="Bannir définitivement un membre du serveur.")
    @app_commands.describe(membre="Le membre à bannir", raison="La raison du bannissement")
    @checks.has_permission_or_modrole("ban_members")
    async def ban(self, ctx: commands.Context, membre: discord.Member, *, raison: str = "Aucune raison fournie"):
        if not await self.check_targetable(ctx, membre):
            return
        try:
            await membre.send(embed=embeds.warning(f"Vous avez été **banni** de **{ctx.guild.name}**.\nRaison : {raison}"))
        except discord.Forbidden:
            pass
        await ctx.guild.ban(membre, reason=f"{ctx.author} : {raison}", delete_message_seconds=0)
        e = self.sanction_embed("Bannissement", membre, ctx.author, raison)
        await ctx.send(embed=e)
        await self.log_action(ctx.guild, e)

    @commands.hybrid_command(name="tempban", description="Bannir temporairement un membre (ex: 1h, 2j).", with_app_command=False)
    @app_commands.describe(membre="Le membre à bannir", duree="Durée (ex: 30m, 2h, 1j)", raison="La raison")
    @checks.has_permission_or_modrole("ban_members")
    async def tempban(self, ctx: commands.Context, membre: discord.Member, duree: str, *, raison: str = "Aucune raison fournie"):
        if not await self.check_targetable(ctx, membre):
            return
        seconds = helpers.parse_duration(duree)
        if seconds is None:
            return await ctx.send(embed=embeds.error("Durée invalide. Exemples valides : `30m`, `2h`, `1j`."))
        try:
            await membre.send(embed=embeds.warning(f"Vous avez été **banni temporairement** de **{ctx.guild.name}** pour {helpers.format_duration(seconds)}.\nRaison : {raison}"))
        except discord.Forbidden:
            pass
        await ctx.guild.ban(membre, reason=f"{ctx.author} (temporaire {duree}) : {raison}", delete_message_seconds=0)
        await self.bot.db.execute(
            "INSERT INTO tempactions (guild_id, user_id, action, expires_at) VALUES (?, ?, 'ban', ?)",
            (ctx.guild.id, membre.id, now() + seconds),
        )
        e = self.sanction_embed("Bannissement temporaire", membre, ctx.author, raison, f"Durée : {helpers.format_duration(seconds)}")
        await ctx.send(embed=e)
        await self.log_action(ctx.guild, e)

    @commands.hybrid_command(name="unban", description="Débannir un utilisateur via son identifiant Discord.")
    @app_commands.describe(user_id="L'identifiant Discord de l'utilisateur", raison="La raison")
    @checks.has_permission_or_modrole("ban_members")
    async def unban(self, ctx: commands.Context, user_id: str, *, raison: str = "Aucune raison fournie"):
        try:
            uid = int(user_id)
        except ValueError:
            return await ctx.send(embed=embeds.error("Identifiant Discord invalide."))
        try:
            user = await self.bot.fetch_user(uid)
            await ctx.guild.unban(user, reason=f"{ctx.author} : {raison}")
        except discord.NotFound:
            return await ctx.send(embed=embeds.error("Cet utilisateur n'est pas banni ou n'existe pas."))
        e = self.sanction_embed("Débannissement", user, ctx.author, raison)
        await ctx.send(embed=e)
        await self.log_action(ctx.guild, e)

    # ---------------------------------------------------------------- KICK

    @commands.hybrid_command(name="kick", description="Expulser un membre du serveur.")
    @app_commands.describe(membre="Le membre à expulser", raison="La raison de l'expulsion")
    @checks.has_permission_or_modrole("kick_members")
    async def kick(self, ctx: commands.Context, membre: discord.Member, *, raison: str = "Aucune raison fournie"):
        if not await self.check_targetable(ctx, membre):
            return
        try:
            await membre.send(embed=embeds.warning(f"Vous avez été **expulsé** de **{ctx.guild.name}**.\nRaison : {raison}"))
        except discord.Forbidden:
            pass
        await ctx.guild.kick(membre, reason=f"{ctx.author} : {raison}")
        e = self.sanction_embed("Expulsion", membre, ctx.author, raison)
        await ctx.send(embed=e)
        await self.log_action(ctx.guild, e)

    # ---------------------------------------------------------------- MUTE

    async def get_mute_role(self, guild: discord.Guild) -> discord.Role | None:
        conf = await self.bot.db.get_guild_config(guild.id)
        if conf and conf["mute_role"]:
            role = guild.get_role(conf["mute_role"])
            if role:
                return role
        return discord.utils.get(guild.roles, name="Muet")

    @commands.hybrid_command(name="mute", description="Rendre muet un membre (timeout Discord natif).")
    @app_commands.describe(membre="Le membre à rendre muet", duree="Durée (ex: 10m, 1h)", raison="La raison")
    @checks.has_permission_or_modrole("moderate_members")
    async def mute(self, ctx: commands.Context, membre: discord.Member, duree: str = "10m", *, raison: str = "Aucune raison fournie"):
        if not await self.check_targetable(ctx, membre):
            return
        seconds = helpers.parse_duration(duree)
        if seconds is None or seconds > 2419200:
            return await ctx.send(embed=embeds.error("Durée invalide (maximum 28 jours). Exemple : `10m`, `1h`, `1j`."))
        until = discord.utils.utcnow() + discord.utils.timedelta(seconds=seconds)
        await membre.timeout(until, reason=f"{ctx.author} : {raison}")
        e = self.sanction_embed("Mute (timeout)", membre, ctx.author, raison, f"Durée : {helpers.format_duration(seconds)}")
        await ctx.send(embed=e)
        await self.log_action(ctx.guild, e)

    @commands.hybrid_command(name="unmute", description="Retirer le mute (timeout) d'un membre.", with_app_command=False)
    @app_commands.describe(membre="Le membre à démuter", raison="La raison")
    @checks.has_permission_or_modrole("moderate_members")
    async def unmute(self, ctx: commands.Context, membre: discord.Member, *, raison: str = "Aucune raison fournie"):
        await membre.timeout(None, reason=f"{ctx.author} : {raison}")
        e = self.sanction_embed("Unmute", membre, ctx.author, raison)
        await ctx.send(embed=e)
        await self.log_action(ctx.guild, e)

    # ---------------------------------------------------------------- WARN

    @commands.hybrid_command(name="warn", description="Avertir un membre (enregistré en base de données).")
    @app_commands.describe(membre="Le membre à avertir", raison="La raison de l'avertissement")
    @checks.has_permission_or_modrole("moderate_members")
    async def warn(self, ctx: commands.Context, membre: discord.Member, *, raison: str = "Aucune raison fournie"):
        if not await self.check_targetable(ctx, membre):
            return
        await self.bot.db.execute(
            "INSERT INTO warnings (guild_id, user_id, moderator_id, reason, timestamp) VALUES (?, ?, ?, ?, ?)",
            (ctx.guild.id, membre.id, ctx.author.id, raison, now()),
        )
        rows = await self.bot.db.fetchall(
            "SELECT id FROM warnings WHERE guild_id = ? AND user_id = ?", (ctx.guild.id, membre.id)
        )
        total = len(rows)
        conf = await self.bot.db.get_guild_config(ctx.guild.id)

        # Rôle automatique d'avertissement (/setwarnrole) : ajouté au membre à chaque
        # /warn, tant qu'il ne l'a pas déjà et que le bot a la permission de le faire.
        role_note = ""
        if conf and conf["warn_role"]:
            role = ctx.guild.get_role(conf["warn_role"])
            if role and role not in membre.roles:
                try:
                    await membre.add_roles(role, reason=f"Avertissement par {ctx.author} : {raison}")
                    role_note = f"\nRôle {role.mention} attribué automatiquement."
                except discord.HTTPException:
                    role_note = f"\n⚠️ Impossible d'attribuer le rôle {role.mention} (permissions/hiérarchie)."

        try:
            await membre.send(embed=embeds.warning(f"Vous avez reçu un **avertissement** sur **{ctx.guild.name}**.\nRaison : {raison}"))
        except discord.Forbidden:
            pass
        e = self.sanction_embed("Avertissement", membre, ctx.author, raison, f"Total d'avertissements : {total}{role_note}")
        await ctx.send(embed=e)
        await self.log_action(ctx.guild, e)

        # Bannissement automatique au bout de N avertissements (/setwarnbanthreshold,
        # 3 par défaut, 0 = désactivé). Pas de confirmation demandée : c'est le but de
        # ce seuil, agir automatiquement dès qu'il est atteint.
        threshold = conf["warn_ban_threshold"] if conf and conf["warn_ban_threshold"] else 0
        if threshold and total >= threshold:
            err = checks.check_bot_hierarchy(ctx.guild, membre)
            if err:
                await ctx.send(embed=embeds.warning(
                    f"{membre.mention} a atteint **{total}** avertissements (seuil : {threshold}) mais n'a pas pu "
                    f"être banni automatiquement : {err}"
                ))
                return
            try:
                await membre.send(embed=embeds.warning(
                    f"Vous avez été **banni automatiquement** de **{ctx.guild.name}** pour avoir atteint "
                    f"**{threshold}** avertissements."
                ))
            except discord.Forbidden:
                pass
            try:
                await ctx.guild.ban(
                    membre, reason=f"Ban automatique : {threshold} avertissements atteints", delete_message_seconds=0
                )
            except discord.HTTPException:
                await ctx.send(embed=embeds.error(f"Le bannissement automatique de {membre.mention} a échoué (permissions)."))
                return
            ban_e = self.sanction_embed(
                "Bannissement", membre, self.bot.user, f"Seuil de {threshold} avertissements atteint",
                f"Bannissement automatique — total d'avertissements : {total}",
            )
            ban_e.title = "🚨 Bannissement automatique (seuil d'avertissements)"
            await ctx.send(embed=ban_e)
            await self.log_action(ctx.guild, ban_e)

    @commands.hybrid_command(name="unwarn", description="Supprimer un avertissement précis via son identifiant.", with_app_command=False)
    @app_commands.describe(warn_id="L'identifiant de l'avertissement (voir /warnings)")
    @checks.has_permission_or_modrole("moderate_members")
    async def unwarn(self, ctx: commands.Context, warn_id: int):
        row = await self.bot.db.fetchone(
            "SELECT * FROM warnings WHERE id = ? AND guild_id = ?", (warn_id, ctx.guild.id)
        )
        if not row:
            return await ctx.send(embed=embeds.error("Aucun avertissement trouvé avec cet identifiant."))
        await self.bot.db.execute("DELETE FROM warnings WHERE id = ?", (warn_id,))
        await ctx.send(embed=embeds.success(f"L'avertissement `#{warn_id}` a été supprimé."))

    @commands.hybrid_command(name="warnings", description="Afficher les avertissements d'un membre.")
    @app_commands.describe(membre="Le membre à consulter")
    @checks.has_permission_or_modrole("moderate_members")
    async def warnings_cmd(self, ctx: commands.Context, membre: discord.Member):
        rows = await self.bot.db.fetchall(
            "SELECT * FROM warnings WHERE guild_id = ? AND user_id = ? ORDER BY timestamp DESC",
            (ctx.guild.id, membre.id),
        )
        if not rows:
            return await ctx.send(embed=embeds.info(f"{membre.mention} n'a aucun avertissement."))
        e = embeds.neutral(f"⚠️ Avertissements de {membre.display_name}", f"Total : {len(rows)}")
        for row in rows[:15]:
            mod = ctx.guild.get_member(row["moderator_id"])
            e.add_field(
                name=f"#{row['id']} — <t:{row['timestamp']}:R>",
                value=f"Par {mod.mention if mod else 'Modérateur inconnu'}\n{row['reason']}",
                inline=False,
            )
        await ctx.send(embed=e)

    @commands.hybrid_command(name="clearwarnings", description="Supprimer tous les avertissements d'un membre.", with_app_command=False)
    @app_commands.describe(membre="Le membre concerné")
    @checks.has_permission_or_modrole("moderate_members")
    async def clearwarnings(self, ctx: commands.Context, membre: discord.Member):
        await self.bot.db.execute(
            "DELETE FROM warnings WHERE guild_id = ? AND user_id = ?", (ctx.guild.id, membre.id)
        )
        await ctx.send(embed=embeds.success(f"Tous les avertissements de {membre.mention} ont été supprimés."))

    # ---------------------------------------------------------------- SALON

    @commands.hybrid_command(name="clear", description="Supprimer un nombre de messages dans le salon.")
    @app_commands.describe(nombre="Nombre de messages à supprimer (1-100)")
    @checks.has_permission_or_modrole("manage_messages")
    async def clear(self, ctx: commands.Context, nombre: app_commands.Range[int, 1, 100]):
        await ctx.defer(ephemeral=True) if ctx.interaction else None
        deleted = await ctx.channel.purge(limit=nombre)
        await ctx.send(embed=embeds.success(f"{len(deleted)} message(s) supprimé(s)."), ephemeral=True)

    @commands.hybrid_command(name="slowmode", description="Définir le mode lent du salon (en secondes).", with_app_command=False)
    @app_commands.describe(secondes="Délai entre les messages en secondes (0 pour désactiver)")
    @checks.has_permission_or_modrole("manage_channels")
    async def slowmode(self, ctx: commands.Context, secondes: app_commands.Range[int, 0, 21600]):
        await ctx.channel.edit(slowmode_delay=secondes)
        if secondes == 0:
            await ctx.send(embed=embeds.success("Le mode lent a été désactivé."))
        else:
            await ctx.send(embed=embeds.success(f"Mode lent réglé sur {secondes} seconde(s)."))

    @commands.hybrid_command(name="lock", description="Verrouiller le salon (empêche @everyone d'écrire).", with_app_command=False)
    @checks.has_permission_or_modrole("manage_channels")
    async def lock(self, ctx: commands.Context, raison: str = "Aucune raison fournie"):
        overwrite = ctx.channel.overwrites_for(ctx.guild.default_role)
        overwrite.send_messages = False
        await ctx.channel.set_permissions(ctx.guild.default_role, overwrite=overwrite, reason=raison)
        await ctx.send(embed=embeds.warning(f"🔒 Salon verrouillé.\nRaison : {raison}"))

    @commands.hybrid_command(name="unlock", description="Déverrouiller le salon.", with_app_command=False)
    @checks.has_permission_or_modrole("manage_channels")
    async def unlock(self, ctx: commands.Context):
        overwrite = ctx.channel.overwrites_for(ctx.guild.default_role)
        overwrite.send_messages = None
        await ctx.channel.set_permissions(ctx.guild.default_role, overwrite=overwrite)
        await ctx.send(embed=embeds.success("🔓 Salon déverrouillé."))

    @commands.hybrid_command(name="hide", description="Cacher le salon aux membres (@everyone).", with_app_command=False)
    @checks.has_permission_or_modrole("manage_channels")
    async def hide(self, ctx: commands.Context):
        overwrite = ctx.channel.overwrites_for(ctx.guild.default_role)
        overwrite.view_channel = False
        await ctx.channel.set_permissions(ctx.guild.default_role, overwrite=overwrite)
        await ctx.send(embed=embeds.success("🙈 Salon caché."))

    @commands.hybrid_command(name="show", description="Rendre le salon à nouveau visible.", with_app_command=False)
    @checks.has_permission_or_modrole("manage_channels")
    async def show(self, ctx: commands.Context):
        overwrite = ctx.channel.overwrites_for(ctx.guild.default_role)
        overwrite.view_channel = None
        await ctx.channel.set_permissions(ctx.guild.default_role, overwrite=overwrite)
        await ctx.send(embed=embeds.success("👁️ Salon à nouveau visible."))

    # ---------------------------------------------------------------- DIVERS

    @commands.hybrid_command(name="nickname", description="Changer le pseudo d'un membre.", with_app_command=False)
    @app_commands.describe(membre="Le membre concerné", pseudo="Le nouveau pseudo")
    @checks.has_permission_or_modrole("manage_nicknames")
    async def nickname(self, ctx: commands.Context, membre: discord.Member, *, pseudo: str):
        if not await self.check_targetable(ctx, membre):
            return
        await membre.edit(nick=pseudo[:32])
        await ctx.send(embed=embeds.success(f"Le pseudo de {membre.mention} est maintenant **{pseudo[:32]}**."))

    @commands.hybrid_command(name="resetnick", description="Réinitialiser le pseudo d'un membre.", with_app_command=False)
    @app_commands.describe(membre="Le membre concerné")
    @checks.has_permission_or_modrole("manage_nicknames")
    async def resetnick(self, ctx: commands.Context, membre: discord.Member):
        await membre.edit(nick=None)
        await ctx.send(embed=embeds.success(f"Le pseudo de {membre.mention} a été réinitialisé."))

    @commands.hybrid_command(name="move", description="Déplacer un membre vers un autre salon vocal.", with_app_command=False)
    @app_commands.describe(membre="Le membre à déplacer", salon="Le salon vocal de destination")
    @checks.has_permission_or_modrole("move_members")
    async def move(self, ctx: commands.Context, membre: discord.Member, salon: discord.VoiceChannel):
        if not membre.voice:
            return await ctx.send(embed=embeds.error("Ce membre n'est pas en vocal."))
        await membre.move_to(salon)
        await ctx.send(embed=embeds.success(f"{membre.mention} a été déplacé vers **{salon.name}**."))

    @commands.hybrid_command(name="disconnect", description="Déconnecter un membre du vocal.", with_app_command=False)
    @app_commands.describe(membre="Le membre à déconnecter")
    @checks.has_permission_or_modrole("move_members")
    async def disconnect(self, ctx: commands.Context, membre: discord.Member):
        if not membre.voice:
            return await ctx.send(embed=embeds.error("Ce membre n'est pas en vocal."))
        await membre.move_to(None)
        await ctx.send(embed=embeds.success(f"{membre.mention} a été déconnecté du vocal."))


async def setup(bot: commands.Bot):
    await bot.add_cog(Moderation(bot))
