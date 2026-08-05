"""
Cog UTILITAIRES.
/help /ping /avatar /serverinfo /userinfo /roleinfo /channelinfo
/membercount /addemoji /emoji-list /poll /remind /reminder-list /reminder-cancel
/say /embed-create /translate /weather /suggest /report-bug
/afk /roll /choose
"""

import asyncio
import ipaddress
import logging
import re
import socket
from urllib.parse import urljoin, urlparse

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from utils import embeds, helpers, checks, design_system
from database.db import now

logger = logging.getLogger("bot")

# Ordre volontaire : catégories utiles à tout le monde en premier, catégories staff/technique
# ensuite — pour que /help mette en avant ce qui sert le plus grand nombre.
CATEGORY_LABELS = {
    "Ai": "🤖 Intelligence Artificielle",
    "Economy": "💰 Économie",
    "Levels": "📈 Niveaux / Communauté",
    "Minigames": "🎮 Mini-jeux",
    "Music": "🎵 Musique",
    "Events": "🎉 Giveaways / Événements",
    "Invites": "📨 Invitations",
    "Utility": "🧰 Utilitaires",
    "Moderation": "🛡️ Modération",
    "Automod": "🔒 Sécurité / AutoMod",
    "Security": "🔐 Sécurité avancée",
    "Tickets": "🎫 Tickets",
    "Verification": "● Vérification / Rôles",
    "Configuration": "⚙️ Configuration",
    "ServerBuilder": "🏗️ Création de serveur",
    "Stats": "📊 Statistiques / Développement",
    "Owner": "🔑 Propriétaire du bot",
    "EmbedBuilder": "📨 Créateur d'embeds",
    "Design": "Design et apparence",
}

# Catégories entièrement réservées au staff : un membre normal ne les voit JAMAIS
# dans /help, même si elles contiennent une commande techniquement publique.
MEMBER_HIDDEN_CATEGORIES = {"Moderation", "Automod", "Security", "Tickets", "Configuration", "ServerBuilder", "Utility", "Verification", "Stats", "Owner", "EmbedBuilder"}

# Décorateurs qui, sur une commande, signifient "réservé au staff". On les repère par
# le nom qualifié de la fonction de vérification plutôt que par une liste de commandes
# écrite à la main : ainsi le filtrage reste juste même quand des commandes sont
# ajoutées ou déplacées plus tard.
STAFF_CHECK_MARKERS = ("is_owner_or_admin", "has_permission_or_modrole", "has_permissions", "has_guild_permissions", "is_owner", "is_bot_owner")


def is_staff_command(cmd) -> bool:
    for check in getattr(cmd, "checks", []):
        qualname = getattr(check, "__qualname__", "") or ""
        if any(marker in qualname for marker in STAFF_CHECK_MARKERS):
            return True
    return False


def visible_commands(cog, is_staff: bool):
    # walk_commands inclut aussi toutes les sous-commandes des groupes. Cela évite que
    # +help oublie d'anciennes commandes dès qu'elles sont rangées dans un groupe.
    walker = getattr(cog, "walk_commands", None)
    source = list(walker()) if walker else cog.get_commands()
    cmds = [c for c in source if not c.hidden]
    return cmds if is_staff else [c for c in cmds if not is_staff_command(c)]


def category_visible(cog_name: str, cog, is_staff: bool) -> bool:
    if not is_staff and cog_name in MEMBER_HIDDEN_CATEGORIES:
        return False
    return bool(visible_commands(cog, is_staff))


def split_category_label(label: str) -> tuple[str | None, str]:
    """Sépare l'emoji décoratif du nom seulement si le premier élément est réellement
    un symbole. Une catégorie textuelle comme "Design et apparence" reste intacte."""
    first, separator, rest = label.partition(" ")
    if separator and first and any(not char.isalnum() for char in first):
        return first, rest
    return None, label


CATEGORY_EMOJI = {name: split_category_label(label)[0] for name, label in CATEGORY_LABELS.items()}


