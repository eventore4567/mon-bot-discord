"""
Cog INVITATIONS.
/invites (alias +i) /invite-leaderboard /invited-by /addbonusinvites /removebonusinvites /invitebonushistory

Détecte automatiquement quelle invitation a été utilisée à chaque arrivée (en comparant
le nombre d'utilisations avant/après), enregistre qui a invité qui, et suit les départs
pour distinguer les invitations "actives" des invitations "reparties".

Refonte visuelle (Phase 2, design premium/sombre) : /invites et /invite-leaderboard passent
maintenant par utils/design_system et affichent un détail réelles/fake/reparties/bonus,
façon InviteLogger. AUCUNE de ces valeurs n'est inventée :
- "fake" est déduit de l'âge réel du compte au moment de son arrivée (member.created_at,
  capturé et stocké dans member_invites.account_age_days) — jamais un compte n'est
  qualifié de fake sans cette donnée réelle (une ligne sans donnée reste "réelle" par
  défaut, pour ne jamais accuser à tort faute de preuve).
- "bonus" est un ajustement 100% manuel et traçable, accordé explicitement par un membre
  du staff via /addbonusinvites — jamais généré automatiquement par le bot.
Voir database/db.py::get_invite_breakdown() pour le détail du calcul.

⚠️ Détection de "doubles comptes" : Discord ne transmet JAMAIS l'adresse IP à un bot,
donc aucune détection fiable de multi-compte n'est possible. Ce cog applique seulement
une heuristique (plusieurs comptes très récents invités par la même personne en peu de
temps) qui peut se tromper — à traiter comme une alerte à vérifier, pas une preuve.
"""

import logging
import time

import discord
from discord import app_commands
from discord.ext import commands

import config
from cogs import language_runtime
from utils import embeds, helpers, checks, design_system
from utils import sentrix_panels as panels
from database.db import FAKE_INVITE_ACCOUNT_AGE_DAYS

logger = logging.getLogger("bot.invites")

# Fenêtre et seuil de l'heuristique "comptes suspects" : si le même invitant amène au
# moins ce nombre de comptes créés depuis moins de 3 jours, en moins de 10 minutes.
SUSPECT_WINDOW = 600
SUSPECT_THRESHOLD = 3
SUSPECT_ACCOUNT_AGE_DAYS = 3


