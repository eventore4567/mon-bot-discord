"""
Cog CONFIGURATION.
/setup (assistant complet en un clic) /setprefix /setmodrole /setlogchannel /create-logs
/setwelcomechannel /setgoodbyechannel /setwelcomemessage /setgoodbyemessage
/setticketcategory /setticketlogchannel /setautorole /disablecommand /enablecommand
/ignorechannel /unignorechannel /config-view /config-reset /setlevelchannel
/setsuggestchannel /setannouncechannel /setgiveawaychannel
"""

import re
import discord
from discord import app_commands
from discord.ext import commands

from utils import embeds, checks

ROLE_MENTION_RE = re.compile(r"<@&(\d+)>")


def parse_role_input(guild: discord.Guild, value: str):
    """Accepte une mention de rôle (@Role), un ID brut, ou un nom exact."""
    value = value.strip()
    m = ROLE_MENTION_RE.match(value)
    if m:
        return guild.get_role(int(m.group(1)))
    if value.isdigit():
        return guild.get_role(int(value))
    return discord.utils.get(guild.roles, name=value)


class Configuration(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.hybrid_command(name="setprefix", description="Changer le préfixe des commandes textuelles.")
    @app_commands.describe(prefixe="Le nouveau préfixe (ex: !, ?, +)")
    @checks.is_owner_or_admin()
    async def setprefix(self, ctx: commands.Context, prefixe: str):
        if len(prefixe) > 5:
            return await ctx.send(embed=embeds.error("Le préfixe doit faire 5 caractères maximum."))
        await self.bot.db.set_guild_config(ctx.guild.id, "prefix", prefixe)
        self.bot.prefix_cache[ctx.guild.id] = prefixe
        await ctx.send(embed=embeds.success(f"Le préfixe a été changé pour `{prefixe}`."))

    @commands.hybrid_command(name="setmodrole", description="Définir le rôle du staff/modération.")
    @app_commands.describe(role="Le rôle à définir comme rôle staff")
    @checks.is_owner_or_admin()
    async def setmodrole(self, ctx: commands.Context, role: discord.Role):
        await self.bot.db.set_guild_config(ctx.guild.id, "mod_role", role.id)
        await ctx.send(embed=embeds.success(f"Le rôle staff a été défini sur {role.mention}."))

    @commands.hybrid_command(name="setlogchannel", description="Définir le salon de logs des sanctions.")
    @app_commands.describe(salon="Le salon où seront envoyés les logs")
    @checks.is_owner_or_admin()
    async def setlogchannel(self, ctx: commands.Context, salon: discord.TextChannel):
        await self.bot.db.set_guild_config(ctx.guild.id, "log_channel", salon.id)
        await ctx.send(embed=embeds.success(f"Le salon de logs a été défini sur {salon.mention}."))

    @commands.hybrid_command(
        name="create-logs",
        description="Créer automatiquement un salon de logs privé et le configurer, sans étape manuelle.",
    )
    @checks.is_owner_or_admin()
    async def create_logs(self, ctx: commands.Context):
        guild = ctx.guild
        conf = await self.bot.db.get_guild_config(guild.id)

        # Si un salon de logs valide existe déjà, on ne le recrée pas en double.
        if conf and conf["log_channel"] and guild.get_channel(conf["log_channel"]):
            existing = guild.get_channel(conf["log_channel"])
            return await ctx.send(
                embed=embeds.warning(f"Un salon de logs existe déjà : {existing.mention}. Utilisez `/setlogchannel` pour en choisir un autre.")
            )

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True),
        }
        if conf and conf["mod_role"]:
            role = guild.get_role(conf["mod_role"])
            if role:
                overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
        if ctx.author.guild_permissions.administrator:
            overwrites[ctx.author] = discord.PermissionOverwrite(view_channel=True, send_messages=True)

        channel = await guild.create_text_channel(
            "sentrix-logs",
            overwrites=overwrites,
            topic="Salon de logs automatique de SentriX : sanctions, tickets, sécurité.",
            reason=f"/create-logs par {ctx.author}",
        )

        await self.bot.db.set_guild_config(guild.id, "log_channel", channel.id)
        if not (conf and conf["ticket_log_channel"]):
            await self.bot.db.set_guild_config(guild.id, "ticket_log_channel", channel.id)

        e = embeds.brand(
            "📡 Salon de logs créé",
            f"{channel.mention} a été créé et configuré automatiquement comme salon de logs "
            "(sanctions, sécurité, tickets). Seul le staff peut le voir.",
        )
        await ctx.send(embed=e)
        await channel.send(embed=embeds.brand("📡 Journal SentriX", "Ce salon recevra automatiquement tous les logs du bot à partir de maintenant."))

    @commands.hybrid_command(name="setwelcomechannel", description="Définir le salon de bienvenue.", with_app_command=False)
    @app_commands.describe(salon="Le salon de bienvenue")
    @checks.is_owner_or_admin()
    async def setwelcomechannel(self, ctx: commands.Context, salon: discord.TextChannel):
        await self.bot.db.set_guild_config(ctx.guild.id, "welcome_channel", salon.id)
        await ctx.send(embed=embeds.success(f"Le salon de bienvenue a été défini sur {salon.mention}."))

    @commands.hybrid_command(name="setgoodbyechannel", description="Définir le salon des messages de départ.", with_app_command=False)
    @app_commands.describe(salon="Le salon de départ")
    @checks.is_owner_or_admin()
    async def setgoodbyechannel(self, ctx: commands.Context, salon: discord.TextChannel):
        await self.bot.db.set_guild_config(ctx.guild.id, "goodbye_channel", salon.id)
        await ctx.send(embed=embeds.success(f"Le salon de départ a été défini sur {salon.mention}."))

    @commands.hybrid_command(name="setwelcomemessage", description="Personnaliser le message de bienvenue ({member}, {server}).", with_app_command=False)
    @app_commands.describe(message="Le message (utilisez {member} et {server})")
    @checks.is_owner_or_admin()
    async def setwelcomemessage(self, ctx: commands.Context, *, message: str):
        await self.bot.db.set_guild_config(ctx.guild.id, "welcome_message", message)
        await ctx.send(embed=embeds.success("Message de bienvenue mis à jour."))

    @commands.hybrid_command(name="setgoodbyemessage", description="Personnaliser le message de départ ({member}, {server}).", with_app_command=False)
    @app_commands.describe(message="Le message (utilisez {member} et {server})")
    @checks.is_owner_or_admin()
    async def setgoodbyemessage(self, ctx: commands.Context, *, message: str):
        await self.bot.db.set_guild_config(ctx.guild.id, "goodbye_message", message)
        await ctx.send(embed=embeds.success("Message de départ mis à jour."))

    @commands.hybrid_command(name="setticketcategory", description="Définir la catégorie où seront créés les tickets.", with_app_command=False)
    @app_commands.describe(categorie="La catégorie Discord pour les tickets")
    @checks.is_owner_or_admin()
    async def setticketcategory(self, ctx: commands.Context, categorie: discord.CategoryChannel):
        await self.bot.db.set_guild_config(ctx.guild.id, "ticket_category", categorie.id)
        await ctx.send(embed=embeds.success(f"Catégorie des tickets définie sur **{categorie.name}**."))

    @commands.hybrid_command(name="setticketlogchannel", description="Définir le salon de logs des tickets.", with_app_command=False)
    @app_commands.describe(salon="Le salon de logs des tickets")
    @checks.is_owner_or_admin()
    async def setticketlogchannel(self, ctx: commands.Context, salon: discord.TextChannel):
        await self.bot.db.set_guild_config(ctx.guild.id, "ticket_log_channel", salon.id)
        await ctx.send(embed=embeds.success(f"Salon de logs des tickets défini sur {salon.mention}."))

    @commands.hybrid_command(name="setautorole", description="Définir un rôle attribué automatiquement à l'arrivée.")
    @app_commands.describe(role="Le rôle à attribuer automatiquement")
    @checks.is_owner_or_admin()
    async def setautorole(self, ctx: commands.Context, role: discord.Role):
        await self.bot.db.set_guild_config(ctx.guild.id, "autorole", role.id)
        await ctx.send(embed=embeds.success(f"Rôle automatique défini sur {role.mention}."))

    @commands.hybrid_command(name="disablecommand", description="Désactiver une commande sur ce serveur.", with_app_command=False)
    @app_commands.describe(commande="Le nom de la commande à désactiver")
    @checks.is_owner_or_admin()
    async def disablecommand(self, ctx: commands.Context, commande: str):
        cmd = self.bot.get_command(commande)
        if not cmd:
            return await ctx.send(embed=embeds.error(f"Commande `{commande}` introuvable."))
        await self.bot.db.execute(
            "INSERT OR IGNORE INTO disabled_commands (guild_id, command_name) VALUES (?, ?)",
            (ctx.guild.id, commande),
        )
        await ctx.send(embed=embeds.success(f"La commande `{commande}` a été désactivée sur ce serveur."))

    @commands.hybrid_command(name="enablecommand", description="Réactiver une commande précédemment désactivée.", with_app_command=False)
    @app_commands.describe(commande="Le nom de la commande à réactiver")
    @checks.is_owner_or_admin()
    async def enablecommand(self, ctx: commands.Context, commande: str):
        await self.bot.db.execute(
            "DELETE FROM disabled_commands WHERE guild_id = ? AND command_name = ?",
            (ctx.guild.id, commande),
        )
        await ctx.send(embed=embeds.success(f"La commande `{commande}` a été réactivée."))

    @commands.hybrid_command(name="ignorechannel", description="Ignorer un salon (le bot n'y répondra plus).", with_app_command=False)
    @app_commands.describe(salon="Le salon à ignorer")
    @checks.is_owner_or_admin()
    async def ignorechannel(self, ctx: commands.Context, salon: discord.TextChannel = None):
        salon = salon or ctx.channel
        await self.bot.db.execute(
            "INSERT OR IGNORE INTO ignored_channels (guild_id, channel_id) VALUES (?, ?)",
            (ctx.guild.id, salon.id),
        )
        await ctx.send(embed=embeds.success(f"Le salon {salon.mention} est maintenant ignoré."))

    @commands.hybrid_command(name="unignorechannel", description="Ne plus ignorer un salon.", with_app_command=False)
    @app_commands.describe(salon="Le salon à ne plus ignorer")
    @checks.is_owner_or_admin()
    async def unignorechannel(self, ctx: commands.Context, salon: discord.TextChannel = None):
        salon = salon or ctx.channel
        await self.bot.db.execute(
            "DELETE FROM ignored_channels WHERE guild_id = ? AND channel_id = ?",
            (ctx.guild.id, salon.id),
        )
        await ctx.send(embed=embeds.success(f"Le salon {salon.mention} n'est plus ignoré."))

    @commands.hybrid_command(name="setlevelchannel", description="Définir le salon des annonces de niveau.", with_app_command=False)
    @app_commands.describe(salon="Le salon pour les annonces de niveau")
    @checks.is_owner_or_admin()
    async def setlevelchannel(self, ctx: commands.Context, salon: discord.TextChannel):
        await self.bot.db.set_guild_config(ctx.guild.id, "level_channel", salon.id)
        await ctx.send(embed=embeds.success(f"Salon des niveaux défini sur {salon.mention}."))

    @commands.hybrid_command(name="setsuggestchannel", description="Définir le salon des suggestions.", with_app_command=False)
    @app_commands.describe(salon="Le salon des suggestions")
    @checks.is_owner_or_admin()
    async def setsuggestchannel(self, ctx: commands.Context, salon: discord.TextChannel):
        await self.bot.db.set_guild_config(ctx.guild.id, "suggest_channel", salon.id)
        await ctx.send(embed=embeds.success(f"Salon des suggestions défini sur {salon.mention}."))

    @commands.hybrid_command(name="setannouncechannel", description="Définir le salon des annonces générales.", with_app_command=False)
    @app_commands.describe(salon="Le salon des annonces")
    @checks.is_owner_or_admin()
    async def setannouncechannel(self, ctx: commands.Context, salon: discord.TextChannel):
        await self.bot.db.set_guild_config(ctx.guild.id, "announce_channel", salon.id)
        await ctx.send(embed=embeds.success(f"Salon des annonces défini sur {salon.mention}."))

    @commands.hybrid_command(name="setgiveawaychannel", description="Définir le salon par défaut des giveaways.", with_app_command=False)
    @app_commands.describe(salon="Le salon par défaut des giveaways")
    @checks.is_owner_or_admin()
    async def setgiveawaychannel(self, ctx: commands.Context, salon: discord.TextChannel):
        await self.bot.db.set_guild_config(ctx.guild.id, "giveaway_channel", salon.id)
        await ctx.send(embed=embeds.success(f"Salon des giveaways défini sur {salon.mention}."))

    @commands.hybrid_command(name="config-view", description="Afficher la configuration actuelle du serveur.")
    @checks.is_owner_or_admin()
    async def config_view(self, ctx: commands.Context):
        conf = await self.bot.db.get_guild_config(ctx.guild.id)
        e = embeds.neutral("⚙️ Configuration du serveur")
        if not conf:
            e.description = "Aucune configuration définie pour l'instant."
            return await ctx.send(embed=e)

        def fmt_channel(cid):
            if not cid:
                return "Non défini"
            ch = ctx.guild.get_channel(cid)
            return ch.mention if ch else "Salon introuvable"

        def fmt_role(rid):
            if not rid:
                return "Non défini"
            r = ctx.guild.get_role(rid)
            return r.mention if r else "Rôle introuvable"

        e.add_field(name="Préfixe", value=f"`{conf['prefix'] or '+'}`", inline=True)
        e.add_field(name="Rôle staff", value=fmt_role(conf["mod_role"]), inline=True)
        e.add_field(name="Salon logs", value=fmt_channel(conf["log_channel"]), inline=True)
        e.add_field(name="Salon bienvenue", value=fmt_channel(conf["welcome_channel"]), inline=True)
        e.add_field(name="Salon départ", value=fmt_channel(conf["goodbye_channel"]), inline=True)
        e.add_field(name="Rôle auto", value=fmt_role(conf["autorole"]), inline=True)
        e.add_field(name="Catégorie tickets", value=fmt_channel(conf["ticket_category"]), inline=True)
        e.add_field(name="Logs tickets", value=fmt_channel(conf["ticket_log_channel"]), inline=True)
        await ctx.send(embed=e)

    @commands.hybrid_command(name="config-reset", description="Réinitialiser toute la configuration du serveur.", with_app_command=False)
    @checks.is_owner_or_admin()
    async def config_reset(self, ctx: commands.Context):
        await self.bot.db.execute("DELETE FROM guild_config WHERE guild_id = ?", (ctx.guild.id,))
        await self.bot.db.ensure_guild(ctx.guild.id)
        self.bot.prefix_cache.pop(ctx.guild.id, None)
        await ctx.send(embed=embeds.success("La configuration du serveur a été réinitialisée."))

    @commands.hybrid_command(
        name="setup",
        description="Assistant de configuration complet du bot (tous les réglages, en plusieurs pages).",
    )
    @checks.is_owner_or_admin()
    async def setup_wizard(self, ctx: commands.Context):
        """
        Fonctionnalité phare : configure absolument tout le bot (rôles, salons,
        préfixe, messages de bienvenue/départ...) via des menus déroulants et
        un formulaire, sans jamais avoir à taper une commande. Découpé en pages
        pour rester lisible (Discord limite un message à 5 lignes de menus).
        """
        view = SetupView(self.bot, ctx.guild.id, ctx.author.id)
        await ctx.send(embed=view.build_embed(), view=view)