def build_help_home(bot: commands.Bot, guild: discord.Guild | None, prefix: str, is_staff: bool) -> discord.Embed:
    """Construit l'embed d'accueil de /help. Partagé entre la première commande et le
    bouton "Accueil", pour que revenir en arrière affiche exactement la même chose."""
    rows = []  # (nom sans emoji, nombre de commandes, réservé au staff ?)
    visible_total = 0
    for cog_name, label in CATEGORY_LABELS.items():
        cog = bot.get_cog(cog_name)
        if not cog or not category_visible(cog_name, cog, is_staff):
            continue
        count = len(visible_commands(cog, is_staff))
        visible_total += count
        name = split_category_label(label)[1]
        rows.append((name, count, cog_name in MEMBER_HIDDEN_CATEGORIES))

    bot_name = bot.user.name if bot.user else "le bot"
    server_name = guild.name if guild else "ce serveur"

    e = embeds.brand(
        f"📖 Bienvenue dans l'aide de {bot_name}",
        f"Je suis l'assistant du serveur **{server_name}**. Je m'occupe de la modération, de la sécurité, "
        f"des tickets de support, de l'économie virtuelle, des niveaux, de la musique et de plein de "
        f"mini-jeux — pour que la communauté reste agréable et vivante.\n\n"
        f"Utilisez le menu déroulant tout en bas pour explorer une catégorie en détail, le bouton "
        f"**🔎 Rechercher** pour trouver une commande par mot-clé, ou tapez `{prefix}help <commande>` "
        f"pour l'aide détaillée d'une commande précise."
    )
    if bot.user:
        e.set_thumbnail(url=bot.user.display_avatar.url)

    if rows:
        name_width = max(len(n) for n, _, _ in rows) + 2
        lines = []
        for name, count, staff_only in rows:
            suffix = " (staff)" if staff_only else ""
            lines.append(f"{name.ljust(name_width)}{str(count).rjust(2)}{suffix}")
        e.add_field(name="📚 Catégories disponibles", value="```\n" + "\n".join(lines) + "\n```", inline=False)

    e.add_field(
        name="ℹ️ Bon à savoir",
        value=(
            f"**{visible_total} commande(s)** disponibles pour vous. Toutes fonctionnent avec le "
            f"préfixe `{prefix}` ; celles marquées `/ ou {prefix}` fonctionnent aussi en slash.\n"
            f"Astuce : `/sentrix <question>` répond à n'importe quelle question avec une jauge de confiance."
        ),
        inline=False,
    )
    return e


def format_command_line(cmd, prefix: str, slash_names: set) -> str:
    marker = f"/ ou {prefix}" if cmd.qualified_name in slash_names else prefix
    usage = ""
    if isinstance(cmd, commands.HybridCommand) and cmd.clean_params:
        parts = []
        for pname, param in cmd.clean_params.items():
            parts.append(f"[{pname}]" if param.required else f"({pname})")
        usage = " " + " ".join(parts)
    lock = "🔒 " if is_staff_command(cmd) else ""
    return f"{lock}**`{marker}{cmd.qualified_name}{usage}`**\n╰ {cmd.description or 'Pas de description.'}"


def search_commands(bot: commands.Bot, is_staff: bool, keyword: str):
    """Cherche un mot-clé dans le nom ET la description de toutes les commandes visibles,
    toutes catégories confondues. Retourne une liste de (label_catégorie, commande)."""
    keyword = keyword.lower().strip()
    results = []
    for cog_name, label in CATEGORY_LABELS.items():
        cog = bot.get_cog(cog_name)
        if not cog or not category_visible(cog_name, cog, is_staff):
            continue
        for cmd in visible_commands(cog, is_staff):
            haystack = f"{cmd.qualified_name} {cmd.description or ''}".lower()
            if keyword in haystack:
                results.append((label, cmd))
    return results


class SearchModal(discord.ui.Modal, title="🔎 Rechercher une commande"):
    mot_cle = discord.ui.TextInput(label="Mot-clé (nom ou description)", max_length=50)

    def __init__(self, bot: commands.Bot, prefix: str, is_staff: bool):
        super().__init__()
        self.bot = bot
        self.prefix = prefix
        self.is_staff = is_staff

    async def on_submit(self, interaction: discord.Interaction):
        slash_names = {c.qualified_name for c in self.bot.tree.get_commands()}
        results = search_commands(self.bot, self.is_staff, self.mot_cle.value)

        if not results:
            e = embeds.brand("🔎 Recherche", f"Aucune commande trouvée pour `{self.mot_cle.value}`.")
            return await interaction.response.edit_message(embed=e, view=HelpView(self.bot, self.prefix, self.is_staff))

        lines = [f"*{label}*\n{format_command_line(cmd, self.prefix, slash_names)}" for label, cmd in results]
        chunks = [lines[i:i + 6] for i in range(0, len(lines), 6)] or [[]]
        pages = []
        for i, chunk in enumerate(chunks):
            e = embeds.brand(f"🔎 Résultats pour « {self.mot_cle.value} »", "\n\n".join(chunk))
            e.set_footer(text=f"Page {i + 1}/{len(chunks)} • {len(results)} commande(s) trouvée(s)")
            pages.append(e)

        home_embed = build_help_home(self.bot, interaction.guild, self.prefix, self.is_staff)
        view = CategoryHelpView(self.bot, self.prefix, self.is_staff, pages, interaction.user.id, home_embed)
        await interaction.response.edit_message(embed=pages[0], view=view)