class Invites(commands.Cog, name="Invites"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.invite_cache: dict[int, dict[str, int]] = {}
        self.recent_new_accounts: dict[tuple[int, int], list[float]] = {}

    async def cache_guild_invites(self, guild: discord.Guild):
        try:
            invites = await guild.invites()
            self.invite_cache[guild.id] = {inv.code: (inv.uses or 0) for inv in invites}
        except discord.Forbidden:
            self.invite_cache[guild.id] = {}

    @commands.Cog.listener()
    async def on_ready(self):
        for guild in self.bot.guilds:
            await self.cache_guild_invites(guild)

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild):
        await self.cache_guild_invites(guild)

    @commands.Cog.listener()
    async def on_invite_create(self, invite: discord.Invite):
        self.invite_cache.setdefault(invite.guild.id, {})[invite.code] = invite.uses or 0

    @commands.Cog.listener()
    async def on_invite_delete(self, invite: discord.Invite):
        self.invite_cache.get(invite.guild.id, {}).pop(invite.code, None)

    async def find_used_invite(self, guild: discord.Guild) -> discord.Invite | None:
        """Compare le nombre d'utilisations de chaque invitation avec le cache précédent :
        celle qui a augmenté est celle qui vient d'être utilisée. Nécessite que le bot ait
        la permission Gérer le serveur, sinon on ne peut simplement pas savoir (limite Discord)."""
        try:
            current = await guild.invites()
        except discord.Forbidden:
            return None
        cached = self.invite_cache.get(guild.id, {})
        used = None
        for inv in current:
            if (inv.uses or 0) > cached.get(inv.code, 0):
                used = inv
                break
        self.invite_cache[guild.id] = {inv.code: (inv.uses or 0) for inv in current}

        if used is None:
            # Une URL personnalisée (vanity) n'apparaît pas dans guild.invites() : sans
            # ce repli, une arrivée par le lien vanity restait « invitation inconnue ».
            # Elle n'a jamais d'invitant, et on n'en invente donc aucun.
            used = await self._invitation_vanity(guild)
        return used

    async def _invitation_vanity(self, guild: discord.Guild) -> discord.Invite | None:
        """Détecte une arrivée par l'URL personnalisée du serveur, si elle a servi."""
        if "VANITY_URL" not in getattr(guild, "features", ()):
            return None
        try:
            vanity = await guild.vanity_invite()
        except (discord.Forbidden, discord.HTTPException, AttributeError):
            return None
        if vanity is None:
            return None
        cle = f"vanity:{vanity.code}"
        cache = self.invite_cache.setdefault(guild.id, {})
        precedent = cache.get(cle, 0)
        actuel = vanity.uses or 0
        cache[cle] = actuel
        return vanity if actuel > precedent else None

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.bot:
            return
        guild = member.guild
        invite = await self.find_used_invite(guild)
        inviter_id = invite.inviter.id if invite and invite.inviter else None
        code = invite.code if invite else None
        # Âge réel du compte au moment de l'arrivée, capturé une fois pour toutes ici :
        # c'est cette valeur (et elle seule) qui permettra plus tard de distinguer une
        # invitation "réelle" d'une invitation "fake" sur /invites, sans jamais deviner.
        account_age_days = (discord.utils.utcnow() - member.created_at).days
        await self.bot.db.record_invite_join(guild.id, member.id, inviter_id, code, account_age_days)
        await self._journaliser_arrivee(member, code, inviter_id)

        if not inviter_id:
            return
        if account_age_days >= SUSPECT_ACCOUNT_AGE_DAYS:
            return

        key = (guild.id, inviter_id)
        t = time.time()
        hits = self.recent_new_accounts.setdefault(key, [])
        hits.append(t)
        self.recent_new_accounts[key] = [x for x in hits if t - x < SUSPECT_WINDOW]
        if len(self.recent_new_accounts[key]) >= SUSPECT_THRESHOLD:
            e = embeds.log_entry(
                "🕵️ Comptes suspects invités en rafale",
                config.COLOR_WARNING,
                cible=member,
                cible_label="👤 Dernier arrivant",
                extra={
                    "🔗 Invité par": f"<@{inviter_id}>\n`ID: {inviter_id}`",
                    "📊 Comptes très récents (< 3 jours) invités en 10 min": str(len(self.recent_new_accounts[key])),
                    "⚠️ Important": (
                        "Ceci est une estimation basée sur l'âge des comptes, PAS une preuve : "
                        "Discord ne transmet jamais l'adresse IP à un bot. Vérifiez manuellement "
                        "avant de sanctionner."
                    ),
                },
            )
            await helpers.send_log(self.bot, guild, "automod", e)
            self.recent_new_accounts[key] = []

    async def _journaliser_arrivee(
        self, member: discord.Member, code: str | None, inviter_id: int | None
    ) -> None:
        """Annonce l'arrivée dans le salon d'invitations CONFIGURÉ.

        Le salon n'est jamais codé en dur : il passe par la route de logs
        « dossiers », que le Setup relie au salon voulu (📬・invitations ou autre).
        Quand l'invitant est inconnu — permission manquante, lien vanity, ou deux
        arrivées simultanées — on l'écrit noir sur blanc plutôt que d'attribuer
        l'arrivée à quelqu'un au hasard.
        """
        guild = member.guild
        try:
            language = await language_runtime.get_language(self.bot, guild.id)
            english = language == language_runtime.LANG_EN
            if inviter_id:
                detail = await self.bot.db.get_invite_breakdown(guild.id, inviter_id)
                invitant = f"<@{inviter_id}>\n`ID: {inviter_id}`"
                total = (
                    f"**{detail['credited']}** credited invite(s)"
                    if english
                    else f"**{detail['credited']}** invitation(s) créditée(s)"
                )
            else:
                invitant = "Unknown" if english else "Inconnu"
                total = (
                    "Unattributed: SentriX could not determine which invite was used."
                    if english
                    else "Non attribué : SentriX n'a pas pu déterminer l'invitation utilisée."
                )

            extra = {
                ("🔗 Invited by" if english else "🔗 Invité par"): invitant,
                ("📊 Inviter total" if english else "📊 Total de l'invitant"): total,
                ("🎟️ Invite used" if english else "🎟️ Invitation utilisée"): (
                    f"`{code}`" if code else ("Unknown" if english else "Inconnue")
                ),
            }
            entree = embeds.log_entry(
                "📬 New member joined" if english else "📬 Nouvelle arrivée",
                config.COLOR_SUCCESS,
                cible=member,
                cible_label="👤 Member" if english else "👤 Membre",
                extra=extra,
            )
            # La clé d'événement empêche un double log si deux couches relaient l'arrivée.
            await helpers.send_log(
                self.bot,
                guild,
                "dossiers",
                entree,
                event_key=f"invite-join:{guild.id}:{member.id}",
            )
        except Exception:
            # Un journal en échec ne doit jamais empêcher l'enregistrement de l'arrivée,
            # déjà persisté juste avant cet appel.
            logger.exception("Log d'arrivée par invitation impossible (serveur %s).", guild.id)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        if member.bot:
            return
        await self.bot.db.mark_invite_left(member.guild.id, member.id)

    @commands.hybrid_command(
        name="invites",
        aliases=["i"],
        description="Afficher le détail des invitations d'un membre (réelles / fake / reparties / bonus).",
    )
    @app_commands.describe(membre="Le membre à consulter (vous par défaut)")
    async def invites_cmd(self, ctx: commands.Context, membre: discord.Member = None):
        membre = membre or ctx.author
        design = await self.bot.db.get_design_settings(ctx.guild.id)
        b = await self.bot.db.get_invite_breakdown(ctx.guild.id, membre.id)

        style = design_system.CATEGORY_STYLES["invites"]
        embed = design_system.create_embed(
            title=f"{style['emoji']} Invitations de {membre.display_name}",
            description=f"**{design_system.format_number(b['credited'])}** invitation(s) créditée(s) au total.",
            colour=design.get("primary_color", style["colour"]),
            user=membre if design.get("show_avatars", True) else None,
            thumbnail=membre.display_avatar.url if design.get("show_avatars", True) else None,
            footer=design.get("footer"),
        )
        embed.add_field(name="● Réelles", value=design_system.format_number(b["real"]), inline=True)
        embed.add_field(name="🕵️ Fake (compte suspect)", value=design_system.format_number(b["fake"]), inline=True)
        embed.add_field(name="🚪 Reparties", value=design_system.format_number(b["left"]), inline=True)
        embed.add_field(name="🎁 Bonus (staff)", value=design_system.format_number(b["bonus"]), inline=True)
        embed.add_field(name="📊 Total brut", value=design_system.format_number(b["total"]), inline=True)
        embed.add_field(name="🏆 Total crédité", value=f"**{design_system.format_number(b['credited'])}**", inline=True)
        embed.set_footer(text=(
            (design.get("footer") or "SentriX")
            + " • Fake = compte de moins de "
            + f"{FAKE_INVITE_ACCOUNT_AGE_DAYS} jours à l'arrivée. Ce n'est qu'une estimation, pas une preuve."
        ))
        await panels.envoyer(ctx, panels.depuis_embed(embed))

    @commands.hybrid_command(name="invite-leaderboard", description="Classement des membres ayant le plus invité (invitations créditées).")
    async def invite_leaderboard(self, ctx: commands.Context):
        design = await self.bot.db.get_design_settings(ctx.guild.id)
        rows = await self.bot.db.get_invite_leaderboard_credited(ctx.guild.id, 10)
        if not rows:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.info("Personne n'a encore d'invitation enregistrée sur ce serveur.")))
        style = design_system.CATEGORY_STYLES["invites"]
        lines = []
        for i, (inviter_id, b) in enumerate(rows, start=1):
            bonus_txt = f" (+{b['bonus']} bonus)" if b["bonus"] else ""
            lines.append(
                f"**{i}.** <@{inviter_id}> — **{design_system.format_number(b['credited'])}** créditée(s){bonus_txt} "
                f"• {b['real']} réelle(s), {b['fake']} fake, {b['left']} repartie(s)"
            )
        embed = design_system.create_embed(
            title=f"{style['emoji']} 🏆 Classement des invitations",
            description="\n".join(lines),
            colour=design.get("primary_color", style["colour"]),
            footer=design.get("footer"),
        )
        await panels.envoyer(ctx, panels.depuis_embed(embed))

    @commands.hybrid_command(name="invited-by", description="Voir qui a invité un membre.", with_app_command=False)
    @app_commands.describe(membre="Le membre à consulter")
    async def invited_by(self, ctx: commands.Context, membre: discord.Member):
        row = await self.bot.db.get_invited_by(ctx.guild.id, membre.id)
        if not row or not row["inviter_id"]:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.info(f'Je ne sais pas qui a invité {membre.mention} (invitation inconnue ou lien de vanité).')))
        await panels.envoyer(ctx, panels.depuis_embed(embeds.neutral("🔗 Origine de l'invitation", f"{membre.mention} a été invité par <@{row['inviter_id']}> le <t:{row['joined_at']}:D>.")))

    @commands.hybrid_command(
        name="invited-list",
        aliases=["invitedlist", "invite-list"],
        description="Lister les membres réellement attribués à un invitant.",
        with_app_command=False,
    )
    @app_commands.describe(membre="L'invitant à consulter")
    async def invited_list(self, ctx: commands.Context, membre: discord.Member = None):
        membre = membre or ctx.author
        rows = await self.bot.db.fetchall(
            "SELECT member_id,invite_code,joined_at,left_at,account_age_days "
            "FROM member_invites WHERE guild_id=? AND inviter_id=? "
            "ORDER BY joined_at DESC LIMIT 25",
            (ctx.guild.id, membre.id),
        )
        if not rows:
            return await panels.envoyer(
                ctx,
                panels.depuis_embed(embeds.info(f"Aucune invitation attribuée à {membre.mention}.")),
            )
        lines = []
        for row in rows:
            state = "reparti" if row["left_at"] is not None else "présent"
            age = row["account_age_days"]
            suspect = age is not None and int(age) < FAKE_INVITE_ACCOUNT_AGE_DAYS
            extra = " · compte récent" if suspect else ""
            code = f" · `{row['invite_code']}`" if row["invite_code"] else ""
            lines.append(
                f"<@{row['member_id']}> · {state}{extra}{code} · <t:{row['joined_at']}:R>"
            )
        embed = embeds.neutral(
            f"Invités par {membre.display_name}",
            "\n".join(lines)[:4000],
        )
        embed.set_footer(text=f"SentriX • {len(rows)} résultat(s) affiché(s) • données réellement enregistrées")
        await panels.envoyer(ctx, panels.depuis_embed(embed))

    @commands.hybrid_command(
        name="invite-codes",
        aliases=["invitecodes"],
        description="Afficher les codes d'invitation créés par un membre.",
        with_app_command=False,
    )
    @app_commands.describe(membre="Le créateur des invitations")
    async def invite_codes(self, ctx: commands.Context, membre: discord.Member = None):
        membre = membre or ctx.author
        try:
            invites = await ctx.guild.invites()
        except discord.Forbidden:
            return await panels.envoyer(
                ctx,
                panels.depuis_embed(embeds.error("SentriX a besoin de la permission Gérer le serveur pour lire les invitations.")),
            )
        own = [inv for inv in invites if inv.inviter and inv.inviter.id == membre.id]
        if not own:
            return await panels.envoyer(
                ctx,
                panels.depuis_embed(embeds.info(f"Aucun code d'invitation actif créé par {membre.mention}.")),
            )
        own.sort(key=lambda inv: int(inv.uses or 0), reverse=True)
        lines = [
            f"`{inv.code}` · **{int(inv.uses or 0)}** utilisation(s) · {getattr(inv.channel, 'mention', '#salon')}"
            for inv in own[:25]
        ]
        await panels.envoyer(
            ctx,
            panels.depuis_embed(embeds.neutral(f"Codes d'invitation de {membre.display_name}", "\n".join(lines))),
        )

    @commands.hybrid_command(
        name="sync-invites",
        aliases=["syncinvites", "invite-sync", "invites-sync", "resync-invites"],
        description="[Admin] Synchroniser l'inventaire actuel des codes d'invitation.",
        with_app_command=False,
    )
    @checks.is_owner_or_admin_for("configuration")
    async def sync_invites(self, ctx: commands.Context):
        try:
            invites = await ctx.guild.invites()
        except discord.Forbidden:
            return await panels.envoyer(
                ctx,
                panels.depuis_embed(embeds.error("SentriX a besoin de la permission Gérer le serveur pour lire les invitations.")),
            )
        now_ts = int(time.time())
        await self.bot.db.execute(
            "CREATE TABLE IF NOT EXISTS invite_code_meta ("
            "guild_id INTEGER NOT NULL, code TEXT NOT NULL, label TEXT NOT NULL DEFAULT '', "
            "last_seen_uses INTEGER NOT NULL DEFAULT 0, last_seen_at INTEGER NOT NULL DEFAULT 0, "
            "PRIMARY KEY (guild_id, code))"
        )
        for inv in invites:
            existing = await self.bot.db.fetchone(
                "SELECT label FROM invite_code_meta WHERE guild_id=? AND code=?",
                (ctx.guild.id, str(inv.code)),
            )
            label = str(existing["label"] or "") if existing else ""
            await self.bot.db.execute(
                "INSERT INTO invite_code_meta(guild_id,code,label,last_seen_uses,last_seen_at) "
                "VALUES(?,?,?,?,?) ON CONFLICT(guild_id,code) DO UPDATE SET "
                "last_seen_uses=excluded.last_seen_uses,last_seen_at=excluded.last_seen_at",
                (ctx.guild.id, str(inv.code), label, int(inv.uses or 0), now_ts),
            )
        await self.cache_guild_invites(ctx.guild)
        await panels.envoyer(
            ctx,
            panels.depuis_embed(
                embeds.success(
                    f"{len(invites)} code(s) synchronisé(s). "
                    "Aucune attribution historique de membre n'a été inventée."
                )
            ),
        )


    @commands.hybrid_command(
        name="invite-stats",
        aliases=["invitestats", "stats-invites"],
        description="Afficher les statistiques détaillées d'invitations d'un membre.",
        with_app_command=False,
    )
    @app_commands.describe(membre="Le membre à consulter")
    async def invite_stats(self, ctx: commands.Context, membre: discord.Member = None):
        membre = membre or ctx.author
        b = await self.bot.db.get_invite_breakdown(ctx.guild.id, membre.id)
        total = int(b["total"] or 0)
        active = max(0, total - int(b["left"] or 0))
        retention = round((active / total) * 100, 1) if total else 0.0
        latest = await self.bot.db.fetchone(
            "SELECT MAX(joined_at) AS ts FROM member_invites WHERE guild_id=? AND inviter_id=?",
            (ctx.guild.id, membre.id),
        )
        last_ts = int(latest["ts"] or 0) if latest else 0
        description = (
            f"Réelles : **{b['real']}**\n"
            f"Fake actives : **{b['fake']}**\n"
            f"Reparties : **{b['left']}**\n"
            f"Bonus staff : **{b['bonus']}**\n"
            f"Total brut : **{b['total']}**\n"
            f"Total crédité : **{b['credited']}**\n"
            f"Rétention : **{retention}%**"
        )
        if last_ts:
            description += f"\nDernière invitation attribuée : <t:{last_ts}:R>"
        await panels.envoyer(
            ctx,
            panels.depuis_embed(embeds.neutral(f"Statistiques d'invitations de {membre.display_name}", description)),
        )

    @commands.hybrid_command(
        name="invite-rank",
        aliases=["inviterank", "rank-invites"],
        description="Afficher le rang d'un membre dans le classement des invitations.",
        with_app_command=False,
    )
    @app_commands.describe(membre="Le membre à consulter")
    async def invite_rank(self, ctx: commands.Context, membre: discord.Member = None):
        membre = membre or ctx.author
        rows = await self.bot.db.fetchall(
            "SELECT DISTINCT inviter_id FROM member_invites WHERE guild_id=? AND inviter_id IS NOT NULL "
            "UNION SELECT DISTINCT user_id AS inviter_id FROM invite_bonuses WHERE guild_id=?",
            (ctx.guild.id, ctx.guild.id),
        )
        ranking = []
        for row in rows:
            inviter_id = int(row["inviter_id"])
            breakdown = await self.bot.db.get_invite_breakdown(ctx.guild.id, inviter_id)
            ranking.append((inviter_id, int(breakdown["credited"] or 0)))
        ranking.sort(key=lambda item: item[1], reverse=True)
        position = next((i for i, (uid, _score) in enumerate(ranking, start=1) if uid == membre.id), None)
        score = next((score for uid, score in ranking if uid == membre.id), 0)
        if position is None:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.info(f"{membre.mention} n'est pas encore classé.")))
        await panels.envoyer(
            ctx,
            panels.depuis_embed(
                embeds.neutral(
                    f"Rang de {membre.display_name}",
                    f"Position : **#{position}** sur **{len(ranking)}**\nInvitations créditées : **{score}**",
                )
            ),
        )

    @commands.hybrid_command(
        name="invite-history",
        aliases=["invitehistory", "history-invites"],
        description="Afficher les dernières invitations attribuées à un membre.",
        with_app_command=False,
    )
    @app_commands.describe(membre="L'invitant à consulter")
    async def invite_history(self, ctx: commands.Context, membre: discord.Member = None):
        membre = membre or ctx.author
        rows = await self.bot.db.fetchall(
            "SELECT member_id,invite_code,joined_at,left_at,account_age_days "
            "FROM member_invites WHERE guild_id=? AND inviter_id=? ORDER BY joined_at DESC LIMIT 15",
            (ctx.guild.id, membre.id),
        )
        if not rows:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.info(f"Aucun historique d'invitation pour {membre.mention}.")))
        lines = []
        for row in rows:
            status = "reparti" if row["left_at"] is not None else "présent"
            age = row["account_age_days"]
            recent = age is not None and int(age) < FAKE_INVITE_ACCOUNT_AGE_DAYS
            code = str(row["invite_code"] or "code inconnu")
            suffix = " · compte récent" if recent else ""
            lines.append(f"<@{row['member_id']}> · {code} · {status}{suffix} · <t:{row['joined_at']}:R>")
        await panels.envoyer(
            ctx,
            panels.depuis_embed(embeds.neutral(f"Historique d'invitations de {membre.display_name}", "\n".join(lines))),
        )

    @commands.hybrid_command(
        name="invite-info",
        aliases=["inviteinfo", "info-invite"],
        description="Afficher les informations d'un code d'invitation actif.",
        with_app_command=False,
    )
    async def invite_info(self, ctx: commands.Context, code: str):
        code = str(code or "").strip()
        try:
            invites = await ctx.guild.invites()
        except discord.Forbidden:
            return await panels.envoyer(
                ctx,
                panels.depuis_embed(embeds.error("SentriX a besoin de la permission Gérer le serveur pour lire les invitations.")),
            )
        invite = next((inv for inv in invites if str(inv.code) == code), None)
        if invite is None:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.info(f"Aucune invitation active trouvée avec le code {code}.")))
        tracked = await self.bot.db.fetchone(
            "SELECT COUNT(*) AS joins,SUM(CASE WHEN left_at IS NULL THEN 1 ELSE 0 END) AS active "
            "FROM member_invites WHERE guild_id=? AND invite_code=?",
            (ctx.guild.id, code),
        )
        description = (
            f"Code : **{invite.code}**\n"
            f"Créateur : {invite.inviter.mention if invite.inviter else 'Inconnu'}\n"
            f"Salon : {invite.channel.mention if invite.channel else 'Inconnu'}\n"
            f"Utilisations Discord : **{int(invite.uses or 0)}**\n"
            f"Arrivées suivies par SentriX : **{int(tracked['joins'] or 0) if tracked else 0}**\n"
            f"Encore présentes : **{int(tracked['active'] or 0) if tracked else 0}**"
        )
        await panels.envoyer(ctx, panels.depuis_embed(embeds.neutral("Informations de l'invitation", description)))

    @commands.hybrid_command(
        name="invite-sources",
        aliases=["invitesources", "sources-invites"],
        description="Afficher les sources d'arrivée réellement enregistrées.",
        with_app_command=False,
    )
    async def invite_sources(self, ctx: commands.Context):
        rows = await self.bot.db.fetchall(
            "SELECT inviter_id,invite_code FROM member_invites WHERE guild_id=?",
            (ctx.guild.id,),
        )
        attributed = sum(1 for r in rows if r["inviter_id"] is not None and r["invite_code"])
        code_only = sum(1 for r in rows if r["inviter_id"] is None and r["invite_code"])
        unknown = sum(1 for r in rows if not r["invite_code"])
        await panels.envoyer(
            ctx,
            panels.depuis_embed(
                embeds.neutral(
                    "Sources d'arrivée",
                    f"Invitation attribuée : **{attributed}**\n"
                    f"Code sans invitant / vanity possible : **{code_only}**\n"
                    f"Source inconnue : **{unknown}**\n"
                    f"Total observé : **{len(rows)}**",
                )
            ),
        )

    @commands.hybrid_command(
        name="invite-retention",
        aliases=["inviteretention", "retention-invites"],
        description="Afficher le taux de rétention des membres invités.",
        with_app_command=False,
    )
    @app_commands.describe(membre="L'invitant à consulter")
    async def invite_retention(self, ctx: commands.Context, membre: discord.Member = None):
        membre = membre or ctx.author
        stats = await self.bot.db.get_invite_stats(ctx.guild.id, membre.id)
        total = int(stats["total"] or 0)
        active = int(stats["active"] or 0)
        left = int(stats["left"] or 0)
        retention = round((active / total) * 100, 1) if total else 0.0
        await panels.envoyer(
            ctx,
            panels.depuis_embed(
                embeds.neutral(
                    f"Rétention de {membre.display_name}",
                    f"Invités suivis : **{total}**\nEncore présents : **{active}**\nRepartis : **{left}**\nRétention : **{retention}%**",
                )
            ),
        )

    @commands.hybrid_command(
        name="invite-label",
        aliases=["invitelabel", "label-invite"],
        description="[Admin] Donner un label interne à un code d'invitation.",
        with_app_command=False,
    )
    @checks.is_owner_or_admin_for("configuration")
    async def invite_label(self, ctx: commands.Context, code: str, *, label: str):
        code = str(code or "").strip()
        label = str(label or "").strip()
        if not code or len(code) > 64:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error("Code d'invitation invalide.")))
        if not label or len(label) > 80:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error("Le label doit contenir entre 1 et 80 caractères.")))
        await self.bot.db.execute(
            "CREATE TABLE IF NOT EXISTS invite_code_meta ("
            "guild_id INTEGER NOT NULL, code TEXT NOT NULL, label TEXT NOT NULL DEFAULT '', "
            "last_seen_uses INTEGER NOT NULL DEFAULT 0, last_seen_at INTEGER NOT NULL DEFAULT 0, "
            "PRIMARY KEY (guild_id, code))"
        )
        await self.bot.db.execute(
            "INSERT INTO invite_code_meta(guild_id,code,label,last_seen_uses,last_seen_at) "
            "VALUES(?,?,?,0,0) ON CONFLICT(guild_id,code) DO UPDATE SET label=excluded.label",
            (ctx.guild.id, code, label),
        )
        await panels.envoyer(ctx, panels.depuis_embed(embeds.success(f"Label **{label}** enregistré pour {code}.")))

    @commands.hybrid_command(
        name="invite-unlabel",
        aliases=["inviteunlabel", "unlabel-invite"],
        description="[Admin] Retirer le label interne d'un code d'invitation.",
        with_app_command=False,
    )
    @checks.is_owner_or_admin_for("configuration")
    async def invite_unlabel(self, ctx: commands.Context, code: str):
        code = str(code or "").strip()
        try:
            await self.bot.db.execute(
                "UPDATE invite_code_meta SET label='' WHERE guild_id=? AND code=?",
                (ctx.guild.id, code),
            )
        except Exception:
            pass
        await panels.envoyer(ctx, panels.depuis_embed(embeds.success(f"Label retiré pour {code}.")))

    @commands.hybrid_command(
        name="invite-search",
        aliases=["invitesearch", "search-invites"],
        description="Rechercher un code, un invité ou un invitant dans l'historique.",
        with_app_command=False,
    )
    async def invite_search(self, ctx: commands.Context, recherche: str):
        term = str(recherche or "").strip()
        if not term:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error("Indiquez un code ou un identifiant Discord.")))
        params = [ctx.guild.id]
        where = ["guild_id=?"]
        if term.isdigit():
            where.append("(member_id=? OR inviter_id=?)")
            params.extend([int(term), int(term)])
        else:
            where.append("invite_code LIKE ?")
            params.append("%" + term + "%")
        rows = await self.bot.db.fetchall(
            "SELECT member_id,inviter_id,invite_code,joined_at,left_at "
            "FROM member_invites WHERE " + " AND ".join(where) + " ORDER BY joined_at DESC LIMIT 20",
            tuple(params),
        )
        if not rows:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.info("Aucun résultat dans l'historique des invitations.")))
        lines = []
        for row in rows:
            inviter = f"<@{row['inviter_id']}>" if row["inviter_id"] else "inconnu"
            code = str(row["invite_code"] or "code inconnu")
            lines.append(f"<@{row['member_id']}> · invité par {inviter} · {code} · <t:{row['joined_at']}:R>")
        await panels.envoyer(ctx, panels.depuis_embed(embeds.neutral("Recherche invitations", "\n".join(lines)[:4000])))


    @commands.hybrid_command(
        name="reset-invites",
        aliases=["resetinvites", "invites-reset"],
        description="[Admin] Réinitialiser toutes les données d'invitations du serveur.",
        with_app_command=False,
    )
    @checks.is_owner_or_admin_for("configuration")
    async def reset_invites(self, ctx: commands.Context):
        tracked = await self.bot.db.fetchone(
            "SELECT COUNT(*) AS c FROM member_invites WHERE guild_id=?",
            (ctx.guild.id,),
        )
        bonuses = await self.bot.db.fetchone(
            "SELECT COUNT(*) AS c FROM invite_bonuses WHERE guild_id=?",
            (ctx.guild.id,),
        )
        if not await helpers.double_confirm_destructive(
            ctx,
            "réinitialiser toutes les invitations du serveur",
            detail=(
                f"{int(tracked['c'] or 0) if tracked else 0} suivi(s) d'arrivée et "
                f"{int(bonuses['c'] or 0) if bonuses else 0} ajustement(s) bonus seront supprimés. "
                "Les codes Discord eux-mêmes ne seront pas supprimés."
            ),
        ):
            return

        await self.bot.db.execute("DELETE FROM member_invites WHERE guild_id=?", (ctx.guild.id,))
        await self.bot.db.execute("DELETE FROM invite_bonuses WHERE guild_id=?", (ctx.guild.id,))
        try:
            await self.bot.db.execute("DELETE FROM invite_code_meta WHERE guild_id=?", (ctx.guild.id,))
        except Exception:
            pass
        try:
            await self.bot.db.execute("DELETE FROM invite_leaderboard_hidden WHERE guild_id=?", (ctx.guild.id,))
        except Exception:
            pass

        await self.cache_guild_invites(ctx.guild)
        await panels.envoyer(
            ctx,
            panels.depuis_embed(
                embeds.success(
                    "Les statistiques, bonus, labels et préférences de classement des invitations "
                    "ont été réinitialisés. Les codes Discord actifs ont été conservés et le cache "
                    "a été resynchronisé pour repartir proprement."
                )
            ),
        )

    # -------------------------------------------------------------- Bonus (staff)

    @commands.hybrid_command(
        name="addbonusinvites",
        description="[Admin] Accorder manuellement des invitations bonus à un membre (concours, événement...).",
        with_app_command=False,
    )
    @checks.is_owner_or_admin_for("configuration")
    @app_commands.describe(membre="Le membre à créditer", montant="Nombre d'invitations bonus (peut être négatif pour retirer)", raison="Raison de cet ajustement")
    async def addbonusinvites(self, ctx: commands.Context, membre: discord.Member, montant: int, *, raison: str = "Non précisée"):
        if montant == 0:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Le montant ne peut pas être zéro.')))
        await self.bot.db.grant_invite_bonus(ctx.guild.id, membre.id, montant, ctx.author.id, raison)
        b = await self.bot.db.get_invite_breakdown(ctx.guild.id, membre.id)
        verbe = "accordé" if montant > 0 else "retiré"
        await panels.envoyer(ctx, panels.depuis_embed(embeds.success(f"🎁 {abs(montant)} invitation(s) bonus {verbe}(s) à {membre.mention} — raison : {raison}\nTotal bonus de {membre.mention} : **{design_system.format_number(b['bonus'])}** • Total crédité : **{design_system.format_number(b['credited'])}**")))

    @commands.hybrid_command(
        name="removebonusinvites",
        description="[Admin] Retirer des invitations bonus à un membre (raccourci de /addbonusinvites avec un montant négatif).",
        with_app_command=False,
    )
    @checks.is_owner_or_admin_for("configuration")
    @app_commands.describe(membre="Le membre concerné", montant="Nombre d'invitations bonus à retirer (positif)", raison="Raison de ce retrait")
    async def removebonusinvites(self, ctx: commands.Context, membre: discord.Member, montant: int, *, raison: str = "Non précisée"):
        if montant <= 0:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Indiquez un montant positif à retirer (ex: `10`).')))
        await self.bot.db.grant_invite_bonus(ctx.guild.id, membre.id, -montant, ctx.author.id, raison)
        b = await self.bot.db.get_invite_breakdown(ctx.guild.id, membre.id)
        await panels.envoyer(ctx, panels.depuis_embed(embeds.success(f"🎁 {montant} invitation(s) bonus retirée(s) à {membre.mention} — raison : {raison}\nTotal bonus de {membre.mention} : **{design_system.format_number(b['bonus'])}** • Total crédité : **{design_system.format_number(b['credited'])}**")))

    @commands.hybrid_command(
        name="invitebonushistory",
        description="[Admin] Voir l'historique des invitations bonus accordées à un membre.",
        with_app_command=False,
    )
    @checks.is_owner_or_admin_for("configuration")
    @app_commands.describe(membre="Le membre concerné")
    async def invitebonushistory(self, ctx: commands.Context, membre: discord.Member):
        rows = await self.bot.db.get_invite_bonus_history(ctx.guild.id, membre.id, 10)
        if not rows:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.info(f'Aucun ajustement bonus enregistré pour {membre.mention}.')))
        lines = [
            f"<t:{r['created_at']}:d> — **{'+' if r['amount'] >= 0 else ''}{r['amount']}** par <@{r['granted_by']}> — {r['reason'] or 'Non précisée'}"
            for r in rows
        ]
        await panels.envoyer(ctx, panels.depuis_embed(embeds.neutral(f'🎁 Historique bonus de {membre.display_name}', '\n'.join(lines))))


async def setup(bot: commands.Bot):
    await bot.add_cog(Invites(bot))
