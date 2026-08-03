"""
Cog CRÉATION DE SERVEUR.
/create-server — génère automatiquement toute la structure d'un serveur (rôles, catégories,
salons texte/vocaux) à partir d'un modèle choisi dans un menu (Communauté/Gaming,
Professionnel/Entreprise, Support/SAV). Idempotent : si relancée, ne duplique jamais les
rôles/catégories/salons déjà existants (comparaison par nom).
/delete-channel — supprimer un salon précis.
/wipe-server — supprimer TOUS les salons/catégories du serveur (confirmation obligatoire,
en tapant le nom exact du serveur), pour repartir d'une base propre.
"""

import asyncio

import discord
from discord import app_commands
from discord.ext import commands

from utils import embeds, checks

# Chaque modèle : une liste de rôles (nom, couleur, affiché séparément ("hoist"),
# permissions Discord accordées) + une liste de catégories, chacune avec ses salons
# texte ("text") ou vocaux ("voice"), et si elle doit être privée (visible uniquement
# par le rôle staff + le bot).
SERVER_TEMPLATES = {
    "communaute": {
        "label": "🎮 Communauté / Gaming",
        "description": "Structure complète : infos, communauté, gaming, vocaux, support, staff — 5 rôles, ~20 salons.",
        "roles": [
            ("👑 Admin", discord.Color.red(), True, discord.Permissions(administrator=True)),
            (
                "🛡️ Modérateur", discord.Color.orange(), True,
                discord.Permissions(kick_members=True, ban_members=True, manage_messages=True, moderate_members=True, manage_nicknames=True),
            ),
            ("🎧 Helper", discord.Color.teal(), True, discord.Permissions(manage_messages=True, moderate_members=True)),
            ("🌟 Membre Actif", discord.Color.gold(), False, discord.Permissions.none()),
            ("🎮 Membre", discord.Color.blurple(), False, discord.Permissions.none()),
        ],
        "staff_role_index": 1,
        "member_role_index": 4,
        "categories": [
            {
                "name": "📌 INFOS",
                "private": False,
                "channels": [
                    ("📢・annonces", "text"), ("📜・règlement", "text"),
                    ("🆕・nouveautés", "text"), ("👋・bienvenue", "text"),
                ],
            },
            {
                "name": "💬 COMMUNAUTÉ",
                "private": False,
                "channels": [
                    ("💬・général", "text"), ("🗣️・discussion-libre", "text"), ("😂・memes", "text"),
                    ("📸・médias-clips", "text"), ("🎉・événements", "text"), ("💡・suggestions", "text"),
                ],
            },
            {
                "name": "🎮 GAMING",
                "private": False,
                "channels": [("🎮・gaming-général", "text"), ("🔍・recherche-équipe", "text"), ("🏆・victoires", "text")],
            },
            {
                "name": "🔊 VOCAUX",
                "private": False,
                "channels": [
                    ("🔊・général-1", "voice"), ("🔊・général-2", "voice"),
                    ("🎵・musique", "voice"), ("😴・afk", "voice"),
                ],
            },
            {
                "name": "🎫 SUPPORT",
                "private": False,
                "channels": [("🎫・infos-tickets", "text"), ("❓・aide", "text")],
            },
            {
                "name": "🔒 STAFF",
                "private": True,
                "channels": [("🔒・staff-chat", "text"), ("🛡️・modération", "text"), ("📋・logs-internes", "text")],
            },
        ],
    },
    "pro": {
        "label": "💼 Professionnel / Entreprise",
        "description": "Structure complète : général, travail, réunions, support, direction — 5 rôles, ~16 salons.",
        "roles": [
            ("👑 Direction", discord.Color.dark_red(), True, discord.Permissions(administrator=True)),
            (
                "📊 Manager", discord.Color.gold(), True,
                discord.Permissions(manage_channels=True, manage_messages=True, kick_members=True, mute_members=True, moderate_members=True),
            ),
            ("🧭 Responsable d'équipe", discord.Color.orange(), True, discord.Permissions(manage_messages=True, moderate_members=True)),
            ("💼 Employé", discord.Color.green(), False, discord.Permissions.none()),
            ("👤 Invité", discord.Color.light_grey(), False, discord.Permissions.none()),
        ],
        "staff_role_index": 1,
        "member_role_index": 4,
        "categories": [
            {
                "name": "📢 GÉNÉRAL",
                "private": False,
                "channels": [("📢・annonces", "text"), ("📰・actualités", "text"), ("👋・accueil", "text")],
            },
            {
                "name": "💼 TRAVAIL",
                "private": False,
                "channels": [
                    ("💬・discussion-générale", "text"), ("📁・projets", "text"),
                    ("📊・ressources", "text"), ("🗂️・documents", "text"), ("💡・idées", "text"),
                ],
            },
            {
                "name": "📅 RÉUNIONS",
                "private": False,
                "channels": [("🔊・salle-réunion-1", "voice"), ("🔊・salle-réunion-2", "voice"), ("🎥・visio", "voice")],
            },
            {
                "name": "🆘 SUPPORT",
                "private": False,
                "channels": [("🆘・support-interne", "text"), ("❓・questions-rh", "text")],
            },
            {
                "name": "🔒 DIRECTION",
                "private": True,
                "channels": [("🔒・direction", "text"), ("💰・rh-finance", "text"), ("📋・comptes-rendus", "text")],
            },
        ],
    },
    "support": {
        "label": "🆘 Support / SAV",
        "description": "Structure complète : infos, support, communauté, vocaux, staff — 5 rôles, ~15 salons.",
        "roles": [
            ("👑 Responsable Support", discord.Color.dark_purple(), True, discord.Permissions(administrator=True)),
            (
                "🥇 Agent Senior", discord.Color.dark_teal(), True,
                discord.Permissions(kick_members=True, mute_members=True, moderate_members=True, manage_messages=True),
            ),
            ("🎧 Agent Support", discord.Color.teal(), True, discord.Permissions(manage_messages=True, moderate_members=True)),
            ("⭐ Client Premium", discord.Color.gold(), False, discord.Permissions.none()),
            ("👤 Client", discord.Color.light_grey(), False, discord.Permissions.none()),
        ],
        "staff_role_index": 2,
        "member_role_index": 4,
        "categories": [
            {
                "name": "📢 INFOS",
                "private": False,
                "channels": [("📢・annonces", "text"), ("📜・règles", "text"), ("❓・faq", "text")],
            },
            {
                "name": "🆘 SUPPORT",
                "private": False,
                "channels": [
                    ("🆘・support-général", "text"), ("🐛・signaler-un-bug", "text"),
                    ("💳・facturation", "text"), ("💡・suggestions", "text"),
                ],
            },
            {
                "name": "💬 COMMUNAUTÉ",
                "private": False,
                "channels": [("💬・discussion", "text"), ("🌟・témoignages", "text")],
            },
            {
                "name": "🔊 VOCAUX",
                "private": False,
                "channels": [("🔊・support-vocal", "voice"), ("🔊・discussion-libre", "voice")],
            },
            {
                "name": "🔒 STAFF",
                "private": True,
                "channels": [("🔒・staff-chat", "text"), ("📋・logs-support", "text")],
            },
        ],
    },
}


class TemplateSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label=data["label"], value=key, description=data["description"])
            for key, data in SERVER_TEMPLATES.items()
        ]
        super().__init__(placeholder="Choisissez un modèle de serveur", options=options, min_values=1, max_values=1, row=0)

    async def callback(self, interaction: discord.Interaction):
        view: "ServerBuilderView" = self.view
        view.selected_template = self.values[0]
        view.confirm_btn.disabled = False
        await interaction.response.edit_message(embed=view.build_preview_embed(), view=view)


class ServerBuilderView(discord.ui.View):
    def __init__(self, bot: commands.Bot, author_id: int):
        super().__init__(timeout=180)
        self.bot = bot
        self.author_id = author_id
        self.selected_template: str | None = None
        self.add_item(TemplateSelect())
        self.confirm_btn = discord.ui.Button(label="✅ Créer la structure", style=discord.ButtonStyle.success, disabled=True, row=1)
        self.confirm_btn.callback = self.confirm
        self.add_item(self.confirm_btn)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Seule la personne ayant lancé `/create-server` peut l'utiliser.", ephemeral=True)
            return False
        return True

    def build_preview_embed(self) -> discord.Embed:
        if not self.selected_template:
            return embeds.neutral("🏗️ Création de serveur", "Choisissez un modèle ci-dessous pour voir l'aperçu de ce qui sera créé.")

        data = SERVER_TEMPLATES[self.selected_template]
        total_channels = sum(len(cat["channels"]) for cat in data["categories"])
        lines = []
        for cat in data["categories"]:
            tag = " *(privé, staff uniquement)*" if cat["private"] else ""
            chans = ", ".join(f"`{n}`" for n, _ in cat["channels"])
            lines.append(f"**{cat['name']}**{tag}\n{chans}")

        admin_role_name = data["roles"][0][0]
        e = embeds.neutral(
            f"🏗️ Aperçu — {data['label']}",
            f"Voici ce qui va être créé : **{len(data['roles'])} rôles**, **{len(data['categories'])} catégories** "
            f"et **{total_channels} salons**. Les rôles, catégories et salons déjà existants avec le même nom "
            "ne seront **jamais dupliqués** (vous pouvez relancer la commande sans risque).\n\n"
            f"⚠️ Le rôle **{admin_role_name}** recevra la permission **Administrateur** — ne le donnez qu'à des personnes de confiance.",
        )
        e.add_field(name="Rôles (du plus élevé au plus bas)", value="\n".join(f"• {r[0]}" for r in data["roles"]), inline=False)
        for cat_lines in [lines[i:i + 3] for i in range(0, len(lines), 3)]:
            e.add_field(name="​", value="\n\n".join(cat_lines)[:1024], inline=False)
        return e

    async def confirm(self, interaction: discord.Interaction):
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(
            embed=embeds.neutral("🏗️ Création en cours...", "Merci de patienter, cela peut prendre quelques dizaines de secondes selon la taille du modèle."),
            view=self,
        )
        cog: "ServerBuilder" = self.bot.get_cog("ServerBuilder")
        summary = await cog.build_server(interaction.guild, self.selected_template, interaction.user)
        await interaction.edit_original_response(embed=summary, view=None)
        self.stop()