# Chaque "étape" = une page de l'assistant. "role"/"channel" = type de menu déroulant.
# Pour "channel", on peut préciser les types de salons acceptés (texte, catégorie...).
SETUP_STEPS = [
    {
        "title": "1/4 — Général",
        "fields": [
            ("mod_role", "role", "🛡️ Rôle staff (modération)"),
            ("log_channel", "channel", "📝 Salon de logs (sanctions)"),
            ("welcome_channel", "channel", "👋 Salon de bienvenue"),
            ("goodbye_channel", "channel", "🚪 Salon de départ"),
        ],
    },
    {
        "title": "2/4 — Rôles & Tickets",
        "fields": [
            ("autorole", "role", "🎭 Rôle automatique à l'arrivée"),
            ("verify_role", "role", "✅ Rôle donné après vérification"),
            ("ticket_category", "channel", "🎫 Catégorie des tickets", [discord.ChannelType.category]),
            ("ticket_log_channel", "channel", "🎫 Salon de logs des tickets"),
        ],
    },
    {
        "title": "3/4 — Salons annexes",
        "fields": [
            ("level_channel", "channel", "📈 Annonces de passage de niveau"),
            ("suggest_channel", "channel", "💡 Suggestions"),
            ("announce_channel", "channel", "📢 Annonces générales"),
            ("giveaway_channel", "channel", "🎉 Giveaways par défaut"),
        ],
    },
    {
        "title": "4/4 — Rôles de niveau",
        "fields": [],
        "custom": "level_roles",
    },
]

