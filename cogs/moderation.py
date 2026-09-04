"""
Cog MODÉRATION.
/ban /tempban /unban /kick /mute /unmute /warn /unwarn /warnings /clearwarnings
/clear /slowmode /lock /unlock /hide /show /nickname /resetnick /move /disconnect
/case /modhistory

Toutes les commandes existent en slash ET en commande préfixée (+), vérifient les
permissions, respectent la hiérarchie des rôles et journalisent dans le salon de logs.

Refonte visuelle (Phase 3, design premium/sombre) : chaque sanction RÉELLEMENT exécutée
(ban/tempban/unban/kick/mute/unmute/warn, y compris le ban automatique par seuil
d'avertissements) reçoit maintenant un numéro de dossier séquentiel PAR SERVEUR (jamais
partagé entre serveurs, jamais deviné — voir database/db.py::record_sanction()), affiché
sur une "fiche de sanction" façon design_system. /case permet de retrouver une sanction
précise par son numéro, /modhistory affiche l'historique complet d'un membre (tous types
confondus, pas seulement les avertissements comme avec /warnings).
"""

import logging
from datetime import timedelta

import discord
from discord import app_commands
from discord.ext import commands, tasks

import config
from utils import embeds, checks, helpers, design_system
from utils import sentrix_panels as panels
from database.db import now

logger = logging.getLogger("bot.moderation")


