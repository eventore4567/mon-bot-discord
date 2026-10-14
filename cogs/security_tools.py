"""
Cog OUTILS DE SÉCURITÉ AVANCÉS.
/quarantine /unquarantine /role-snapshot /role-restore /permission-audit
/server-backup /server-restore

Ces commandes complètent AutoMod (cogs/automod.py, protection automatique) avec des
outils MANUELS pour réagir à un incident (raid, compromission de compte, erreur de
permissions) : isoler un membre suspect, sauvegarder/restaurer des rôles, auditer les
permissions dangereuses du serveur, et sauvegarder/restaurer la structure du serveur.

Refonte visuelle (Phase 3, design premium/sombre) : /permission-audit affiche maintenant
un "score de sécurité" sur 100 en plus de la liste des points relevés. Ce score est un
calcul 100% déterministe et transparent à partir des MÊMES points déjà détectés par
l'audit (rien n'est ajouté ni deviné) : chaque point 🔴 Critique retire 30 points, chaque
point 🟠 À surveiller retire 15, chaque point 🟡 Information retire 5, plancher à 0. Voir
_compute_security_score() pour le détail — la règle de calcul est documentée pour rester
vérifiable, pas une "boîte noire".
"""

import json
import logging
from datetime import timedelta

import discord
from discord import app_commands
from discord.ext import commands, tasks

from utils import embeds, checks, helpers, design_system
from utils import sentrix_panels as panels
from database.db import now

logger = logging.getLogger("bot.security-tools")

SCORE_DEDUCTIONS = {"🔴 Critique": 30, "🟠 À surveiller": 15, "🟡 Information": 5}

# Permissions considérées "dangereuses" si accordées à @everyone ou à un rôle très
# largement distribué : c'est ce que /permission-audit vérifie en priorité.
DANGEROUS_PERMISSIONS = [
    "administrator", "ban_members", "kick_members", "manage_guild", "manage_roles",
    "manage_channels", "manage_webhooks", "manage_messages", "mention_everyone",
    "moderate_members", "manage_nicknames", "manage_emojis_and_stickers",
]

DANGEROUS_LABELS = {
    "administrator": "Administrateur", "ban_members": "Bannir des membres",
    "kick_members": "Expulser des membres", "manage_guild": "Gérer le serveur",
    "manage_roles": "Gérer les rôles", "manage_channels": "Gérer les salons",
    "manage_webhooks": "Gérer les webhooks", "manage_messages": "Gérer les messages",
    "mention_everyone": "Mentionner @everyone", "moderate_members": "Timeout/Modérer",
    "manage_nicknames": "Gérer les pseudos", "manage_emojis_and_stickers": "Gérer les emojis",
}


