"""SentriX V2.1 — finition visible, marché durci, progression et monitoring.

Cette couche complète SentriX V2 sans dupliquer les systèmes existants : elle enrichit les
badges et le centre IA, ajoute recherche/historique au marché, confirme les achats et
réutilise l'observabilité Production V9 pour un diagnostic lisible depuis Discord.
"""
from __future__ import annotations

import asyncio
import functools
import sys
from datetime import datetime, timezone

import discord
from discord.ext import commands

from utils import design_system, embeds, stats_service
from utils import sentrix_panels as panels
from utils import helpers
from utils.v21_rules import (
    MARKET_MAX_ACTIVE_PER_USER,
    achievement_rows,
    challenge_rows,
    clean_market_query,
    market_totals,
)

V21_PUBLIC_COMMANDS = frozenset({
    "achievements", "challenges", "market-find", "market-history", "market-my",
})
V21_DIRECT_COMMANDS = V21_PUBLIC_COMMANDS | {"systemstatus"}


def _fmt(value) -> str:
    return stats_service.format_number(value)


class MarketConfirmView(design_system.SentriXView):
    def __init__(self, cog: "SentriXV21", member: discord.Member, listing_id: int):
        super().__init__(author_id=member.id, allowed_staff=False, timeout=60)
        self.cog = cog
        self.listing_id = int(listing_id)
        self.finished = False

    async def _disable(self, interaction: discord.Interaction):
        for child in self.children:
            child.disabled = True
        try:
            await interaction.message.edit(view=self)
        except Exception:
            pass

    @discord.ui.button(label="Confirmer l'achat", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.finished:
            return await interaction.response.send_message("Cette confirmation est déjà terminée.", ephemeral=True)
        self.finished = True
        await interaction.response.defer(ephemeral=True)
        await self._disable(interaction)
        embed = await self.cog.execute_purchase(interaction.guild, interaction.user, self.listing_id)
        await panels.envoyer(interaction.followup, panels.depuis_embed(embed), ephemere=True)

    @discord.ui.button(label="Annuler", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.finished = True
        await self._disable(interaction)
        await panels.envoyer(interaction.response, panels.depuis_embed(embeds.warning('Achat annulé.')), ephemere=True)


class SentriXV21(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._market_lock = asyncio.Lock()
        self._market_patched = False
        self._v2 = None
        self._original_badge_data = None
        self._original_ai_embed = None

    async def cog_load(self):
        self._v2 = self.bot.get_cog("SentriXV2")
        self.install_policy()
        self.install_help()
        self.install_v2_enrichment()
        self.install_market_hardening()

    def install_policy(self):
        for module_name in ("main", "__main__"):
            main = sys.modules.get(module_name)
            if main is None or not hasattr(main, "PUBLIC_COMMANDS"):
                continue
            main.PUBLIC_COMMANDS = main.PUBLIC_COMMANDS | V21_PUBLIC_COMMANDS
            main.DISCORD_PERMISSION_COMMANDS["systemstatus"] = "manage_guild"
            main.KNOWN_PERMISSION_COMMANDS = (
                main.PUBLIC_COMMANDS | main.OWNER_ONLY_COMMANDS | main.CUSTOM_PERMISSION_COMMANDS
                | frozenset(main.DISCORD_PERMISSION_COMMANDS)
                | frozenset().union(*main.CATEGORY_COMMANDS.values())
            )
        try:
            from . import command_catalog_cleanup
            command_catalog_cleanup.NORMAL_DIRECT_COMMANDS = command_catalog_cleanup.NORMAL_DIRECT_COMMANDS | V21_DIRECT_COMMANDS
            command_catalog_cleanup.RESTORED_COMMANDS = command_catalog_cleanup.NORMAL_DIRECT_COMMANDS
            command_catalog_cleanup.apply_surface(self.bot)
        except Exception:
            pass

    def install_help(self):
        try:
            from . import help_complete
            for spec in help_complete.CATEGORIES:
                if spec.key == "v2":
                    try:
                        spec.command_names = frozenset(spec.command_names) | V21_DIRECT_COMMANDS
                    except Exception:
                        pass
                    break
        except Exception:
            pass

    def install_v2_enrichment(self):
        v2 = self._v2
        if v2 is None or getattr(v2, "_sentrix_v21_enriched", False):
            return

        self._original_badge_data = v2.badge_data
        original_badge_data = v2.badge_data

        async def expanded_badges(guild: discord.Guild, member: discord.Member, stats: dict):
            base = await original_badge_data(guild, member, stats)
            row = await v2.checkin_row(guild.id, member.id)
            joined_days = 0
            if member.joined_at:
                joined_days = max(0, (datetime.now(timezone.utc) - member.joined_at).days)
            rows = achievement_rows(
                stats,
                streak=int(row["streak"] if row else 0),
                best_streak=int(row["best_streak"] if row else 0),
                total_claims=int(row["total_claims"] if row else 0),
                joined_days=joined_days,
            )
            merged = list(base)
            seen = {name.casefold() for name, _ in merged}
            for achievement in rows:
                if achievement["unlocked"] and achievement["name"].casefold() not in seen:
                    merged.append((achievement["name"], achievement["description"]))
                    seen.add(achievement["name"].casefold())
            return merged

        v2.badge_data = expanded_badges

        self._original_ai_embed = v2.build_ai_embed
        original_ai_embed = v2.build_ai_embed

        async def richer_ai_embed(guild: discord.Guild, member: discord.Member):
            embed = await original_ai_embed(guild, member)
            day = datetime.now(timezone.utc).date().isoformat()
            try:
                mine = await self.bot.db.fetchone(
                    "SELECT requests,tokens_estimate FROM ai_usage WHERE guild_id=? AND user_id=? AND day=?",
                    (guild.id, member.id, day),
                )
                server = await self.bot.db.fetchone(
                    "SELECT COALESCE(SUM(requests),0) AS requests,COALESCE(SUM(tokens_estimate),0) AS tokens FROM ai_usage WHERE guild_id=? AND day=?",
                    (guild.id, day),
                )
                mine_requests = int(mine["requests"] if mine else 0)
                server_requests = int(server["requests"] if server else 0)
                embed.add_field(
                    name="Utilisation aujourd'hui",
                    value=f"Vous **{_fmt(mine_requests)}** requête(s) · Serveur **{_fmt(server_requests)}**",
                    inline=False,
                )
            except Exception:
                pass
            snapshot = getattr(self.bot, "production_v9_health_snapshot", None)
            if isinstance(snapshot, dict):
                ai_state = (snapshot.get("openai") or {}).get("state", "inconnu")
                embed.add_field(name="Santé IA", value=str(ai_state).replace("_", " ").title(), inline=True)
            embed.add_field(
                name="V2.1",
                value="Contexte serveur isolé, mémoire contrôlée, limites d'usage et monitoring de santé actifs.",
                inline=False,
            )
            return embed

        v2.build_ai_embed = richer_ai_embed
        v2._sentrix_v21_enriched = True

    def install_market_hardening(self):
        if self._market_patched:
            return
        sell = self.bot.get_command("market-sell")
        buy = self.bot.get_command("market-buy")
        if sell is None or buy is None:
            return

        original_sell = sell.callback
        sell_params = sell.params.copy()

        @functools.wraps(original_sell)
        async def guarded_sell(v2_cog, ctx: commands.Context, quantity: int, unit_price: int, *, item: str):
            if ctx.guild is None:
                return await original_sell(v2_cog, ctx, quantity, unit_price, item=item)
            try:
                market_totals(quantity, unit_price, fee_bps=0)
            except ValueError as exc:
                return await panels.envoyer(ctx, panels.depuis_embed(embeds.error(f'Annonce refusée : {exc}.')))
            count = await self.bot.db.fetchone(
                "SELECT COUNT(*) AS n FROM v2_market_listings WHERE guild_id=? AND seller_id=? AND status='active'",
                (ctx.guild.id, ctx.author.id),
            )
            if count and int(count["n"] or 0) >= MARKET_MAX_ACTIVE_PER_USER:
                return await panels.envoyer(ctx, panels.depuis_embed(embeds.warning(f"Vous avez déjà **{MARKET_MAX_ACTIVE_PER_USER} annonces actives**. Vendez ou annulez-en une avant d'en créer une autre.")))
            return await original_sell(v2_cog, ctx, quantity, unit_price, item=item)

        sell.callback = guarded_sell
        sell.params = sell_params
        sell._sentrix_v21_market_guard = True

        buy_params = buy.params.copy()

        async def confirmed_buy(v2_cog, ctx: commands.Context, listing_id: int):
            if ctx.guild is None or not isinstance(ctx.author, discord.Member):
                return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Utilisez cette commande sur un serveur.')))
            row = await self.bot.db.fetchone(
                "SELECT * FROM v2_market_listings WHERE id=? AND guild_id=? AND status='active'",
                (listing_id, ctx.guild.id),
            )
            if row is None:
                return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Annonce indisponible.')))
            if int(row["seller_id"]) == ctx.author.id:
                return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Vous ne pouvez pas acheter votre propre annonce.')))
            try:
                totals = market_totals(int(row["quantity"]), int(row["unit_price"]), fee_bps=0)
            except ValueError:
                return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Cette annonce contient des valeurs invalides.')))
            embed = discord.Embed(
                title="Confirmer l'achat",
                description=(
                    f"Annonce **#{int(row['id'])}**\n"
                    f"Objet **{row['quantity']}× {row['item_name']}**\n"
                    f"Total **{_fmt(totals.subtotal)}** pièces\n\n"
                    "L'annonce est revérifiée au moment du clic pour empêcher les doubles achats."
                ),
                colour=discord.Colour.blurple(),
            )
            view = MarketConfirmView(self, ctx.author, listing_id)
            view.message = await panels.envoyer(ctx, panels.avec_composants(panels.depuis_embed(embed), view))

        functools.update_wrapper(confirmed_buy, buy.callback)
        buy.callback = confirmed_buy
        buy.params = buy_params
        buy._sentrix_v21_confirmed_purchase = True
        self._market_patched = True

    async def execute_purchase(self, guild: discord.Guild, buyer: discord.Member, listing_id: int):
        async with self._market_lock:
            row = await self.bot.db.fetchone(
                "SELECT * FROM v2_market_listings WHERE id=? AND guild_id=? AND status='active'",
                (listing_id, guild.id),
            )
            if row is None:
                return embeds.error("Cette annonce n'est plus disponible.")
            seller_id = int(row["seller_id"])
            if seller_id == buyer.id:
                return embeds.error("Vous ne pouvez pas acheter votre propre annonce.")
            try:
                totals = market_totals(int(row["quantity"]), int(row["unit_price"]), fee_bps=0)
            except ValueError:
                return embeds.error("Annonce invalide : achat bloqué par la protection V2.1.")

            lock = await self.bot.db.execute(
                "UPDATE v2_market_listings SET status='processing' WHERE id=? AND guild_id=? AND status='active'",
                (listing_id, guild.id),
            )
            if getattr(lock, "rowcount", 0) == 0:
                return embeds.warning("Cette annonce vient d'être achetée par quelqu'un d'autre.")

            paid = await self.bot.db.pay_member(
                guild.id, buyer.id, seller_id, totals.subtotal,
                reason=f"Marché V2.1 #{listing_id}",
            )
            if not paid:
                await self.bot.db.execute(
                    "UPDATE v2_market_listings SET status='active' WHERE id=? AND guild_id=? AND status='processing'",
                    (listing_id, guild.id),
                )
                return embeds.error("Pas assez d'argent liquide pour cet achat.")

            try:
                await self.bot.db.execute(
                    "INSERT INTO inventory (guild_id,user_id,item_name,quantity) VALUES (?,?,?,?) "
                    "ON CONFLICT(guild_id,user_id,item_name) DO UPDATE SET quantity=inventory.quantity+excluded.quantity",
                    (guild.id, buyer.id, row["item_name"], int(row["quantity"])),
                )
                await self.bot.db.execute(
                    "UPDATE v2_market_listings SET status='sold',buyer_id=?,sold_at=? "
                    "WHERE id=? AND guild_id=? AND status='processing'",
                    (buyer.id, int(datetime.now(timezone.utc).timestamp()), listing_id, guild.id),
                )
            except Exception:
                refunded = False
                try:
                    refunded = await self.bot.db.pay_member(
                        guild.id, seller_id, buyer.id, totals.subtotal,
                        reason=f"Remboursement marché V2.1 #{listing_id}",
                    )
                except Exception:
                    refunded = False
                await self.bot.db.execute(
                    "UPDATE v2_market_listings SET status=? WHERE id=? AND guild_id=?",
                    ("active" if refunded else "refund_required", listing_id, guild.id),
                )
                if refunded:
                    return embeds.error("L'ajout de l'objet a échoué. Votre achat a été remboursé automatiquement.")
                return embeds.error(
                    "L'achat a rencontré une erreur critique après paiement. L'annonce est bloquée pour contrôle staff."
                )

            return embeds.success(
                f"Achat terminé : **{row['quantity']}× {row['item_name']}** pour **{_fmt(totals.subtotal)}** pièces."
            )

    async def _member_stats_and_checkin(self, guild: discord.Guild, member: discord.Member):
        stats = await stats_service.get_member_statistics(self.bot, guild, member)
        row = await self.bot.db.fetchone(
            "SELECT streak,best_streak,total_claims FROM v2_daily_checkins WHERE guild_id=? AND user_id=?",
            (guild.id, member.id),
        )
        joined_days = 0
        if member.joined_at:
            joined_days = max(0, (datetime.now(timezone.utc) - member.joined_at).days)
        return stats, row, joined_days

    @commands.hybrid_command(name="achievements", aliases=["badges"], description="Afficher tous les succès V2.1.", with_app_command=False)
    @commands.cooldown(2, 5, commands.BucketType.user)
    async def achievements(self, ctx: commands.Context, membre: discord.Member = None):
        if ctx.guild is None:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Utilisez cette commande sur un serveur.')))
        member = membre or ctx.author
        stats, row, joined_days = await self._member_stats_and_checkin(ctx.guild, member)
        achievements = achievement_rows(
            stats,
            streak=int(row["streak"] if row else 0),
            best_streak=int(row["best_streak"] if row else 0),
            total_claims=int(row["total_claims"] if row else 0),
            joined_days=joined_days,
        )
        unlocked = [a for a in achievements if a["unlocked"]]
        locked = [a for a in achievements if not a["unlocked"]]
        embed = discord.Embed(
            title=f"Succès V2.1 — {member.display_name}",
            description=f"**{len(unlocked)}/{len(achievements)}** succès débloqués.",
            colour=discord.Colour.blurple(),
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(
            name="Débloqués",
            value="\n".join(f"**{a['name']}** — {a['description']}" for a in unlocked[-10:]) or "Aucun succès pour le moment.",
            inline=False,
        )
        embed.add_field(
            name="À débloquer",
            value="\n".join(f"**{a['name']}** — {a['description']}" for a in locked[:7]) or "Tous les succès sont débloqués.",
            inline=False,
        )
        await panels.envoyer(ctx, panels.depuis_embed(embed))

    @commands.hybrid_command(name="challenges", aliases=["defis"], description="Afficher les défis de progression V2.1.", with_app_command=False)
    @commands.cooldown(2, 5, commands.BucketType.user)
    async def challenges(self, ctx: commands.Context, membre: discord.Member = None):
        if ctx.guild is None:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Utilisez cette commande sur un serveur.')))
        member = membre or ctx.author
        stats, row, _ = await self._member_stats_and_checkin(ctx.guild, member)
        challenges = challenge_rows(stats, streak=int(row["streak"] if row else 0))
        lines = []
        for challenge in challenges:
            state = "TERMINÉ" if challenge["complete"] else f"{challenge['percent']}%"
            lines.append(
                f"**{challenge['name']}** · {state}\n"
                f"{_fmt(challenge['current'])}/{_fmt(challenge['target'])} {challenge['unit']}"
            )
        embed = discord.Embed(
            title=f"Défis V2.1 — {member.display_name}",
            description="\n\n".join(lines),
            colour=discord.Colour.blurple(),
        )
        await panels.envoyer(ctx, panels.depuis_embed(embed))

    @commands.hybrid_command(name="market-find", aliases=["market-search"], description="Rechercher un objet sur le marché.", with_app_command=False)
    @commands.cooldown(2, 5, commands.BucketType.user)
    async def market_find(self, ctx: commands.Context, *, recherche: str):
        if ctx.guild is None:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Utilisez cette commande sur un serveur.')))
        try:
            query = clean_market_query(recherche)
        except ValueError:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error("Indiquez le nom d'un objet à rechercher.")))
        rows = await self.bot.db.fetchall(
            "SELECT id,seller_id,item_name,quantity,unit_price FROM v2_market_listings "
            "WHERE guild_id=? AND status='active' AND lower(item_name) LIKE lower(?) "
            "ORDER BY unit_price ASC,id DESC LIMIT 12",
            (ctx.guild.id, f"%{query}%"),
        )
        embed = discord.Embed(
            title="Recherche marché",
            description=f"Résultats pour **{query}**.",
            colour=discord.Colour.blurple(),
        )
        if rows:
            embed.add_field(
                name=f"Annonces ({len(rows)})",
                value="\n".join(
                    f"**#{r['id']}** · {r['quantity']}× **{r['item_name']}** · {_fmt(r['unit_price'])}/u · <@{r['seller_id']}>"
                    for r in rows
                ),
                inline=False,
            )
        else:
            embed.add_field(name="Résultat", value="Aucune annonce correspondante.", inline=False)
        await panels.envoyer(ctx, panels.depuis_embed(embed))

    @commands.hybrid_command(name="market-my", description="Afficher vos annonces actives.", with_app_command=False)
    async def market_my(self, ctx: commands.Context):
        if ctx.guild is None:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Utilisez cette commande sur un serveur.')))
        rows = await self.bot.db.fetchall(
            "SELECT id,item_name,quantity,unit_price,created_at FROM v2_market_listings "
            "WHERE guild_id=? AND seller_id=? AND status='active' ORDER BY id DESC LIMIT 20",
            (ctx.guild.id, ctx.author.id),
        )
        embed = discord.Embed(title="Mes annonces", colour=discord.Colour.blurple())
        embed.description = (
            "\n".join(
                f"**#{r['id']}** · {r['quantity']}× **{r['item_name']}** · {_fmt(r['unit_price'])}/u"
                for r in rows
            ) if rows else "Vous n'avez aucune annonce active."
        )
        embed.set_footer(text=f"Maximum {MARKET_MAX_ACTIVE_PER_USER} annonces actives par membre")
        await panels.envoyer(ctx, panels.depuis_embed(embed))

    @commands.hybrid_command(name="market-history", description="Afficher votre historique du marché.", with_app_command=False)
    async def market_history(self, ctx: commands.Context):
        if ctx.guild is None:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Utilisez cette commande sur un serveur.')))
        rows = await self.bot.db.fetchall(
            "SELECT id,seller_id,buyer_id,item_name,quantity,unit_price,status,sold_at,created_at "
            "FROM v2_market_listings WHERE guild_id=? AND (seller_id=? OR buyer_id=?) "
            "ORDER BY COALESCE(sold_at,created_at) DESC,id DESC LIMIT 15",
            (ctx.guild.id, ctx.author.id, ctx.author.id),
        )
        lines = []
        for row in rows:
            role = "Vente" if int(row["seller_id"]) == ctx.author.id else "Achat"
            total = int(row["quantity"]) * int(row["unit_price"])
            lines.append(
                f"**{role} #{row['id']}** · {row['quantity']}× {row['item_name']} · {_fmt(total)} · {row['status']}"
            )
        embed = discord.Embed(
            title="Historique marché",
            description="\n".join(lines) if lines else "Aucun historique de marché.",
            colour=discord.Colour.blurple(),
        )
        await panels.envoyer(ctx, panels.depuis_embed(embed))

    @commands.hybrid_command(name="systemstatus", aliases=["botstatus"], description="Afficher la santé technique de SentriX.", with_app_command=False)
    @commands.has_permissions(manage_guild=True)
    @commands.cooldown(2, 10, commands.BucketType.guild)
    async def systemstatus(self, ctx: commands.Context):
        runtime = self.bot.get_cog("ProductionObservabilityV9")
        snapshot = None
        if runtime is not None and hasattr(runtime, "refresh_health"):
            try:
                snapshot = await runtime.refresh_health()
            except Exception:
                snapshot = None
        if not isinstance(snapshot, dict):
            snapshot = getattr(self.bot, "production_v9_health_snapshot", None)
        if not isinstance(snapshot, dict):
            try:
                db_row = await self.bot.db.fetchone("SELECT 1 AS ok")
                db_ok = bool(db_row and int(db_row["ok"]) == 1)
            except Exception:
                db_ok = False
            snapshot = {
                "status": "healthy" if self.bot.is_ready() and db_ok else "degraded",
                "discord": {"ready": self.bot.is_ready(), "latency_ms": helpers.latence_ms(self.bot)},
                "database": {"sqlite": "ok" if db_ok else "erreur", "postgres": "inconnu", "redis": "inconnu"},
                "openai": {"state": "inconnu"},
                "commands": {},
                "problems": [],
            }
        commands_state = snapshot.get("commands") or {}
        database = snapshot.get("database") or {}
        discord_state = snapshot.get("discord") or {}
        problems = snapshot.get("problems") or []
        colour = discord.Colour.green() if snapshot.get("status") == "healthy" else discord.Colour.orange()
        embed = discord.Embed(
            title=f"SentriX V2.1 — État {str(snapshot.get('status', 'inconnu')).upper()}",
            colour=colour,
        )
        embed.add_field(
            name="Discord",
            value=f"{'En ligne' if discord_state.get('ready') else 'Indisponible'} · {discord_state.get('latency_ms', '?')} ms",
            inline=True,
        )
        embed.add_field(
            name="Données",
            value=f"SQLite **{database.get('sqlite','?')}**\nPostgreSQL **{database.get('postgres','?')}**\nRedis **{database.get('redis','?')}**",
            inline=True,
        )
        embed.add_field(name="IA", value=str((snapshot.get("openai") or {}).get("state", "inconnu")).replace("_", " ").title(), inline=True)
        embed.add_field(
            name="Commandes — 15 min",
            value=(
                f"Erreurs **{int(commands_state.get('recent_errors', 0) or 0)}** · "
                f"Lentes/bloquées **{int(commands_state.get('recent_slow_or_stuck', 0) or 0)}** · "
                f"Doubles réponses **{int(commands_state.get('recent_double_responses', 0) or 0)}**"
            ),
            inline=False,
        )
        embed.add_field(
            name="Diagnostic",
            value="\n".join(f"• {problem}" for problem in problems[:6]) if problems else "Aucun problème critique détecté.",
            inline=False,
        )
        await panels.envoyer(ctx, panels.depuis_embed(embed))
