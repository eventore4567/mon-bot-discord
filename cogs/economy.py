"""
Cog ÉCONOMIE.
/balance /economy /daily /weekly /work /rob /pay /economyleaderboard /shop /buy /buyrole
/shopsetup /shoppanel /shoprole add|remove|price|list
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

import asyncio
import random
import time
import discord
from discord import app_commands
from discord.ext import commands

from utils import embeds, checks, stats_service, design_system
from utils import sentrix_panels as panels
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


def _self_assignable_role_error(guild: discord.Guild, role: discord.Role) -> str | None:
    """Refuse les rôles impossibles à donner ou permettant une élévation de privilèges."""
    if role.is_default():
        return "Le rôle @everyone ne peut pas être vendu."
    if role.managed:
        return "Ce rôle est géré par Discord ou une intégration et ne peut pas être attribué."
    bot_member = guild.me
    if bot_member is None or role >= bot_member.top_role:
        return "Placez ce rôle sous le rôle du bot dans Paramètres du serveur > Rôles."
    permissions = role.permissions
    dangerous = (
        permissions.administrator
        or permissions.manage_guild
        or permissions.manage_roles
        or permissions.manage_channels
        or permissions.ban_members
        or permissions.kick_members
        or permissions.moderate_members
        or permissions.manage_webhooks
    )
    if dangerous:
        return "Un rôle de boutique ne peut pas contenir de permissions d'administration ou de modération."
    return None


class ShopRoleSelect(discord.ui.Select):
    """Menu public : un choix déclenche directement l'achat du rôle."""

    def __init__(self, slot: int, options: list[discord.SelectOption] | None = None, *, handler: bool = False):
        real_options = options or [discord.SelectOption(label="Boutique indisponible", value="none")]
        super().__init__(
            placeholder=f"Choisissez un rôle{f' — page {slot + 1}' if slot else ''}",
            min_values=1,
            max_values=1,
            options=real_options,
            custom_id=f"sentrix:shop:role:{slot}",
            disabled=not options and not handler,
            row=slot,
        )

    async def callback(self, interaction: discord.Interaction):
        if not self.values or self.values[0] == "none":
            return await interaction.response.send_message("La boutique ne contient encore aucun rôle.", ephemeral=True)
        cog = interaction.client.get_cog("Economy")
        if cog is None:
            return await interaction.response.send_message("La boutique est temporairement indisponible.", ephemeral=True)
        await cog.handle_shop_selection(interaction, self.values[0])


class ShopRoleView(discord.ui.View):
    def __init__(
        self,
        option_chunks: list[list[discord.SelectOption]] | None = None,
        *,
        persistent_handler: bool = False,
    ):
        super().__init__(timeout=None)
        if persistent_handler:
            for slot in range(4):
                self.add_item(ShopRoleSelect(slot, handler=True))
            return
        chunks = option_chunks or []
        if not chunks:
            self.add_item(ShopRoleSelect(0))
            return
        for slot, options in enumerate(chunks[:4]):
            self.add_item(ShopRoleSelect(slot, options))