class Security(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.check_quarantines.start()

    def cog_unload(self):
        self.check_quarantines.cancel()

    async def log_action(self, guild: discord.Guild, embed: discord.Embed):
        await helpers.send_log(self.bot, guild, "moderation", embed)

    # ---------------------------------------------------------------- QUARANTAINE

    @tasks.loop(minutes=1)
    async def check_quarantines(self):
        rows = await self.bot.db.fetchall(
            "SELECT * FROM quarantines WHERE active = 1 AND expires_at <= ?", (now(),)
        )
        for row in rows:
            guild = self.bot.get_guild(row["guild_id"])
            if not guild:
                await self.bot.db.execute("UPDATE quarantines SET active = 0 WHERE id = ?", (row["id"],))
                continue
            member = guild.get_member(row["user_id"])
            if member:
                await self._restore_from_quarantine(guild, member, row)
            await self.bot.db.execute("UPDATE quarantines SET active = 0 WHERE id = ?", (row["id"],))

    @check_quarantines.before_loop
    async def before_check_quarantines(self):
        await self.bot.wait_until_ready()

    async def _restore_from_quarantine(self, guild: discord.Guild, member: discord.Member, quarantine_row):
        snapshot = await self.bot.db.fetchone(
            "SELECT * FROM role_snapshots WHERE id = ?", (quarantine_row["snapshot_id"],)
        )
        try:
            await member.timeout(None, reason="Fin de quarantaine")
        except discord.HTTPException:
            pass
        restored = 0
        if snapshot and snapshot["role_ids"]:
            role_ids = [int(x) for x in snapshot["role_ids"].split(",") if x.strip().isdigit()]
            roles = [guild.get_role(rid) for rid in role_ids]
            roles = [r for r in roles if r and r < guild.me.top_role]
            if roles:
                try:
                    await member.add_roles(*roles, reason="Fin de quarantaine : restauration des rôles")
                    restored = len(roles)
                except discord.HTTPException:
                    pass
        e = embeds.log_entry(
            "🔓 Fin de quarantaine", 0x57F287, cible=member,
            extra={"📄 Détail": f"Rôles restaurés automatiquement : {restored}"},
        )
        await self.log_action(guild, e)

    @commands.hybrid_command(
        name="quarantine",
        aliases=["quar"],
        description="Isoler un membre suspect : rôles retirés (sauvegardés) + muet pendant une durée donnée.",
    )
    @app_commands.describe(membre="Le membre à mettre en quarantaine", duree="Durée (ex: 7d, 12h, 30m)", raison="La raison")
    @checks.has_permission_or_modrole("moderate_members")
    async def quarantine(self, ctx: commands.Context, membre: discord.Member, duree: str, *, raison: str = "Aucune raison fournie"):
        err = checks.check_hierarchy(ctx.author, membre)
        if err:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error(err)))
        err = checks.check_bot_hierarchy(ctx.guild, membre)
        if err:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error(err)))

        seconds = helpers.parse_duration(duree)
        if seconds is None or seconds > 2419200:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Durée invalide (maximum 28 jours, limite du timeout Discord). Exemples : `7d`, `12h`, `30m`.')))

        existing = await self.bot.db.fetchone(
            "SELECT * FROM quarantines WHERE guild_id = ? AND user_id = ? AND active = 1", (ctx.guild.id, membre.id)
        )
        if existing:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.warning(f"{membre.mention} est déjà en quarantaine (jusqu'à <t:{existing['expires_at']}:R>).\nPour la lever tout de suite : `+unquarantine @{membre.name}`.")))

        role_ids = [str(r.id) for r in membre.roles if r != ctx.guild.default_role]
        cur = await self.bot.db.execute(
            "INSERT INTO role_snapshots (guild_id, user_id, role_ids, label, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (ctx.guild.id, membre.id, ",".join(role_ids), "Avant quarantaine", ctx.author.id, now()),
        )
        snapshot_id = cur.lastrowid

        if role_ids:
            try:
                await membre.edit(roles=[], reason=f"Quarantaine par {ctx.author} : {raison}")
            except discord.HTTPException:
                return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Impossible de retirer les rôles de ce membre (permissions).')))

        until = discord.utils.utcnow() + timedelta(seconds=seconds)
        try:
            await membre.timeout(until, reason=f"Quarantaine : {raison}")
        except discord.HTTPException:
            pass

        await self.bot.db.execute(
            "INSERT INTO quarantines (guild_id, user_id, snapshot_id, reason, moderator_id, created_at, expires_at, active) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 1)",
            (ctx.guild.id, membre.id, snapshot_id, raison, ctx.author.id, now(), now() + seconds),
        )

        try:
            await panels.envoyer(membre, panels.depuis_embed(embeds.warning(f'Vous avez été placé en **quarantaine** sur **{ctx.guild.name}** pour {helpers.format_duration(seconds)}.\nRaison : {raison}\nVos rôles ont été sauvegardés et seront restaurés automatiquement à la fin de la quarantaine.')))
        except discord.Forbidden:
            pass

        e = embeds.log_entry(
            "🔒 Quarantaine", 0xED4245, cible=membre, acteur=ctx.author, raison=raison,
            extra={"⏱️ Durée": helpers.format_duration(seconds), "📸 Rôles sauvegardés": f"{len(role_ids)} (snapshot #{snapshot_id})"},
        )
        await panels.envoyer(ctx, panels.depuis_embed(e))
        await self.log_action(ctx.guild, e)

    @commands.hybrid_command(
        name="unquarantine",
        aliases=["unquar"],
        description="Lever immédiatement la quarantaine d'un membre et lui rendre ses rôles.",
        with_app_command=False,
    )
    @app_commands.describe(membre="Le membre à sortir de quarantaine")
    @checks.has_permission_or_modrole("moderate_members")
    async def unquarantine(self, ctx: commands.Context, membre: discord.Member):
        row = await self.bot.db.fetchone(
            "SELECT * FROM quarantines WHERE guild_id = ? AND user_id = ? AND active = 1", (ctx.guild.id, membre.id)
        )
        if not row:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error(f"{membre.mention} n'est pas en quarantaine.")))
        await self._restore_from_quarantine(ctx.guild, membre, row)
        await self.bot.db.execute("UPDATE quarantines SET active = 0 WHERE id = ?", (row["id"],))
        await panels.envoyer(ctx, panels.depuis_embed(embeds.success(f'🔓 Quarantaine levée pour {membre.mention} — ses rôles lui ont été rendus.')))

    # ---------------------------------------------------------------- SNAPSHOTS DE RÔLES

    @commands.hybrid_command(
        name="role-snapshot",
        aliases=["rolesave"], description="Sauvegarder les rôles actuels d'un membre (pour restauration future).",
        with_app_command=False,
    )
    @app_commands.describe(membre="Le membre dont sauvegarder les rôles")
    @checks.has_permission_or_modrole("manage_roles")
    async def role_snapshot(self, ctx: commands.Context, membre: discord.Member):
        role_ids = [str(r.id) for r in membre.roles if r != ctx.guild.default_role]
        cur = await self.bot.db.execute(
            "INSERT INTO role_snapshots (guild_id, user_id, role_ids, label, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (ctx.guild.id, membre.id, ",".join(role_ids), "Manuel", ctx.author.id, now()),
        )
        e = embeds.success(
            f"📸 Snapshot **#{cur.lastrowid}** enregistré pour {membre.mention} — **{len(role_ids)}** rôle(s).\n"
            f"Utilisez `+role-restore @{membre.name} {cur.lastrowid}` pour les restaurer plus tard."
        )
        if role_ids:
            roles_text = ", ".join(f"<@&{rid}>" for rid in role_ids[:20])
            e.add_field(name="Rôles sauvegardés", value=roles_text, inline=False)
        await panels.envoyer(ctx, panels.depuis_embed(e))

    @commands.hybrid_command(
        name="role-restore",
        aliases=["roleload"], description="Restaurer les rôles d'un membre depuis un snapshot précédent.",
        with_app_command=False,
    )
    @app_commands.describe(membre="Le membre concerné", snapshot_id="L'identifiant du snapshot (voir +role-snapshot)")
    @checks.has_permission_or_modrole("manage_roles")
    async def role_restore(self, ctx: commands.Context, membre: discord.Member, snapshot_id: int):
        snapshot = await self.bot.db.fetchone(
            "SELECT * FROM role_snapshots WHERE id = ? AND guild_id = ?", (snapshot_id, ctx.guild.id)
        )
        if not snapshot:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error(f'Aucun snapshot #{snapshot_id} trouvé sur ce serveur.')))
        if snapshot["user_id"] != membre.id:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error(f'Le snapshot #{snapshot_id} appartient à un autre membre (protection anti-erreur).')))

        role_ids = [int(x) for x in snapshot["role_ids"].split(",") if x.strip().isdigit()]
        added, skipped = [], []
        for rid in role_ids:
            role = ctx.guild.get_role(rid)
            if not role:
                skipped.append(f"`{rid}` (rôle supprimé)")
                continue
            if role in membre.roles:
                continue
            if role >= ctx.guild.me.top_role:
                skipped.append(f"{role.mention} (hiérarchie)")
                continue
            added.append(role)

        if added:
            try:
                await membre.add_roles(*added, reason=f"Restauration du snapshot #{snapshot_id} par {ctx.author}")
            except discord.HTTPException:
                return await panels.envoyer(ctx, panels.depuis_embed(embeds.error("Échec lors de l'attribution des rôles (permissions).")))

        e = embeds.success(f"🔄 Snapshot **#{snapshot_id}** restauré pour {membre.mention}.")
        e.add_field(name="Rôles ajoutés", value=", ".join(r.mention for r in added) if added else "Aucun (déjà à jour)", inline=False)
        if skipped:
            e.add_field(name="Ignorés", value=", ".join(skipped), inline=False)
        await panels.envoyer(ctx, panels.depuis_embed(e))
        await self.log_action(ctx.guild, embeds.log_entry(
            "🔄 Restauration de rôles", 0x5865F2, cible=membre, acteur=ctx.author,
            extra={"📸 Snapshot": f"#{snapshot_id}", "● Rôles ajoutés": str(len(added))},
        ))

    # ---------------------------------------------------------------- AUDIT DE PERMISSIONS

    @commands.hybrid_command(
        name="permission-audit",
        aliases=["perms"], description="Analyser les permissions du serveur et repérer les réglages dangereux.",
    )
    @checks.is_owner_or_admin_for("securite")
    async def permission_audit(self, ctx: commands.Context):
        await ctx.defer() if ctx.interaction else None
        guild = ctx.guild
        findings = []

        everyone_perms = guild.default_role.permissions
        everyone_dangerous = [p for p in DANGEROUS_PERMISSIONS if getattr(everyone_perms, p, False)]
        if everyone_dangerous:
            findings.append((
                "🔴 Critique",
                f"**@everyone** possède : {', '.join(DANGEROUS_LABELS[p] for p in everyone_dangerous)}. "
                "N'importe quel membre (y compris un compte piraté ou un raider) en profite automatiquement.",
            ))

        admin_roles = [r for r in guild.roles if r.permissions.administrator and not r.managed and r != guild.default_role]
        if len(admin_roles) > 3:
            findings.append((
                "🟠 À surveiller",
                f"**{len(admin_roles)} rôles** ont la permission Administrateur : "
                f"{', '.join(r.mention for r in admin_roles[:10])}. Plus il y a de rôles admin, plus la surface d'attaque est grande.",
            ))

        admin_members = {m for r in admin_roles for m in r.members}
        if len(admin_members) > max(5, guild.member_count // 100):
            findings.append((
                "🟠 À surveiller",
                f"**{len(admin_members)} membres** ont un rôle Administrateur — c'est beaucoup pour un serveur "
                f"de {guild.member_count} membres. Vérifiez que ce sont bien tous des membres de confiance.",
            ))

        risky_widespread = []
        for role in guild.roles:
            if role == guild.default_role or role.permissions.administrator:
                continue
            dangerous = [p for p in DANGEROUS_PERMISSIONS if getattr(role.permissions, p, False)]
            if dangerous and len(role.members) > max(10, guild.member_count // 20):
                risky_widespread.append(f"{role.mention} ({len(role.members)} membres) : {', '.join(DANGEROUS_LABELS[p] for p in dangerous)}")
        if risky_widespread:
            findings.append(("🟡 Information", "\n".join(risky_widespread[:5])))

        bot_position = guild.me.top_role.position
        highest_position = max((r.position for r in guild.roles if not r.is_bot_managed()), default=0)
        if bot_position < highest_position * 0.7:
            findings.append((
                "🟡 Information",
                f"Le rôle du bot ({guild.me.top_role.mention}) est assez bas dans la hiérarchie — "
                "certaines commandes de modération (ban, mute, quarantaine...) pourraient échouer sur des membres "
                "ayant un rôle plus haut. Montez-le si possible.",
            ))

        conf = await self.bot.db.get_guild_config(guild.id)
        if not conf or not conf["mod_role"]:
            findings.append(("🟡 Information", "Aucun rôle staff n'est configuré (`/setmodrole`) — certaines commandes de modération se basent uniquement sur les permissions Discord natives."))

        score = self._compute_security_score(findings)
        style = design_system.CATEGORY_STYLES["security"]
        if score >= 80:
            score_colour, score_label = design_system.COLORS.success, "🟢 Bon niveau de sécurité"
        elif score >= 50:
            score_colour, score_label = design_system.COLORS.warning, "🟠 Des points à corriger"
        else:
            score_colour, score_label = design_system.COLORS.danger, "🔴 Sécurité fragile — à corriger rapidement"

        e = design_system.create_embed(
            title=f"{style['emoji']} Tableau de bord sécurité",
            description=f"**{score} / 100** — {score_label}",
            colour=score_colour,
            footer=f"SentriX • {len(findings)} point(s) relevé(s) sur {len(guild.roles)} rôles",
        )
        if not findings:
            e.add_field(name="● Résultat", value="Aucun problème de permission évident détecté. Bon travail !", inline=False)
        else:
            for label, text in findings:
                e.add_field(name=label, value=helpers.truncate(text, 1024), inline=False)
        await panels.envoyer(ctx, panels.depuis_embed(e))

    @staticmethod
    def _compute_security_score(findings: list[tuple[str, str]]) -> int:
        """Score déterministe à partir des points RÉELLEMENT détectés par l'audit ci-dessus
        (aucune valeur inventée) : 100 au départ, déductions par sévérité, plancher à 0.
        Voir SCORE_DEDUCTIONS en tête de fichier pour le barème exact."""
        score = 100
        for label, _ in findings:
            score -= SCORE_DEDUCTIONS.get(label, 5)
        return max(0, score)

    # ---------------------------------------------------------------- BACKUP / RESTORE SERVEUR

    def _snapshot_overwrites(self, channel) -> list:
        result = []
        for target, overwrite in channel.overwrites.items():
            allow, deny = overwrite.pair()
            result.append({
                "type": "role" if isinstance(target, discord.Role) else "member",
                "name": target.name if isinstance(target, discord.Role) else str(target.id),
                "allow": allow.value,
                "deny": deny.value,
            })
        return result

    @commands.hybrid_command(
        name="server-backup", description="Sauvegarder la structure actuelle du serveur (rôles, catégories, salons).",
        with_app_command=False,
    )
    @app_commands.describe(label="Un nom pour retrouver facilement cette sauvegarde")
    @checks.is_owner_or_admin_for("securite")
    async def server_backup(self, ctx: commands.Context, *, label: str = ""):
        await ctx.defer() if ctx.interaction else None
        guild = ctx.guild
        label = label or f"Sauvegarde du {discord.utils.utcnow():%d/%m/%Y}"

        data = {
            "roles": [
                {
                    "name": r.name, "color": r.color.value, "hoist": r.hoist,
                    "mentionable": r.mentionable, "permissions": r.permissions.value, "position": r.position,
                }
                for r in guild.roles if r.name != "@everyone" and not r.managed
            ],
            "categories": [],
        }
        for category in guild.categories:
            cat_data = {
                "name": category.name, "position": category.position,
                "overwrites": self._snapshot_overwrites(category),
                "channels": [],
            }
            for ch in category.channels:
                ch_data = {
                    "name": ch.name,
                    "type": "voice" if isinstance(ch, discord.VoiceChannel) else "text",
                    "position": ch.position,
                    "overwrites": self._snapshot_overwrites(ch),
                }
                if isinstance(ch, discord.TextChannel):
                    ch_data["topic"] = ch.topic
                    ch_data["nsfw"] = ch.nsfw
                    ch_data["slowmode_delay"] = ch.slowmode_delay
                cat_data["channels"].append(ch_data)
            data["categories"].append(cat_data)

        no_category_channels = [ch for ch in guild.channels if ch.category is None and isinstance(ch, (discord.TextChannel, discord.VoiceChannel))]
        data["uncategorized"] = [
            {"name": ch.name, "type": "voice" if isinstance(ch, discord.VoiceChannel) else "text", "position": ch.position}
            for ch in no_category_channels
        ]

        cur = await self.bot.db.execute(
            "INSERT INTO server_backups (guild_id, label, data_json, created_by, created_at) VALUES (?, ?, ?, ?, ?)",
            (guild.id, label, json.dumps(data), ctx.author.id, now()),
        )
        e = embeds.success(
            f"💾 Sauvegarde **#{cur.lastrowid}** (« {label} ») enregistrée : "
            f"**{len(data['roles'])}** rôles, **{len(data['categories'])}** catégories, "
            f"**{sum(len(c['channels']) for c in data['categories']) + len(data['uncategorized'])}** salons."
        )
        e.add_field(name="Restaurer plus tard", value=f"`+server-restore {cur.lastrowid}`", inline=False)
        await panels.envoyer(ctx, panels.depuis_embed(e))

    # ---------------------------------------------------------------- JOURNAL D'AUDIT
    # Une sauvegarde ne sert que si quelqu'un a pensé à la faire AVANT. Le
    # journal d'audit Discord, lui, existe toujours : chaque suppression de
    # salon ou de rôle y laisse le nom et les réglages de l'objet supprimé.
    # C'est donc le seul filet disponible après un nuke sur un serveur qui
    # n'avait aucune sauvegarde.
    FENETRE_AUDIT_HEURES_DEFAUT = 24
    LIMITE_ENTREES_AUDIT = 400

    async def _suppressions_recentes(self, guild: discord.Guild, heures: int) -> dict:
        """Relit le journal d'audit et reconstitue ce qui a été supprimé.

        Ne renvoie que ce qui n'existe plus aujourd'hui : un salon supprimé
        puis recréé à la main ne doit pas être proposé une deuxième fois.
        """
        depuis = discord.utils.utcnow() - timedelta(hours=heures)
        roles_vivants = {r.name for r in guild.roles}
        salons_vivants = {c.name for c in guild.channels}

        roles: list[dict] = []
        categories: list[dict] = []
        salons: list[dict] = []
        auteurs: dict[int, int] = {}
        premiere = derniere = None

        paires = (
            (discord.AuditLogAction.role_delete, "role"),
            (discord.AuditLogAction.channel_delete, "channel"),
        )
        for action, genre in paires:
            try:
                entrees = [
                    e async for e in guild.audit_logs(limit=self.LIMITE_ENTREES_AUDIT, action=action)
                    if e.created_at >= depuis
                ]
            except discord.Forbidden:
                raise
            except discord.HTTPException:
                logger.warning("Journal d'audit illisible sur guild=%s action=%s", guild.id, action, exc_info=True)
                continue

            for entree in entrees:
                avant = entree.before
                nom = getattr(avant, "name", None)
                if not nom:
                    continue
                acteur = getattr(entree.user, "id", None)
                if acteur is not None:
                    auteurs[acteur] = auteurs.get(acteur, 0) + 1
                premiere = entree.created_at if premiere is None else min(premiere, entree.created_at)
                derniere = entree.created_at if derniere is None else max(derniere, entree.created_at)

                if genre == "role":
                    if nom in roles_vivants or nom == "@everyone":
                        continue
                    roles_vivants.add(nom)  # une seule recréation par nom
                    roles.append({
                        "name": nom,
                        "permissions": int(getattr(getattr(avant, "permissions", None), "value", 0) or 0),
                        "color": int(getattr(getattr(avant, "colour", None), "value", 0) or 0),
                        "hoist": bool(getattr(avant, "hoist", False)),
                        "mentionable": bool(getattr(avant, "mentionable", False)),
                    })
                    continue

                if nom in salons_vivants:
                    continue
                salons_vivants.add(nom)
                type_salon = getattr(avant, "type", None)
                fiche = {
                    "name": nom,
                    "topic": getattr(avant, "topic", None),
                    "nsfw": bool(getattr(avant, "nsfw", False)),
                }
                if type_salon == discord.ChannelType.category:
                    categories.append(fiche)
                elif type_salon in (discord.ChannelType.voice, discord.ChannelType.stage_voice):
                    fiche["kind"] = "voice"
                    salons.append(fiche)
                else:
                    fiche["kind"] = "text"
                    salons.append(fiche)

        return {
            "roles": roles, "categories": categories, "channels": salons,
            "auteurs": auteurs, "premiere": premiere, "derniere": derniere,
        }

    async def _restaurer_depuis_audit(self, ctx: commands.Context, heures: int):
        """Recrée ce que le journal d'audit Discord dit avoir été supprimé.

        Rien n'est supprimé ni modifié : on ne recrée que ce qui n'existe
        plus, par nom. Le journal ne conserve pas la catégorie d'origine d'un
        salon, donc les salons recréés arrivent hors catégorie — c'est dit
        dans le compte rendu plutôt que passé sous silence.
        """
        guild = ctx.guild
        moi = guild.me
        if moi is None or not moi.guild_permissions.view_audit_log:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error(
                "Il me faut la permission **Voir le journal d'audit** pour savoir ce qui a été supprimé."
            )))

        attente = await panels.envoyer(ctx, panels.depuis_embed(embeds.info(
            f"Lecture du journal d'audit Discord sur les **{heures} dernières heures**…"
        )))
        try:
            trouve = await self._suppressions_recentes(guild, heures)
        except discord.Forbidden:
            return await panels.editer(attente, panels.depuis_embed(embeds.error(
                "Discord refuse l'accès au journal d'audit. Vérifiez la permission **Voir le journal d'audit**."
            )))

        total = len(trouve["roles"]) + len(trouve["categories"]) + len(trouve["channels"])
        if not total:
            return await panels.editer(attente, panels.depuis_embed(embeds.info(
                f"Aucune suppression de salon ou de rôle à rattraper sur les {heures} dernières heures. "
                "Tout ce qui a été supprimé existe à nouveau, ou rien n'a été supprimé."
            )))

        qui = ", ".join(
            f"<@{uid}> ({n})" for uid, n in sorted(trouve["auteurs"].items(), key=lambda kv: -kv[1])[:5]
        ) or "inconnu"
        quand = (
            f"<t:{int(trouve['premiere'].timestamp())}:f> → <t:{int(trouve['derniere'].timestamp())}:f>"
            if trouve["premiere"] and trouve["derniere"] else "période inconnue"
        )

        apercu = embeds.warning(
            f"Le journal d'audit Discord indique **{total}** élément(s) supprimé(s) et toujours absent(s).\n\n"
            "SentriX va les **recréer**. Rien de ce qui existe aujourd'hui ne sera supprimé ni modifié.",
            title="🧾 Restauration depuis le journal d'audit",
        )
        apercu.add_field(name="À recréer", value=(
            f"**{len(trouve['roles'])}** rôle(s), **{len(trouve['categories'])}** catégorie(s), "
            f"**{len(trouve['channels'])}** salon(s)"
        ), inline=False)
        apercu.add_field(name="Supprimés par", value=qui, inline=False)
        apercu.add_field(name="Entre", value=quand, inline=False)
        apercu.add_field(name="À savoir", value=(
            "Le journal d'audit ne conserve ni la catégorie d'origine d'un salon, ni ses permissions "
            "détaillées, ni son historique de messages. Les salons reviennent hors catégorie, à replacer "
            "à la main. Pour une restauration fidèle, `+server-backup` reste la bonne méthode — en amont."
        ), inline=False)

        vue = helpers.ConfirmView(ctx.author.id)
        await panels.editer(attente, panels.avec_composants(panels.depuis_embed(apercu), vue))
        await vue.wait()
        if not vue.value:
            return await panels.editer(attente, panels.depuis_embed(embeds.error("Restauration annulée.")))

        raison = f"Restauration depuis le journal d'audit par {ctx.author}"
        faits = {"roles": 0, "categories": 0, "channels": 0}
        echecs: list[str] = []

        for fiche in trouve["roles"]:
            try:
                await guild.create_role(
                    name=fiche["name"], colour=discord.Colour(fiche["color"]),
                    hoist=fiche["hoist"], mentionable=fiche["mentionable"],
                    permissions=discord.Permissions(fiche["permissions"]), reason=raison,
                )
                faits["roles"] += 1
            except discord.HTTPException:
                echecs.append(f"rôle « {fiche['name']} »")

        for fiche in trouve["categories"]:
            try:
                await guild.create_category(fiche["name"], reason=raison)
                faits["categories"] += 1
            except discord.HTTPException:
                echecs.append(f"catégorie « {fiche['name']} »")

        for fiche in trouve["channels"]:
            try:
                if fiche["kind"] == "voice":
                    await guild.create_voice_channel(fiche["name"], reason=raison)
                else:
                    await guild.create_text_channel(
                        fiche["name"], topic=fiche.get("topic"),
                        nsfw=fiche.get("nsfw", False), reason=raison,
                    )
                faits["channels"] += 1
            except discord.HTTPException:
                echecs.append(f"salon « {fiche['name']} »")

        texte = (
            f"● Restauration terminée depuis le journal d'audit : **{faits['roles']}** rôle(s), "
            f"**{faits['categories']}** catégorie(s), **{faits['channels']}** salon(s) recréé(s)."
        )
        if echecs:
            texte += "\n\n⚠️ Non recréé(s) — Discord a refusé : " + ", ".join(echecs[:10])
            if len(echecs) > 10:
                texte += f" et {len(echecs) - 10} autre(s)"
        resultat = embeds.success(texte) if not echecs else embeds.warning(texte)
        await panels.editer(attente, panels.depuis_embed(resultat))
        await self.log_action(guild, embeds.log_entry(
            "🧾 Restauration depuis le journal d'audit", 0x4DA3FF,
            acteur=ctx.author,
            extra={
                "♻️ Recréés": f"{faits['roles']} rôle(s), {faits['categories']} catégorie(s), {faits['channels']} salon(s)",
                "🕒 Fenêtre": f"{heures} h",
                "⚠️ Échecs": str(len(echecs)),
            },
        ))

    @commands.hybrid_command(
        name="server-restore",
        description="Recréer les rôles/catégories/salons manquants d'une sauvegarde (rien n'est supprimé).",
        with_app_command=False,
    )
    @app_commands.describe(
        backup_id="L'identifiant de la sauvegarde (voir +server-backup). Sans rien : relit le journal d'audit Discord.",
    )
    @checks.is_owner_or_admin_for("securite")
    async def server_restore(self, ctx: commands.Context, backup_id: int | None = None):
        if backup_id is None:
            return await self._restaurer_depuis_audit(ctx, self.FENETRE_AUDIT_HEURES_DEFAUT)

        row = await self.bot.db.fetchone("SELECT * FROM server_backups WHERE id = ? AND guild_id = ?", (backup_id, ctx.guild.id))
        if not row:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error(
                f"Aucune sauvegarde #{backup_id} trouvée sur ce serveur.\n"
                "Sans sauvegarde, tapez `+server-restore` sans numéro : SentriX relira le journal "
                "d'audit Discord et proposera de recréer ce qui a été supprimé récemment."
            )))
        data = json.loads(row["data_json"])

        preview = embeds.warning(
            f"Cette action va **recréer** les rôles/catégories/salons de la sauvegarde **« {row['label']} »** "
            "qui n'existent plus actuellement (comparaison par nom).\n\n"
            "⚠️ Rien de ce qui existe déjà n'est supprimé ni modifié — utilisez `/wipe-server` séparément si vous "
            "voulez repartir de zéro avant de restaurer.",
            title="💾 Confirmer la restauration",
        )
        preview.add_field(name="Contenu de la sauvegarde", value=(
            f"**{len(data['roles'])}** rôles, **{len(data['categories'])}** catégories, "
            f"**{sum(len(c['channels']) for c in data['categories']) + len(data.get('uncategorized', []))}** salons"
        ), inline=False)
        view = helpers.ConfirmView(ctx.author.id)
        msg = await panels.envoyer(ctx, panels.avec_composants(panels.depuis_embed(preview), view))
        await view.wait()
        if not view.value:
            return await panels.editer(msg, panels.depuis_embed(embeds.error('Restauration annulée.')))

        guild = ctx.guild
        created_roles = created_categories = created_channels = 0

        for r in sorted(data["roles"], key=lambda x: x["position"]):
            if discord.utils.get(guild.roles, name=r["name"]):
                continue
            await guild.create_role(
                name=r["name"], color=discord.Color(r["color"]), hoist=r["hoist"],
                mentionable=r["mentionable"], permissions=discord.Permissions(r["permissions"]),
                reason=f"Restauration de la sauvegarde #{backup_id} par {ctx.author}",
            )
            created_roles += 1

        for cat_data in data["categories"]:
            category = discord.utils.get(guild.categories, name=cat_data["name"])
            if not category:
                category = await guild.create_category(cat_data["name"], reason=f"Restauration #{backup_id}")
                created_categories += 1
            existing_names = {ch.name for ch in category.channels}
            for ch_data in cat_data["channels"]:
                if ch_data["name"] in existing_names:
                    continue
                if ch_data["type"] == "voice":
                    await guild.create_voice_channel(ch_data["name"], category=category, reason=f"Restauration #{backup_id}")
                else:
                    await guild.create_text_channel(
                        ch_data["name"], category=category, topic=ch_data.get("topic"),
                        nsfw=ch_data.get("nsfw", False), reason=f"Restauration #{backup_id}",
                    )
                created_channels += 1

        existing_top_level = {ch.name for ch in guild.channels if ch.category is None}
        for ch_data in data.get("uncategorized", []):
            if ch_data["name"] in existing_top_level:
                continue
            if ch_data["type"] == "voice":
                await guild.create_voice_channel(ch_data["name"], reason=f"Restauration #{backup_id}")
            else:
                await guild.create_text_channel(ch_data["name"], reason=f"Restauration #{backup_id}")
            created_channels += 1

        result = embeds.success(
            f"● Restauration terminée : **{created_roles}** rôle(s), **{created_categories}** catégorie(s), "
            f"**{created_channels}** salon(s) recréé(s) (les éléments déjà existants ont été ignorés)."
        )
        await panels.editer(msg, panels.depuis_embed(result))
        await self.log_action(ctx.guild, embeds.log_entry(
            "💾 Restauration de sauvegarde serveur", 0x5865F2, acteur=ctx.author,
            extra={"📦 Sauvegarde": f"#{backup_id} « {row['label']} »", "Créés": f"{created_roles} rôles, {created_categories} catégories, {created_channels} salons"},
        ))


async def setup(bot: commands.Bot):
    await bot.add_cog(Security(bot))