class HelpSelect(discord.ui.Select):
    def __init__(self, bot: commands.Bot, prefix: str, is_staff: bool):
        self.bot = bot
        self.prefix = prefix
        self.is_staff = is_staff
        options = []
        for cog_name, label in CATEGORY_LABELS.items():
            cog = bot.get_cog(cog_name)
            if not cog or not category_visible(cog_name, cog, is_staff):
                continue
            # Aucun emoji dans les options : Discord rejette certains symboles Unicode
            # ordinaires (par exemple ●) lorsqu'ils sont envoyés comme emoji de composant.
            options.append(discord.SelectOption(
                label=split_category_label(label)[1],
                value=cog_name,
                description=f"{len(visible_commands(cog, is_staff))} commande(s)",
            ))
        # Discord autorise au maximum 25 options dans un menu.
        super().__init__(placeholder="Choisissez une catégorie...", options=options[:25])

    async def callback(self, interaction: discord.Interaction):
        cog = self.bot.get_cog(self.values[0])
        label = CATEGORY_LABELS.get(self.values[0], self.values[0])
        slash_names = {c.qualified_name for c in self.bot.tree.get_commands()}

        lines = [format_command_line(cmd, self.prefix, slash_names) for cmd in visible_commands(cog, self.is_staff)]

        if not lines:
            e = embeds.brand(label, "Aucune commande visible dans cette catégorie pour vous.")
            return await interaction.response.edit_message(embed=e, view=self.view)

        chunks = [lines[i:i + 8] for i in range(0, len(lines), 8)] or [[]]
        pages = []
        for i, chunk in enumerate(chunks):
            e = embeds.brand(label, "\n\n".join(chunk))
            e.set_footer(text=f"Page {i + 1}/{len(chunks)} • {len(lines)} commande(s) au total • [param] = requis, (param) = optionnel")
            pages.append(e)

        home_embed = build_help_home(self.bot, interaction.guild, self.prefix, self.is_staff)
        view = CategoryHelpView(self.bot, self.prefix, self.is_staff, pages, interaction.user.id, home_embed)
        await interaction.response.edit_message(embed=pages[0], view=view)


