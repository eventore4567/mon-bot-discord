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

Réponses : une sanction répond dans le salon par UNE ligne de texte
(« @membre a été banni. ») via panels.texte_court ; la fiche complète (membre,
modérateur, raison, durée, dossier, historique) part dans le salon de logs. Les
commandes d'information (/warnings, /case, /modhistory) gardent leur panneau.
"""

import asyncio
import io
import logging
import re
import time
from datetime import timedelta

import discord
from discord import app_commands
from discord.ext import commands, tasks

import config
from utils import embeds, checks, helpers, design_system, log_service
from utils import sentrix_panels as panels
from utils.helpers import parse_duration
from utils.v22_rules import clean_reason
from database.db import now
from services import moderation as moderation_service

logger = logging.getLogger("bot.moderation")

# Sentinelle distincte de None : None est une valeur légitime pour case_number
# quand la persistance a déjà été tentée par le service et a ÉCHOUÉ (Core V2,
# Phase 2) — log_sanction ne doit alors PAS retenter un appel non protégé.
_CASE_NUMBER_UNSET = object()


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

    # Type d'événement du journal par action : c'est lui qui pilote la phrase narrative
    # de la carte (« X a été mis en timeout par Y pour 1 minute »). Avec le type générique
    # « moderation », la carte perdait modérateur et durée.
    SANCTION_EVENT_TYPES = {
        "ban": "member_ban", "tempban": "member_ban", "kick": "member_kick", "mute": "member_timeout",
        "unmute": "member_untimeout", "warn": "member_warn", "unban": "member_unban",
    }

    async def log_action(self, guild: discord.Guild, embed: discord.Embed, event_type: str = "moderation"):
        # Utilise le salon "logs-moderation" dédié s'il existe (via /create-logs), sinon
        # retombe sur le salon de logs général — jamais de log perdu.
        await helpers.send_log(self.bot, guild, event_type, embed)

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
        case_number: int | None = _CASE_NUMBER_UNSET,
    ) -> discord.Embed:
        """Point de passage UNIQUE pour toute sanction réelle : enregistre le dossier en
        base (numéro de dossier séquentiel réel), construit la fiche visuelle, l'envoie
        dans le salon de logs, et retourne l'embed pour l'affichage dans le salon courant.

        ``case_number`` : optionnel, rétrocompatible. Si fourni — y compris explicitement
        None (Core V2, Phase 2 — services/moderation.py::persist_sanction() déjà tenté par
        l'appelant, et échoué) — la persistance n'est PAS retentée ici : un None explicite
        veut dire « déjà essayé, ne recommence pas sans protection ». Seule l'ABSENCE
        d'argument (comportement historique, inchangé pour tempban/kick/mute/unmute/warn/
        unban tant qu'ils ne sont pas migrés) déclenche encore la persistance directe,
        non protégée, ici."""
        if case_number is _CASE_NUMBER_UNSET:
            case_number = await self.bot.db.record_sanction(
                ctx.guild.id, target.id, ctx.author.id, action, reason, duration_seconds
            )
        kind = self.SANCTION_KIND.get(action, "danger")
        colour = {"success": config.COLOR_SUCCESS, "warning": config.COLOR_WARNING, "danger": config.COLOR_ERROR}[kind]
        label = self.SANCTION_LABELS.get(action, action)
        style = design_system.CATEGORY_STYLES["moderation"]
        # La sanction Discord a réussi même quand case_number est None (échec de
        # persistance, Core V2 Phase 2) — jamais "Dossier #None", un texte honnête.
        titre_dossier = f"Dossier #{case_number}" if case_number is not None else "Sanction (dossier non enregistré)"
        e = design_system.create_embed(
            title=f"{style['emoji']} {titre_dossier} — {label}",
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
        await self.log_action(ctx.guild, e, self.SANCTION_EVENT_TYPES.get(action, "moderation"))
        return e

    # Deux appels identiques (même serveur, même action, même cible) en moins de
    # SANCTION_DUPLICATE_TTL s : double clic, double envoi, deux modérateurs en même
    # temps. Le second est annulé au lieu de produire deux dossiers et deux MP.
    SANCTION_DUPLICATE_TTL = 6.0

    def _sanction_duplicate(self, ctx: commands.Context, action: str, target_id: int | None) -> bool:
        if ctx.guild is None or target_id is None:
            return False
        # Par instance (jamais un dict partagé au niveau de la classe).
        recent: dict[tuple[int, str, int], float] = self.__dict__.setdefault("_recent_sanctions", {})
        key = (int(ctx.guild.id), str(action), int(target_id))
        mono = time.monotonic()
        previous = recent.get(key)
        if previous is not None and mono - previous <= self.SANCTION_DUPLICATE_TTL:
            return True
        recent[key] = mono
        if len(recent) > 5000:
            cutoff = mono - 30.0
            for candidate, stamp in list(recent.items()):
                if stamp < cutoff:
                    recent.pop(candidate, None)
        return False

    @staticmethod
    def _normalise_prefix_duration(duree: str, raison: str) -> tuple[str, str]:
        """Réassemble les durées françaises que le parseur préfixe coupe en deux mots
        (`+mute @x 10 minutes spam` → durée « 10 minutes », raison « spam »)."""
        raw_duration = str(duree or "").strip()
        raw_reason = str(raison or "").strip()
        if parse_duration(raw_duration) is not None or not raw_reason:
            return raw_duration, raw_reason or "Aucune raison"
        first, *rest = raw_reason.split(maxsplit=1)
        candidate = f"{raw_duration} {first}".strip()
        if parse_duration(candidate) is None:
            return raw_duration, raw_reason or "Aucune raison"
        return candidate, rest[0] if rest else "Aucune raison"

    async def _reply(self, ctx: commands.Context, message: str, *, ephemere: bool = False):
        """Confirmation courte dans le salon de la commande (texte brut, sans ping)."""
        return await panels.texte_court(ctx, message, ephemere=ephemere)

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

    @staticmethod
    def _render_sanction_dm_text(
        template: str,
        *,
        target: discord.abc.User,
        guild: discord.Guild,
        reason: str,
        duration_seconds: int | None,
        actor: discord.abc.User,
        action_label: str,
    ) -> str:
        """Substitution pure des variables du gabarit — extrait de
        _send_sanction_dm pour être réutilisable par services/moderation.py
        (Core V2, Phase 2) sans dupliquer la logique de substitution."""
        values = {
            "membre": getattr(target, "display_name", str(target)),
            "serveur": guild.name,
            "raison": reason or "Aucune raison fournie",
            "duree": helpers.format_duration(duration_seconds) if duration_seconds else "Non précisée",
            "moderateur": getattr(actor, "display_name", str(actor)),
            "action": action_label,
        }
        message = template
        for key, value in values.items():
            message = message.replace("{" + key + "}", str(value))
        return message[:1900]

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
        message = self._render_sanction_dm_text(
            template,
            target=target,
            guild=ctx.guild,
            reason=reason,
            duration_seconds=duration_seconds,
            actor=ctx.author,
            action_label=self.DM_ACTION_LABELS[action],
        )
        try:
            await target.send(message, allowed_mentions=discord.AllowedMentions.none())
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
            return await self._reply(ctx, "Action inconnue : ban, tempban, kick, mute, warn, unban ou unmute.", ephemere=True)
        if not message:
            return await self._reply(ctx, f"Ajoutez le texte. Exemple : `+sanctiondm {normalised} Votre message`", ephemere=True)
        if len(message) > 1900:
            return await self._reply(ctx, "Le message doit contenir au maximum 1 900 caractères.", ephemere=True)
        await self.bot.db.execute(
            """
            INSERT INTO sanction_dm_templates (guild_id, action, message, enabled)
            VALUES (?, ?, ?, 1)
            ON CONFLICT(guild_id, action)
            DO UPDATE SET message = excluded.message, enabled = 1
            """,
            (ctx.guild.id, normalised, message),
        )
        await self._reply(ctx, f"MP de **{self.DM_ACTION_LABELS[normalised]}** configuré. Aperçu :\n{message[:1000]}")

    @sanctiondm.command(name="off", aliases=["disable", "desactiver"])
    @checks.is_owner_or_admin()
    async def sanctiondm_off(self, ctx: commands.Context, action: str):
        """Désactiver le MP d'un type de sanction."""
        normalised = self._normalise_dm_action(action)
        if normalised is None:
            return await self._reply(ctx, "Action de sanction inconnue.", ephemere=True)
        await self.bot.db.execute(
            """
            INSERT INTO sanction_dm_templates (guild_id, action, message, enabled)
            VALUES (?, ?, '', 0)
            ON CONFLICT(guild_id, action)
            DO UPDATE SET enabled = 0
            """,
            (ctx.guild.id, normalised),
        )
        await self._reply(ctx, f"MP de **{self.DM_ACTION_LABELS[normalised]}** désactivé.")

    @sanctiondm.command(name="reset", aliases=["default", "defaut"])
    @checks.is_owner_or_admin()
    async def sanctiondm_reset(self, ctx: commands.Context, action: str):
        """Remettre le message par défaut d'un type de sanction."""
        normalised = self._normalise_dm_action(action)
        if normalised is None:
            return await self._reply(ctx, "Action de sanction inconnue.", ephemere=True)
        await self.bot.db.execute(
            "DELETE FROM sanction_dm_templates WHERE guild_id = ? AND action = ?",
            (ctx.guild.id, normalised),
        )
        await self._reply(ctx, f"MP de **{self.DM_ACTION_LABELS[normalised]}** : texte par défaut rétabli.")

    @sanctiondm.command(name="status", aliases=["liste", "list"])
    @checks.is_owner_or_admin()
    async def sanctiondm_status(self, ctx: commands.Context):
        """Afficher l'état des messages privés de sanction."""
        await self._show_sanction_dm_status(ctx)

    async def check_targetable(self, ctx: commands.Context, membre: discord.Member) -> bool:
        err = checks.check_hierarchy(ctx.author, membre)
        if err:
            await self._reply(ctx, err, ephemere=True)
            return False
        err = checks.check_bot_hierarchy(ctx.guild, membre)
        if err:
            await self._reply(ctx, err, ephemere=True)
            return False
        return True

    # ---------------------------------------------------------------- BAN

    @commands.hybrid_command(name="ban", description="Bannir définitivement un membre du serveur.")
    @app_commands.describe(membre="Le membre à bannir", raison="La raison du bannissement")
    # AUTORISATION -> utils/access_matrix.py (matrice unique).
    # VALIDATION METIER -> le bot doit réellement posséder la permission Discord.
    @checks.action_validation(bot_permissions=("ban_members",), target="member_moderation")
    async def ban(self, ctx: commands.Context, membre: discord.Member, *, raison: str = "Aucune raison fournie"):
        """Core V2, Phase 2 (docs/core-v2-plan.md) : première commande de sanction
        migrée vers services/moderation.py::ban(). Ce corps ne fait plus que
        l'adaptation Discord (parser ctx, préparer le texte du MP, rendre le
        résultat) ; hiérarchie, exécution et persistance vivent dans le service,
        testé sans Discord dans tests/test_services_moderation_ban.py — y compris
        la correction d'un vrai trou trouvé pendant l'extraction : une exception de
        persistance ne fait plus jamais passer une sanction réellement appliquée
        pour un échec de commande."""
        raison = clean_reason(raison)
        if self._sanction_duplicate(ctx, "ban", membre.id):
            return await self._reply(ctx, "Cette sanction vient déjà d'être lancée sur ce membre.", ephemere=True)
        await self._ack(ctx)

        template = await self._get_sanction_dm_template(ctx.guild.id, "ban")
        dm_text = None
        if template is not None:
            dm_text = self._render_sanction_dm_text(
                template,
                target=membre,
                guild=ctx.guild,
                reason=raison,
                duration_seconds=None,
                actor=ctx.author,
                action_label=self.DM_ACTION_LABELS["ban"],
            )

        outcome = await moderation_service.ban(
            self.bot, guild=ctx.guild, actor=ctx.author, target=membre, reason=raison, dm_text=dm_text,
        )
        if not outcome.executed:
            return await self._reply(ctx, outcome.hierarchy_error, ephemere=True)

        await self.log_sanction(ctx, "ban", membre, raison, case_number=outcome.case_number)
        await self._reply(ctx, f"{membre.mention} a été banni.")

    @commands.hybrid_command(name="tempban", description="Bannir temporairement un membre (ex: 1h, 2j).", with_app_command=False)
    @app_commands.describe(membre="Le membre à bannir", duree="Durée (ex: 30m, 2h, 1j)", raison="La raison")
    # AUTORISATION -> utils/access_matrix.py (matrice unique).
    # VALIDATION METIER -> le bot doit réellement posséder la permission Discord.
    @checks.action_validation(bot_permissions=("ban_members",), target="member_moderation")
    async def tempban(self, ctx: commands.Context, membre: discord.Member, duree: str, *, raison: str = "Aucune raison fournie"):
        """Core V2, Phase 2 (docs/core-v2-plan.md) : cinquième commande de
        sanction migrée — voir services/moderation.py::tempban(). Remplace au
        passage @checks.has_permission_or_modrole (autorisation locale,
        redondante avec utils/access_matrix.py) par @checks.action_validation,
        déjà en place sur ban/kick/mute/unmute — même famille de commandes,
        même garde-fou : le bot doit réellement posséder la permission
        Discord avant l'exécution."""
        raison = clean_reason(raison)
        if ctx.interaction is None:
            duree, raison = self._normalise_prefix_duration(duree, raison)
        if self._sanction_duplicate(ctx, "tempban", membre.id):
            return await self._reply(ctx, "Cette sanction vient déjà d'être lancée sur ce membre.", ephemere=True)
        await self._ack(ctx)
        existing = await self.bot.db.fetchone(
            "SELECT id FROM tempactions WHERE guild_id=? AND user_id=? AND action='ban' AND expires_at>? LIMIT 1",
            (ctx.guild.id, membre.id, now()),
        )
        if existing:
            return await self._reply(ctx, f"{membre.mention} a déjà un bannissement temporaire actif.", ephemere=True)

        template = await self._get_sanction_dm_template(ctx.guild.id, "tempban")

        def render_dm_text(seconds: int) -> str | None:
            if template is None:
                return None
            return self._render_sanction_dm_text(
                template,
                target=membre,
                guild=ctx.guild,
                reason=raison,
                duration_seconds=seconds,
                actor=ctx.author,
                action_label=self.DM_ACTION_LABELS["tempban"],
            )

        outcome = await moderation_service.tempban(
            self.bot, guild=ctx.guild, actor=ctx.author, target=membre, reason=raison,
            duree=duree, render_dm_text=render_dm_text,
        )
        if not outcome.executed:
            return await self._reply(ctx, outcome.rejection_reason, ephemere=True)

        await self.log_sanction(
            ctx, "tempban", membre, raison,
            duration_seconds=outcome.duration_seconds, case_number=outcome.case_number,
        )
        await self._reply(ctx, f"{membre.mention} a été banni pendant {helpers.format_duration(outcome.duration_seconds)}.")

    @commands.hybrid_command(name="unban", description="Débannir un utilisateur via son identifiant Discord.")
    @app_commands.describe(user_id="L'identifiant Discord de l'utilisateur", raison="La raison")
    # AUTORISATION -> utils/access_matrix.py (matrice unique).
    # VALIDATION METIER -> le bot doit réellement posséder la permission Discord.
    @checks.action_validation(bot_permissions=("ban_members",), target="external_user")
    async def unban(self, ctx: commands.Context, user_id: str, *, raison: str = "Aucune raison fournie"):
        """Core V2, Phase 2 (docs/core-v2-plan.md) : septième et dernière
        commande de sanction migrée — voir services/moderation.py::unban().
        Corrige le même trou que les six précédentes : record_sanction()
        n'était protégé par aucun try/except alors que le débannissement
        Discord avait déjà réellement réussi."""
        raison = clean_reason(raison)
        try:
            uid = int(user_id)
        except ValueError:
            return await self._reply(ctx, "Identifiant Discord invalide.", ephemere=True)
        if self._sanction_duplicate(ctx, "unban", uid):
            return await self._reply(ctx, "Ce débannissement vient déjà d'être lancé.", ephemere=True)
        await self._ack(ctx)

        template = await self._get_sanction_dm_template(ctx.guild.id, "unban")

        def render_dm_text(user: discord.abc.User) -> str | None:
            if template is None:
                return None
            return self._render_sanction_dm_text(
                template, target=user, guild=ctx.guild, reason=raison,
                duration_seconds=None, actor=ctx.author, action_label=self.DM_ACTION_LABELS["unban"],
            )

        outcome = await moderation_service.unban(
            self.bot, guild=ctx.guild, actor=ctx.author, user_id=uid, reason=raison,
            fetch_user=self.bot.fetch_user, render_dm_text=render_dm_text,
        )
        if not outcome.executed:
            return await self._reply(ctx, outcome.rejection_reason, ephemere=True)

        await self.log_sanction(ctx, "unban", outcome.resolved_target, raison, case_number=outcome.case_number)
        await self._reply(ctx, f"{outcome.resolved_target} a été débanni.")

    # ---------------------------------------------------------------- KICK

    @commands.hybrid_command(name="kick", description="Expulser un membre du serveur.")
    @app_commands.describe(membre="Le membre à expulser", raison="La raison de l'expulsion")
    # AUTORISATION -> utils/access_matrix.py (matrice unique).
    # VALIDATION METIER -> le bot doit réellement posséder la permission Discord.
    @checks.action_validation(bot_permissions=("kick_members",), target="member_moderation")
    async def kick(self, ctx: commands.Context, membre: discord.Member, *, raison: str = "Aucune raison fournie"):
        """Core V2, Phase 2 (docs/core-v2-plan.md) : deuxième commande de
        sanction migrée vers services/moderation.py — voir le docstring de
        ban() ci-dessus pour le détail de la migration et du trou de
        persistance corrigé en l'extrayant."""
        raison = clean_reason(raison)
        if self._sanction_duplicate(ctx, "kick", membre.id):
            return await self._reply(ctx, "Cette sanction vient déjà d'être lancée sur ce membre.", ephemere=True)
        await self._ack(ctx)

        template = await self._get_sanction_dm_template(ctx.guild.id, "kick")
        dm_text = None
        if template is not None:
            dm_text = self._render_sanction_dm_text(
                template,
                target=membre,
                guild=ctx.guild,
                reason=raison,
                duration_seconds=None,
                actor=ctx.author,
                action_label=self.DM_ACTION_LABELS["kick"],
            )

        outcome = await moderation_service.kick(
            self.bot, guild=ctx.guild, actor=ctx.author, target=membre, reason=raison, dm_text=dm_text,
        )
        if not outcome.executed:
            return await self._reply(ctx, outcome.hierarchy_error, ephemere=True)

        await self.log_sanction(ctx, "kick", membre, raison, case_number=outcome.case_number)
        await self._reply(ctx, f"{membre.mention} a été expulsé.")

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
        """Core V2, Phase 2 (docs/core-v2-plan.md) : troisième commande de
        sanction migrée. Forme différente de ban()/kick() (durée à valider, MP
        après l'exécution) — voir services/moderation.py::mute()."""
        if ctx.interaction is None:
            duree, raison = self._normalise_prefix_duration(duree, raison)
        raison = clean_reason(raison)
        if self._sanction_duplicate(ctx, "mute", membre.id):
            return await self._reply(ctx, "Cette sanction vient déjà d'être lancée sur ce membre.", ephemere=True)
        await self._ack(ctx)

        template = await self._get_sanction_dm_template(ctx.guild.id, "mute")

        def render_dm_text(seconds: int) -> str | None:
            if template is None:
                return None
            return self._render_sanction_dm_text(
                template,
                target=membre,
                guild=ctx.guild,
                reason=raison,
                duration_seconds=seconds,
                actor=ctx.author,
                action_label=self.DM_ACTION_LABELS["mute"],
            )

        outcome = await moderation_service.mute(
            self.bot, guild=ctx.guild, actor=ctx.author, target=membre, reason=raison,
            duree=duree, render_dm_text=render_dm_text,
        )
        if not outcome.executed:
            return await self._reply(ctx, outcome.rejection_reason, ephemere=True)

        await self.log_sanction(
            ctx, "mute", membre, raison,
            duration_seconds=outcome.duration_seconds, case_number=outcome.case_number,
        )
        await self._reply(ctx, f"{membre.mention} a été rendu muet pendant {helpers.format_duration(outcome.duration_seconds)}.")

    @commands.hybrid_command(name="unmute", description="Retirer le mute (timeout) d'un membre.", with_app_command=False)
    @app_commands.describe(membre="Le membre à démuter", raison="La raison")
    # AUTORISATION -> utils/access_matrix.py (matrice unique).
    # VALIDATION METIER -> le bot doit réellement posséder la permission Discord.
    @checks.action_validation(bot_permissions=("moderate_members",), target="member_moderation")
    async def unmute(self, ctx: commands.Context, membre: discord.Member, *, raison: str = "Aucune raison fournie"):
        """Core V2, Phase 2 (docs/core-v2-plan.md) : quatrième commande de
        sanction migrée — voir services/moderation.py::unmute()."""
        raison = clean_reason(raison)
        if self._sanction_duplicate(ctx, "unmute", membre.id):
            return await self._reply(ctx, "Cette action vient déjà d'être lancée sur ce membre.", ephemere=True)
        await self._ack(ctx)

        template = await self._get_sanction_dm_template(ctx.guild.id, "unmute")
        dm_text = None
        if template is not None:
            dm_text = self._render_sanction_dm_text(
                template,
                target=membre,
                guild=ctx.guild,
                reason=raison,
                duration_seconds=None,
                actor=ctx.author,
                action_label=self.DM_ACTION_LABELS["unmute"],
            )

        outcome = await moderation_service.unmute(
            self.bot, guild=ctx.guild, actor=ctx.author, target=membre, reason=raison, dm_text=dm_text,
        )
        if not outcome.executed:
            return await self._reply(ctx, outcome.rejection_reason, ephemere=True)

        await self.log_sanction(ctx, "unmute", membre, raison, case_number=outcome.case_number)
        await self._reply(ctx, f"{membre.mention} n'est plus muet.")

    # ---------------------------------------------------------------- WARN

    @commands.hybrid_command(name="warn", description="Avertir un membre (enregistré en base de données).")
    @app_commands.describe(membre="Le membre à avertir", raison="La raison de l'avertissement")
    # AUTORISATION -> utils/access_matrix.py (matrice unique).
    # VALIDATION METIER -> le bot doit réellement posséder la permission Discord.
    @checks.action_validation(bot_permissions=("moderate_members",), target="member_moderation")
    async def warn(self, ctx: commands.Context, membre: discord.Member, *, raison: str = "Aucune raison fournie"):
        """Core V2, Phase 2 (docs/core-v2-plan.md) : sixième commande de
        sanction migrée — voir services/moderation.py::warn(). Forme la plus
        large de toutes les commandes migrées : au-delà du dossier de
        sanction habituel, corrige aussi le même trou de persistance sur le
        bannissement automatique par seuil d'avertissements (une sanction
        Discord distincte, déjà réellement exécutée avant son propre
        record_sanction() non protégé) et sur le comptage total (une lecture
        qui ne doit plus jamais faire passer un avertissement déjà enregistré
        pour un échec)."""
        raison = clean_reason(raison)
        if self._sanction_duplicate(ctx, "warn", membre.id):
            return await self._reply(ctx, "Cet avertissement vient déjà d'être lancé sur ce membre.", ephemere=True)
        await self._ack(ctx)

        template = await self._get_sanction_dm_template(ctx.guild.id, "warn")
        dm_text = None
        if template is not None:
            dm_text = self._render_sanction_dm_text(
                template, target=membre, guild=ctx.guild, reason=raison,
                duration_seconds=None, actor=ctx.author, action_label=self.DM_ACTION_LABELS["warn"],
            )

        conf = await self.bot.db.get_guild_config(ctx.guild.id)
        # Rôle automatique d'avertissement (/setwarnrole) : ajouté au membre à chaque
        # /warn, tant qu'il ne l'a pas déjà et que le bot a la permission de le faire.
        warn_role = ctx.guild.get_role(conf["warn_role"]) if conf and conf["warn_role"] else None
        # Bannissement automatique au bout de N avertissements (/setwarnbanthreshold,
        # 3 par défaut, 0 = désactivé). Pas de confirmation demandée : c'est le but de
        # ce seuil, agir automatiquement dès qu'il est atteint.
        threshold = conf["warn_ban_threshold"] if conf and conf["warn_ban_threshold"] else 0

        template_ban = await self._get_sanction_dm_template(ctx.guild.id, "ban")

        def render_ban_dm_text() -> str | None:
            if template_ban is None:
                return None
            return self._render_sanction_dm_text(
                template_ban, target=membre, guild=ctx.guild,
                reason=f"Seuil de {threshold} avertissements atteint",
                duration_seconds=None, actor=ctx.author, action_label=self.DM_ACTION_LABELS["ban"],
            )

        outcome = await moderation_service.warn(
            self.bot, guild=ctx.guild, actor=ctx.author, target=membre, reason=raison,
            dm_text=dm_text, warn_role=warn_role, ban_threshold=threshold,
            render_ban_dm_text=render_ban_dm_text,
        )
        if not outcome.executed:
            return await self._reply(ctx, outcome.hierarchy_error, ephemere=True)

        role_note = ""
        if warn_role is not None:
            if outcome.role_assigned:
                role_note = f"\nRôle {warn_role.mention} attribué automatiquement."
            elif outcome.role_error:
                role_note = f"\n⚠️ Impossible d'attribuer le rôle {warn_role.mention} (permissions/hiérarchie)."

        total_txt = (
            str(outcome.total_warnings) if outcome.total_warnings is not None
            else "inconnu (erreur de comptage)"
        )
        extra = {"📌 Détails": f"Total d'avertissements : {total_txt}{role_note}"}
        await self.log_sanction(ctx, "warn", membre, raison, extra_fields=extra, case_number=outcome.case_number)
        total_note = f" ({total_txt} au total)" if outcome.total_warnings is not None else ""
        await self._reply(ctx, f"{membre.mention} a été averti{total_note}.")

        if not outcome.auto_ban_triggered:
            return
        if outcome.auto_ban_hierarchy_error:
            return await self._reply(
                ctx,
                f"{membre.mention} a atteint {outcome.total_warnings} avertissements (seuil : {threshold}) "
                f"mais n'a pas pu être banni automatiquement : {outcome.auto_ban_hierarchy_error}",
            )
        if not outcome.auto_ban_executed:
            return await self._reply(ctx, f"Le bannissement automatique de {membre.mention} a échoué (permissions).")

        style = design_system.CATEGORY_STYLES["moderation"]
        titre_dossier = (
            f"Dossier #{outcome.auto_ban_case_number}" if outcome.auto_ban_case_number is not None
            else "Sanction (dossier non enregistré)"
        )
        ban_e = design_system.create_embed(
            title=f"{style['emoji']} {titre_dossier} — 🚨 Bannissement automatique (seuil d'avertissements)",
            colour=config.COLOR_ERROR,
            thumbnail=membre.display_avatar.url,
            footer="SentriX",
        )
        ban_e.add_field(name="👤 Membre", value=f"{membre.mention}\n`ID: {membre.id}`", inline=True)
        ban_e.add_field(name="🛡️ Modérateur", value=f"{self.bot.user.mention} (automatique)", inline=True)
        ban_e.add_field(name="📝 Raison", value=f"Seuil de {threshold} avertissements atteint", inline=False)
        ban_e.add_field(name="📌 Détails", value=f"Bannissement automatique — total d'avertissements : {outcome.total_warnings}", inline=False)
        await self.log_action(ctx.guild, ban_e)
        await self._reply(ctx, f"{membre.mention} a été banni automatiquement (seuil de {threshold} avertissements atteint).")

    @commands.hybrid_command(name="unwarn", description="Supprimer un avertissement précis via son identifiant.", with_app_command=False)
    @app_commands.describe(warn_id="L'identifiant de l'avertissement (voir /warnings)")
    @checks.has_permission_or_modrole("moderate_members")
    async def unwarn(self, ctx: commands.Context, warn_id: int):
        await self._ack(ctx)
        row = await self.bot.db.fetchone(
            "SELECT * FROM warnings WHERE id = ? AND guild_id = ?", (warn_id, ctx.guild.id)
        )
        if not row:
            return await self._reply(ctx, "Aucun avertissement trouvé avec cet identifiant.", ephemere=True)
        member = ctx.guild.get_member(int(row["user_id"]))
        if member is not None and not await self.check_targetable(ctx, member):
            return
        await self.bot.db.execute("DELETE FROM warnings WHERE id = ?", (warn_id,))
        await self._reply(ctx, f"Avertissement #{warn_id} supprimé.")

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
            return await self._reply(ctx, f"{membre.mention} n'a aucun avertissement.", ephemere=True)
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
        if not await self.check_targetable(ctx, membre):
            return
        await self.bot.db.execute(
            "DELETE FROM warnings WHERE guild_id = ? AND user_id = ?", (ctx.guild.id, membre.id)
        )
        await self._reply(ctx, f"Tous les avertissements de {membre.mention} ont été supprimés.")

    # ---------------------------------------------------------------- DOSSIERS DE SANCTION

    @commands.hybrid_command(name="case", description="Retrouver une sanction précise via son numéro de dossier.", with_app_command=False)
    @app_commands.describe(numero="Le numéro de dossier (voir la fiche envoyée lors de la sanction)")
    @checks.has_permission_or_modrole("moderate_members")
    async def case(self, ctx: commands.Context, numero: int):
        await self._ack(ctx)
        row = await self.bot.db.get_sanction_by_case(ctx.guild.id, numero)
        if not row:
            return await self._reply(ctx, f"Aucun dossier #{numero} sur ce serveur.", ephemere=True)
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
            return await self._reply(ctx, f"{membre.mention} n'a aucune sanction enregistrée sur ce serveur.", ephemere=True)
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
    async def clear(self, ctx: commands.Context, nombre: commands.Range[int, 1, 100]):
        """Implémentation UNIQUE de +clear / /clear.

        Historique : trois implémentations coexistaient (ce corps, cogs/help_clear_fix_v80
        et utils/sentrix_runtime._patch_clear, la dernière posée gagnant). Elles sont
        fusionnées ici : la réponse est une ligne de texte, l'utilisateur est servi
        AVANT le journal (transcription + aperçu, envoyés en tâche de fond), et les
        identifiants purgés sont marqués pour que le journal « Messages » ne reçoive
        pas N cartes individuelles avant le récapitulatif.
        """
        requested = max(1, min(int(nombre), 100))
        if ctx.interaction is not None and not ctx.interaction.response.is_done():
            await ctx.interaction.response.defer(ephemeral=True)

        is_prefix = ctx.interaction is None
        purge_limit = requested + (1 if is_prefix else 0)
        invocation_id = getattr(getattr(ctx, "message", None), "id", None) if is_prefix else None

        candidates = [message async for message in ctx.channel.history(limit=purge_limit)]
        log_service.mark_purged(int(message.id) for message in candidates)

        try:
            deleted = await self._purge_messages(ctx, candidates, purge_limit)
        except discord.Forbidden:
            return await panels.texte_court(
                ctx.channel if is_prefix else ctx,
                "Il manque à SentriX la permission **Gérer les messages** ou **Voir l'historique** dans ce salon.",
                ephemere=True,
                supprimer_apres=8,
            )
        messages = [
            message for message in deleted
            if invocation_id is None or int(message.id) != int(invocation_id)
        ]

        texte = f"{len(messages)} message(s) supprimé(s)."
        if is_prefix:
            # Le message de commande vient d'être purgé : la confirmation est éphémère à
            # sa manière (courte durée), sans référence à un message disparu.
            await panels.texte_court(ctx.channel, texte, supprimer_apres=4)
        else:
            await panels.texte_court(ctx, texte, ephemere=True)

        asyncio.create_task(self._log_clear_safely(ctx, messages, requested))

    @staticmethod
    async def _purge_messages(ctx: commands.Context, candidates: list, purge_limit: int) -> list:
        """Supprime des messages DÉJÀ récupérés, sans relire l'historique."""
        if not candidates:
            return []
        limite_groupee = discord.utils.utcnow() - timedelta(days=14)
        if any(message.created_at <= limite_groupee for message in candidates):
            # Suppression groupée impossible au-delà de 14 jours : purge() sait le faire un par un.
            return await ctx.channel.purge(limit=purge_limit)
        try:
            if len(candidates) == 1:
                await candidates[0].delete()
            else:
                await ctx.channel.delete_messages(candidates)
        except discord.HTTPException:
            # Repli intégral plutôt que de laisser le salon à moitié nettoyé.
            return await ctx.channel.purge(limit=purge_limit)
        return candidates

    async def _log_clear_safely(self, ctx: commands.Context, messages: list, requested: int) -> None:
        """Journal de purge hors du chemin critique : un échec ici ne casse pas la commande."""
        try:
            await self._send_clear_log(ctx, messages, requested=requested)
        except Exception:
            logger.exception(
                "Journal de purge impossible guild=%s salon=%s",
                getattr(ctx.guild, "id", None), getattr(ctx.channel, "id", None),
            )

    _MASS_MENTION_RE = re.compile(r"@(everyone|here)\b", re.IGNORECASE)

    @classmethod
    def _neutralize_mentions(cls, value: object) -> str:
        """Garde le texte lisible sans transformer @everyone/@here en mention Discord."""
        return cls._MASS_MENTION_RE.sub(lambda m: "@\u200b" + m.group(1), str(value or ""))

    @classmethod
    def _clear_preview(cls, messages: list, limit: int = 10) -> str:
        rows: list[str] = []
        budget = 1000
        for message in messages[:limit]:
            author = cls._neutralize_mentions(getattr(message.author, "display_name", str(message.author)))
            content = cls._neutralize_mentions(message.content or "[message sans texte]")
            content = discord.utils.escape_markdown(content).replace("\n", " ").strip()
            if len(content) > 150:
                content = content[:149].rstrip() + "…"
            row = f"**{author}** — {content}"
            if len("\n".join([*rows, row])) > budget:
                break
            rows.append(row)
        return "\n".join(rows) if rows else "Aucun contenu texte disponible."

    @staticmethod
    def _clear_transcript(ctx: commands.Context, messages: list, requested: int) -> bytes:
        lines = [
            "SentriX — transcription de clear",
            f"Serveur: {ctx.guild.name} ({ctx.guild.id})",
            f"Salon: #{ctx.channel.name} ({ctx.channel.id})",
            f"Modérateur: {ctx.author} ({ctx.author.id})",
            f"Demandé: {requested}",
            f"Supprimé: {len(messages)}",
            "",
        ]
        for index, message in enumerate(sorted(messages, key=lambda m: m.created_at), start=1):
            lines.append(
                f"[{index}] {message.created_at.isoformat()} | {message.author} ({message.author.id}) | "
                f"message={message.id}"
            )
            lines.append(message.content or "[message sans texte]")
            if message.attachments:
                lines.append("Pièces jointes: " + " | ".join(attachment.url for attachment in message.attachments))
            lines.append("")
        return "\n".join(lines).encode("utf-8", errors="replace")

    async def _send_clear_log(self, ctx: commands.Context, messages: list, *, requested: int) -> None:
        if ctx.guild is None:
            return
        panel = embeds.canonical_log_embed(
            "Messages supprimés avec Clear",
            fields=(
                ("Modérateur", f"<@{ctx.author.id}>", True),
                ("Salon", f"<#{ctx.channel.id}>", True),
                ("Nombre", str(len(messages)), True),
                ("Messages supprimés", self._clear_preview(messages), False),
                (
                    "Transcription",
                    "Le fichier joint contient la totalité des messages supprimés, leurs auteurs, IDs et pièces jointes.",
                    False,
                ),
            ),
        )
        file: discord.File | None = None
        setting = await log_service.get_log_setting(self.bot, ctx.guild.id, "messages")
        if setting.get("enabled"):
            ok, _reason = log_service.validate_channel(ctx.guild, setting.get("channel_id"), needs_file=True)
            if ok:
                file = discord.File(
                    io.BytesIO(self._clear_transcript(ctx, messages, requested)),
                    filename=f"sentrix-clear-{ctx.channel.id}-{int(time.time())}.txt",
                )
        event_key = log_service.make_event_key(
            ctx.guild.id, "clear_command", executor_id=ctx.author.id, discriminator=time.time_ns(),
        )
        await log_service.send_log(self.bot, ctx.guild, "messages", panel, file=file, event_key=event_key)

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
                return await self._reply(ctx, "Durée invalide. Exemples : `5s`, `30s`, `1m`, `10m`, `1h`, ou `0` / `off` pour désactiver.", ephemere=True)
        secondes = max(0, min(21600, secondes))
        await ctx.channel.edit(slowmode_delay=secondes)
        if secondes == 0:
            await self._reply(ctx, f"Mode lent désactivé dans {ctx.channel.mention}.")
        else:
            await self._reply(ctx, f"Mode lent : {helpers.format_duration(secondes)} entre deux messages dans {ctx.channel.mention}.")

    @commands.hybrid_command(name="lock", description="Verrouiller le salon (empêche @everyone d'écrire).", with_app_command=False)
    # AUTORISATION -> utils/access_matrix.py (matrice unique).
    # VALIDATION METIER -> le bot doit réellement posséder la permission Discord.
    @checks.action_validation(bot_permissions=("manage_channels",), target="channel_target")
    async def lock(self, ctx: commands.Context, raison: str = "Aucune raison fournie"):
        await self._ack(ctx)
        error = checks.check_channel_target(ctx.author, ctx.channel)
        if error:
            return await self._reply(ctx, error, ephemere=True)
        overwrite = ctx.channel.overwrites_for(ctx.guild.default_role)
        overwrite.send_messages = False
        await ctx.channel.set_permissions(ctx.guild.default_role, overwrite=overwrite, reason=raison)
        await self._reply(ctx, f"{ctx.channel.mention} est verrouillé. Raison : {raison}")

    @commands.hybrid_command(name="unlock", description="Déverrouiller le salon.", with_app_command=False)
    # AUTORISATION -> utils/access_matrix.py (matrice unique).
    # VALIDATION METIER -> le bot doit réellement posséder la permission Discord.
    @checks.action_validation(bot_permissions=("manage_channels",), target="channel_target")
    async def unlock(self, ctx: commands.Context):
        await self._ack(ctx)
        error = checks.check_channel_target(ctx.author, ctx.channel)
        if error:
            return await self._reply(ctx, error, ephemere=True)
        overwrite = ctx.channel.overwrites_for(ctx.guild.default_role)
        overwrite.send_messages = None
        await ctx.channel.set_permissions(ctx.guild.default_role, overwrite=overwrite)
        await self._reply(ctx, f"{ctx.channel.mention} est déverrouillé.")

    @commands.hybrid_command(name="hide", description="Cacher le salon aux membres (@everyone).", with_app_command=False)
    @checks.has_permission_or_modrole("manage_channels")
    async def hide(self, ctx: commands.Context):
        await self._ack(ctx)
        if await self._set_everyone_visibility(ctx, visible=False):
            await self._reply(ctx, f"{ctx.channel.mention} est maintenant caché aux membres.")

    @commands.hybrid_command(name="show", description="Rendre le salon à nouveau visible.", with_app_command=False)
    @checks.has_permission_or_modrole("manage_channels")
    async def show(self, ctx: commands.Context):
        await self._ack(ctx)
        if await self._set_everyone_visibility(ctx, visible=True):
            await self._reply(ctx, f"{ctx.channel.mention} est à nouveau visible.")

    # Code d'erreur Discord renvoyé quand on tente de cacher un salon déclaré dans
    # l'onboarding communautaire (« Onboarding channels must be readable by everyone »).
    _ONBOARDING_CHANNEL_ERROR = 350003

    async def _set_everyone_visibility(self, ctx: commands.Context, *, visible: bool) -> bool:
        """Applique la permission « voir le salon » de @everyone ; retourne False (après
        une phrase courte) quand Discord refuse — ce n'est pas une erreur technique."""
        overwrite = ctx.channel.overwrites_for(ctx.guild.default_role)
        overwrite.view_channel = None if visible else False
        try:
            await ctx.channel.set_permissions(ctx.guild.default_role, overwrite=overwrite, reason=f"{ctx.author} : {'show' if visible else 'hide'}")
        except discord.Forbidden:
            await self._reply(ctx, "Il manque à SentriX la permission **Gérer les salons** ici.", ephemere=True)
            return False
        except discord.HTTPException as exc:
            if getattr(exc, "code", None) == self._ONBOARDING_CHANNEL_ERROR:
                await self._reply(
                    ctx,
                    f"{ctx.channel.mention} fait partie de l'onboarding du serveur : Discord impose qu'il reste visible par tous. "
                    "Retirez-le de l'onboarding (Paramètres du serveur › Onboarding) pour pouvoir le cacher.",
                    ephemere=True,
                )
                return False
            raise
        return True

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
        await self._reply(ctx, f"Le pseudo de {membre.mention} est maintenant **{pseudo[:32]}**.")

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
        await self._reply(ctx, f"Le pseudo de {membre.mention} a été réinitialisé.")

    @commands.hybrid_command(name="move", description="Déplacer un membre vers un autre salon vocal.", with_app_command=False)
    @app_commands.describe(membre="Le membre à déplacer", salon="Le salon vocal de destination")
    @checks.has_permission_or_modrole("move_members")
    async def move(self, ctx: commands.Context, membre: discord.Member, salon: discord.VoiceChannel):
        await self._ack(ctx)
        if not await self.check_targetable(ctx, membre):
            return
        if not membre.voice:
            return await self._reply(ctx, "Ce membre n'est pas en vocal.", ephemere=True)
        await membre.move_to(salon)
        await self._reply(ctx, f"{membre.mention} a été déplacé vers **{salon.name}**.")

    @commands.hybrid_command(name="disconnect", description="Déconnecter un membre du vocal.", with_app_command=False)
    @app_commands.describe(membre="Le membre à déconnecter")
    @checks.has_permission_or_modrole("move_members")
    async def disconnect(self, ctx: commands.Context, membre: discord.Member):
        await self._ack(ctx)
        if not await self.check_targetable(ctx, membre):
            return
        if not membre.voice:
            return await self._reply(ctx, "Ce membre n'est pas en vocal.", ephemere=True)
        await membre.move_to(None)
        await self._reply(ctx, f"{membre.mention} a été déconnecté du vocal.")


async def setup(bot: commands.Bot):
    await bot.add_cog(Moderation(bot))