FIELD_LABELS = {
    "mod_role": "Rôle staff", "log_channel": "Salon de logs", "welcome_channel": "Salon de bienvenue",
    "goodbye_channel": "Salon de départ", "autorole": "Rôle automatique", "verify_role": "Rôle de vérification",
    "ticket_category": "Catégorie tickets", "ticket_log_channel": "Logs tickets",
    "level_channel": "Annonces de niveau", "suggest_channel": "Suggestions",
    "announce_channel": "Annonces", "giveaway_channel": "Giveaways",
    "prefix": "Préfixe", "welcome_message": "Message de bienvenue", "goodbye_message": "Message de départ",
}


class SetupTextModal(discord.ui.Modal, title="Préfixe & messages"):
    """Formulaire pour les réglages texte (pas possible avec des menus déroulants)."""

    prefixe = discord.ui.TextInput(label="Préfixe des commandes (ex: +)", required=False, max_length=5)
    bienvenue = discord.ui.TextInput(
        label="Message de bienvenue ({member}, {server})", required=False,
        style=discord.TextStyle.paragraph, max_length=300,
    )
    depart = discord.ui.TextInput(
        label="Message de départ ({member}, {server})", required=False,
        style=discord.TextStyle.paragraph, max_length=300,
    )

    def __init__(self, view: "SetupView"):
        super().__init__()
        self.view_ref = view

    async def on_submit(self, interaction: discord.Interaction):
        if self.prefixe.value:
            self.view_ref.choices["prefix"] = self.prefixe.value
        if self.bienvenue.value:
            self.view_ref.choices["welcome_message"] = self.bienvenue.value
        if self.depart.value:
            self.view_ref.choices["goodbye_message"] = self.depart.value
        await interaction.response.edit_message(embed=self.view_ref.build_embed(), view=self.view_ref)