class ShopCatalogueView(discord.ui.View):
    """Catalogue paginé : six articles maximum par écran, optimisé pour mobile."""

    def __init__(self, pages: list[discord.Embed], owner_id: int):
        super().__init__(timeout=180)
        self.pages = pages
        self.owner_id = int(owner_id)
        self.index = 0
        self.message: discord.Message | None = None
        self._refresh()

    def _refresh(self):
        self.previous.disabled = self.index <= 0
        self.next.disabled = self.index >= len(self.pages) - 1

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.owner_id:
            return True
        await interaction.response.send_message(
            'Ouvrez votre propre catalogue avec +shop.',
            ephemeral=True,
        )
        return False

    @discord.ui.button(label="Précédent", style=discord.ButtonStyle.secondary)
    async def previous(self, interaction: discord.Interaction, _button: discord.ui.Button):
        self.index = max(0, self.index - 1)
        self._refresh()
        await interaction.response.edit_message(embed=self.pages[self.index], view=self)

    @discord.ui.button(label="Suivant", style=discord.ButtonStyle.secondary)
    async def next(self, interaction: discord.Interaction, _button: discord.ui.Button):
        self.index = min(len(self.pages) - 1, self.index + 1)
        self._refresh()
        await interaction.response.edit_message(embed=self.pages[self.index], view=self)

    @discord.ui.button(label="Fermer", style=discord.ButtonStyle.danger)
    async def close(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await interaction.response.edit_message(view=None)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


class Economy(commands.Cog, name="Economy"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.rob_cooldowns: dict[int, int] = {}

    async def cog_load(self):
        # Un handler générique suffit pour tous les panneaux, même après redémarrage :
        # l'article choisi est toujours revérifié dans SQLite avant le débit.
        if not getattr(self.bot, "_sentrix_shop_view_registered", False):
            self.bot.add_view(ShopRoleView(persistent_handler=True))
            self.bot._sentrix_shop_view_registered = True
        self._shop_panel_refresh_task = asyncio.create_task(self._refresh_shop_panels_after_ready())

    async def cog_unload(self):
        task = getattr(self, "_shop_panel_refresh_task", None)
        if task:
            task.cancel()

    async def _emoji_monnaie(self, guild_id: int) -> str:
        reglages = await self.bot.db.get_stats_settings(guild_id)
        return reglages.get("economy_emoji", "🪙")

    async def _panneau_gain(
        self,
        ctx: commands.Context,
        *,
        titre: str,
        resume: str,
        montant: int,
        cooldown: int,
        details: "list[panels.Ligne] | None" = None,
    ) -> None:
        """Panneau commun a toutes les recompenses.

        Les confirmations disaient seulement combien on venait de gagner. Elles ne
        disaient ni le nouveau solde, ni QUAND on peut recommencer — la question
        posee juste apres, a chaque fois. Les deux sont ici.
        """
        emoji = await self._emoji_monnaie(ctx.guild.id)
        stats = await stats_service.get_member_statistics(self.bot, ctx.guild, ctx.author)
        nombre = stats_service.format_number
        prochain = int(time.time()) + cooldown

        gain = [panels.Ligne("Gagné", f"**+{nombre(montant)}** {emoji}")]
        gain.extend(details or [])
        gain.append(panels.Ligne("Nouveau solde", f"{nombre(stats['total_money'])} {emoji}"))

        await panels.envoyer(
            ctx,
            panels.Panneau(
                titre=titre,
                sous_titre=resume,
                kind="economie",
                vignette=ctx.author.display_avatar.url,
                sections=[
                    panels.Section("Récompense", gain),
                    panels.Section(
                        "Prochaine fois",
                        [
                            panels.Ligne("Disponible", f"<t:{prochain}:R>"),
                            panels.Ligne("Soit", f"<t:{prochain}:t>"),
                        ],
                    ),
                ],
                pied="SentriX • Économie",
            ),
        )

    async def _panneau_attente(
        self, ctx: commands.Context, *, titre: str, restant: int, commande: str
    ) -> None:
        """Refus d'une recompense encore en attente.

        « Revenez dans 3h20 » obligeait a calculer soi-meme l'heure. Un horodatage
        Discord s'affiche dans le fuseau de chacun et se met a jour tout seul.
        """
        pret = int(time.time()) + max(0, int(restant))
        await panels.envoyer(
            ctx,
            panels.Panneau(
                titre=titre,
                sous_titre="Cette récompense n'est pas encore disponible.",
                kind="warning",
                sections=[
                    panels.Section(
                        "Disponible",
                        [
                            panels.Ligne("Dans", f"<t:{pret}:R>"),
                            panels.Ligne("À", f"<t:{pret}:t>"),
                        ],
                    ),
                    panels.Section(
                        "En attendant",
                        [
                            panels.Ligne("`+balance`", "Voir votre solde et votre classement"),
                            panels.Ligne("`+shop`", "Dépenser ce que vous avez déjà"),
                        ],
                    ),
                ],
                pied="SentriX • Économie",
            ),
        )

    async def _send_balance(self, ctx: commands.Context, membre: discord.Member):
        """Fiche économique composée : avoirs, activité, position.

        L'ancienne version affichait trois champs côte à côte — portefeuille,
        banque, total — sans dire ce que ces montants valent sur ce serveur. Le
        classement et les gains récurrents rendent le chiffre lisible.
        """
        settings = await self.bot.db.get_stats_settings(ctx.guild.id)
        emoji = settings.get("economy_emoji", "🪙")
        stats = await stats_service.get_member_statistics(self.bot, ctx.guild, membre)
        nombre = stats_service.format_number

        avoirs = [
            panels.Ligne("Portefeuille", f"{nombre(stats['wallet'])} {emoji}"),
            panels.Ligne("Banque", f"{nombre(stats['bank'])} {emoji}"),
            panels.Ligne("Total", f"{nombre(stats['total_money'])} {emoji}"),
        ]

        # Ce que le montant vaut sur CE serveur : sans repère, un chiffre ne dit rien.
        situation: list[panels.Ligne] = []
        if stats.get("is_ranked"):
            situation.append(panels.Ligne("Classement", f"#{stats.get('rank', 0)}"))
        situation.append(panels.Ligne("Niveau", str(stats.get("current_level", 0))))
        situation.append(panels.Ligne("Messages", nombre(stats.get("message_count", 0))))

        sections = [
            panels.Section("Avoirs", avoirs, aligne=True),
            panels.Section("Sur ce serveur", situation, aligne=True),
            panels.Section(
                "Gagner plus",
                [
                    panels.Ligne("`+daily`", "Récompense quotidienne"),
                    panels.Ligne("`+work`", "Travailler, avec un délai entre deux fois"),
                    panels.Ligne("`+shop`", "Dépenser dans la boutique du serveur"),
                ],
            ),
        ]

        panneau = panels.Panneau(
            titre="SentriX — Économie",
            sous_titre=f"{membre.mention} · **{nombre(stats['total_money'])} {emoji}** au total",
            kind="warning" if stats["total_money"] == 0 else "success",
            vignette=membre.display_avatar.url,
            sections=sections,
            pied=f"SentriX • Économie · demandé par {ctx.author.display_name}",
        )
        await panels.envoyer(ctx, panneau)

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
            return await self._panneau_attente(
                ctx, titre="SentriX — Récompense quotidienne", restant=remaining, commande="daily"
            )
        await self._panneau_gain(
            ctx,
            titre="SentriX — Récompense quotidienne",
            resume=f"Récompense du jour encaissée par {ctx.author.mention}.",
            montant=DAILY_AMOUNT,
            cooldown=DAILY_COOLDOWN,
        )

    @commands.hybrid_command(name="weekly", description="Récupérer votre récompense hebdomadaire.")
    async def weekly(self, ctx: commands.Context):
        ok, remaining = await self.bot.db.claim_timed_reward(ctx.guild.id, ctx.author.id, "last_weekly", WEEKLY_AMOUNT, WEEKLY_COOLDOWN, "weekly")
        if not ok:
            return await self._panneau_attente(
                ctx, titre="SentriX — Récompense hebdomadaire", restant=remaining, commande="weekly"
            )
        await self._panneau_gain(
            ctx,
            titre="SentriX — Récompense hebdomadaire",
            resume=f"Récompense de la semaine encaissée par {ctx.author.mention}.",
            montant=WEEKLY_AMOUNT,
            cooldown=WEEKLY_COOLDOWN,
        )

    @commands.hybrid_command(name="work", description="Travailler pour gagner de l'argent.")
    async def work(self, ctx: commands.Context):
        amount = random.randint(WORK_MIN, WORK_MAX)
        ok, remaining = await self.bot.db.claim_timed_reward(ctx.guild.id, ctx.author.id, "last_work", amount, WORK_COOLDOWN, "work")
        if not ok:
            return await self._panneau_attente(
                ctx, titre="SentriX — Travail", restant=remaining, commande="work"
            )
        metiers = ["développeur", "livreur", "chef cuisinier", "streamer", "modérateur", "vendeur"]
        metier = random.choice(metiers)
        await self._panneau_gain(
            ctx,
            titre="SentriX — Travail",
            resume=f"{ctx.author.mention} a travaillé comme **{metier}**.",
            montant=amount,
            cooldown=WORK_COOLDOWN,
            details=[panels.Ligne("Métier", metier.capitalize())],
        )

    @commands.hybrid_command(name="rob", description="Tenter de voler un autre membre.")
    @app_commands.describe(membre="Le membre à voler")
    async def rob(self, ctx: commands.Context, membre: discord.Member):
        if membre.id == ctx.author.id:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Vous ne pouvez pas vous voler vous-même.')))
        if membre.bot:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Vous ne pouvez pas voler un bot.')))
        last = self.rob_cooldowns.get(ctx.author.id, 0)
        if now() - last < ROB_COOLDOWN:
            remaining = ROB_COOLDOWN - (now() - last)
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.warning(f'Vous devez attendre {remaining // 60} minutes avant de retenter un vol.')))
        await self.bot.db.ensure_economy(ctx.guild.id, membre.id)
        target_bal = await self.bot.db.get_balance(ctx.guild.id, membre.id)
        self.rob_cooldowns[ctx.author.id] = now()
        if target_bal["cash"] < 50:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.warning(f"{membre.display_name} n'a pas assez d'argent liquide à voler.")))
        success = random.random() < 0.4
        if success:
            amount = random.randint(1, min(target_bal["cash"], 300))
            await self.bot.db.add_balance(ctx.guild.id, membre.id, -amount)
            await self.bot.db.add_balance(ctx.guild.id, ctx.author.id, amount)
            await self.bot.db.log_transaction(ctx.guild.id, membre.id, ctx.author.id, "rob", amount, "Vol réussi")
            await panels.envoyer(ctx, panels.depuis_embed(embeds.success(f'🕵️ Vous avez volé **{stats_service.format_number(amount)} 🪙** à {membre.display_name} !')))
        else:
            penalty = random.randint(20, 100)
            await self.bot.db.add_balance(ctx.guild.id, ctx.author.id, -penalty)
            await self.bot.db.log_transaction(ctx.guild.id, ctx.author.id, None, "rob_fail", penalty, "Vol raté, amende")
            await panels.envoyer(ctx, panels.depuis_embed(embeds.error(f"🚨 Vous avez été attrapé et payé **{stats_service.format_number(penalty)} 🪙** d'amende !")))

    @commands.hybrid_command(name="pay", description="Transférer de l'argent à un autre membre.")
    @app_commands.describe(membre="Le membre à qui envoyer", montant="Le montant à envoyer (ou 'all' pour tout envoyer)")
    async def pay(self, ctx: commands.Context, membre: discord.Member, montant: str):
        if membre.id == ctx.author.id:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Vous ne pouvez pas vous payer vous-même.')))
        if membre.bot:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Vous ne pouvez pas payer un bot.')))
        await self.bot.db.ensure_economy(ctx.guild.id, ctx.author.id)
        bal = await self.bot.db.get_balance(ctx.guild.id, ctx.author.id)
        amount = _parse_amount(montant, bal["cash"])
        if amount is None or amount <= 0:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Montant invalide — utilisez un nombre positif ou `all`.')))
        ok = await self.bot.db.pay_member(ctx.guild.id, ctx.author.id, membre.id, amount, reason="Paiement entre membres")
        if not ok:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error("Vous n'avez pas assez d'argent liquide (ou le montant est invalide).")))
        await panels.envoyer(ctx, panels.depuis_embed(embeds.success(f'💸 Vous avez envoyé **{stats_service.format_number(amount)} 🪙** à {membre.mention}.')))

    @commands.hybrid_command(name="economyleaderboard", description="Afficher le classement des plus riches.")
    async def economyleaderboard(self, ctx: commands.Context):
        """Classement economique, compose.

        Le podium etait en trois champs cote a cote et la suite dans la
        description : deux mises en forme differentes pour la meme liste. Et la
        position du demandeur, ce qu'on cherche d'abord, n'apparaissait nulle part.
        """
        emoji = await self._emoji_monnaie(ctx.guild.id)
        rows = await self.bot.db.fetchall(
            "SELECT * FROM economy WHERE guild_id = ? ORDER BY (cash + bank) DESC LIMIT 50",
            (ctx.guild.id,),
        )
        classement = []
        for row in rows:
            membre = ctx.guild.get_member(row["user_id"])
            if membre is not None and membre.bot:
                continue
            nom = membre.display_name if membre else f"Utilisateur {row['user_id']}"
            classement.append((row["user_id"], nom, int(row["cash"] + row["bank"])))

        if not classement:
            return await panels.envoyer(
                ctx,
                panels.Panneau(
                    titre="SentriX — Classement économique",
                    sous_titre="Personne n'a encore de solde sur ce serveur.",
                    kind="economie",
                    sections=[
                        panels.Section(
                            "Comment démarrer",
                            [
                                panels.Ligne("`+daily`", "Récompense quotidienne"),
                                panels.Ligne("`+work`", "Travailler pour gagner"),
                            ],
                        )
                    ],
                    pied="SentriX • Économie",
                ),
            )

        nombre = stats_service.format_number
        medailles = ("1er", "2e", "3e")
        podium = [
            panels.Ligne(medailles[i], f"**{nom}**", indice=f"{nombre(total)} {emoji}")
            for i, (_uid, nom, total) in enumerate(classement[:3])
        ]
        suite = [
            panels.Ligne(f"{i}", f"{nom} · {nombre(total)}")
            for i, (_uid, nom, total) in enumerate(classement[3:10], start=4)
        ]

        sections = [panels.Section("Podium", podium)]
        if suite:
            sections.append(panels.Section("Suivants", suite, aligne=True))

        rang = next(
            (i for i, (uid, *_r) in enumerate(classement, start=1) if uid == ctx.author.id), None
        )
        if rang is not None:
            _uid, _nom, total = classement[rang - 1]
            ecart = classement[rang - 2][2] - total if rang > 1 else 0
            lignes = [
                panels.Ligne("Rang", f"**#{rang}** sur {len(classement)}"),
                panels.Ligne("Fortune", f"{nombre(total)} {emoji}"),
            ]
            if ecart > 0:
                lignes.append(panels.Ligne("Pour passer devant", f"{nombre(ecart + 1)} {emoji}"))
            sections.append(panels.Section("Votre position", lignes, aligne=True))
        else:
            sections.append(
                panels.Section(
                    "Votre position",
                    [panels.Ligne("Non classé", "`+daily` puis `+work` pour démarrer")],
                )
            )

        await panels.envoyer(
            ctx,
            panels.Panneau(
                titre="SentriX — Classement économique",
                sous_titre=f"**{len(classement)}** membre(s) classé(s) sur {ctx.guild.name}.",
                kind="economie",
                sections=sections,
                pied="SentriX • Économie",
            ),
        )

    @commands.hybrid_command(name="leaderboard-money", description="Afficher le classement des plus riches.", with_app_command=False)
    async def leaderboard_money(self, ctx: commands.Context):
        """Alias historique de /economyleaderboard — conservé pour ne rien casser."""
        await self.economyleaderboard(ctx)

    @commands.command(name="shopsetup", aliases=["boutiquesetup"])
    @checks.is_owner_or_admin()
    async def shopsetup(self, ctx: commands.Context):
        """Affiche le guide court de configuration de la boutique de rôles."""
        await self._send_shop_setup(ctx)

    async def _send_shop_setup(self, ctx: commands.Context):
        await panels.envoyer(ctx, panels.depuis_embed(embeds.info('**Configurer la boutique de rôles**\n`+shoprole add @VIP 500` — ajoute un rôle au prix choisi\n`+shoprole add @VIP @Booster 500` — ajoute plusieurs rôles au même prix\n`+shoprole price @VIP 750` — change le prix\n`+shoprole remove @VIP` — retire le rôle de la boutique\n`+shoprole list` — affiche la configuration\n`+shoppanel` — publie le menu interactif dans le salon\n\nAprès cela, les membres choisissent directement un rôle dans le menu : aucune commande à taper.')))

    async def _shop_role_options(self, guild: discord.Guild) -> list[list[discord.SelectOption]]:
        rows = await self.bot.db.fetchall(
            "SELECT * FROM shop_items WHERE guild_id = ? AND role_id IS NOT NULL ORDER BY price ASC, id ASC LIMIT 100",
            (guild.id,),
        )
        options = []
        for item in rows:
            role = guild.get_role(item["role_id"])
            if role is None or _self_assignable_role_error(guild, role):
                continue
            details = f"Prix : {stats_service.format_number(item['price'])} pièces"
            if item["description"]:
                details = f"{details} — {item['description']}"
            options.append(discord.SelectOption(
                label=role.name[:100],
                value=str(item["id"]),
                description=details[:100],
            ))
        return [options[index:index + 25] for index in range(0, len(options), 25)]

    async def _shop_panel_embed(self, guild: discord.Guild) -> discord.Embed:
        count = await self.bot.db.fetchone(
            "SELECT COUNT(*) AS total FROM shop_items WHERE guild_id = ? AND role_id IS NOT NULL",
            (guild.id,),
        )
        total = int(count["total"] if count else 0)
        design = await self.bot.db.get_design_settings(guild.id)
        style = design_system.CATEGORY_STYLES["economy"]
        return design_system.create_embed(
            title="Boutique de rôles",
            description=(
                f'**{total} rôle(s) disponible(s)**\nChoisissez un rôle ci-dessous. Le prix est débité automatiquement et le résultat reste privé.'
            ),
            colour=design.get("primary_color", style["colour"]),
            footer=design.get("footer"),
        )

    async def _refresh_shop_panels(self, guild: discord.Guild):
        panels = await self.bot.db.fetchall(
            "SELECT * FROM shop_panels WHERE guild_id = ?",
            (guild.id,),
        )
        if not panels:
            return
        chunks = await self._shop_role_options(guild)
        embed = await self._shop_panel_embed(guild)
        for panel in panels:
            channel = guild.get_channel(panel["channel_id"]) or self.bot.get_channel(panel["channel_id"])
            if channel is None:
                continue
            try:
                message = await channel.fetch_message(panel["message_id"])
                view = ShopRoleView(chunks)
                if message.reference is not None:
                    replacement = await channel.send(embed=embed, view=view)
                    await self.bot.db.execute(
                        "INSERT INTO shop_panels (guild_id, channel_id, message_id, created_by, created_at) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (
                            guild.id,
                            channel.id,
                            replacement.id,
                            panel["created_by"],
                            panel["created_at"],
                        ),
                    )
                    await self.bot.db.execute(
                        "DELETE FROM shop_panels WHERE guild_id = ? AND message_id = ?",
                        (guild.id, panel["message_id"]),
                    )
                    try:
                        await message.delete()
                    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                        pass
                    continue
                await message.edit(embed=embed, view=view)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                continue

    async def _refresh_shop_panels_after_ready(self):
        await self.bot.wait_until_ready()
        for guild in self.bot.guilds:
            await self._refresh_shop_panels(guild)

    @commands.command(name="shoppanel", aliases=["boutiquepanel", "shop-panel"])
    @checks.is_owner_or_admin()
    async def shoppanel(self, ctx: commands.Context):
        """Publie la boutique que les membres utilisent sans commande."""
        chunks = await self._shop_role_options(ctx.guild)
        message = await ctx.channel.send(embed=await self._shop_panel_embed(ctx.guild), view=ShopRoleView(chunks))
        await self.bot.db.execute(
            "INSERT INTO shop_panels (guild_id, channel_id, message_id, created_by, created_at) "
            "VALUES (?, ?, ?, ?, ?) ON CONFLICT(guild_id, message_id) DO NOTHING",
            (ctx.guild.id, ctx.channel.id, message.id, ctx.author.id, now()),
        )

    async def handle_shop_selection(self, interaction: discord.Interaction, raw_item_id: str):
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("Cette boutique fonctionne uniquement dans un serveur.", ephemeral=True)
        try:
            item_id = int(raw_item_id)
        except ValueError:
            return await interaction.response.send_message("Ce choix n'est plus disponible.", ephemeral=True)
        item = await self.bot.db.fetchone(
            "SELECT * FROM shop_items WHERE guild_id = ? AND id = ? AND role_id IS NOT NULL",
            (interaction.guild.id, item_id),
        )
        if item is None:
            return await interaction.response.send_message("Ce rôle n'est plus dans la boutique.", ephemeral=True)
        await interaction.response.defer(ephemeral=True, thinking=True)
        result = await self._purchase_role_result(interaction.guild, interaction.user, item)
        await interaction.followup.send(embed=result, ephemeral=True)

    @commands.group(name="shoprole", aliases=["boutiquerole"], invoke_without_command=True)
    @checks.is_owner_or_admin_for("economie")
    async def shoprole(self, ctx: commands.Context):
        """Configure les rôles achetables avec l'argent du portefeuille."""
        await self._send_shop_setup(ctx)

    @shoprole.command(name="add", aliases=["ajouter"])
    @checks.is_owner_or_admin()
    async def shoprole_add(
        self,
        ctx: commands.Context,
        roles: commands.Greedy[discord.Role],
        price: int,
        *,
        description: str = "",
    ):
        if not roles:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Mentionnez au moins un rôle à ajouter.')))
        if price < 1 or price > 1_000_000_000_000:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Le prix doit être compris entre 1 et 1 000 000 000 000.')))
        accepted = []
        refused = []
        for role in roles:
            error = _self_assignable_role_error(ctx.guild, role)
            if error:
                refused.append(f"{role.mention} : {error}")
                continue
            existing = await self.bot.db.fetchone(
                "SELECT id FROM shop_items WHERE guild_id = ? AND role_id = ?",
                (ctx.guild.id, role.id),
            )
            if existing:
                await self.bot.db.execute(
                    "UPDATE shop_items SET name = ?, price = ?, description = ? WHERE id = ?",
                    (role.name, price, description.strip(), existing["id"]),
                )
                accepted.append(f"{role.mention} (article #{existing['id']} mis à jour)")
            else:
                cursor = await self.bot.db.execute(
                    "INSERT INTO shop_items (guild_id, name, price, description, role_id) VALUES (?, ?, ?, ?, ?)",
                    (ctx.guild.id, role.name, price, description.strip(), role.id),
                )
                accepted.append(f"{role.mention} (article #{cursor.lastrowid})")
        description_lines = []
        if accepted:
            description_lines.append(
                f"**Ajoutés à {stats_service.format_number(price)} 🪙**\n" + "\n".join(accepted)
            )
        if refused:
            description_lines.append("**Refusés**\n" + "\n".join(refused))
        if accepted:
            await self._refresh_shop_panels(ctx.guild)
        kind = "success" if accepted else "danger"
        await panels.envoyer(ctx, panels.depuis_embed(await self._shop_config_embed(ctx.guild.id, 'Boutique mise à jour', '\n\n'.join(description_lines), kind)))

    @shoprole.command(name="remove", aliases=["delete", "retirer"])
    @checks.is_owner_or_admin()
    async def shoprole_remove(self, ctx: commands.Context, role: discord.Role):
        cursor = await self.bot.db.execute(
            "DELETE FROM shop_items WHERE guild_id = ? AND role_id = ?",
            (ctx.guild.id, role.id),
        )
        if cursor.rowcount < 1:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error("Ce rôle n'est pas dans la boutique.")))
        await self._refresh_shop_panels(ctx.guild)
        await panels.envoyer(ctx, panels.depuis_embed(embeds.success(f'{role.mention} a été retiré de la boutique.')))

    @shoprole.command(name="price", aliases=["prix"])
    @checks.is_owner_or_admin()
    async def shoprole_price(self, ctx: commands.Context, role: discord.Role, price: int):
        if price < 1 or price > 1_000_000_000_000:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Le prix doit être compris entre 1 et 1 000 000 000 000.')))
        cursor = await self.bot.db.execute(
            "UPDATE shop_items SET price = ?, name = ? WHERE guild_id = ? AND role_id = ?",
            (price, role.name, ctx.guild.id, role.id),
        )
        if cursor.rowcount < 1:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error("Ce rôle n'est pas dans la boutique.")))
        await self._refresh_shop_panels(ctx.guild)
        await panels.envoyer(ctx, panels.depuis_embed(embeds.success(f'Le prix de {role.mention} est maintenant de **{stats_service.format_number(price)} 🪙**.')))

    @shoprole.command(name="list", aliases=["liste"])
    @checks.is_owner_or_admin()
    async def shoprole_list(self, ctx: commands.Context):
        await self._send_shop(ctx)

    async def _shop_config_embed(self, guild_id: int, title: str, description: str, kind: str) -> discord.Embed:
        design = await self.bot.db.get_design_settings(guild_id)
        style = design_system.CATEGORY_STYLES["economy"]
        colour_key = "success_color" if kind == "success" else "danger_color"
        default = getattr(design_system.COLORS, kind)
        return design_system.create_embed(
            title=design_system.kind_title(title, kind=kind, category_emoji=style["emoji"]),
            description=description,
            colour=design.get(colour_key, default),
            footer=design.get("footer"),
        )

    @commands.hybrid_command(name="shop", description="Afficher la boutique du serveur.")
    async def shop(self, ctx: commands.Context):
        await self._send_shop(ctx)

    async def _send_shop(self, ctx: commands.Context):
        design = await self.bot.db.get_design_settings(ctx.guild.id)
        items = await self.bot.db.fetchall(
            "SELECT * FROM shop_items WHERE guild_id = ? ORDER BY price ASC, id ASC",
            (ctx.guild.id,),
        )
        if not items:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.info("La boutique est vide pour l'instant.")))

        chunks = [items[index:index + 6] for index in range(0, len(items), 6)]
        pages: list[discord.Embed] = []
        style = design_system.CATEGORY_STYLES["economy"]
        for page_number, chunk in enumerate(chunks, start=1):
            lines = []
            for item in chunk:
                role = ctx.guild.get_role(item["role_id"]) if item["role_id"] else None
                name = role.mention if role else item["name"]
                suffix = f" — {item['description']}" if item["description"] else ""
                if item["role_id"] and role is None:
                    suffix += " — indisponible"
                lines.append(
                    f"**#{item['id']}** {name} • **{stats_service.format_number(item['price'])} pièces**{suffix}"
                )
            embed = design_system.create_embed(
                title="Boutique",
                description="\n".join(lines) + "\n\nAcheter : +buy <id> ou +buyrole @rôle",
                colour=design.get("primary_color", style["colour"]),
                footer=f"Page {page_number}/{len(chunks)}",
            )
            pages.append(embed)

        view = ShopCatalogueView(pages, ctx.author.id)
        message = await ctx.send(embed=pages[0], view=view)
        view.message = message

    @commands.hybrid_command(name="buy", description="Acheter un article de la boutique.")
    @app_commands.describe(id="L'identifiant de l'article (voir /shop)")
    async def buy(self, ctx: commands.Context, id: int):
        item = await self.bot.db.fetchone("SELECT * FROM shop_items WHERE id = ? AND guild_id = ?", (id, ctx.guild.id))
        if not item:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Article introuvable.')))
        await self._purchase_item(ctx, item)

    @commands.command(name="buyrole", aliases=["acheterrole"])
    async def buyrole(self, ctx: commands.Context, role: discord.Role):
        item = await self.bot.db.fetchone(
            "SELECT * FROM shop_items WHERE guild_id = ? AND role_id = ?",
            (ctx.guild.id, role.id),
        )
        if not item:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error("Ce rôle n'est pas dans la boutique.")))
        await self._purchase_item(ctx, item)

    async def _purchase_item(self, ctx: commands.Context, item):
        if item["role_id"]:
            result = await self._purchase_role_result(ctx.guild, ctx.author, item)
            return await ctx.send(embed=result)

        status, purchased_item = await self.bot.db.purchase_shop_item(ctx.guild.id, ctx.author.id, item["id"])
        if status == "not_found":
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Article introuvable ou prix invalide.')))
        if status == "insufficient_funds":
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error("Vous n'avez pas assez d'argent dans votre portefeuille. Utilisez `+withdraw` pour retirer de la banque.")))
        await self.bot.db.execute(
            "INSERT INTO inventory (guild_id, user_id, item_name, quantity) VALUES (?, ?, ?, 1) "
            "ON CONFLICT(guild_id, user_id, item_name) DO UPDATE SET quantity = quantity + 1",
            (ctx.guild.id, ctx.author.id, purchased_item["name"]),
        )
        await panels.envoyer(ctx, panels.depuis_embed(embeds.success(f"Vous avez acheté **{purchased_item['name']}** pour {stats_service.format_number(purchased_item['price'])} 🪙.")))

    async def _purchase_role_result(self, guild: discord.Guild, member: discord.Member, item) -> discord.Embed:
        role = guild.get_role(item["role_id"]) if item["role_id"] else None
        if role is None:
            return embeds.error("Ce rôle n'existe plus. Un administrateur doit actualiser la boutique.")
        role_error = _self_assignable_role_error(guild, role)
        if role_error:
            return embeds.error(role_error)
        if role in member.roles:
            return embeds.info("Vous possédez déjà ce rôle. Aucun argent n'a été retiré.")

        status, purchased_item = await self.bot.db.purchase_shop_item(guild.id, member.id, item["id"])
        if status == "not_found":
            return embeds.error("Ce rôle n'est plus disponible dans la boutique.")
        if status == "insufficient_funds":
            return embeds.error(
                f"Vous n'avez pas assez d'argent. Ce rôle coûte **{stats_service.format_number(item['price'])} 🪙**."
            )
        if status == "already_owned":
            # Cas d'un rôle acheté auparavant puis retiré, ou d'un double-clic : on le
            # restaure sans facturer une deuxième fois.
            try:
                await member.add_roles(role, reason=f"Restauration achat boutique #{item['id']}")
            except (discord.Forbidden, discord.HTTPException):
                return embeds.error(
                    "Ce rôle a déjà été acheté, mais Discord refuse de le réattribuer. Vérifiez la hiérarchie des rôles."
                )
            return embeds.success(
                f"{role.mention} vous a été restauré sans nouvel achat."
            )

        try:
            await member.add_roles(role, reason=f"Achat boutique #{purchased_item['id']}")
        except (discord.Forbidden, discord.HTTPException):
            await self.bot.db.refund_shop_item(
                guild.id,
                member.id,
                purchased_item,
                f"Remboursement : attribution du rôle {role.name} impossible",
            )
            return embeds.error("Discord a refusé le rôle. Votre argent a été automatiquement remboursé.")
        return embeds.success(
            f"Vous avez acheté {role.mention} pour **{stats_service.format_number(purchased_item['price'])} 🪙**."
        )

    @commands.hybrid_command(name="inventory", description="Afficher votre inventaire.", with_app_command=False)
    async def inventory(self, ctx: commands.Context):
        design = await self.bot.db.get_design_settings(ctx.guild.id)
        rows = await self.bot.db.fetchall(
            "SELECT * FROM inventory WHERE guild_id = ? AND user_id = ?", (ctx.guild.id, ctx.author.id)
        )
        emoji = await self._emoji_monnaie(ctx.guild.id)
        nombre = stats_service.format_number
        if not rows:
            return await panels.envoyer(
                ctx,
                panels.Panneau(
                    titre="SentriX — Inventaire",
                    sous_titre=f"L'inventaire de {ctx.author.mention} est vide.",
                    kind="economie",
                    vignette=ctx.author.display_avatar.url,
                    sections=[
                        panels.Section(
                            "Comment le remplir",
                            [
                                panels.Ligne("`+shop`", "Voir ce que le serveur propose"),
                                panels.Ligne("`+buy <objet>`", "Acheter avec votre solde"),
                            ],
                        )
                    ],
                    pied="SentriX • Économie",
                ),
            )

        objets = sorted(rows, key=lambda r: int(r["quantity"]), reverse=True)
        total_objets = sum(int(r["quantity"]) for r in objets)
        await panels.envoyer(
            ctx,
            panels.Panneau(
                titre="SentriX — Inventaire",
                sous_titre=f"{ctx.author.mention} possède **{nombre(total_objets)}** objet(s), "
                           f"en **{len(objets)}** type(s).",
                kind="economie",
                vignette=ctx.author.display_avatar.url,
                sections=[
                    panels.Section(
                        f"Objets ({len(objets)})",
                        [
                            panels.Ligne(str(r["item_name"]), nombre(r["quantity"]))
                            for r in objets[:20]
                        ],
                        aligne=True,
                    ),
                    panels.Section(
                        "Que faire",
                        [
                            panels.Ligne("`+sell <objet>`", "Revendre un objet"),
                            panels.Ligne("`+balance`", "Voir votre solde"),
                        ],
                    ),
                ],
                pied="SentriX • Économie",
            ),
        )

    @commands.hybrid_command(name="sell", description="Vendre un article de votre inventaire.", with_app_command=False)
    @app_commands.describe(objet="Le nom de l'objet à vendre")
    async def sell(self, ctx: commands.Context, *, objet: str):
        row = await self.bot.db.fetchone(
            "SELECT * FROM inventory WHERE guild_id = ? AND user_id = ? AND item_name = ?", (ctx.guild.id, ctx.author.id, objet)
        )
        if not row or row["quantity"] < 1:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Vous ne possédez pas cet objet.')))
        item = await self.bot.db.fetchone("SELECT * FROM shop_items WHERE guild_id = ? AND name = ?", (ctx.guild.id, objet))
        price = int(item["price"] * 0.5) if item else 10
        await self.bot.db.execute(
            "UPDATE inventory SET quantity = quantity - 1 WHERE guild_id = ? AND user_id = ? AND item_name = ?",
            (ctx.guild.id, ctx.author.id, objet),
        )
        await self.bot.db.add_balance(ctx.guild.id, ctx.author.id, price)
        await self.bot.db.log_transaction(ctx.guild.id, None, ctx.author.id, "sell", price, f"Vente : {objet}")
        await panels.envoyer(ctx, panels.depuis_embed(embeds.success(f'Vous avez vendu **{objet}** pour {stats_service.format_number(price)} 🪙.')))

    @commands.hybrid_command(name="gamble", description="Miser de l'argent au casino (50% de chance).")
    @app_commands.describe(montant="Le montant à miser")
    async def gamble(self, ctx: commands.Context, montant: int):
        if montant <= 0:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Le montant doit être positif.')))
        await self.bot.db.ensure_economy(ctx.guild.id, ctx.author.id)
        bal = await self.bot.db.get_balance(ctx.guild.id, ctx.author.id)
        if bal["cash"] < montant:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error("Vous n'avez pas assez d'argent.")))
        if random.random() < 0.5:
            await self.bot.db.add_balance(ctx.guild.id, ctx.author.id, montant)
            await self.bot.db.log_transaction(ctx.guild.id, None, ctx.author.id, "gamble_win", montant, "Casino")
            await panels.envoyer(ctx, panels.depuis_embed(embeds.success(f'🎰 Vous avez gagné **{stats_service.format_number(montant)} 🪙** !')))
        else:
            await self.bot.db.add_balance(ctx.guild.id, ctx.author.id, -montant)
            await self.bot.db.log_transaction(ctx.guild.id, ctx.author.id, None, "gamble_loss", montant, "Casino")
            await panels.envoyer(ctx, panels.depuis_embed(embeds.error(f'🎰 Vous avez perdu **{stats_service.format_number(montant)} 🪙**.')))

    async def _deposit_to_bank(self, ctx: commands.Context, montant: str):
        """Transfère un montant du portefeuille vers la banque."""
        await self.bot.db.ensure_economy(ctx.guild.id, ctx.author.id)
        bal = await self.bot.db.get_balance(ctx.guild.id, ctx.author.id)
        amount = _parse_amount(montant, bal["cash"])
        if amount is None or amount <= 0 or amount > bal["cash"]:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Montant invalide. Utilisez un nombre positif ou `all`.')))
        await self.bot.db.execute(
            "UPDATE economy SET cash = cash - ?, bank = bank + ? WHERE guild_id = ? AND user_id = ?",
            (amount, amount, ctx.guild.id, ctx.author.id),
        )
        await panels.envoyer(ctx, panels.depuis_embed(embeds.success(f'{stats_service.format_number(amount)} 🪙 transférés dans votre banque. Cet argent ne peut pas être volé.')))

    @commands.hybrid_command(name="deposit", description="Déposer de l'argent à la banque (ou 'all').", with_app_command=False)
    @app_commands.describe(montant="Le montant à déposer (ou 'all')")
    async def deposit(self, ctx: commands.Context, montant: str):
        await self._deposit_to_bank(ctx, montant)

    @commands.hybrid_command(name="withdraw", description="Retirer de l'argent de la banque (ou 'all').", with_app_command=False)
    @app_commands.describe(montant="Le montant à retirer (ou 'all')")
    async def withdraw(self, ctx: commands.Context, montant: str):
        await self.bot.db.ensure_economy(ctx.guild.id, ctx.author.id)
        bal = await self.bot.db.get_balance(ctx.guild.id, ctx.author.id)
        amount = _parse_amount(montant, bal["bank"])
        if amount is None or amount <= 0 or amount > bal["bank"]:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Montant invalide.')))
        await self.bot.db.execute(
            "UPDATE economy SET cash = cash + ?, bank = bank - ? WHERE guild_id = ? AND user_id = ?",
            (amount, amount, ctx.guild.id, ctx.author.id),
        )
        await panels.envoyer(ctx, panels.depuis_embed(embeds.success(f'💵 {stats_service.format_number(amount)} 🪙 retirés de la banque.')))

    @commands.hybrid_command(
        name="banque",
        aliases=["bank"],
        description="Déposer de l'argent à la banque ou afficher votre solde.",
        with_app_command=False,
    )
    @app_commands.describe(montant="Montant à déposer, ou 'all' pour tout déposer (optionnel)")
    async def bank(self, ctx: commands.Context, montant: str = None):
        if montant is not None:
            return await self._deposit_to_bank(ctx, montant)

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
        await panels.envoyer(ctx, panels.depuis_embed(e))

    @commands.hybrid_command(name="give-money", description="[Admin] Donner de l'argent à un membre.", with_app_command=False)
    @app_commands.describe(membre="Le membre visé", montant="Le montant à donner")
    @checks.is_owner_or_admin_for("economie")
    async def give_money(self, ctx: commands.Context, membre: discord.Member, montant: int):
        await self.bot.db.ensure_economy(ctx.guild.id, membre.id)
        await self.bot.db.add_balance(ctx.guild.id, membre.id, montant)
        await self.bot.db.log_transaction(ctx.guild.id, ctx.author.id, membre.id, "admin_grant", montant, "Ajout manuel (staff)")
        await panels.envoyer(ctx, panels.depuis_embed(embeds.success(f'{stats_service.format_number(montant)} 🪙 ajoutés au compte de {membre.mention}.')))

    @commands.hybrid_command(name="reset-economy", description="[Admin] Réinitialiser l'économie du serveur.", with_app_command=False)
    @checks.is_owner_or_admin_for("economie")
    async def reset_economy(self, ctx: commands.Context):
        await self.bot.db.execute("DELETE FROM economy WHERE guild_id = ?", (ctx.guild.id,))
        await panels.envoyer(ctx, panels.depuis_embed(embeds.success("L'économie du serveur a été réinitialisée. (L'historique des transactions est conservé pour l'audit.)")))


async def setup(bot: commands.Bot):
    await bot.add_cog(Economy(bot))