class ServerBuilder(commands.Cog, name="ServerBuilder"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def build_server(self, guild: discord.Guild, template_key: str, author: discord.Member) -> discord.Embed:
        data = SERVER_TEMPLATES[template_key]
        reason = f"Structure de serveur ({data['label']}) créée par {author}"

        role_list: list[discord.Role] = []
        roles_created = 0
        for name, color, hoist, perms in data["roles"]:
            existing = discord.utils.get(guild.roles, name=name)
            if existing:
                role_list.append(existing)
                continue
            role = await guild.create_role(name=name, color=color, hoist=hoist, permissions=perms, reason=reason)
            role_list.append(role)
            roles_created += 1
            await asyncio.sleep(0.3)

        staff_role = role_list[data["staff_role_index"]]
        member_role = role_list[data["member_role_index"]]

        categories_created = 0
        channels_created = 0
        for cat in data["categories"]:
            category = discord.utils.get(guild.categories, name=cat["name"])
            if not category:
                overwrites = {}
                if cat["private"]:
                    overwrites[guild.default_role] = discord.PermissionOverwrite(view_channel=False)
                    overwrites[staff_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, connect=True)
                    overwrites[guild.me] = discord.PermissionOverwrite(view_channel=True, send_messages=True, connect=True)
                category = await guild.create_category(cat["name"], overwrites=overwrites, reason=reason)
                categories_created += 1
                await asyncio.sleep(0.3)

            for chan_name, chan_type in cat["channels"]:
                existing_chan = discord.utils.get(category.channels, name=chan_name)
                if existing_chan:
                    continue
                if chan_type == "text":
                    await guild.create_text_channel(chan_name, category=category, reason=reason)
                else:
                    await guild.create_voice_channel(chan_name, category=category, reason=reason)
                channels_created += 1
                await asyncio.sleep(0.3)

        # Branchement automatique dans la config du bot : le rôle staff créé devient le
        # rôle staff du bot, et le rôle membre devient le rôle donné automatiquement.
        await self.bot.db.set_guild_config(guild.id, "mod_role", staff_role.id)
        await self.bot.db.set_guild_config(guild.id, "autorole", member_role.id)

        e = embeds.success(
            f"**{categories_created}** catégorie(s) et **{channels_created}** salon(s) créés "
            f"({roles_created} nouveau(x) rôle(s), les autres existaient déjà).\n\n"
            f"🛡️ Rôle staff du bot configuré automatiquement sur {staff_role.mention} (`/setmodrole`).\n"
            f"🎭 Rôle automatique à l'arrivée configuré sur {member_role.mention} (`/setautorole`).\n\n"
            "Pensez à utiliser `/create-logs` pour ajouter les salons de logs, et `+ticketsetup` "
            "pour créer et installer votre panneau de tickets si besoin.",
            title="✅ Structure du serveur créée",
        )
        return e

    @commands.hybrid_command(
        name="create-server",
        description="Générer automatiquement toute la structure d'un serveur (rôles, catégories, salons) selon un modèle au choix.",
    )
    @checks.is_owner_or_admin()
    async def create_server(self, ctx: commands.Context):
        if ctx.interaction:
            await ctx.defer()
        me = ctx.guild.me
        if not me.guild_permissions.manage_channels or not me.guild_permissions.manage_roles:
            return await ctx.send(embed=embeds.error(
                "Il me manque la permission **Gérer les salons** et/ou **Gérer les rôles** pour faire ça. "
                "Donnez-moi ces permissions (rôle du bot dans Paramètres du serveur → Rôles) puis réessayez."
            ))
        view = ServerBuilderView(self.bot, ctx.author.id)
        await ctx.send(embed=view.build_preview_embed(), view=view)

    # ---------------------------------------------------------------- SUPPRESSION DE SALONS

    @commands.hybrid_command(name="delete-channel", description="Supprimer un salon précis du serveur.")
    @app_commands.describe(salon="Le salon à supprimer", raison="La raison (optionnel)")
    @checks.is_owner_or_admin()
    async def delete_channel(self, ctx: commands.Context, salon: discord.TextChannel, *, raison: str = "Aucune raison fournie"):
        if salon.id == ctx.channel.id:
            return await ctx.send(embed=embeds.error("Vous ne pouvez pas supprimer le salon depuis lequel vous lancez cette commande."))
        name = salon.name
        try:
            await salon.delete(reason=f"{ctx.author} : {raison}")
        except discord.Forbidden:
            return await ctx.send(embed=embeds.error("Je n'ai pas la permission de supprimer ce salon."))
        await ctx.send(embed=embeds.success(f"Le salon **{name}** a été supprimé.\nRaison : {raison}"))

    @commands.hybrid_command(
        name="wipe-server",
        description="[DANGER] Supprimer TOUS les salons et catégories du serveur (irréversible, confirmation requise).",
        with_app_command=False,
    )
    @checks.is_owner_or_admin()
    async def wipe_server(self, ctx: commands.Context):
        guild = ctx.guild
        total = len(guild.channels)
        if total == 0:
            return await ctx.send(embed=embeds.info("Il n'y a aucun salon à supprimer."))
        e = embeds.error(
            f"Vous êtes sur le point de supprimer **{total}** salon(s)/catégorie(s) sur **{guild.name}**.\n"
            "C'est **IRRÉVERSIBLE** : tous les messages et l'historique de ces salons seront perdus.\n\n"
            "⚠️ Seuls les salons et catégories sont supprimés — les rôles et les membres ne sont **pas** touchés "
            "(supprimer des rôles en masse est trop risqué, y compris pour le bot lui-même).\n\n"
            "Cliquez ci-dessous puis tapez le **nom exact du serveur** pour confirmer.",
            title="🧨 Suppression totale des salons",
        )
        view = WipeConfirmView(ctx.author.id, guild, ctx.channel.id)
        await ctx.send(embed=e, view=view)


class WipeConfirmModal(discord.ui.Modal, title="Confirmation de suppression totale"):
    def __init__(self, guild: discord.Guild, invoker_channel_id: int):
        super().__init__()
        self.guild = guild
        self.invoker_channel_id = invoker_channel_id
        self.confirm_input = discord.ui.TextInput(
            label="Nom exact du serveur (sensible à la casse)",
            placeholder=guild.name,
            required=True,
            max_length=100,
        )
        self.add_item(self.confirm_input)

    async def on_submit(self, interaction: discord.Interaction):
        if self.confirm_input.value.strip() != self.guild.name:
            return await interaction.response.send_message(
                "Nom incorrect — suppression **annulée**, aucun salon n'a été touché.", ephemeral=True
            )
        await interaction.response.defer()
        deleted = 0
        failed = 0
        for channel in list(self.guild.channels):
            if channel.id == self.invoker_channel_id:
                continue
            try:
                await channel.delete(reason=f"Suppression totale demandée par {interaction.user}")
                deleted += 1
                await asyncio.sleep(0.4)
            except discord.HTTPException:
                failed += 1
        description = f"**{deleted}** salon(s)/catégorie(s) supprimé(s)."
        if failed:
            description += f" ({failed} échec(s), probablement des permissions manquantes.)"
        description += "\n\nLe salon actuel n'a pas été supprimé, pour que vous puissiez voir ce message."
        await interaction.followup.send(embed=embeds.success(description, title="🧹 Suppression terminée"))


class WipeConfirmView(discord.ui.View):
    def __init__(self, author_id: int, guild: discord.Guild, invoker_channel_id: int):
        super().__init__(timeout=60)
        self.author_id = author_id
        self.guild = guild
        self.invoker_channel_id = invoker_channel_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Seule la personne ayant lancé la commande peut confirmer.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="⚠️ Confirmer la suppression totale", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(WipeConfirmModal(self.guild, self.invoker_channel_id))
        self.stop()


async def setup(bot: commands.Bot):
    await bot.add_cog(ServerBuilder(bot))
