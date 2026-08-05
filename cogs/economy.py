"""
Cog ÉCONOMIE.
/balance /economy /daily /weekly /work /rob /pay /economyleaderboard /shop /buy
/inventory /sell /gamble /deposit /withdraw /banque (+bank) /give-money /reset-economy

Toutes les commandes qui affichent un solde (/balance, /economy, /banque, /bank, /stats, /profile)
passent par utils/stats_service.get_member_statistics() : portefeuille, banque et total
viennent TOUJOURS de la même requête, et le total n'est jamais stocké séparément — il est
toujours recalculé comme wallet + bank (voir stats_service.get_member_statistics).

Sécurité : /pay et les récompenses périodiques (/daily, /weekly, /work) passent par
Database.pay_member() / Database.claim_timed_reward(), qui vérifient ET écrivent sous un
même verrou asyncio (Database._economy_lock) pour empêcher toute double dépense ou double
récompense en cas de double-clic ou d'appel concurrent. Chaque transaction significative
est enregistrée dans economy_transactions (Database.log_transaction).
"""

import random
import discord
from discord import app_commands
from discord.ext import commands

from utils import embeds, checks, stats_service, design_system
from database.db import now

DAILY_AMOUNT = 200
WEEKLY_AMOUNT = 1000
WORK_MIN, WORK_MAX = 50, 250
ROB_COOLDOWN = 3600
DAILY_COOLDOWN = 86400
WEEKLY_COOLDOWN = 7 * 86400
WORK_COOLDOWN = 3600


def _parse_amount(value: str, available: int) -> int | None:
    """Convertit '150', 'all' ou 'tout' en un montant entier. Retourne None si invalide."""
    value = value.strip().lower()
    if value in ("all", "tout", "max"):
        return available
    try:
        amount = int(value)
    except ValueError:
        return None
    return amount