class LevelRoleModal(discord.ui.Modal, title="Ajouter un rôle de niveau"):
    """Formulaire pour associer un rôle récompense à un niveau atteint."""

    niveau = discord.ui.TextInput(label="Niveau requis (ex: 5)", required=True, max_length=5)
    role = discord.ui.TextInput(
        label="Rôle (mentionnez-le avec @, ou collez son ID/nom)", required=True, max_length=100
    )

    def __init__(self, view: "SetupView"):
        super().__init__()
        self.view_ref = view

    async def on_submit(self, interaction: discord.Interaction):
        try:
            level = int(self.niveau.value.strip())
        except ValueError:
            return await interaction.response.send_message("Niveau invalide : entrez un nombre entier.", ephemeral=True)
        role = parse_role_input(interaction.guild, self.role.value)
        if not role:
            return await interaction.response.send_message("Rôle introuvable. Essayez de le mentionner avec @.", ephemeral=True)

        await self.view_ref.bot.db.execute(
            "INSERT INTO level_roles (guild_id, level, role_id) VALUES (?, ?, ?) "
            "ON CONFLICT(guild_id, level) DO UPDATE SET role_id = excluded.role_id",
            (self.view_ref.guild_id, level, role.id),
        )
        self.view_ref.level_role_additions.append((level, role))
        await interaction.response.edit_message(embed=self.view_ref.build_embed(), view=self.view_ref)


