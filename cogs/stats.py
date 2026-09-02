"""
Cog STATISTIQUES / DÉVELOPPEMENT.
/bot-status /server-growth /command-stats /latency /changelog /feedback /botinfo /diagnostic
"""

import time
import platform
import discord

from database.db import PRIMARY_CREATOR_DISPLAY_NAME, PRIMARY_CREATOR_ID
from discord import app_commands
from discord.ext import commands

from utils import embeds, design_system, checks, helpers
from utils import sentrix_panels as panels
from database.db import now

START_TIME = time.time()


class Stats(commands.Cog, name="Stats"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _embed(self, guild_id: int | None, *, title: str, description: str = None, kind: str = "primary") -> discord.Embed:
        """Embed statut/dev cohérent avec +designsetup (catégorie CATEGORY_STYLES["utility"],
        car ces commandes techniques n'ont pas leur propre catégorie visuelle dédiée)."""
        style = design_system.CATEGORY_STYLES["utility"]
        colour_key = {"primary": "primary_color", "success": "success_color", "warning": "warning_color", "danger": "danger_color"}.get(kind, "primary_color")
        default_colour = style["colour"] if kind == "primary" else getattr(design_system.COLORS, kind)
        design = await self.bot.db.get_design_settings(guild_id) if guild_id else dict(design_system.DEFAULT_DESIGN_SETTINGS)
        return design_system.create_embed(
            title=design_system.kind_title(title, kind=kind, category_emoji=style["emoji"]),
            description=description,
            colour=design.get(colour_key, default_colour),
            footer=design.get("footer"),
        )

    def _runtime_snapshot(self) -> dict:
        try:
            from . import runtime_observability_v26
            return runtime_observability_v26.snapshot(self.bot)
        except Exception:
            return {}

    @commands.hybrid_command(name="bot-status", description="Afficher l'état général du bot.")
    async def system_status(self, ctx: commands.Context):
        e = await self._embed(ctx.guild.id if ctx.guild else None, title="État du bot")
        e.add_field(name="Latence", value=f"{helpers.latence_ms(self.bot)}ms", inline=True)
        e.add_field(name="Serveurs", value=len(self.bot.guilds), inline=True)
        e.add_field(name="Utilisateurs", value=sum(g.member_count for g in self.bot.guilds), inline=True)
        e.add_field(name="Python", value=platform.python_version(), inline=True)
        e.add_field(name="discord.py", value=discord.__version__, inline=True)
        uptime = int(time.time() - START_TIME)
        h, rem = divmod(uptime, 3600)
        m, s = divmod(rem, 60)
        e.add_field(name="Uptime", value=f"{h}h {m}m {s}s", inline=True)
        runtime = self._runtime_snapshot()
        if runtime:
            e.add_field(name="Release", value=f"`{runtime.get('release', 'inconnu')}`", inline=True)
            e.add_field(
                name="Santé runtime",
                value=(
                    f"Erreurs récentes : {runtime.get('error_count', 0)}\n"
                    f"Commandes lentes : {runtime.get('slow_command_count', 0)}\n"
                    f"Requêtes DB lentes : {runtime.get('slow_db_count', 0)}"
                ),
                inline=True,
            )
        try:
            level_row = await self.bot.db.fetchone("SELECT COUNT(*) AS n FROM levels")
            e.add_field(
                name="📦 Profils en base (tous serveurs)",
                value=str(level_row["n"] if level_row else 0),
                inline=True,
            )
        except Exception:
            pass
        await panels.envoyer(ctx, panels.depuis_embed(e))

    @commands.hybrid_command(
        name="diagnostic",
        description="Vérifier la base, les modules et les permissions indispensables du bot.",
    )
    @commands.guild_only()
    @checks.is_owner_or_admin_for("configuration")
    async def diagnostic(self, ctx: commands.Context):
        database_ok = True
        try:
            row = await self.bot.db.fetchone("SELECT 1 AS ok")
            database_ok = bool(row and row["ok"] == 1)
        except Exception:
            database_ok = False

        def count_slash(commands_list) -> int:
            total = 0
            for command in commands_list:
                total += 1
                total += count_slash(getattr(command, "commands", []))
            return total

        bot_member = ctx.guild.me
        channel_permissions = ctx.channel.permissions_for(bot_member)
        required_permissions = {
            "Voir le salon": channel_permissions.view_channel,
            "Envoyer des messages": channel_permissions.send_messages,
            "Intégrer des liens": channel_permissions.embed_links,
            "Joindre des fichiers": channel_permissions.attach_files,
            "Gérer les messages": channel_permissions.manage_messages,
            "Gérer les salons": channel_permissions.manage_channels,
            "Gérer les rôles": channel_permissions.manage_roles,
            "Exclure temporairement": channel_permissions.moderate_members,
            "Expulser": channel_permissions.kick_members,
            "Bannir": channel_permissions.ban_members,
        }
        missing = [name for name, enabled in required_permissions.items() if not enabled]

        modules_loaded = len(self.bot.extensions)
        modules_expected = getattr(self.bot, "expected_extension_count", modules_loaded)
        database_label = "Opérationnelle" if database_ok else "Indisponible"
        permission_label = "Toutes disponibles" if not missing else f"{len(missing)} manquante(s)"

        integrity = getattr(self.bot, "_sentrix_integrity_state", None)
        quality = getattr(self.bot, "_sentrix_quality_v25_state", None)
        runtime = self._runtime_snapshot()
        quality_ok = bool(quality.get("ready")) if isinstance(quality, dict) else True
        kind = "success" if database_ok and not missing and quality_ok else "warning"

        e = await self._embed(
            ctx.guild.id,
            title="Diagnostic de SentriX",
            description=(
                "Contrôle du salon, des commandes et du runtime actuel. "
                "Aucun réglage n'est modifié."
            ),
            kind=kind,
        )
        e.add_field(name="Connexion Discord", value=f"En ligne — {helpers.latence_ms(self.bot)} ms", inline=True)
        e.add_field(name="Base de données", value=database_label, inline=True)
        e.add_field(name="Modules chargés", value=f"{modules_loaded} / {modules_expected}", inline=True)
        e.add_field(name="Commandes texte", value=str(len(self.bot.commands)), inline=True)
        e.add_field(name="Commandes slash", value=str(count_slash(self.bot.tree.get_commands())), inline=True)
        e.add_field(name="Permissions", value=permission_label, inline=True)

        if isinstance(integrity, dict):
            integrity_ok = bool(integrity.get("ready"))
            e.add_field(
                name="Intégrité des commandes",
                value=(
                    f"{'OK' if integrity_ok else 'À vérifier'} — "
                    f"{integrity.get('commands_checked', 0)} commande(s) contrôlée(s)"
                ),
                inline=True,
            )

        if isinstance(quality, dict):
            contracts = quality.get("contracts", {}) if isinstance(quality.get("contracts"), dict) else {}
            protections = quality.get("protections", {}) if isinstance(quality.get("protections"), dict) else {}
            enabled = sum(1 for value in protections.values() if value)
            total = len(protections)
            e.add_field(
                name="Qualité V2.5",
                value=(
                    f"{'OK' if quality.get('ready') else 'À vérifier'} — "
                    f"{contracts.get('commands_checked', 0)} commande(s), "
                    f"{contracts.get('critical_contracts', 0)} contrat(s), "
                    f"{enabled}/{total} protection(s)"
                ),
                inline=False,
            )

        if runtime:
            runtime_lines = [
                f"Release : `{runtime.get('release', 'inconnu')}`",
                f"DB : {runtime.get('db_calls', 0)} appel(s), moyenne {runtime.get('db_avg_ms', 0)} ms",
                f"DB lente : {runtime.get('slow_db_count', 0)}",
                f"Commandes lentes : {runtime.get('slow_command_count', 0)}",
                f"Erreurs récentes : {runtime.get('error_count', 0)}",
            ]
            last_error = runtime.get("last_error")
            if isinstance(last_error, dict):
                runtime_lines.append(
                    f"Dernière erreur : `{last_error.get('command', 'inconnue')}` / `{last_error.get('type', 'Erreur')}` "
                    f"(réf. `{last_error.get('reference') or 'n/a'}`)"
                )
            e.add_field(name="Runtime", value="\n".join(runtime_lines), inline=False)

        if missing:
            e.add_field(
                name="À corriger dans ce salon",
                value="\n".join(f"• {permission}" for permission in missing),
                inline=False,
            )
            e.add_field(
                name="Solution",
                value=(
                    "Ouvrez les paramètres du serveur, vérifiez le rôle SentriX, puis placez-le au-dessus "
                    "des rôles qu’il doit gérer. Relancez ensuite cette commande dans le salon concerné."
                ),
                inline=False,
            )
        else:
            e.add_field(
                name="Résultat",
                value="La base répond et les permissions indispensables sont disponibles dans ce salon.",
                inline=False,
            )
        await panels.envoyer(ctx, panels.depuis_embed(e), ephemere=True if ctx.interaction else False)

    @commands.hybrid_command(name="server-growth", description="Afficher la croissance des membres du serveur.", with_app_command=False)
    async def server_growth(self, ctx: commands.Context):
        rows = await self.bot.db.fetchall(
            "SELECT * FROM growth_snapshots WHERE guild_id = ? ORDER BY timestamp DESC LIMIT 7", (ctx.guild.id,)
        )
        if not rows:
            return await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id, title='Pas assez de données', description='Pas encore assez de données de croissance.')))
        lines = [f"<t:{r['timestamp']}:D> — {r['member_count']} membres" for r in reversed(rows)]
        await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id, title='Croissance du serveur', description='\n'.join(lines))))

    @commands.hybrid_command(name="command-stats", description="Afficher les commandes les plus utilisées.", with_app_command=False)
    async def command_stats(self, ctx: commands.Context):
        rows = await self.bot.db.fetchall(
            "SELECT command_name, COUNT(*) as c FROM command_logs WHERE guild_id = ? GROUP BY command_name ORDER BY c DESC LIMIT 10",
            (ctx.guild.id,),
        )
        if not rows:
            return await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id, title='Aucune statistique', description="Aucune statistique de commande pour l'instant.")))
        lines = [f"`{r['command_name']}` — {r['c']} utilisations" for r in rows]
        await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id, title='Commandes les plus utilisées', description='\n'.join(lines))))

    @commands.hybrid_command(name="latency", description="Afficher la latence détaillée du bot.", with_app_command=False)
    async def latency(self, ctx: commands.Context):
        guild_id = ctx.guild.id if ctx.guild else None
        start = time.perf_counter()
        msg = await panels.envoyer(ctx, panels.depuis_embed(await self._embed(guild_id, title='Latence', description='Calcul en cours...')))
        elapsed = (time.perf_counter() - start) * 1000
        e = await self._embed(guild_id, title="Latence", description=f"🏓 Latence API : **{helpers.latence_ms(self.bot)}ms**\n📨 Latence message : **{round(elapsed)}ms**")
        if ctx.interaction:
            await ctx.edit_original_response(embed=e)
        else:
            await msg.edit(embed=e)

    @commands.hybrid_command(name="changelog", description="Afficher les dernières nouveautés du bot.", with_app_command=False)
    async def changelog(self, ctx: commands.Context):
        e = await self._embed(
            ctx.guild.id if ctx.guild else None,
            title="Changelog",
            description="Dernières nouveautés de SentriX (les plus récentes en premier) :",
        )
        e.add_field(
            name="Mise à jour de stabilité",
            value=(
                "• Réponses harmonisées : titres sobres, erreurs détaillées et permissions expliquées en français.\n"
                "• Aide corrigée : chaque membre voit ses commandes publiques, sans afficher les outils du staff.\n"
                "• Tickets renforcés : emojis Unicode et personnalisés animés validés avant l’envoi à Discord.\n"
                "• `/diagnostic` contrôle maintenant aussi les contrats de commandes et la santé runtime.\n"
                "• Les erreurs slash et cooldowns donnent une explication claire."
            ),
            inline=False,
        )
        e.add_field(
            name="🛡️ Sécurité",
            value=(
                "• Anti-nuke : détection des renommages massifs et des élévations de permissions "
                "suspectes, en plus des suppressions.\n"
                "• Système de logs automatique (`/create-logs`, 7 salons dédiés)."
            ),
            inline=False,
        )
        e.add_field(
            name="⚙️ Configuration",
            value=(
                "• `/setup` : assistant complet en plusieurs pages (rôles, salons, niveaux, logs, "
                "gestionnaires du bot).\n"
                "• Possibilité d'ajouter des membres autorisés à configurer le bot sans être admin."
            ),
            inline=False,
        )
        e.add_field(
            name="🎫 Tickets & IA",
            value=(
                "• Panneau de tickets avec catégories, priorité et fermeture automatique.\n"
                "• `/sentrix` : répond à n'importe quelle question avec un indice de confiance, "
                "et réagit aussi si on lui parle directement en mentionnant le bot ou en écrivant \"sentrix\"."
            ),
            inline=False,
        )
        await panels.envoyer(ctx, panels.depuis_embed(e))

    @commands.hybrid_command(name="feedback", description="Envoyer un retour aux développeurs du bot.", with_app_command=False)
    @app_commands.describe(texte="Votre retour")
    async def feedback(self, ctx: commands.Context, *, texte: str):
        await self.bot.db.execute(
            "INSERT INTO bug_reports (guild_id, user_id, content, created_at) VALUES (?, ?, ?, ?)",
            (ctx.guild.id if ctx.guild else None, ctx.author.id, f"[FEEDBACK] {texte}", now()),
        )
        await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id if ctx.guild else None, title='Merci !', description='Merci pour votre retour !', kind='success')))

    @commands.hybrid_command(name="botinfo", description="Afficher des informations générales sur le bot.")
    async def botinfo(self, ctx: commands.Context):
        bot = self.bot
        serveurs = len(bot.guilds)
        membres = sum(g.member_count or 0 for g in bot.guilds)
        prefixees = sum(1 for _ in bot.walk_commands())
        slash = sum(1 for _ in bot.tree.walk_commands())
        latence = bot.latency
        latence_ms = round(latence * 1000) if latence and latence == latence else None

        depuis = getattr(bot, "_sentrix_started_at", None)
        if depuis is None:
            depuis = int(time.time())
            bot._sentrix_started_at = depuis

        ouverture = (
            f"**{bot.user.name}** veille sur **{serveurs}** serveur"
            f"{'s' if serveurs > 1 else ''} et **{membres:,}** membres."
        ).replace(",", " ")
        ouverture += f"\nEn ligne depuis <t:{depuis}:R>."

        e = await self._embed(
            ctx.guild.id if ctx.guild else None,
            title=f"À propos de {bot.user.name}",
            description=ouverture,
        )
        e.set_thumbnail(url=bot.user.display_avatar.url)

        e.add_field(
            name="Portée",
            value=(
                f"**{serveurs}** serveur{'s' if serveurs > 1 else ''}\n"
                f"**{membres:,}** membres".replace(",", " ")
            ),
            inline=True,
        )
        e.add_field(
            name="Commandes",
            value=f"**{prefixees}** préfixées\n**{slash}** slash",
            inline=True,
        )

        sante = []
        if latence_ms is not None:
            qualite = "excellente" if latence_ms < 120 else "correcte" if latence_ms < 300 else "dégradée"
            sante.append(f"Latence **{latence_ms} ms** — {qualite}")
        shards = getattr(bot, "shard_count", None)
        if shards:
            sante.append(f"**{shards}** shard{'s' if shards > 1 else ''}")
        sante.append(f"discord.py **{discord.__version__}**")
        e.add_field(name="Santé", value="\n".join(sante), inline=True)

        createur = ctx.bot.get_user(PRIMARY_CREATOR_ID)
        e.add_field(
            name="Créateur",
            value=(
                f"{createur.mention} · `{PRIMARY_CREATOR_ID}`"
                if createur is not None
                else f"**{PRIMARY_CREATOR_DISPLAY_NAME}** · `{PRIMARY_CREATOR_ID}`"
            ),
            inline=False,
        )
        e.set_footer(text=f"{ctx.clean_prefix}help pour la liste complète des commandes")
        await panels.envoyer(ctx, panels.depuis_embed(e))


async def setup(bot: commands.Bot):
    await bot.add_cog(Stats(bot))
    from . import integrity_hardening, runtime_observability_v26, user_facing_hygiene
    integrity_hardening.install(bot)
    runtime_observability_v26.install(bot)
    user_facing_hygiene.install(bot)