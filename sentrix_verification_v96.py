"""SentriX V96 — configuration guidée du règlement + CAPTCHA de vérification.

Ce module complète le cog historique ``cogs.verification`` sans recopier son moteur
CAPTCHA. Il remplace les anciennes entrées +verify-panel / +verify-setup par un seul
assistant de configuration : salon, rôle, texte du règlement, image facultative,
apercu puis publication.
"""
from __future__ import annotations

import logging
import re
import time

import discord
from discord.ext import commands

logger = logging.getLogger("bot.verification-v96")

_SETUP_TIMEOUT = 10 * 60
_DEFAULT_TITLE = "Règlement & vérification"
_DEFAULT_RULES = (
    "Bienvenue sur le serveur.\n\n"
    "Merci de lire attentivement le règlement avant de continuer. "
    "En cliquant sur le bouton ci-dessous, vous certifiez avoir lu et accepté les règles. "
    "Un CAPTCHA vous sera ensuite demandé avant l'attribution du rôle vérifié."
)
_IMAGE_RE = re.compile(r"^https?://[^\s]+$", re.I)


class VerificationRulesModal(discord.ui.Modal, title="Configurer le règlement"):
    panel_title = discord.ui.TextInput(
        label="Titre de l'embed",
        max_length=100,
        required=True,
        default=_DEFAULT_TITLE,
    )
    rules = discord.ui.TextInput(
        label="Règlement / message",
        style=discord.TextStyle.paragraph,
        max_length=4000,
        required=True,
        default=_DEFAULT_RULES,
    )
    image_url = discord.ui.TextInput(
        label="Image (URL) — facultatif",
        placeholder="https://.../image.png",
        max_length=500,
        required=False,
    )

    def __init__(self, view: "VerificationSetupView") -> None:
        super().__init__()
        self.setup_view = view
        self.panel_title.default = view.panel_title
        self.rules.default = view.rules_text
        self.image_url.default = view.image_url or ""

    async def on_submit(self, interaction: discord.Interaction) -> None:
        image = str(self.image_url.value or "").strip()
        if image and not _IMAGE_RE.fullmatch(image):
            return await interaction.response.send_message(
                "L'image doit être une URL `http://` ou `https://` valide, ou être laissée vide.",
                ephemeral=True,
            )
        self.setup_view.panel_title = str(self.panel_title.value).strip()[:100] or _DEFAULT_TITLE
        self.setup_view.rules_text = str(self.rules.value).strip()[:4000] or _DEFAULT_RULES
        self.setup_view.image_url = image or None
        await interaction.response.edit_message(
            embed=self.setup_view.configuration_embed(),
            view=self.setup_view,
        )


class VerificationChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, setup_view: "VerificationSetupView") -> None:
        self.setup_view = setup_view
        super().__init__(
            placeholder="1. Choisir le salon du règlement / CAPTCHA",
            channel_types=[discord.ChannelType.text],
            min_values=1,
            max_values=1,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        channel = self.values[0]
        self.setup_view.channel_id = int(channel.id)
        await interaction.response.edit_message(
            embed=self.setup_view.configuration_embed(),
            view=self.setup_view,
        )


class VerificationRoleSelect(discord.ui.RoleSelect):
    def __init__(self, setup_view: "VerificationSetupView") -> None:
        self.setup_view = setup_view
        super().__init__(
            placeholder="2. Choisir le rôle donné après vérification",
            min_values=1,
            max_values=1,
            row=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        role = self.values[0]
        self.setup_view.role_id = int(role.id)
        await interaction.response.edit_message(
            embed=self.setup_view.configuration_embed(),
            view=self.setup_view,
        )


class VerificationSetupView(discord.ui.View):
    def __init__(self, cog: "VerificationConfigV96", guild_id: int, author_id: int) -> None:
        super().__init__(timeout=_SETUP_TIMEOUT)
        self.cog = cog
        self.bot = cog.bot
        self.guild_id = int(guild_id)
        self.author_id = int(author_id)
        self.channel_id: int | None = None
        self.role_id: int | None = None
        self.panel_title = _DEFAULT_TITLE
        self.rules_text = _DEFAULT_RULES
        self.image_url: str | None = None

        self.add_item(VerificationChannelSelect(self))
        self.add_item(VerificationRoleSelect(self))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "Seule la personne qui a lancé cette configuration peut la modifier.",
                ephemeral=True,
            )
            return False
        return True

    def _guild(self) -> discord.Guild | None:
        return self.bot.get_guild(self.guild_id)

    def configuration_embed(self) -> discord.Embed:
        guild = self._guild()
        channel = guild.get_channel(self.channel_id) if guild and self.channel_id else None
        role = guild.get_role(self.role_id) if guild and self.role_id else None
        embed = discord.Embed(
            title="SentriX — Configuration de la vérification",
            description=(
                "Configurez le panneau dans l'ordre. Rien n'est publié avant le bouton **Publier**.\n\n"
                "Après le clic sur **● Je certifie avoir lu les règles**, le membre reçoit le CAPTCHA. "
                "Le rôle choisi est attribué uniquement après réussite du CAPTCHA."
            ),
            colour=discord.Colour.blurple(),
        )
        embed.add_field(
            name="1 • Salon",
            value=channel.mention if isinstance(channel, discord.TextChannel) else "Non choisi",
            inline=False,
        )
        embed.add_field(
            name="2 • Rôle après vérification",
            value=role.mention if isinstance(role, discord.Role) else "Non choisi",
            inline=False,
        )
        embed.add_field(
            name="3 • Règlement",
            value=(self.rules_text[:700] + ("…" if len(self.rules_text) > 700 else "")),
            inline=False,
        )
        embed.add_field(
            name="4 • Image",
            value=self.image_url or "Aucune image — facultatif",
            inline=False,
        )
        embed.set_footer(text="SentriX • Vérification • CAPTCHA activé")
        return embed

    def final_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title=self.panel_title,
            description=self.rules_text,
            colour=discord.Colour.blurple(),
        )
        if self.image_url:
            embed.set_image(url=self.image_url)
        embed.set_footer(text="SentriX • Vérification sécurisée")
        return embed

    @discord.ui.button(label="3. Modifier le règlement", style=discord.ButtonStyle.secondary, row=2)
    async def edit_rules(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await interaction.response.send_modal(VerificationRulesModal(self))

    @discord.ui.button(label="Aperçu", style=discord.ButtonStyle.primary, row=2)
    async def preview(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        from cogs.verification import VerifyView

        await interaction.response.send_message(
            content="**Aperçu exact du panneau qui sera publié :**",
            embed=self.final_embed(),
            view=VerifyView(),
            ephemeral=True,
        )

    @discord.ui.button(label="Publier", style=discord.ButtonStyle.success, row=2)
    async def publish(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        guild = self._guild()
        if guild is None:
            return await interaction.response.send_message("Serveur introuvable.", ephemeral=True)
        channel = guild.get_channel(self.channel_id) if self.channel_id else None
        role = guild.get_role(self.role_id) if self.role_id else None
        if not isinstance(channel, discord.TextChannel):
            return await interaction.response.send_message(
                "Choisissez d'abord le salon où publier le règlement.", ephemeral=True
            )
        if not isinstance(role, discord.Role):
            return await interaction.response.send_message(
                "Choisissez d'abord le rôle à donner après la vérification.", ephemeral=True
            )

        from cogs.verification import VerifyView, role_grant_problem

        problem = role_grant_problem(guild, role)
        if problem:
            return await interaction.response.send_message(
                f"Impossible d'utiliser ce rôle : {problem}", ephemeral=True
            )
        permissions = channel.permissions_for(guild.me) if guild.me else None
        if permissions is None or not permissions.send_messages or not permissions.embed_links:
            return await interaction.response.send_message(
                "SentriX doit pouvoir **Voir le salon**, **Envoyer des messages** et **Intégrer des liens** dans ce salon.",
                ephemeral=True,
            )

        await interaction.response.defer(ephemeral=True, thinking=True)
        await self.cog._ensure_table()

        # Les trois clés historiques sont maintenues pour toutes les couches Setup existantes.
        await self.bot.db.set_guild_config(guild.id, "verify_role", role.id)
        await self.bot.db.set_guild_config(guild.id, "verification_role", role.id)
        await self.bot.db.set_guild_config(guild.id, "verification_channel", channel.id)
        await self.bot.db.set_guild_config(guild.id, "verify_captcha_enabled", 1)

        existing = await self.bot.db.fetchone(
            "SELECT channel_id, message_id FROM verification_panels_v96 WHERE guild_id = ?",
            (guild.id,),
        )
        sent: discord.Message | None = None
        if existing:
            old_channel = guild.get_channel(int(existing["channel_id"]))
            if isinstance(old_channel, discord.TextChannel):
                try:
                    old_message = await old_channel.fetch_message(int(existing["message_id"]))
                    if old_channel.id == channel.id:
                        await old_message.edit(embed=self.final_embed(), view=VerifyView())
                        sent = old_message
                    else:
                        await old_message.delete()
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    pass

        if sent is None:
            sent = await channel.send(embed=self.final_embed(), view=VerifyView())

        await self.bot.db.execute(
            "INSERT INTO verification_panels_v96(guild_id,channel_id,message_id,role_id,title,rules_text,image_url,updated_at) "
            "VALUES(?,?,?,?,?,?,?,?) "
            "ON CONFLICT(guild_id) DO UPDATE SET channel_id=excluded.channel_id, message_id=excluded.message_id, "
            "role_id=excluded.role_id, title=excluded.title, rules_text=excluded.rules_text, "
            "image_url=excluded.image_url, updated_at=excluded.updated_at",
            (
                guild.id,
                channel.id,
                sent.id,
                role.id,
                self.panel_title,
                self.rules_text,
                self.image_url,
                int(time.time()),
            ),
        )
        await interaction.followup.send(
            f"Vérification configurée et publiée dans {channel.mention}.\n"
            f"Après le règlement + CAPTCHA, le membre recevra {role.mention}.\n"
            "Les accès aux salons restent gérés par les permissions Discord de ce rôle, ce qui évite d'ouvrir les tickets privés aux autres membres.",
            ephemeral=True,
        )


class VerificationConfigV96(commands.Cog, name="VerificationConfigV96"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        await self._ensure_table()
        from cogs.verification import VerifyView

        if not getattr(self.bot, "_sentrix_verify_view_registered_v96", False):
            self.bot.add_view(VerifyView())
            self.bot._sentrix_verify_view_registered_v96 = True

    async def _ensure_table(self) -> None:
        await self.bot.db.execute(
            """
            CREATE TABLE IF NOT EXISTS verification_panels_v96 (
                guild_id INTEGER PRIMARY KEY,
                channel_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                role_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                rules_text TEXT NOT NULL,
                image_url TEXT,
                updated_at INTEGER NOT NULL
            )
            """
        )

    @commands.hybrid_command(
        name="verification",
        aliases=["verify-panel", "verify-setup", "verify-config", "verification-config"],
        description="Configurer le règlement, le CAPTCHA et le rôle de vérification.",
        with_app_command=False,
    )
    @commands.guild_only()
    async def verification_setup(self, ctx: commands.Context) -> None:
        # Check explicite ici pour que la commande reste protégée même si une ancienne
        # couche de permissions est rechargée dans un ordre différent.
        from utils import checks

        predicate = checks.is_owner_or_admin().predicate
        if not await predicate(ctx):
            return
        view = VerificationSetupView(self, ctx.guild.id, ctx.author.id)
        await ctx.send(embed=view.configuration_embed(), view=view)


async def _attach(bot: commands.Bot) -> None:
    if bot.get_cog("VerificationConfigV96") is not None:
        return

    # Les anciennes commandes existaient séparément. On les remplace par l'assistant
    # unique tout en gardant leurs noms comme alias préfixés.
    for legacy in ("verify-panel", "verify-setup"):
        command = bot.get_command(legacy)
        if command is not None:
            bot.remove_command(command.name)

    await bot.add_cog(VerificationConfigV96(bot))

    # Politique centrale : une seule commande configuration, admin uniquement.
    try:
        import main

        main.CATEGORY_COMMANDS["configuration"] = (
            main.CATEGORY_COMMANDS.get("configuration", frozenset()) | frozenset({"verification"})
        )
        main.KNOWN_PERMISSION_COMMANDS = main.KNOWN_PERMISSION_COMMANDS | frozenset({"verification"})
        main.PRUNED_COMMANDS = frozenset(
            name for name in main.PRUNED_COMMANDS if name not in {"verification", "verify-panel", "verify-setup"}
        )
    except Exception:
        logger.exception("Impossible de réaffirmer la politique de permission vérification V96.")


def _install_v95_route() -> None:
    try:
        import sentrix_v95_runtime as v95
    except Exception:
        return
    current = v95._special_group
    if getattr(current, "_sentrix_verification_v96", False):
        return

    def special_group_v96(command):
        name = str(getattr(command, "name", "") or "").casefold()
        if name == "verification":
            return "roles", "verification"
        return current(command)

    special_group_v96._sentrix_verification_v96 = True
    special_group_v96._sentrix_original = current
    v95._special_group = special_group_v96


def install() -> None:
    """Branche V96 juste après le chargement du cog de vérification historique."""
    _install_v95_route()
    current = commands.Bot.load_extension
    if getattr(current, "_sentrix_verification_v96", False):
        return

    async def load_extension_v96(self, name, *args, **kwargs):
        result = await current(self, name, *args, **kwargs)
        if str(name) == "cogs.verification":
            await _attach(self)
        return result

    load_extension_v96._sentrix_verification_v96 = True
    load_extension_v96._sentrix_original = current
    commands.Bot.load_extension = load_extension_v96
    logger.info("V96 : assistant règlement + CAPTCHA branché sur cogs.verification.")


__all__ = ["VerificationConfigV96", "VerificationSetupView", "install"]