class Moderation(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.check_tempactions.start()

    def cog_unload(self):
        self.check_tempactions.cancel()

    @tasks.loop(minutes=1)
    async def check_tempactions(self):
        """Lève les sanctions temporaires échues.

        Toute exception qui sortait d'ici TERMINAIT la tâche : discord.py n'en
        relance que les erreurs réseau de sa liste de reconnexion, et le
        watchdog Mastery était incapable de ressusciter une boucle terminée.
        Un seul incident figeait donc l'expiration des tempbans jusqu'au
        prochain déploiement. Chaque étape est désormais isolée.
        """
        try:
            rows = await self.bot.db.fetchall("SELECT * FROM tempactions WHERE expires_at <= ?", (now(),))
        except Exception:
            logger.exception("Lecture des sanctions temporaires impossible ; nouvel essai dans une minute.")
            return

        for row in rows:
            try:
                consommer = await self._expirer_tempaction(row)
            except Exception:
                # Une ligne défectueuse ne doit jamais emporter la boucle entière —
                # ni être consommée : on la rejouera au tour suivant.
                logger.exception("Expiration de la sanction temporaire #%s impossible.", row["id"])
                continue

            if not consommer:
                # Discord n'a PAS confirmé la levée : garder la ligne est la seule
                # chose qui garantisse un nouvel essai. La supprimer laisserait un
                # bannissement « temporaire » devenir définitif en silence.
                continue

            try:
                await self.bot.db.execute("DELETE FROM tempactions WHERE id = ?", (row["id"],))
            except Exception:
                logger.exception("Suppression de la sanction temporaire #%s impossible.", row["id"])

    async def _expirer_tempaction(self, row) -> bool:
        """Lève UNE sanction échue.

        Retourne True si la ligne peut être supprimée, False s'il faut la rejouer.

        Ce booléen est tout l'enjeu : la ligne était auparavant supprimée dans un
        ``finally``, donc même quand Discord refusait le débannissement. Une simple
        HTTPException passagère laissait le membre banni ET effaçait la seule trace
        qui aurait permis de réessayer — le bannissement temporaire devenait
        définitif sans que rien ne le signale.

        Après un débannissement réussi, un échec de journalisation remonte à
        l'appelant, qui garde la ligne : le tour suivant retombera sur NotFound et
        la consommera. Réessayer est donc toujours sans danger.
        """
        guild = self.bot.get_guild(row["guild_id"])
        if not guild or row["action"] != "ban":
            return True  # rien à lever ici : la ligne n'a plus d'objet

        try:
            await guild.unban(discord.Object(id=row["user_id"]), reason="Fin du bannissement temporaire")
        except discord.NotFound:
            # Discord confirme qu'il n'y a plus de bannissement : la sanction EST
            # levée (débannissement manuel, par exemple). Rien à annoncer.
            return True
        except discord.HTTPException as exc:
            # Couvre aussi Forbidden, qui en hérite : permission retirée, panne
            # passagère, rate limit. Dans tous ces cas la levée n'est PAS acquise.
            logger.warning(
                "Débannissement automatique refusé par Discord (serveur %s, membre %s) : %r ; "
                "la sanction est conservée et sera réessayée.",
                row["guild_id"],
                row["user_id"],
                exc,
            )
            return False

        case_number = await self.bot.db.record_sanction(
            guild.id, row["user_id"], self.bot.user.id, "unban", "Fin du bannissement temporaire (automatique)"
        )
        e = design_system.create_embed(
            title=f"⏰ Dossier #{case_number} — Fin de sanction temporaire",
            colour=config.COLOR_INFO,
            footer="SentriX",
        )
        e.add_field(name="👤 Utilisateur", value=f"<@{row['user_id']}>\n`ID: {row['user_id']}`", inline=False)
        e.add_field(name="📄 Détail", value="Débanni automatiquement (fin du tempban)", inline=False)
        await self.log_action(guild, e)
        return True

    @check_tempactions.before_loop
    async def before_check_tempactions(self):
        await self.bot.wait_until_ready()

    @check_tempactions.error
    async def check_tempactions_error(self, error: BaseException) -> None:
        """Dernier filet, indépendant du watchdog Mastery (qui peut ne pas être chargé)."""
        logger.error("Boucle check_tempactions interrompue (%r) ; relance immédiate.", error)
        self.check_tempactions.restart()

    async def log_action(self, guild: discord.Guild, embed: discord.Embed):
        # Utilise le salon "logs-moderation" dédié s'il existe (via /create-logs), sinon
        # retombe sur le salon de logs général — jamais de log perdu.
        await helpers.send_log(self.bot, guild, "moderation", embed)

    # "kind" détermine seulement la couleur de la fiche (succès/avertissement/danger) —
    # l'action elle-même (ce qui a réellement été fait) reste toujours le texte exact.
    SANCTION_KIND = {
        "ban": "danger", "tempban": "danger", "kick": "danger", "mute": "warning",
        "warn": "warning", "unban": "success", "unmute": "success",
    }
    SANCTION_LABELS = {
        "ban": "🔨 Bannissement", "tempban": "🔨 Bannissement temporaire", "kick": "👢 Expulsion",
        "mute": "🔇 Mute (timeout)", "warn": "⚠️ Avertissement", "unban": "🔓 Débannissement",
        "unmute": "🔊 Unmute",
    }

    DM_ACTION_LABELS = {
        "ban": "bannissement",
        "tempban": "bannissement temporaire",
        "kick": "expulsion",
        "mute": "mute",
        "warn": "avertissement",
        "unban": "débannissement",
        "unmute": "retrait du mute",
    }
    DM_ACTION_ALIASES = {
        "banni": "ban",
        "bannissement": "ban",
        "temp-ban": "tempban",
        "expulsion": "kick",
        "timeout": "mute",
        "avertissement": "warn",
        "demute": "unmute",
        "démute": "unmute",
        "deban": "unban",
        "déban": "unban",
    }
    DEFAULT_DM_TEMPLATES = {
        "ban": "Vous avez été banni de {serveur}.\nRaison : {raison}",
        "tempban": "Vous avez été banni temporairement de {serveur} pendant {duree}.\nRaison : {raison}",
        "kick": "Vous avez été expulsé de {serveur}.\nRaison : {raison}",
        "mute": "Vous avez été rendu muet sur {serveur} pendant {duree}.\nRaison : {raison}",
        "warn": "Vous avez reçu un avertissement sur {serveur}.\nRaison : {raison}",
        "unban": "Votre bannissement de {serveur} a été retiré.\nRaison : {raison}",
        "unmute": "Votre mute sur {serveur} a été retiré.\nRaison : {raison}",
    }

    async def log_sanction(
        self, ctx: commands.Context, action: str, target: discord.abc.User, reason: str,
        duration_seconds: int | None = None, extra_fields: dict | None = None,
    ) -> discord.Embed:
        """Point de passage UNIQUE pour toute sanction réelle : enregistre le dossier en
        base (numéro de dossier séquentiel réel), construit la fiche visuelle, l'envoie
        dans le salon de logs, et retourne l'embed pour l'affichage dans le salon courant."""
        case_number = await self.bot.db.record_sanction(
            ctx.guild.id, target.id, ctx.author.id, action, reason, duration_seconds
        )
        kind = self.SANCTION_KIND.get(action, "danger")
        colour = {"success": config.COLOR_SUCCESS, "warning": config.COLOR_WARNING, "danger": config.COLOR_ERROR}[kind]
        label = self.SANCTION_LABELS.get(action, action)
        style = design_system.CATEGORY_STYLES["moderation"]
        e = design_system.create_embed(
            title=f"{style['emoji']} Dossier #{case_number} — {label}",
            colour=colour,
            thumbnail=target.display_avatar.url if hasattr(target, "display_avatar") else None,
            footer="SentriX",
        )
        e.add_field(name="👤 Membre", value=f"{getattr(target, 'mention', target)}\n`ID: {target.id}`", inline=True)
        e.add_field(name="🛡️ Modérateur", value=f"{ctx.author.mention}\n`ID: {ctx.author.id}`", inline=True)
        total = await self.bot.db.get_sanction_count(ctx.guild.id, target.id)
        e.add_field(name="📁 Historique", value=f"{total} sanction(s) au total pour ce membre", inline=True)
        if duration_seconds:
            e.add_field(name="⏱️ Durée", value=helpers.format_duration(duration_seconds), inline=True)
        e.add_field(name="📝 Raison", value=reason or "Aucune raison fournie", inline=False)
        for name, value in (extra_fields or {}).items():
            e.add_field(name=name, value=value, inline=False)
        await self.log_action(ctx.guild, e)
        return e

    async def _ack(self, ctx: commands.Context):
        """Accuse réception IMMÉDIATEMENT, avant tout appel API/DB. Corrige la lenteur
        perçue du système de modération : chaque sanction enchaîne plusieurs appels
        séquentiels (DM au membre, action Discord, écriture en base du dossier, envoi
        du log, PUIS seulement la réponse) — sans accusé de réception immédiat, une
        commande slash dépasse facilement les 3 secondes de Discord et affiche
        « L'application ne répond plus », et une commande texte ne donne aucun signe
        de vie pendant tout ce temps. Pour une interaction, on defer() tout de suite
        (le petit indicateur "réflexion en cours" apparaît instantanément) ; pour une
        commande texte, on affiche l'indicateur de frappe."""
        if ctx.interaction:
            if not ctx.interaction.response.is_done():
                await ctx.interaction.response.defer()
        else:
            await ctx.typing()

    @classmethod
    def _normalise_dm_action(cls, action: str) -> str | None:
        value = action.casefold().strip()
        value = cls.DM_ACTION_ALIASES.get(value, value)
        return value if value in cls.DEFAULT_DM_TEMPLATES else None

    async def _get_sanction_dm_template(self, guild_id: int, action: str) -> str | None:
        row = await self.bot.db.fetchone(
            "SELECT message, enabled FROM sanction_dm_templates WHERE guild_id = ? AND action = ?",
            (guild_id, action),
        )
        if row is None:
            return self.DEFAULT_DM_TEMPLATES[action]
        if not row["enabled"]:
            return None
        return row["message"]

    async def _send_sanction_dm(
        self,
        ctx: commands.Context,
        target: discord.abc.User,
        action: str,
        reason: str,
        duration_seconds: int | None = None,
    ) -> bool:
        """Envoyer le MP configuré. Un MP fermé ne bloque jamais la sanction."""
        template = await self._get_sanction_dm_template(ctx.guild.id, action)
        if template is None:
            return False
        values = {
            "membre": getattr(target, "display_name", str(target)),
            "serveur": ctx.guild.name,
            "raison": reason or "Aucune raison fournie",
            "duree": helpers.format_duration(duration_seconds) if duration_seconds else "Non précisée",
            "moderateur": getattr(ctx.author, "display_name", str(ctx.author)),
            "action": self.DM_ACTION_LABELS[action],
        }
        message = template
        for key, value in values.items():
            message = message.replace("{" + key + "}", str(value))
        try:
            await target.send(message[:1900], allowed_mentions=discord.AllowedMentions.none())
            return True
        except discord.HTTPException:
            return False

    async def _show_sanction_dm_status(self, ctx: commands.Context):
        rows = await self.bot.db.fetchall(
            "SELECT action, message, enabled FROM sanction_dm_templates WHERE guild_id = ?",
            (ctx.guild.id,),
        )
        configured = {row["action"]: row for row in rows}
        lines = []
        for action, label in self.DM_ACTION_LABELS.items():
            row = configured.get(action)
            state = "par défaut" if row is None else ("personnalisé" if row["enabled"] else "désactivé")
            lines.append(f"**{label.capitalize()}** — {state}")
        e = embeds.neutral(
            "Messages privés de sanction",
            "\n".join(lines)
            + "\n\nConfiguration simple : +sanctiondm ban Votre texte\n"
              "Variables : {membre} {serveur} {raison} {duree} {moderateur} {action}",
        )
        await panels.envoyer(ctx, panels.depuis_embed(e))

    @commands.group(name="sanctiondm", aliases=["dm-sanction"], invoke_without_command=True)
    @checks.is_owner_or_admin()
    async def sanctiondm(
        self,
        ctx: commands.Context,
        action: str | None = None,
        *,
        message: str | None = None,
    ):
        """Configurer le message privé envoyé lors d'une sanction."""
        if action is None:
            return await self._show_sanction_dm_status(ctx)
        normalised = self._normalise_dm_action(action)
        if normalised is None:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Action inconnue : ban, tempban, kick, mute, warn, unban ou unmute.')))
        if not message:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error(f'Ajoutez le texte. Exemple : +sanctiondm {normalised} Votre message')))
        if len(message) > 1900:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Le message doit contenir au maximum 1 900 caractères.')))
        await self.bot.db.execute(
            """
            INSERT INTO sanction_dm_templates (guild_id, action, message, enabled)
            VALUES (?, ?, ?, 1)
            ON CONFLICT(guild_id, action)
            DO UPDATE SET message = excluded.message, enabled = 1
            """,
            (ctx.guild.id, normalised, message),
        )
        await panels.envoyer(ctx, panels.depuis_embed(embeds.success(f'Le MP de **{self.DM_ACTION_LABELS[normalised]}** est configuré.\nAperçu :\n{message[:1000]}')))

    @sanctiondm.command(name="off", aliases=["disable", "desactiver"])
    @checks.is_owner_or_admin()
    async def sanctiondm_off(self, ctx: commands.Context, action: str):
        """Désactiver le MP d'un type de sanction."""
        normalised = self._normalise_dm_action(action)
        if normalised is None:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Action de sanction inconnue.')))
        await self.bot.db.execute(
            """
            INSERT INTO sanction_dm_templates (guild_id, action, message, enabled)
            VALUES (?, ?, '', 0)
            ON CONFLICT(guild_id, action)
            DO UPDATE SET enabled = 0
            """,
            (ctx.guild.id, normalised),
        )
        await panels.envoyer(ctx, panels.depuis_embed(embeds.success(f'Le MP de **{self.DM_ACTION_LABELS[normalised]}** est désactivé.')))

    @sanctiondm.command(name="reset", aliases=["default", "defaut"])
    @checks.is_owner_or_admin()
    async def sanctiondm_reset(self, ctx: commands.Context, action: str):
        """Remettre le message par défaut d'un type de sanction."""
        normalised = self._normalise_dm_action(action)
        if normalised is None:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Action de sanction inconnue.')))
        await self.bot.db.execute(
            "DELETE FROM sanction_dm_templates WHERE guild_id = ? AND action = ?",
            (ctx.guild.id, normalised),
        )
        await panels.envoyer(ctx, panels.depuis_embed(embeds.success(f'Le MP de **{self.DM_ACTION_LABELS[normalised]}** utilise le texte par défaut.')))

    @sanctiondm.command(name="status", aliases=["liste", "list"])
    @checks.is_owner_or_admin()
    async def sanctiondm_status(self, ctx: commands.Context):
        """Afficher l'état des messages privés de sanction."""
        await self._show_sanction_dm_status(ctx)

    async def check_targetable(self, ctx: commands.Context, membre: discord.Member) -> bool:
        err = checks.check_hierarchy(ctx.author, membre)
        if err:
            await panels.envoyer(ctx, panels.depuis_embed(embeds.error(err)))
            return False
        err = checks.check_bot_hierarchy(ctx.guild, membre)
        if err:
            await panels.envoyer(ctx, panels.depuis_embed(embeds.error(err)))
            return False
        return True

    # ---------------------------------------------------------------- BAN

    @commands.hybrid_command(name="ban", description="Bannir définitivement un membre du serveur.")
    @app_commands.describe(membre="Le membre à bannir", raison="La raison du bannissement")
    # AUTORISATION -> utils/access_matrix.py (matrice unique).
    # VALIDATION METIER -> le bot doit réellement posséder la permission Discord.
    @checks.action_validation(bot_permissions=("ban_members",), target="member_moderation")
    async def ban(self, ctx: commands.Context, membre: discord.Member, *, raison: str = "Aucune raison fournie"):
        await self._ack(ctx)
        if not await self.check_targetable(ctx, membre):
            return
        await self._send_sanction_dm(ctx, membre, "ban", raison)
        await ctx.guild.ban(membre, reason=f"{ctx.author} : {raison}", delete_message_seconds=0)
        e = await self.log_sanction(ctx, "ban", membre, raison)
        await panels.envoyer(ctx, panels.depuis_embed(e, kind="moderation"))

    @commands.hybrid_command(name="tempban", description="Bannir temporairement un membre (ex: 1h, 2j).", with_app_command=False)
    @app_commands.describe(membre="Le membre à bannir", duree="Durée (ex: 30m, 2h, 1j)", raison="La raison")
    @checks.has_permission_or_modrole("ban_members")
    async def tempban(self, ctx: commands.Context, membre: discord.Member, duree: str, *, raison: str = "Aucune raison fournie"):
        await self._ack(ctx)
        if not await self.check_targetable(ctx, membre):
            return
        seconds = helpers.parse_duration(duree)
        if seconds is None:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Durée invalide. Exemples valides : `30m`, `2h`, `1j`.')))
        await self._send_sanction_dm(ctx, membre, "tempban", raison, seconds)
        await ctx.guild.ban(membre, reason=f"{ctx.author} (temporaire {duree}) : {raison}", delete_message_seconds=0)
        await self.bot.db.execute(
            "INSERT INTO tempactions (guild_id, user_id, action, expires_at) VALUES (?, ?, 'ban', ?)",
            (ctx.guild.id, membre.id, now() + seconds),
        )
        e = await self.log_sanction(ctx, "tempban", membre, raison, duration_seconds=seconds)
        await panels.envoyer(ctx, panels.depuis_embed(e, kind="moderation"))

    @commands.hybrid_command(name="unban", description="Débannir un utilisateur via son identifiant Discord.")
    @app_commands.describe(user_id="L'identifiant Discord de l'utilisateur", raison="La raison")
    # AUTORISATION -> utils/access_matrix.py (matrice unique).
    # VALIDATION METIER -> le bot doit réellement posséder la permission Discord.
    @checks.action_validation(bot_permissions=("ban_members",), target="external_user")
    async def unban(self, ctx: commands.Context, user_id: str, *, raison: str = "Aucune raison fournie"):
        await self._ack(ctx)
        try:
            uid = int(user_id)
        except ValueError:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Identifiant Discord invalide.')))
        try:
            user = await self.bot.fetch_user(uid)
            await ctx.guild.unban(user, reason=f"{ctx.author} : {raison}")
            await self._send_sanction_dm(ctx, user, "unban", raison)
        except discord.NotFound:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error("Cet utilisateur n'est pas banni ou n'existe pas.")))
        e = await self.log_sanction(ctx, "unban", user, raison)
        await panels.envoyer(ctx, panels.depuis_embed(e, kind="moderation"))

    # ---------------------------------------------------------------- KICK

    @commands.hybrid_command(name="kick", description="Expulser un membre du serveur.")
    @app_commands.describe(membre="Le membre à expulser", raison="La raison de l'expulsion")
    # AUTORISATION -> utils/access_matrix.py (matrice unique).
    # VALIDATION METIER -> le bot doit réellement posséder la permission Discord.
    @checks.action_validation(bot_permissions=("kick_members",), target="member_moderation")
    async def kick(self, ctx: commands.Context, membre: discord.Member, *, raison: str = "Aucune raison fournie"):
        await self._ack(ctx)
        if not await self.check_targetable(ctx, membre):
            return
        await self._send_sanction_dm(ctx, membre, "kick", raison)
        await ctx.guild.kick(membre, reason=f"{ctx.author} : {raison}")
        e = await self.log_sanction(ctx, "kick", membre, raison)
        await panels.envoyer(ctx, panels.depuis_embed(e, kind="moderation"))

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
    # AUTORISATION -> utils/access_matrix.py (matrice unique).
    # VALIDATION METIER -> le bot doit réellement posséder la permission Discord.
    @checks.action_validation(bot_permissions=("moderate_members",), target="member_moderation")
    async def mute(self, ctx: commands.Context, membre: discord.Member, duree: str = "10m", *, raison: str = "Aucune raison fournie"):
        await self._ack(ctx)
        if not await self.check_targetable(ctx, membre):
            return
        seconds = helpers.parse_duration(duree)
        if seconds is None or seconds > 2419200:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Durée invalide (maximum 28 jours). Exemple : `10m`, `1h`, `1j`.')))
        until = discord.utils.utcnow() + timedelta(seconds=seconds)
        await membre.timeout(until, reason=f"{ctx.author} : {raison}")
        await self._send_sanction_dm(ctx, membre, "mute", raison, seconds)
        e = await self.log_sanction(ctx, "mute", membre, raison, duration_seconds=seconds)
        await panels.envoyer(ctx, panels.depuis_embed(e, kind="moderation"))

    @commands.hybrid_command(name="unmute", description="Retirer le mute (timeout) d'un membre.", with_app_command=False)
    @app_commands.describe(membre="Le membre à démuter", raison="La raison")
    # AUTORISATION -> utils/access_matrix.py (matrice unique).
    # VALIDATION METIER -> le bot doit réellement posséder la permission Discord.
    @checks.action_validation(bot_permissions=("moderate_members",), target="member_moderation")
    async def unmute(self, ctx: commands.Context, membre: discord.Member, *, raison: str = "Aucune raison fournie"):
        await self._ack(ctx)
        if not await self.check_targetable(ctx, membre):
            return
        await membre.timeout(None, reason=f"{ctx.author} : {raison}")
        await self._send_sanction_dm(ctx, membre, "unmute", raison)
        e = await self.log_sanction(ctx, "unmute", membre, raison)
        await panels.envoyer(ctx, panels.depuis_embed(e, kind="moderation"))

    # ---------------------------------------------------------------- WARN

    @commands.hybrid_command(name="warn", description="Avertir un membre (enregistré en base de données).")
    @app_commands.describe(membre="Le membre à avertir", raison="La raison de l'avertissement")
    # AUTORISATION -> utils/access_matrix.py (matrice unique).
    # VALIDATION METIER -> le bot doit réellement posséder la permission Discord.
    @checks.action_validation(bot_permissions=("moderate_members",), target="member_moderation")
    async def warn(self, ctx: commands.Context, membre: discord.Member, *, raison: str = "Aucune raison fournie"):
        await self._ack(ctx)
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

        await self._send_sanction_dm(ctx, membre, "warn", raison)
        extra = {"📌 Détails": f"Total d'avertissements : {total}{role_note}"}
        e = await self.log_sanction(ctx, "warn", membre, raison, extra_fields=extra)
        await panels.envoyer(ctx, panels.depuis_embed(e, kind="moderation"))

        # Bannissement automatique au bout de N avertissements (/setwarnbanthreshold,
        # 3 par défaut, 0 = désactivé). Pas de confirmation demandée : c'est le but de
        # ce seuil, agir automatiquement dès qu'il est atteint.
        threshold = conf["warn_ban_threshold"] if conf and conf["warn_ban_threshold"] else 0
        if threshold and total >= threshold:
            err = checks.check_bot_hierarchy(ctx.guild, membre)
            if err:
                await panels.envoyer(ctx, panels.depuis_embed(embeds.warning(f"{membre.mention} a atteint **{total}** avertissements (seuil : {threshold}) mais n'a pas pu être banni automatiquement : {err}")))
                return
            await self._send_sanction_dm(
                ctx, membre, "ban", f"Seuil de {threshold} avertissements atteint"
            )
            try:
                await ctx.guild.ban(
                    membre, reason=f"Ban automatique : {threshold} avertissements atteints", delete_message_seconds=0
                )
            except discord.HTTPException:
                await panels.envoyer(ctx, panels.depuis_embed(embeds.error(f'Le bannissement automatique de {membre.mention} a échoué (permissions).')))
                return
            case_number = await self.bot.db.record_sanction(
                ctx.guild.id, membre.id, self.bot.user.id, "ban",
                f"Seuil de {threshold} avertissements atteint",
            )
            style = design_system.CATEGORY_STYLES["moderation"]
            ban_e = design_system.create_embed(
                title=f"{style['emoji']} Dossier #{case_number} — 🚨 Bannissement automatique (seuil d'avertissements)",
                colour=config.COLOR_ERROR,
                thumbnail=membre.display_avatar.url,
                footer="SentriX",
            )
            ban_e.add_field(name="👤 Membre", value=f"{membre.mention}\n`ID: {membre.id}`", inline=True)
            ban_e.add_field(name="🛡️ Modérateur", value=f"{self.bot.user.mention} (automatique)", inline=True)
            ban_e.add_field(name="📝 Raison", value=f"Seuil de {threshold} avertissements atteint", inline=False)
            ban_e.add_field(name="📌 Détails", value=f"Bannissement automatique — total d'avertissements : {total}", inline=False)
            await panels.envoyer(ctx, panels.depuis_embed(ban_e))
            await self.log_action(ctx.guild, ban_e)

    @commands.hybrid_command(name="unwarn", description="Supprimer un avertissement précis via son identifiant.", with_app_command=False)
    @app_commands.describe(warn_id="L'identifiant de l'avertissement (voir /warnings)")
    @checks.has_permission_or_modrole("moderate_members")
    async def unwarn(self, ctx: commands.Context, warn_id: int):
        await self._ack(ctx)
        row = await self.bot.db.fetchone(
            "SELECT * FROM warnings WHERE id = ? AND guild_id = ?", (warn_id, ctx.guild.id)
        )
        if not row:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Aucun avertissement trouvé avec cet identifiant.')))
        await self.bot.db.execute("DELETE FROM warnings WHERE id = ?", (warn_id,))
        await panels.envoyer(ctx, panels.depuis_embed(embeds.success(f"L'avertissement `#{warn_id}` a été supprimé.")))

    @commands.hybrid_command(name="warnings", description="Afficher les avertissements d'un membre.")
    @app_commands.describe(membre="Le membre à consulter")
    @checks.has_permission_or_modrole("moderate_members")
    async def warnings_cmd(self, ctx: commands.Context, membre: discord.Member):
        await self._ack(ctx)
        rows = await self.bot.db.fetchall(
            "SELECT * FROM warnings WHERE guild_id = ? AND user_id = ? ORDER BY timestamp DESC",
            (ctx.guild.id, membre.id),
        )
        if not rows:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.info(f"{membre.mention} n'a aucun avertissement.")))
        e = embeds.neutral(f"⚠️ Avertissements de {membre.display_name}", f"Total : {len(rows)}")
        for row in rows[:15]:
            mod = ctx.guild.get_member(row["moderator_id"])
            e.add_field(
                name=f"#{row['id']} — <t:{row['timestamp']}:R>",
                value=f"Par {mod.mention if mod else 'Modérateur inconnu'}\n{row['reason']}",
                inline=False,
            )
        await panels.envoyer(ctx, panels.depuis_embed(e))

    @commands.hybrid_command(name="clearwarnings", description="Supprimer tous les avertissements d'un membre.", with_app_command=False)
    @app_commands.describe(membre="Le membre concerné")
    @checks.has_permission_or_modrole("moderate_members")
    async def clearwarnings(self, ctx: commands.Context, membre: discord.Member):
        await self._ack(ctx)
        await self.bot.db.execute(
            "DELETE FROM warnings WHERE guild_id = ? AND user_id = ?", (ctx.guild.id, membre.id)
        )
        await panels.envoyer(ctx, panels.depuis_embed(embeds.success(f'Tous les avertissements de {membre.mention} ont été supprimés.')))

    # ---------------------------------------------------------------- DOSSIERS DE SANCTION

    @commands.hybrid_command(name="case", description="Retrouver une sanction précise via son numéro de dossier.", with_app_command=False)
    @app_commands.describe(numero="Le numéro de dossier (voir la fiche envoyée lors de la sanction)")
    @checks.has_permission_or_modrole("moderate_members")
    async def case(self, ctx: commands.Context, numero: int):
        await self._ack(ctx)
        row = await self.bot.db.get_sanction_by_case(ctx.guild.id, numero)
        if not row:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error(f'Aucun dossier `#{numero}` trouvé sur ce serveur.')))
        label = self.SANCTION_LABELS.get(row["action"], row["action"])
        kind = self.SANCTION_KIND.get(row["action"], "danger")
        colour = {"success": config.COLOR_SUCCESS, "warning": config.COLOR_WARNING, "danger": config.COLOR_ERROR}[kind]
        style = design_system.CATEGORY_STYLES["moderation"]
        e = design_system.create_embed(title=f"{style['emoji']} Dossier #{row['case_number']} — {label}", colour=colour, footer="SentriX")
        e.add_field(name="👤 Membre", value=f"<@{row['user_id']}>\n`ID: {row['user_id']}`", inline=True)
        e.add_field(name="🛡️ Modérateur", value=f"<@{row['moderator_id']}>\n`ID: {row['moderator_id']}`", inline=True)
        e.add_field(name="📅 Date", value=f"<t:{row['created_at']}:F>", inline=True)
        if row["duration_seconds"]:
            e.add_field(name="⏱️ Durée", value=helpers.format_duration(row["duration_seconds"]), inline=True)
        e.add_field(name="📝 Raison", value=row["reason"] or "Aucune raison fournie", inline=False)
        await panels.envoyer(ctx, panels.depuis_embed(e))

    @commands.hybrid_command(name="modhistory", description="Afficher l'historique complet des sanctions d'un membre (tous types confondus).", with_app_command=False)
    @app_commands.describe(membre="Le membre à consulter")
    @checks.has_permission_or_modrole("moderate_members")
    async def modhistory(self, ctx: commands.Context, membre: discord.Member):
        await self._ack(ctx)
        rows = await self.bot.db.get_sanction_history(ctx.guild.id, membre.id, limit=15)
        total = await self.bot.db.get_sanction_count(ctx.guild.id, membre.id)
        if not rows:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.info(f"{membre.mention} n'a aucune sanction enregistrée sur ce serveur.")))
        style = design_system.CATEGORY_STYLES["moderation"]
        e = design_system.create_embed(
            title=f"{style['emoji']} Historique de sanctions — {membre.display_name}",
            description=f"**{total}** dossier(s) au total"
                        + (f" (les {len(rows)} plus récents affichés ci-dessous)" if total > len(rows) else ""),
            colour=style["colour"],
            thumbnail=membre.display_avatar.url,
            footer="SentriX",
        )
        for row in rows:
            label = self.SANCTION_LABELS.get(row["action"], row["action"])
            e.add_field(
                name=f"Dossier #{row['case_number']} — {label} — <t:{row['created_at']}:R>",
                value=f"Par <@{row['moderator_id']}> — {row['reason'] or 'Aucune raison fournie'}",
                inline=False,
            )
        await panels.envoyer(ctx, panels.depuis_embed(e))

    # ---------------------------------------------------------------- SALON

    @commands.hybrid_command(name="clear", description="Supprimer un nombre de messages dans le salon.")
    @app_commands.describe(nombre="Nombre de messages à supprimer (1-100)")
    # AUTORISATION -> utils/access_matrix.py (matrice unique).
    # VALIDATION METIER -> le bot doit réellement posséder la permission Discord.
    @checks.action_validation(bot_permissions=("manage_messages",), target="channel_target")
    async def clear(self, ctx: commands.Context, nombre: app_commands.Range[int, 1, 100]):
        await ctx.defer(ephemeral=True) if ctx.interaction else None
        deleted = await ctx.channel.purge(limit=nombre)
        auteurs = len({m.author.id for m in deleted if getattr(m, "author", None)})
        await panels.envoyer(
            ctx,
            panels.Panneau(
                titre="SentriX — Nettoyage",
                sous_titre=f"**{len(deleted)}** message(s) supprimé(s) dans {ctx.channel.mention}.",
                kind="moderation",
                sections=[
                    panels.Section(
                        "Détail",
                        [
                            panels.Ligne("Messages supprimés", str(len(deleted))),
                            panels.Ligne("Demandé", str(nombre)),
                            panels.Ligne("Auteurs concernés", str(auteurs)),
                        ],
                        aligne=True,
                    ),
                    panels.Section(
                        "À savoir",
                        [
                            panels.Ligne(
                                "Limite Discord",
                                "Les messages de plus de 14 jours ne peuvent pas être supprimés en masse",
                            ),
                            panels.Ligne("Modérateur", ctx.author.mention),
                        ],
                    ),
                ],
                pied="SentriX • Modération",
            ),
            ephemere=bool(ctx.interaction),
        )

    @commands.hybrid_command(name="slowmode", description="Définir le mode lent du salon (durée libre : 5s, 1m, 10m, 1h...).", with_app_command=False)
    @app_commands.describe(duree="Ex: 5s, 30s, 1m, 10m, 1h — ou 0 / off pour désactiver (maximum 6 heures)")
    @checks.has_permission_or_modrole("manage_channels")
    async def slowmode(self, ctx: commands.Context, duree: str):
        await self._ack(ctx)
        raw = duree.strip().lower()
        if raw in ("0", "off", "desactive", "désactive", "désactivé", "aucun", "none", "stop"):
            secondes = 0
        elif raw.isdigit():
            # Rétrocompatibilité : un nombre seul (ex: "300") reste interprété comme des secondes,
            # comme avant ce changement.
            secondes = int(raw)
        else:
            secondes = helpers.parse_duration(raw)
            if secondes is None:
                return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Durée invalide. Exemples valides : `5s`, `30s`, `1m`, `10m`, `1h`, ou `0` / `off` pour désactiver.')))
        secondes = max(0, min(21600, secondes))
        await ctx.channel.edit(slowmode_delay=secondes)
        if secondes == 0:
            panneau = panels.Panneau(
                titre="SentriX — Mode lent",
                sous_titre=f"Le mode lent est **désactivé** dans {ctx.channel.mention}.",
                kind="moderation",
                sections=[
                    panels.Section(
                        "Effet",
                        [panels.Ligne("Les membres peuvent", "Écrire sans délai imposé")],
                    )
                ],
                pied="SentriX • Modération",
            )
        else:
            panneau = panels.Panneau(
                titre="SentriX — Mode lent",
                sous_titre=f"**{helpers.format_duration(secondes)}** entre deux messages dans {ctx.channel.mention}.",
                kind="moderation",
                sections=[
                    panels.Section(
                        "Réglage",
                        [
                            panels.Ligne("Délai", helpers.format_duration(secondes)),
                            panels.Ligne("Salon", ctx.channel.mention),
                            panels.Ligne("Modérateur", ctx.author.mention),
                        ],
                    ),
                    panels.Section(
                        "À savoir",
                        [
                            panels.Ligne(
                                "Exemptions",
                                "Le staff pouvant gérer les messages n'est pas soumis au délai",
                            ),
                            panels.Ligne("Désactiver", "`+slowmode off`"),
                        ],
                    ),
                ],
                pied="SentriX • Modération",
            )
        await panels.envoyer(ctx, panneau)

    @commands.hybrid_command(name="lock", description="Verrouiller le salon (empêche @everyone d'écrire).", with_app_command=False)
    # AUTORISATION -> utils/access_matrix.py (matrice unique).
    # VALIDATION METIER -> le bot doit réellement posséder la permission Discord.
    @checks.action_validation(bot_permissions=("manage_channels",), target="channel_target")
    async def lock(self, ctx: commands.Context, raison: str = "Aucune raison fournie"):
        await self._ack(ctx)
        error = checks.check_channel_target(ctx.author, ctx.channel)
        if error:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error(error)))
        overwrite = ctx.channel.overwrites_for(ctx.guild.default_role)
        overwrite.send_messages = False
        await ctx.channel.set_permissions(ctx.guild.default_role, overwrite=overwrite, reason=raison)
        await panels.envoyer(
            ctx,
            panels.Panneau(
                titre="SentriX — Salon verrouillé",
                sous_titre=f"{ctx.channel.mention} est fermé à l'écriture.",
                kind="moderation",
                sections=[
                    panels.Section(
                        "Sanction",
                        [
                            panels.Ligne("Salon", ctx.channel.mention),
                            panels.Ligne("Raison", raison),
                            panels.Ligne("Modérateur", ctx.author.mention),
                        ],
                    ),
                    panels.Section(
                        "Qui est concerné",
                        [
                            panels.Ligne("Bloqué", "Tous les membres du rôle par défaut"),
                            panels.Ligne("Non bloqué", "Les rôles ayant une autorisation explicite sur ce salon"),
                            panels.Ligne("Rouvrir", "`+unlock`"),
                        ],
                    ),
                ],
                pied="SentriX • Modération",
            ),
        )

    @commands.hybrid_command(name="unlock", description="Déverrouiller le salon.", with_app_command=False)
    # AUTORISATION -> utils/access_matrix.py (matrice unique).
    # VALIDATION METIER -> le bot doit réellement posséder la permission Discord.
    @checks.action_validation(bot_permissions=("manage_channels",), target="channel_target")
    async def unlock(self, ctx: commands.Context):
        await self._ack(ctx)
        error = checks.check_channel_target(ctx.author, ctx.channel)
        if error:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error(error)))
        overwrite = ctx.channel.overwrites_for(ctx.guild.default_role)
        overwrite.send_messages = None
        await ctx.channel.set_permissions(ctx.guild.default_role, overwrite=overwrite)
        await panels.envoyer(
            ctx,
            panels.Panneau(
                titre="SentriX — Salon déverrouillé",
                sous_titre=f"{ctx.channel.mention} est de nouveau ouvert à l'écriture.",
                kind="success",
                sections=[
                    panels.Section(
                        "Détail",
                        [
                            panels.Ligne("Salon", ctx.channel.mention),
                            panels.Ligne("Modérateur", ctx.author.mention),
                            panels.Ligne(
                                "Permission rétablie",
                                "L'autorisation d'écrire revient à sa valeur d'origine",
                                indice="Les réglages propres à chaque rôle ne sont pas modifiés.",
                            ),
                        ],
                    )
                ],
                pied="SentriX • Modération",
            ),
        )

    @commands.hybrid_command(name="hide", description="Cacher le salon aux membres (@everyone).", with_app_command=False)
    @checks.has_permission_or_modrole("manage_channels")
    async def hide(self, ctx: commands.Context):
        await self._ack(ctx)
        overwrite = ctx.channel.overwrites_for(ctx.guild.default_role)
        overwrite.view_channel = False
        await ctx.channel.set_permissions(ctx.guild.default_role, overwrite=overwrite)
        await panels.envoyer(ctx, panels.depuis_embed(embeds.success('🙈 Salon caché.')))

    @commands.hybrid_command(name="show", description="Rendre le salon à nouveau visible.", with_app_command=False)
    @checks.has_permission_or_modrole("manage_channels")
    async def show(self, ctx: commands.Context):
        await self._ack(ctx)
        overwrite = ctx.channel.overwrites_for(ctx.guild.default_role)
        overwrite.view_channel = None
        await ctx.channel.set_permissions(ctx.guild.default_role, overwrite=overwrite)
        await panels.envoyer(ctx, panels.depuis_embed(embeds.success('👁️ Salon à nouveau visible.')))

    # ---------------------------------------------------------------- DIVERS

    # `nickname` fait partie des commandes directes normales du catalogue, mais était
    # la seule sans version slash : with_app_command=False la privait de /nickname
    # depuis le premier commit, alors que sa signature et son @app_commands.describe
    # étaient déjà prêts pour Discord.
    @commands.hybrid_command(name="nickname", description="Changer le pseudo d'un membre.")
    @app_commands.describe(membre="Le membre concerné", pseudo="Le nouveau pseudo")
    # AUTORISATION -> utils/access_matrix.py (matrice unique).
    # VALIDATION METIER -> le bot doit réellement posséder la permission Discord.
    @checks.action_validation(bot_permissions=("manage_nicknames",), target="member_moderation")
    async def nickname(self, ctx: commands.Context, membre: discord.Member, *, pseudo: str):
        await self._ack(ctx)
        if not await self.check_targetable(ctx, membre):
            return
        await membre.edit(nick=pseudo[:32])
        await panels.envoyer(ctx, panels.depuis_embed(embeds.success(f'Le pseudo de {membre.mention} est maintenant **{pseudo[:32]}**.')))

    @commands.hybrid_command(name="resetnick", description="Réinitialiser le pseudo d'un membre.", with_app_command=False)
    @app_commands.describe(membre="Le membre concerné")
    # AUTORISATION -> utils/access_matrix.py (matrice unique).
    # VALIDATION METIER -> le bot doit réellement posséder la permission Discord.
    @checks.action_validation(bot_permissions=("manage_nicknames",), target="member_moderation")
    async def resetnick(self, ctx: commands.Context, membre: discord.Member):
        await self._ack(ctx)
        if not await self.check_targetable(ctx, membre):
            return
        await membre.edit(nick=None)
        await panels.envoyer(ctx, panels.depuis_embed(embeds.success(f'Le pseudo de {membre.mention} a été réinitialisé.')))

    @commands.hybrid_command(name="move", description="Déplacer un membre vers un autre salon vocal.", with_app_command=False)
    @app_commands.describe(membre="Le membre à déplacer", salon="Le salon vocal de destination")
    @checks.has_permission_or_modrole("move_members")
    async def move(self, ctx: commands.Context, membre: discord.Member, salon: discord.VoiceChannel):
        await self._ack(ctx)
        if not membre.voice:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error("Ce membre n'est pas en vocal.")))
        await membre.move_to(salon)
        await panels.envoyer(ctx, panels.depuis_embed(embeds.success(f'{membre.mention} a été déplacé vers **{salon.name}**.')))

    @commands.hybrid_command(name="disconnect", description="Déconnecter un membre du vocal.", with_app_command=False)
    @app_commands.describe(membre="Le membre à déconnecter")
    @checks.has_permission_or_modrole("move_members")
    async def disconnect(self, ctx: commands.Context, membre: discord.Member):
        await self._ack(ctx)
        if not membre.voice:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error("Ce membre n'est pas en vocal.")))
        await membre.move_to(None)
        await panels.envoyer(ctx, panels.depuis_embed(embeds.success(f'{membre.mention} a été déconnecté du vocal.')))


async def setup(bot: commands.Bot):
    await bot.add_cog(Moderation(bot))