class SetupView(discord.ui.View):
    """
    Assistant /setup complet : parcourt toutes les pages de SETUP_STEPS (menus
    déroulants rôles/salons) + un formulaire dédié au préfixe et aux messages
    texte. Rien n'est écrit en base tant qu'on n'a pas cliqué sur "Terminer".
    """

    def __init__(self, bot: commands.Bot, guild_id: int, author_id: int):
        super().__init__(timeout=300)
        self.bot = bot
        self.guild_id = guild_id
        self.author_id = author_id
        self.choices: dict = {}
        self.level_role_additions: list[tuple[int, discord.Role]] = []
        self.page = 0
        self.render_page()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Seule la personne ayant lancé `/setup` peut l'utiliser.", ephemeral=True)
            return False
        return True

    def build_embed(self) -> discord.Embed:
        step = SETUP_STEPS[self.page]
        if step.get("custom") == "level_roles":
            e = embeds.neutral(
                f"🧙 Assistant de configuration — {step['title']}",
                "Attribuez automatiquement un rôle personnalisé quand un membre atteint un certain niveau. "
                "Cliquez sur **➕ Ajouter un rôle de niveau** pour chaque palier souhaité "
                "(vous pouvez en ajouter autant que vous voulez).\n\n"
                "⚠️ Contrairement aux autres pages, chaque ajout ici est enregistré **immédiatement**.",
            )
            if self.level_role_additions:
                lines = [f"Niveau **{lvl}** → {role.mention}" for lvl, role in self.level_role_additions]
                e.add_field(name=f"✅ Ajoutés dans cette session ({len(self.level_role_additions)})", value="\n".join(lines), inline=False)
            return e

        e = embeds.neutral(
            f"🧙 Assistant de configuration — {step['title']}",
            "Choisissez vos options avec les menus ci-dessous. Laissez vide ce que vous ne voulez pas configurer.\n"
            "Utilisez **✏️ Préfixe & messages** pour le préfixe et les messages de bienvenue/départ.",
        )
        if self.choices:
            summary = ", ".join(FIELD_LABELS.get(k, k) for k in self.choices)
            e.add_field(name=f"✅ Déjà configuré ({len(self.choices)})", value=summary, inline=False)
        return e

    def render_page(self):
        self.clear_items()
        step = SETUP_STEPS[self.page]

        if step.get("custom") == "level_roles":
            add_btn = discord.ui.Button(label="➕ Ajouter un rôle de niveau", style=discord.ButtonStyle.primary, row=0)
            add_btn.callback = self._open_level_role_modal
            self.add_item(add_btn)
        else:
            for i, field in enumerate(step["fields"]):
                key, kind, label = field[0], field[1], field[2]
                if kind == "role":
                    select = discord.ui.RoleSelect(placeholder=label, row=i)
                    select.callback = self._make_role_callback(key, select)
                else:
                    channel_types = field[3] if len(field) > 3 else [discord.ChannelType.text]
                    select = discord.ui.ChannelSelect(placeholder=label, channel_types=channel_types, row=i)
                    select.callback = self._make_channel_callback(key, select)
                self.add_item(select)

        prev_btn = discord.ui.Button(
            label="◀ Précédent", style=discord.ButtonStyle.secondary, row=4, disabled=(self.page == 0)
        )
        prev_btn.callback = self._go_prev
        self.add_item(prev_btn)

        text_btn = discord.ui.Button(label="✏️ Préfixe & messages", style=discord.ButtonStyle.secondary, row=4)
        text_btn.callback = self._open_text_modal
        self.add_item(text_btn)

        if self.page < len(SETUP_STEPS) - 1:
            next_btn = discord.ui.Button(label="Suivant ▶", style=discord.ButtonStyle.primary, row=4)
            next_btn.callback = self._go_next
            self.add_item(next_btn)
        else:
            finish_btn = discord.ui.Button(label="✅ Terminer", style=discord.ButtonStyle.success, row=4)
            finish_btn.callback = self._finish
            self.add_item(finish_btn)

    async def _open_level_role_modal(self, interaction: discord.Interaction):
        await interaction.response.send_modal(LevelRoleModal(self))

    def _make_role_callback(self, field: str, select: discord.ui.RoleSelect):
        async def callback(interaction: discord.Interaction):
            if select.values:
                self.choices[field] = select.values[0].id
            await interaction.response.edit_message(embed=self.build_embed(), view=self)
        return callback

    def _make_channel_callback(self, field: str, select: discord.ui.ChannelSelect):
        async def callback(interaction: discord.Interaction):
            if select.values:
                self.choices[field] = select.values[0].id
            await interaction.response.edit_message(embed=self.build_embed(), view=self)
        return callback

    async def _go_prev(self, interaction: discord.Interaction):
        self.page -= 1
        self.render_page()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def _go_next(self, interaction: discord.Interaction):
        self.page += 1
        self.render_page()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def _open_text_modal(self, interaction: discord.Interaction):
        await interaction.response.send_modal(SetupTextModal(self))

    async def _finish(self, interaction: discord.Interaction):
        if not self.choices and not self.level_role_additions:
            return await interaction.response.send_message("Vous n'avez rien configuré pour l'instant.", ephemeral=True)
        for field, value in self.choices.items():
            await self.bot.db.set_guild_config(self.guild_id, field, value)
        if "prefix" in self.choices:
            self.bot.prefix_cache[self.guild_id] = self.choices["prefix"]
        lines = [f"✅ {FIELD_LABELS.get(k, k)}" for k in self.choices]
        if self.level_role_additions:
            lines.append(f"✅ {len(self.level_role_additions)} rôle(s) de niveau (déjà enregistrés)")
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(
            embed=embeds.success("Configuration enregistrée !\n\n" + "\n".join(lines)), view=self
        )
        self.stop()


async def setup(bot: commands.Bot):
    await bot.add_cog(Configuration(bot))