class Economy(commands.Cog, name="Economy"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.rob_cooldowns: dict[int, int] = {}

    async def _send_balance(self, ctx: commands.Context, membre: discord.Member):
        # Migrée vers design_system (Phase 4) — la couleur/footer viennent de +designsetup,
        # l'emoji de la monnaie reste piloté par +statsconfig (economy_emoji), inchangé.
        settings = await self.bot.db.get_stats_settings(ctx.guild.id)
        design = await self.bot.db.get_design_settings(ctx.guild.id)
        eco_emoji = settings.get("economy_emoji", "🪙")
        stats = await stats_service.get_member_statistics(self.bot, ctx.guild, membre)
        style = design_system.CATEGORY_STYLES["economy"]
        e = design_system.create_embed(
            title=f"{style['emoji']} Économie de {membre.display_name}",
            colour=design.get("primary_color", style["colour"]),
            user=membre if design.get("show_avatars", True) else None,
            thumbnail=membre.display_avatar.url if design.get("show_avatars", True) else None,
            footer=design.get("footer"),
        )
        e.add_field(name="👛 Portefeuille", value=f"{stats_service.format_number(stats['wallet'])} {eco_emoji}", inline=True)
        e.add_field(name="🏦 Banque", value=f"{stats_service.format_number(stats['bank'])} {eco_emoji}", inline=True)
        e.add_field(name="💎 Total", value=f"**{stats_service.format_number(stats['total_money'])}** {eco_emoji}", inline=True)
        await ctx.send(embed=e)

    @commands.hybrid_command(name="balance", description="Afficher votre solde ou celui d'un membre.")
    @app_commands.describe(membre="Le membre visé (optionnel)")
    async def balance(self, ctx: commands.Context, membre: discord.Member = None):
        await self._send_balance(ctx, membre or ctx.author)

    @commands.hybrid_command(name="economy", description="Afficher le résumé économique d'un membre.", with_app_command=False)
    @app_commands.describe(membre="Le membre visé (optionnel)")
    async def economy_cmd(self, ctx: commands.Context, membre: discord.Member = None):
        """Alias de /balance avec le même format, demandé explicitement (+economy)."""
        await self._send_balance(ctx, membre or ctx.author)

    @commands.hybrid_command(name="daily", description="Récupérer votre récompense quotidienne.")
    async def daily(self, ctx: commands.Context):
        ok, remaining = await self.bot.db.claim_timed_reward(ctx.guild.id, ctx.author.id, "last_daily", DAILY_AMOUNT, DAILY_COOLDOWN, "daily")
        if not ok:
            h, m = remaining // 3600, (remaining % 3600) // 60
            return await ctx.send(embed=embeds.warning(f"Vous avez déjà récupéré votre récompense. Revenez dans {h}h{m}m."))
        await ctx.send(embed=embeds.success(f"🎁 Vous avez reçu **{stats_service.format_number(DAILY_AMOUNT)} 🪙** !"))

    @commands.hybrid_command(name="weekly", description="Récupérer votre récompense hebdomadaire.")
    async def weekly(self, ctx: commands.Context):
        ok, remaining = await self.bot.db.claim_timed_reward(ctx.guild.id, ctx.author.id, "last_weekly", WEEKLY_AMOUNT, WEEKLY_COOLDOWN, "weekly")
        if not ok:
            d, rest = remaining // 86400, remaining % 86400
            h = rest // 3600
            return await ctx.send(embed=embeds.warning(f"Vous avez déjà récupéré votre récompense hebdomadaire. Revenez dans {d}j {h}h."))
        await ctx.send(embed=embeds.success(f"🎁 Vous avez reçu votre récompense hebdomadaire de **{stats_service.format_number(WEEKLY_AMOUNT)} 🪙** !"))

    @commands.hybrid_command(name="work", description="Travailler pour gagner de l'argent.")
    async def work(self, ctx: commands.Context):
        amount = random.randint(WORK_MIN, WORK_MAX)
        ok, remaining = await self.bot.db.claim_timed_reward(ctx.guild.id, ctx.author.id, "last_work", amount, WORK_COOLDOWN, "work")
        if not ok:
            return await ctx.send(embed=embeds.warning(f"Vous êtes fatigué. Revenez dans {remaining // 60} minutes."))
        jobs = ["développeur", "livreur", "chef cuisinier", "streamer", "modérateur", "vendeur"]
        await ctx.send(embed=embeds.success(f"💼 Vous avez travaillé comme **{random.choice(jobs)}** et gagné **{stats_service.format_number(amount)} 🪙** !"))

    @commands.hybrid_command(name="rob", description="Tenter de voler un autre membre.")
    @app_commands.describe(membre="Le membre à voler")
    async def rob(self, ctx: commands.Context, membre: discord.Member):
        if membre.id == ctx.author.id:
            return await ctx.send(embed=embeds.error("Vous ne pouvez pas vous voler vous-même."))
        if membre.bot:
            return await ctx.send(embed=embeds.error("Vous ne pouvez pas voler un bot."))
        last = self.rob_cooldowns.get(ctx.author.id, 0)
        if now() - last < ROB_COOLDOWN:
            remaining = ROB_COOLDOWN - (now() - last)
            return await ctx.send(embed=embeds.warning(f"Vous devez attendre {remaining // 60} minutes avant de retenter un vol."))
        await self.bot.db.ensure_economy(ctx.guild.id, membre.id)
        target_bal = await self.bot.db.get_balance(ctx.guild.id, membre.id)
        self.rob_cooldowns[ctx.author.id] = now()
        if target_bal["cash"] < 50:
            return await ctx.send(embed=embeds.warning(f"{membre.display_name} n'a pas assez d'argent liquide à voler."))
        success = random.random() < 0.4
        if success:
            amount = random.randint(1, min(target_bal["cash"], 300))
            await self.bot.db.add_balance(ctx.guild.id, membre.id, -amount)
            await self.bot.db.add_balance(ctx.guild.id, ctx.author.id, amount)
            await self.bot.db.log_transaction(ctx.guild.id, membre.id, ctx.author.id, "rob", amount, "Vol réussi")
            await ctx.send(embed=embeds.success(f"🕵️ Vous avez volé **{stats_service.format_number(amount)} 🪙** à {membre.display_name} !"))
        else:
            penalty = random.randint(20, 100)
            await self.bot.db.add_balance(ctx.guild.id, ctx.author.id, -penalty)
            await self.bot.db.log_transaction(ctx.guild.id, ctx.author.id, None, "rob_fail", penalty, "Vol raté, amende")
            await ctx.send(embed=embeds.error(f"🚨 Vous avez été attrapé et payé **{stats_service.format_number(penalty)} 🪙** d'amende !"))

    @commands.hybrid_command(name="pay", description="Transférer de l'argent à un autre membre.")
    @app_commands.describe(membre="Le membre à qui envoyer", montant="Le montant à envoyer (ou 'all' pour tout envoyer)")
    async def pay(self, ctx: commands.Context, membre: discord.Member, montant: str):
        if membre.id == ctx.author.id:
            return await ctx.send(embed=embeds.error("Vous ne pouvez pas vous payer vous-même."))
        if membre.bot:
            return await ctx.send(embed=embeds.error("Vous ne pouvez pas payer un bot."))
        await self.bot.db.ensure_economy(ctx.guild.id, ctx.author.id)
        bal = await self.bot.db.get_balance(ctx.guild.id, ctx.author.id)
        amount = _parse_amount(montant, bal["cash"])
        if amount is None or amount <= 0:
            return await ctx.send(embed=embeds.error("Montant invalide — utilisez un nombre positif ou `all`."))
        ok = await self.bot.db.pay_member(ctx.guild.id, ctx.author.id, membre.id, amount, reason="Paiement entre membres")
        if not ok:
            return await ctx.send(embed=embeds.error("Vous n'avez pas assez d'argent liquide (ou le montant est invalide)."))
        await ctx.send(embed=embeds.success(f"💸 Vous avez envoyé **{stats_service.format_number(amount)} 🪙** à {membre.mention}."))

    @commands.hybrid_command(name="economyleaderboard", description="Afficher le classement des plus riches.")
    async def economyleaderboard(self, ctx: commands.Context):
        design = await self.bot.db.get_design_settings(ctx.guild.id)
        rows = await self.bot.db.fetchall(
            "SELECT * FROM economy WHERE guild_id = ? ORDER BY (cash + bank) DESC LIMIT 15", (ctx.guild.id,)
        )
        if not rows:
            return await ctx.send(embed=embeds.info("Aucune donnée économique pour l'instant."))
        lines = []
        rank = 0
        for r in rows:
            # Un membre non mis en cache (get_member()=None) n'a pas forcément quitté le
            # serveur — on l'affiche avec un identifiant de secours au lieu de le faire
            # disparaître du classement. Seuls les BOTS confirmés sont exclus.
            member = ctx.guild.get_member(r["user_id"])
            if member is not None and member.bot:
                continue
            name = member.display_name if member else f"Utilisateur {r['user_id']}"
            rank += 1
            if rank > 10:
                break
            medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(rank, f"**{rank}.**")
            lines.append(f"{medal} {name} — {stats_service.format_number(r['cash'] + r['bank'])} 🪙")
        if not lines:
            return await ctx.send(embed=embeds.info("Aucune donnée économique pour l'instant."))
        style = design_system.CATEGORY_STYLES["economy"]
        embed = design_system.create_embed(
            title=f"{style['emoji']} 🏆 Classement des plus riches",
            description="\n".join(lines),
            colour=design.get("primary_color", style["colour"]),
            footer=design.get("footer"),
        )
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="leaderboard-money", description="Afficher le classement des plus riches.", with_app_command=False)
    async def leaderboard_money(self, ctx: commands.Context):
        """Alias historique de /economyleaderboard — conservé pour ne rien casser."""
        await self.economyleaderboard(ctx)

    @commands.hybrid_command(name="shop", description="Afficher la boutique du serveur.")
    async def shop(self, ctx: commands.Context):
        design = await self.bot.db.get_design_settings(ctx.guild.id)
        items = await self.bot.db.fetchall("SELECT * FROM shop_items WHERE guild_id = ?", (ctx.guild.id,))
        if not items:
            return await ctx.send(embed=embeds.info("La boutique est vide pour l'instant."))
        lines = [f"**#{it['id']}** {it['name']} — {stats_service.format_number(it['price'])} 🪙" for it in items]
        style = design_system.CATEGORY_STYLES["economy"]
        embed = design_system.create_embed(
            title=f"🛒 Boutique du serveur",
            description="\n".join(lines),
            colour=design.get("primary_color", style["colour"]),
            footer=design.get("footer"),
        )
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="buy", description="Acheter un article de la boutique.")
    @app_commands.describe(id="L'identifiant de l'article (voir /shop)")
    async def buy(self, ctx: commands.Context, id: int):
        item = await self.bot.db.fetchone("SELECT * FROM shop_items WHERE id = ? AND guild_id = ?", (id, ctx.guild.id))
        if not item:
            return await ctx.send(embed=embeds.error("Article introuvable."))
        await self.bot.db.ensure_economy(ctx.guild.id, ctx.author.id)
        bal = await self.bot.db.get_balance(ctx.guild.id, ctx.author.id)
        if bal["cash"] < item["price"]:
            return await ctx.send(embed=embeds.error("Vous n'avez pas assez d'argent."))
        await self.bot.db.add_balance(ctx.guild.id, ctx.author.id, -item["price"])
        await self.bot.db.log_transaction(ctx.guild.id, ctx.author.id, None, "buy", item["price"], f"Achat : {item['name']}")
        await self.bot.db.execute(
            "INSERT INTO inventory (guild_id, user_id, item_name, quantity) VALUES (?, ?, ?, 1) "
            "ON CONFLICT(guild_id, user_id, item_name) DO UPDATE SET quantity = quantity + 1",
            (ctx.guild.id, ctx.author.id, item["name"]),
        )
        await ctx.send(embed=embeds.success(f"● Vous avez acheté **{item['name']}** pour {stats_service.format_number(item['price'])} 🪙."))

    @commands.hybrid_command(name="inventory", description="Afficher votre inventaire.", with_app_command=False)
    async def inventory(self, ctx: commands.Context):
        design = await self.bot.db.get_design_settings(ctx.guild.id)
        rows = await self.bot.db.fetchall(
            "SELECT * FROM inventory WHERE guild_id = ? AND user_id = ?", (ctx.guild.id, ctx.author.id)
        )
        if not rows:
            return await ctx.send(embed=embeds.info("Votre inventaire est vide."))
        lines = [f"• {r['item_name']} × {stats_service.format_number(r['quantity'])}" for r in rows]
        style = design_system.CATEGORY_STYLES["economy"]
        embed = design_system.create_embed(
            title=f"🎒 Inventaire de {ctx.author.display_name}",
            description="\n".join(lines),
            colour=design.get("primary_color", style["colour"]),
            user=ctx.author if design.get("show_avatars", True) else None,
            thumbnail=ctx.author.display_avatar.url if design.get("show_avatars", True) else None,
            footer=design.get("footer"),
        )
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="sell", description="Vendre un article de votre inventaire.", with_app_command=False)
    @app_commands.describe(objet="Le nom de l'objet à vendre")
    async def sell(self, ctx: commands.Context, *, objet: str):
        row = await self.bot.db.fetchone(
            "SELECT * FROM inventory WHERE guild_id = ? AND user_id = ? AND item_name = ?", (ctx.guild.id, ctx.author.id, objet)
        )
        if not row or row["quantity"] < 1:
            return await ctx.send(embed=embeds.error("Vous ne possédez pas cet objet."))
        item = await self.bot.db.fetchone("SELECT * FROM shop_items WHERE guild_id = ? AND name = ?", (ctx.guild.id, objet))
        price = int(item["price"] * 0.5) if item else 10
        await self.bot.db.execute(
            "UPDATE inventory SET quantity = quantity - 1 WHERE guild_id = ? AND user_id = ? AND item_name = ?",
            (ctx.guild.id, ctx.author.id, objet),
        )
        await self.bot.db.add_balance(ctx.guild.id, ctx.author.id, price)
        await self.bot.db.log_transaction(ctx.guild.id, None, ctx.author.id, "sell", price, f"Vente : {objet}")
        await ctx.send(embed=embeds.success(f"Vous avez vendu **{objet}** pour {stats_service.format_number(price)} 🪙."))

    @commands.hybrid_command(name="gamble", description="Miser de l'argent au casino (50% de chance).")
    @app_commands.describe(montant="Le montant à miser")
    async def gamble(self, ctx: commands.Context, montant: int):
        if montant <= 0:
            return await ctx.send(embed=embeds.error("Le montant doit être positif."))
        await self.bot.db.ensure_economy(ctx.guild.id, ctx.author.id)
        bal = await self.bot.db.get_balance(ctx.guild.id, ctx.author.id)
        if bal["cash"] < montant:
            return await ctx.send(embed=embeds.error("Vous n'avez pas assez d'argent."))
        if random.random() < 0.5:
            await self.bot.db.add_balance(ctx.guild.id, ctx.author.id, montant)
            await self.bot.db.log_transaction(ctx.guild.id, None, ctx.author.id, "gamble_win", montant, "Casino")
            await ctx.send(embed=embeds.success(f"🎰 Vous avez gagné **{stats_service.format_number(montant)} 🪙** !"))
        else:
            await self.bot.db.add_balance(ctx.guild.id, ctx.author.id, -montant)
            await self.bot.db.log_transaction(ctx.guild.id, ctx.author.id, None, "gamble_loss", montant, "Casino")
            await ctx.send(embed=embeds.error(f"🎰 Vous avez perdu **{stats_service.format_number(montant)} 🪙**."))

    @commands.hybrid_command(name="deposit", description="Déposer de l'argent à la banque (ou 'all').", with_app_command=False)
    @app_commands.describe(montant="Le montant à déposer (ou 'all')")
    async def deposit(self, ctx: commands.Context, montant: str):
        await self.bot.db.ensure_economy(ctx.guild.id, ctx.author.id)
        bal = await self.bot.db.get_balance(ctx.guild.id, ctx.author.id)
        amount = _parse_amount(montant, bal["cash"])
        if amount is None or amount <= 0 or amount > bal["cash"]:
            return await ctx.send(embed=embeds.error("Montant invalide."))
        await self.bot.db.execute(
            "UPDATE economy SET cash = cash - ?, bank = bank + ? WHERE guild_id = ? AND user_id = ?",
            (amount, amount, ctx.guild.id, ctx.author.id),
        )
        await ctx.send(embed=embeds.success(f"🏦 {stats_service.format_number(amount)} 🪙 déposés à la banque."))

    @commands.hybrid_command(name="withdraw", description="Retirer de l'argent de la banque (ou 'all').", with_app_command=False)
    @app_commands.describe(montant="Le montant à retirer (ou 'all')")
    async def withdraw(self, ctx: commands.Context, montant: str):
        await self.bot.db.ensure_economy(ctx.guild.id, ctx.author.id)
        bal = await self.bot.db.get_balance(ctx.guild.id, ctx.author.id)
        amount = _parse_amount(montant, bal["bank"])
        if amount is None or amount <= 0 or amount > bal["bank"]:
            return await ctx.send(embed=embeds.error("Montant invalide."))
        await self.bot.db.execute(
            "UPDATE economy SET cash = cash + ?, bank = bank - ? WHERE guild_id = ? AND user_id = ?",
            (amount, amount, ctx.guild.id, ctx.author.id),
        )
        await ctx.send(embed=embeds.success(f"💵 {stats_service.format_number(amount)} 🪙 retirés de la banque."))

    @commands.hybrid_command(name="banque", aliases=["bank"], description="Afficher le détail de votre compte bancaire.", with_app_command=False)
    async def bank(self, ctx: commands.Context):
        design = await self.bot.db.get_design_settings(ctx.guild.id)
        stats = await stats_service.get_member_statistics(self.bot, ctx.guild, ctx.author)
        style = design_system.CATEGORY_STYLES["economy"]
        e = design_system.create_embed(
            title="🏦 Votre banque",
            colour=design.get("primary_color", style["colour"]),
            footer=design.get("footer"),
        )
        e.add_field(name="👛 Espèces", value=f"{stats_service.format_number(stats['wallet'])} 🪙", inline=True)
        e.add_field(name="🏦 Banque", value=f"{stats_service.format_number(stats['bank'])} 🪙", inline=True)
        e.add_field(name="💎 Total", value=f"**{stats_service.format_number(stats['total_money'])}** 🪙", inline=True)
        await ctx.send(embed=e)

    @commands.hybrid_command(name="give-money", description="[Admin] Donner de l'argent à un membre.", with_app_command=False)
    @app_commands.describe(membre="Le membre visé", montant="Le montant à donner")
    @checks.is_owner_or_admin_for("economie")
    async def give_money(self, ctx: commands.Context, membre: discord.Member, montant: int):
        await self.bot.db.ensure_economy(ctx.guild.id, membre.id)
        await self.bot.db.add_balance(ctx.guild.id, membre.id, montant)
        await self.bot.db.log_transaction(ctx.guild.id, ctx.author.id, membre.id, "admin_grant", montant, "Ajout manuel (staff)")
        await ctx.send(embed=embeds.success(f"{stats_service.format_number(montant)} 🪙 ajoutés au compte de {membre.mention}."))

    @commands.hybrid_command(name="reset-economy", description="[Admin] Réinitialiser l'économie du serveur.", with_app_command=False)
    @checks.is_owner_or_admin_for("economie")
    async def reset_economy(self, ctx: commands.Context):
        await self.bot.db.execute("DELETE FROM economy WHERE guild_id = ?", (ctx.guild.id,))
        await ctx.send(embed=embeds.success("L'économie du serveur a été réinitialisée. (L'historique des transactions est conservé pour l'audit.)"))


async def setup(bot: commands.Bot):
    await bot.add_cog(Economy(bot))