class CategoryHelpView(discord.ui.View):
    """Vue affichée après avoir choisi une catégorie : menu déroulant toujours accessible
    pour changer de catégorie, pagination si besoin, et un bouton pour revenir à l'accueil."""

    def __init__(self, bot: commands.Bot, prefix: str, is_staff: bool, pages: list[discord.Embed], author_id: int, home_embed: discord.Embed):
        super().__init__(timeout=180)
        self.bot = bot
        self.prefix = prefix
        self.is_staff = is_staff
        self.pages = pages
        self.author_id = author_id
        self.home_embed = home_embed
        self.index = 0
        self.add_item(HelpSelect(bot, prefix, is_staff))
        self._update_buttons()

    def _update_buttons(self):
        self.previous_page.disabled = self.index == 0
        self.next_page.disabled = len(self.pages) <= 1 or self.index >= len(self.pages) - 1
        if len(self.pages) <= 1:
            self.previous_page.disabled = True

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "Seule la personne à l'origine de la commande peut naviguer.", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary, row=1)
    async def previous_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.index = max(0, self.index - 1)
        self._update_buttons()
        await interaction.response.edit_message(embed=self.pages[self.index], view=self)

    @discord.ui.button(label="🏠 Accueil", style=discord.ButtonStyle.primary, row=1)
    async def home(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = HelpView(self.bot, self.prefix, self.is_staff)
        await interaction.response.edit_message(embed=self.home_embed, view=view)

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary, row=1)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.index = min(len(self.pages) - 1, self.index + 1)
        self._update_buttons()
        await interaction.response.edit_message(embed=self.pages[self.index], view=self)

    @discord.ui.button(label="🔎 Rechercher", style=discord.ButtonStyle.secondary, row=2)
    async def search(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(SearchModal(self.bot, self.prefix, self.is_staff))


class HelpView(discord.ui.View):
    def __init__(self, bot: commands.Bot, prefix: str, is_staff: bool):
        super().__init__(timeout=120)
        self.bot = bot
        self.prefix = prefix
        self.is_staff = is_staff
        self.add_item(HelpSelect(bot, prefix, is_staff))

    @discord.ui.button(label="🔎 Rechercher une commande", style=discord.ButtonStyle.secondary, row=1)
    async def search(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(SearchModal(self.bot, self.prefix, self.is_staff))


class Utility(commands.Cog, name="Utility"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.afk_users: dict[int, str] = {}

    async def _embed(self, guild_id: int | None, *, title: str, description: str = None, kind: str = "primary") -> discord.Embed:
        """Embed utilitaire cohérent avec +designsetup (catégorie CATEGORY_STYLES["utility"]).
        `guild_id` peut être None (ex: commande utilisée en DM) — dans ce cas on retombe sur
        les réglages par défaut plutôt que d'échouer."""
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

    async def _user_is_staff(self, ctx: commands.Context) -> bool:
        if not ctx.guild or not isinstance(ctx.author, discord.Member):
            return False
        import config
        if ctx.author.id in config.OWNER_IDS:
            return True
        if ctx.author.guild_permissions.administrator:
            return True
        return await checks.is_mod_or_permission(ctx, "manage_guild")

    @commands.hybrid_command(name="help", description="Afficher la liste des commandes du bot.")
    @app_commands.describe(commande="Nom d'une commande précise (optionnel)")
    async def help_cmd(self, ctx: commands.Context, *, commande: str = None):
        prefix = self.bot.command_prefix
        if callable(prefix):
            conf = await self.bot.db.get_guild_config(ctx.guild.id) if ctx.guild else None
            prefix = conf["prefix"] if conf and conf["prefix"] else "+"

        is_staff = await self._user_is_staff(ctx)

        if commande:
            cmd = self.bot.get_command(commande)
            if not cmd or (is_staff_command(cmd) and not is_staff):
                return await ctx.send(embed=embeds.error(f"Commande `{commande}` introuvable."))
            slash_names = {c.qualified_name for c in self.bot.tree.get_commands()}
            is_slash = cmd.qualified_name in slash_names
            marker = f"/{cmd.qualified_name}" if is_slash else f"{prefix}{cmd.qualified_name}"

            # Catégorie d'origine de la commande, pour donner du contexte.
            category_label = CATEGORY_LABELS.get(cmd.cog.qualified_name, cmd.cog.qualified_name) if cmd.cog else "—"

            e = embeds.brand(f"📘 {marker}", cmd.description or "Pas de description.")
            e.add_field(name="📂 Catégorie", value=category_label, inline=True)
            e.add_field(
                name="🔗 Accès",
                value="Slash `/` et préfixe" if is_slash else f"Préfixe `{prefix}` uniquement",
                inline=True,
            )
            e.add_field(name="🔒 Staff uniquement", value="Oui" if is_staff_command(cmd) else "Non", inline=True)

            if getattr(cmd, "aliases", None):
                e.add_field(name="🔁 Alias", value=", ".join(f"`{a}`" for a in cmd.aliases), inline=False)

            if isinstance(cmd, commands.HybridCommand) and cmd.clean_params:
                param_lines = []
                usage_parts = []
                for pname, param in cmd.clean_params.items():
                    required = param.required
                    type_name = getattr(param.annotation, "__name__", str(param.annotation)).replace("Optional", "texte")
                    tag = "requis" if required else "optionnel"
                    param_lines.append(f"• **{pname}** ({type_name}, {tag})")
                    usage_parts.append(f"<{pname}>" if required else f"[{pname}]")
                e.add_field(name="🧩 Paramètres", value="\n".join(param_lines), inline=False)
                e.add_field(name="✏️ Exemple d'usage", value=f"`{prefix}{cmd.qualified_name} {' '.join(usage_parts)}`", inline=False)
            else:
                e.add_field(name="✏️ Exemple d'usage", value=f"`{marker}`", inline=False)

            e.set_footer(text=f"Utilisez {prefix}help pour revenir à la liste complète.")
            return await ctx.send(embed=e)

        e = build_help_home(self.bot, ctx.guild, prefix, is_staff)
        try:
            view = HelpView(self.bot, prefix, is_staff)
            await ctx.send(embed=e, view=view)
        except Exception:
            # L'aide textuelle reste disponible même si Discord refuse ponctuellement
            # un composant du menu. Le détail technique reste visible dans Railway.
            logger.exception("Impossible d'afficher le menu interactif de +help")
            await ctx.send(embed=e)

    @commands.hybrid_command(name="ping", description="Afficher la latence du bot.")
    async def ping(self, ctx: commands.Context):
        await ctx.send(embed=await self._embed(ctx.guild.id if ctx.guild else None, title="Pong !", description=f"Latence : **{round(self.bot.latency * 1000)}ms**"))

    @commands.hybrid_command(name="avatar", description="Afficher l'avatar d'un membre.")
    @app_commands.describe(membre="Le membre visé (optionnel)")
    async def avatar(self, ctx: commands.Context, membre: discord.Member = None):
        membre = membre or ctx.author
        e = await self._embed(ctx.guild.id if ctx.guild else None, title=f"Avatar de {membre}")
        e.set_image(url=membre.display_avatar.url)
        await ctx.send(embed=e)

    @commands.hybrid_command(name="serverinfo", description="Afficher les informations du serveur.")
    async def serverinfo(self, ctx: commands.Context):
        guild = ctx.guild
        e = await self._embed(guild.id, title=guild.name)
        if guild.icon:
            e.set_thumbnail(url=guild.icon.url)
        e.add_field(name="Propriétaire", value=f"<@{guild.owner_id}>", inline=True)
        e.add_field(name="Membres", value=guild.member_count, inline=True)
        e.add_field(name="Créé le", value=f"<t:{int(guild.created_at.timestamp())}:D>", inline=True)
        e.add_field(name="Salons textuels", value=len(guild.text_channels), inline=True)
        e.add_field(name="Salons vocaux", value=len(guild.voice_channels), inline=True)
        e.add_field(name="Rôles", value=len(guild.roles), inline=True)
        e.add_field(name="Boosts", value=guild.premium_subscription_count, inline=True)
        await ctx.send(embed=e)

    @commands.hybrid_command(name="userinfo", description="Afficher les informations d'un membre.")
    @app_commands.describe(membre="Le membre visé (optionnel)")
    async def userinfo(self, ctx: commands.Context, membre: discord.Member = None):
        membre = membre or ctx.author
        e = await self._embed(ctx.guild.id, title=str(membre))
        e.set_thumbnail(url=membre.display_avatar.url)
        e.add_field(name="ID", value=membre.id, inline=True)
        e.add_field(name="Compte créé", value=f"<t:{int(membre.created_at.timestamp())}:D>", inline=True)
        e.add_field(name="A rejoint le", value=f"<t:{int(membre.joined_at.timestamp())}:D>" if membre.joined_at else "Inconnu", inline=True)
        roles = [r.mention for r in membre.roles if r.name != "@everyone"]
        e.add_field(name=f"Rôles ({len(roles)})", value=", ".join(roles) if roles else "Aucun", inline=False)
        await ctx.send(embed=e)

    @commands.hybrid_command(name="roleinfo", description="Afficher les informations d'un rôle.", with_app_command=False)
    @app_commands.describe(role="Le rôle visé")
    async def roleinfo(self, ctx: commands.Context, role: discord.Role):
        e = await self._embed(ctx.guild.id, title=role.name)
        # La couleur du rôle prime sur la couleur design_system quand le rôle en a une —
        # information plus pertinente ici que la charte visuelle générique.
        if role.color.value:
            e.color = role.color
        e.add_field(name="ID", value=role.id, inline=True)
        e.add_field(name="Couleur", value=str(role.color), inline=True)
        e.add_field(name="Membres", value=len(role.members), inline=True)
        e.add_field(name="Position", value=role.position, inline=True)
        e.add_field(name="Mentionnable", value="Oui" if role.mentionable else "Non", inline=True)
        await ctx.send(embed=e)

    @commands.hybrid_command(name="channelinfo", description="Afficher les informations d'un salon.", with_app_command=False)
    @app_commands.describe(salon="Le salon visé (optionnel)")
    async def channelinfo(self, ctx: commands.Context, salon: discord.abc.GuildChannel = None):
        salon = salon or ctx.channel
        e = await self._embed(ctx.guild.id, title=f"#{salon.name}")
        e.add_field(name="ID", value=salon.id, inline=True)
        e.add_field(name="Type", value=str(salon.type), inline=True)
        e.add_field(name="Créé le", value=f"<t:{int(salon.created_at.timestamp())}:D>", inline=True)
        await ctx.send(embed=e)

    @commands.hybrid_command(name="membercount", description="Afficher le nombre de membres du serveur.", with_app_command=False)
    async def membercount(self, ctx: commands.Context):
        guild = ctx.guild
        # Un seul passage sur guild.members (au lieu de deux) : sur un serveur de
        # plusieurs dizaines/centaines de milliers de membres, ça compte.
        humans = bots = 0
        for m in guild.members:
            if m.bot:
                bots += 1
            else:
                humans += 1
        e = await self._embed(guild.id, title="Membres du serveur")
        e.add_field(name="Total", value=guild.member_count, inline=True)
        e.add_field(name="Humains", value=humans, inline=True)
        e.add_field(name="Bots", value=bots, inline=True)
        await ctx.send(embed=e)

    @commands.hybrid_command(
        name="addemoji",
        aliases=["add-emoji"],
        description="Importer un emoji collé, une image jointe ou une URL.",
        with_app_command=False,
    )
    @app_commands.describe(nom="Nom du nouvel emoji", url="URL HTTPS directe (optionnelle si une image est jointe)")
    @checks.has_permission("manage_emojis_and_stickers")
    async def addemoji(self, ctx: commands.Context, nom: str, url: str = None):
        if not ctx.guild:
            return await ctx.send(embed=await self._embed(None, title="Commande indisponible", description="Cette commande doit être utilisée sur un serveur.", kind="danger"))
        if not ctx.guild.me.guild_permissions.manage_emojis_and_stickers:
            return await ctx.send(embed=await self._embed(ctx.guild.id, title="Permission manquante", description="Le bot doit avoir la permission **Gérer les emojis et stickers**.", kind="danger"))

        nom = nom.strip()

        # Discord transmet un emoji personnalisé collé sous la forme
        # <:nom:identifiant> ou <a:nom:identifiant>. On récupère automatiquement
        # son nom et son image CDN, sans demander d'URL à l'utilisateur.
        source_is_animated = False
        pasted_emoji = re.fullmatch(r"<(a?):([A-Za-z0-9_]{2,32}):([0-9]+)>", nom)
        if pasted_emoji:
            animated = bool(pasted_emoji.group(1))
            source_is_animated = animated
            nom = pasted_emoji.group(2)
            emoji_id = pasted_emoji.group(3)
            extension = "gif" if animated else "png"
            # Une copie GIF en 64x64 conserve l'animation tout en restant largement
            # sous la limite de poids imposée par Discord.
            url = f"https://cdn.discordapp.com/emojis/{emoji_id}.{extension}?size=64"
        else:
            # Un emoji Unicode normal (ex: 🧟‍♂️) n'a pas d'URL Discord. Twemoji
            # fournit sa représentation PNG à partir de la suite de points de code.
            has_emoji_codepoint = any(
                0x1F000 <= ord(char) <= 0x1FAFF or 0x2600 <= ord(char) <= 0x27BF
                for char in nom
            )
            if has_emoji_codepoint:
                codepoints = "-".join(f"{ord(char):x}" for char in nom)
                first_codepoint = next(
                    ord(char) for char in nom
                    if 0x1F000 <= ord(char) <= 0x1FAFF or 0x2600 <= ord(char) <= 0x27BF
                )
                nom = f"emoji_{first_codepoint:x}"
                url = (
                    "https://cdn.jsdelivr.net/gh/jdecked/twemoji@latest/"
                    f"assets/72x72/{codepoints}.png"
                )

        if not re.fullmatch(r"[A-Za-z0-9_]{2,32}", nom):
            return await ctx.send(embed=await self._embed(
                ctx.guild.id,
                title="Nom invalide",
                description="Collez directement un emoji normal ou personnalisé après +addemoji.",
                kind="danger",
            ))

        async def validate_public_https(candidate: str) -> str:
            parsed = urlparse(candidate)
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError("Utilisez une URL HTTPS publique et directe.")
            loop = asyncio.get_running_loop()
            try:
                addresses = await loop.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)
            except socket.gaierror as exc:
                raise ValueError("Le domaine de cette URL est introuvable.") from exc
            for info in addresses:
                ip = ipaddress.ip_address(info[4][0])
                if not ip.is_global:
                    raise ValueError("Cette URL pointe vers une adresse privée ou non autorisée.")
            return candidate

        try:
            image_data = None
            attachment = ctx.message.attachments[0] if ctx.message.attachments else None

            if attachment is not None:
                content_type = (attachment.content_type or "").split(";", 1)[0].lower()
                extension = attachment.filename.rsplit(".", 1)[-1].lower() if "." in attachment.filename else ""
                if content_type not in {"image/png", "image/jpeg", "image/gif", "image/webp"} and extension not in {"png", "jpg", "jpeg", "gif", "webp"}:
                    raise ValueError("Le fichier joint doit être une image PNG, JPG, GIF ou WebP.")
                if attachment.size > 256 * 1024:
                    raise ValueError("L'image jointe dépasse la limite de 256 Ko pour un emoji Discord.")
                source_is_animated = content_type == "image/gif" or extension == "gif"
                image_data = await attachment.read()
            elif url:
                current_url = await validate_public_https(url.strip())
                timeout = aiohttp.ClientTimeout(total=12)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    for _ in range(4):
                        async with session.get(current_url, allow_redirects=False, headers={"User-Agent": "SentriX-EmojiImporter/1.0"}) as response:
                            if 300 <= response.status < 400 and response.headers.get("Location"):
                                current_url = await validate_public_https(urljoin(current_url, response.headers["Location"]))
                                continue
                            if response.status != 200:
                                raise ValueError(f"Le serveur de l'image a répondu avec le code {response.status}.")
                            content_type = response.headers.get("Content-Type", "").split(";", 1)[0].lower()
                            if content_type not in {"image/png", "image/jpeg", "image/gif", "image/webp"}:
                                raise ValueError("Le lien doit mener directement vers une image PNG, JPG, GIF ou WebP.")
                            declared_size = int(response.headers.get("Content-Length", "0") or 0)
                            if declared_size > 256 * 1024:
                                raise ValueError("L'image dépasse la limite de 256 Ko pour un emoji Discord.")
                            image_data = await response.content.read(256 * 1024 + 1)
                            if len(image_data) > 256 * 1024:
                                raise ValueError("L'image dépasse la limite de 256 Ko pour un emoji Discord.")
                            source_is_animated = source_is_animated or content_type == "image/gif"
                            break
                    if image_data is None:
                        raise ValueError("Le lien contient trop de redirections.")
            else:
                raise ValueError(
                    "Joignez une image au message ou ajoutez une URL HTTPS après le nom. "
                    "Exemple : +addemoji sourire"
                )

            if source_is_animated and (not image_data or not image_data.startswith((b"GIF87a", b"GIF89a"))):
                raise ValueError(
                    "Discord n'a pas renvoyé un vrai GIF animé. Réessayez en collant directement l'emoji animé."
                )

            emoji = await ctx.guild.create_custom_emoji(
                name=nom,
                image=image_data,
                reason=f"Emoji ajouté par {ctx.author} avec +addemoji",
            )
        except ValueError as exc:
            return await ctx.send(embed=await self._embed(ctx.guild.id, title="Image refusée", description=str(exc), kind="danger"))
        except asyncio.TimeoutError:
            return await ctx.send(embed=await self._embed(ctx.guild.id, title="Téléchargement impossible", description="Le serveur de l'image met trop de temps à répondre.", kind="danger"))
        except discord.Forbidden:
            return await ctx.send(embed=await self._embed(ctx.guild.id, title="Création refusée", description="Discord refuse la création. Vérifiez la permission et la position du rôle du bot.", kind="danger"))
        except (aiohttp.ClientError, discord.HTTPException) as exc:
            return await ctx.send(embed=await self._embed(ctx.guild.id, title="Création impossible", description=f"Discord ou le serveur de l'image a refusé la demande : {exc}", kind="danger"))

        await ctx.send(embed=await self._embed(
            ctx.guild.id,
            title="Emoji ajouté",
            description=f"{emoji} a été créé sous le nom `:{emoji.name}:`.",
            kind="success",
        ))

    @commands.hybrid_command(name="emoji-list", description="Lister les emojis du serveur.", with_app_command=False)
    async def emoji_list(self, ctx: commands.Context):
        if not ctx.guild.emojis:
            return await ctx.send(embed=await self._embed(ctx.guild.id, title="Aucun emoji", description="Ce serveur n'a aucun emoji personnalisé.", kind="warning"))
        text = " ".join(str(e) for e in ctx.guild.emojis)[:4000]
        await ctx.send(embed=await self._embed(ctx.guild.id, title=f"Emojis ({len(ctx.guild.emojis)})", description=text))

    @commands.hybrid_command(name="poll", description="Créer un sondage rapide (réactions 👍/👎).")
    @app_commands.describe(question="La question du sondage")
    async def poll(self, ctx: commands.Context, *, question: str):
        e = await self._embed(ctx.guild.id if ctx.guild else None, title="Sondage", description=question)
        e.set_footer(text=f"Créé par {ctx.author}")
        msg = await ctx.send(embed=e)
        await msg.add_reaction("👍")
        await msg.add_reaction("👎")

    @commands.hybrid_command(name="remind", description="Définir un rappel personnel.")
    @app_commands.describe(duree="Durée (ex: 10m, 2h, 1j)", texte="Le texte du rappel")
    async def remind(self, ctx: commands.Context, duree: str, *, texte: str):
        seconds = helpers.parse_duration(duree)
        if not seconds:
            return await ctx.send(embed=await self._embed(ctx.guild.id if ctx.guild else None, title="Durée invalide", description="Exemple : `10m`, `2h`, `1j`.", kind="danger"))
        trigger_at = now() + seconds
        await self.bot.db.execute(
            "INSERT INTO reminders (user_id, channel_id, guild_id, text, trigger_at, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (ctx.author.id, ctx.channel.id, ctx.guild.id if ctx.guild else None, texte, trigger_at, now()),
        )
        await ctx.send(embed=await self._embed(ctx.guild.id if ctx.guild else None, title="Rappel défini", description=f"⏰ Rappel défini dans {helpers.format_duration(seconds)}.", kind="success"))

    @commands.hybrid_command(name="reminder-list", description="Lister vos rappels en cours.", with_app_command=False)
    async def reminder_list(self, ctx: commands.Context):
        rows = await self.bot.db.fetchall("SELECT * FROM reminders WHERE user_id = ? ORDER BY trigger_at ASC", (ctx.author.id,))
        if not rows:
            return await ctx.send(embed=await self._embed(ctx.guild.id if ctx.guild else None, title="Aucun rappel", description="Vous n'avez aucun rappel en cours."))
        lines = [f"`#{r['id']}` <t:{r['trigger_at']}:R> — {r['text'][:50]}" for r in rows[:15]]
        await ctx.send(embed=await self._embed(ctx.guild.id if ctx.guild else None, title="Vos rappels", description="\n".join(lines)))

    @commands.hybrid_command(name="reminder-cancel", description="Annuler un rappel.", with_app_command=False)
    @app_commands.describe(id="L'identifiant du rappel (voir /reminder-list)")
    async def reminder_cancel(self, ctx: commands.Context, id: int):
        row = await self.bot.db.fetchone("SELECT * FROM reminders WHERE id = ? AND user_id = ?", (id, ctx.author.id))
        if not row:
            return await ctx.send(embed=await self._embed(ctx.guild.id if ctx.guild else None, title="Rappel introuvable", kind="danger"))
        await self.bot.db.execute("DELETE FROM reminders WHERE id = ?", (id,))
        await ctx.send(embed=await self._embed(ctx.guild.id if ctx.guild else None, title="Rappel annulé", kind="success"))

    @commands.hybrid_command(name="say", description="Faire répéter un message par le bot.", with_app_command=False)
    @app_commands.describe(texte="Le texte à faire répéter")
    @commands.has_permissions(manage_messages=True)
    async def say(self, ctx: commands.Context, *, texte: str):
        if ctx.interaction:
            await ctx.interaction.response.send_message("Message envoyé.", ephemeral=True)
        else:
            await ctx.message.delete()
        await ctx.channel.send(texte)

    @commands.hybrid_command(name="embed-create", description="Créer un embed personnalisé.", with_app_command=False)
    @app_commands.describe(titre="Titre de l'embed", description="Contenu de l'embed")
    @commands.has_permissions(manage_messages=True)
    async def embed_create(self, ctx: commands.Context, titre: str, *, description: str):
        e = await self._embed(ctx.guild.id if ctx.guild else None, title=titre, description=description)
        await ctx.send(embed=e)

    @commands.hybrid_command(name="translate", description="Traduire un texte vers une autre langue.")
    @app_commands.describe(langue="Code langue cible (ex: en, es, de)", texte="Le texte à traduire")
    async def translate(self, ctx: commands.Context, langue: str, *, texte: str):
        try:
            from deep_translator import GoogleTranslator
            result = GoogleTranslator(source="auto", target=langue).translate(texte)
            await ctx.send(embed=await self._embed(ctx.guild.id if ctx.guild else None, title=f"Traduction ({langue})", description=result))
        except Exception:
            await ctx.send(embed=await self._embed(ctx.guild.id if ctx.guild else None, title="Traduction échouée", description="Vérifiez le code de langue.", kind="danger"))

    @commands.hybrid_command(name="weather", description="Afficher la météo d'une ville.")
    @app_commands.describe(ville="Le nom de la ville")
    async def weather(self, ctx: commands.Context, *, ville: str):
        import config
        if not config.WEATHER_API_KEY:
            return await ctx.send(embed=await self._embed(ctx.guild.id if ctx.guild else None, title="Météo indisponible", description="Aucune clé météo n'est configurée sur ce bot.", kind="danger"))
        import aiohttp
        url = f"https://api.openweathermap.org/data/2.5/weather?q={ville}&appid={config.WEATHER_API_KEY}&units=metric&lang=fr"
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return await ctx.send(embed=await self._embed(ctx.guild.id if ctx.guild else None, title="Ville introuvable", description=f"Ville `{ville}` introuvable.", kind="danger"))
                data = await resp.json()
        e = await self._embed(ctx.guild.id if ctx.guild else None, title=f"Météo à {data['name']}")
        e.add_field(name="Température", value=f"{data['main']['temp']}°C", inline=True)
        e.add_field(name="Ressenti", value=f"{data['main']['feels_like']}°C", inline=True)
        e.add_field(name="Condition", value=data["weather"][0]["description"], inline=True)
        await ctx.send(embed=e)

    @commands.hybrid_command(name="suggest", description="Faire une suggestion pour le serveur.")
    @app_commands.describe(texte="Votre suggestion")
    async def suggest(self, ctx: commands.Context, *, texte: str):
        conf = await self.bot.db.get_guild_config(ctx.guild.id)
        channel = ctx.guild.get_channel(conf["suggest_channel"]) if conf and conf["suggest_channel"] else ctx.channel
        e = await self._embed(ctx.guild.id, title="Nouvelle suggestion", description=texte)
        e.set_footer(text=f"Proposé par {ctx.author}")
        msg = await channel.send(embed=e)
        await msg.add_reaction("👍")
        await msg.add_reaction("👎")
        await self.bot.db.execute(
            "INSERT INTO suggestions (guild_id, user_id, message_id, content, created_at) VALUES (?, ?, ?, ?, ?)",
            (ctx.guild.id, ctx.author.id, msg.id, texte, now()),
        )
        if channel != ctx.channel:
            await ctx.send(embed=await self._embed(ctx.guild.id, title="Suggestion envoyée", description=f"Suggestion envoyée dans {channel.mention} !", kind="success"))

    @commands.hybrid_command(name="report-bug", description="Signaler un bug du bot aux développeurs.", with_app_command=False)
    @app_commands.describe(texte="Description du bug")
    async def report_bug(self, ctx: commands.Context, *, texte: str):
        await self.bot.db.execute(
            "INSERT INTO bug_reports (guild_id, user_id, content, created_at) VALUES (?, ?, ?, ?)",
            (ctx.guild.id if ctx.guild else None, ctx.author.id, texte, now()),
        )
        await ctx.send(embed=await self._embed(ctx.guild.id if ctx.guild else None, title="Signalement enregistré", description="🐛 Merci, votre signalement a été enregistré.", kind="success"))

    @commands.hybrid_command(name="afk", description="Se mettre en mode AFK (absent).")
    @app_commands.describe(raison="La raison de votre absence (optionnel)")
    async def afk(self, ctx: commands.Context, *, raison: str = "Absent"):
        self.afk_users[ctx.author.id] = raison
        await ctx.send(embed=await self._embed(ctx.guild.id if ctx.guild else None, title="Mode AFK activé", description=f"😴 {ctx.author.mention} est maintenant AFK : {raison}"))

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        guild_id = message.guild.id if message.guild else None
        if message.author.id in self.afk_users:
            del self.afk_users[message.author.id]
            try:
                await message.channel.send(embed=await self._embed(guild_id, title="De retour", description=f"👋 Bon retour {message.author.mention}, votre statut AFK a été retiré."), delete_after=5)
            except discord.HTTPException:
                pass
        for mention in message.mentions:
            if mention.id in self.afk_users:
                try:
                    await message.channel.send(embed=await self._embed(guild_id, title="Membre AFK", description=f"💤 {mention.display_name} est AFK : {self.afk_users[mention.id]}"), delete_after=5)
                except discord.HTTPException:
                    pass

    @commands.hybrid_command(name="roll", description="Lancer un dé (par défaut 1-100).")
    @app_commands.describe(max="Valeur maximale (optionnel, défaut 100)")
    async def roll(self, ctx: commands.Context, max: int = 100):
        import random
        result = random.randint(1, max)
        await ctx.send(embed=await self._embed(ctx.guild.id if ctx.guild else None, title="Lancer de dé", description=f"🎲 Vous avez obtenu : **{result}** (sur {max})"))

    @commands.hybrid_command(name="choose", description="Faire choisir le bot parmi plusieurs options.")
    @app_commands.describe(options="Options séparées par des virgules")
    async def choose(self, ctx: commands.Context, *, options: str):
        import random
        choices = [c.strip() for c in options.split(",") if c.strip()]
        if len(choices) < 2:
            return await ctx.send(embed=await self._embed(ctx.guild.id if ctx.guild else None, title="Options manquantes", description="Donnez au moins deux options séparées par des virgules.", kind="danger"))
        await ctx.send(embed=await self._embed(ctx.guild.id if ctx.guild else None, title="Choix du bot", description=f"🤔 Je choisis : **{random.choice(choices)}**"))

async def setup(bot: commands.Bot):
    await bot.add_cog(Utility(bot))
