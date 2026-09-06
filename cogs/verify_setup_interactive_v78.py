"""SentriX V78 — configurateur complet ``+verify-setup`` en Components V2.

L'administrateur choisit le salon et le rôle Vérifié, écrit lui-même le règlement,
ajoute éventuellement une image, règle le CAPTCHA puis publie directement le vrai panneau
de vérification. ``verify-panel`` n'est plus nécessaire.
"""
from __future__ import annotations

import logging
import time

import discord
from discord.ext import commands

from utils import sentrix_panels as panels

logger = logging.getLogger("bot.verify-setup-v78")

_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS dashboard_verification_panels ("
    "guild_id INTEGER PRIMARY KEY, rules_text TEXT NOT NULL DEFAULT '', "
    "image_url TEXT, message_id INTEGER, updated_at INTEGER NOT NULL DEFAULT 0)"
)


def _conf(conf, key: str, default=None):
    if conf is None:
        return default
    try:
        value = conf[key]
    except (KeyError, IndexError, TypeError):
        return default
    return default if value is None else value


def _safe_image(value: str) -> str:
    raw = str(value or "").strip()[:1000]
    if raw and not raw.lower().startswith("https://"):
        raise ValueError("L'image doit utiliser une URL HTTPS publique.")
    return raw


async def _publish_public_panel(
    bot: commands.Bot,
    guild: discord.Guild,
    channel: discord.TextChannel,
    *,
    rules: str,
    image_url: str,
    previous_channel_id: int | None,
    message_id: int | None,
) -> discord.Message:
    """Publie ou met à jour le vrai panneau public de vérification."""
    from cogs.verification import VerifyView

    previous_channel = guild.get_channel(previous_channel_id) if previous_channel_id else None
    previous_message = None
    if message_id and isinstance(previous_channel, discord.TextChannel):
        try:
            previous_message = await previous_channel.fetch_message(int(message_id))
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            previous_message = None

    verification_cog = bot.get_cog("Verification")
    if verification_cog is not None and hasattr(verification_cog, "_embed"):
        public_embed = await verification_cog._embed(
            guild.id,
            title="Règlement & vérification",
            description=rules,
        )
    else:
        public_embed = discord.Embed(
            title="Règlement & vérification",
            description=rules,
            colour=discord.Colour(0x4DA3FF),
        )
    if image_url:
        public_embed.set_image(url=image_url)

    if previous_message is not None and previous_channel.id == channel.id:
        await previous_message.edit(embed=public_embed, view=VerifyView())
        return previous_message

    if previous_message is not None:
        try:
            await previous_message.delete()
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass
    return await channel.send(embed=public_embed, view=VerifyView())


class RulesModal(discord.ui.Modal):
    def __init__(self, parent: "VerifySetupView"):
        super().__init__(title="Écrire le règlement", timeout=300)
        self.parent_view = parent
        self.rules = discord.ui.TextInput(
            label="Votre règlement",
            style=discord.TextStyle.paragraph,
            placeholder="1. Respectez les membres.\n2. Pas de spam.\n3. ...",
            default=parent.rules_text[:3900],
            required=True,
            min_length=1,
            max_length=3900,
        )
        self.add_item(self.rules)

    async def on_submit(self, interaction: discord.Interaction):
        self.parent_view.rules_text = str(self.rules.value).strip()[:3900]
        await interaction.response.defer(ephemeral=True)
        await self.parent_view.refresh_message()
        await interaction.followup.send("Règlement enregistré dans le configurateur.", ephemeral=True)


class ImageModal(discord.ui.Modal):
    def __init__(self, parent: "VerifySetupView"):
        super().__init__(title="Image du règlement", timeout=300)
        self.parent_view = parent
        self.image = discord.ui.TextInput(
            label="URL HTTPS de l'image (facultatif)",
            placeholder="https://.../reglement.png",
            default=parent.image_url[:1000],
            required=False,
            max_length=1000,
        )
        self.add_item(self.image)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            self.parent_view.image_url = _safe_image(str(self.image.value))
        except ValueError as exc:
            return await interaction.response.send_message(str(exc), ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        await self.parent_view.refresh_message()
        await interaction.followup.send(
            "Image mise à jour." if self.parent_view.image_url else "Image retirée du règlement.",
            ephemeral=True,
        )


class VerifySetupView(discord.ui.View):
    def __init__(
        self,
        bot: commands.Bot,
        guild: discord.Guild,
        owner_id: int,
        *,
        channel_id: int | None,
        role_id: int | None,
        rules_text: str,
        image_url: str,
        captcha_enabled: bool,
        captcha_max_attempts: int,
        message_id: int | None,
    ):
        super().__init__(timeout=600)
        self.bot = bot
        self.guild = guild
        self.owner_id = int(owner_id)
        self.channel_id = int(channel_id) if channel_id else None
        self.previous_channel_id = self.channel_id
        self.role_id = int(role_id) if role_id else None
        self.rules_text = str(rules_text or "")[:3900]
        self.image_url = str(image_url or "")[:1000]
        self.captcha_enabled = bool(captcha_enabled)
        self.captcha_max_attempts = max(1, min(10, int(captcha_max_attempts or 3)))
        self.message_id = int(message_id) if message_id else None
        self.message: discord.Message | None = None
        self._build_components()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.owner_id:
            return True
        await interaction.response.send_message("Ce configurateur ne vous appartient pas.", ephemeral=True)
        return False

    def _build_components(self) -> None:
        self.clear_items()

        channel_select = discord.ui.ChannelSelect(
            placeholder="1. Choisir le salon du règlement",
            min_values=1,
            max_values=1,
            channel_types=[discord.ChannelType.text, discord.ChannelType.news],
            row=0,
        )

        async def choose_channel(interaction: discord.Interaction):
            self.channel_id = int(channel_select.values[0].id)
            await panels.editer(interaction.response, self.panel())

        channel_select.callback = choose_channel
        self.add_item(channel_select)

        role_select = discord.ui.RoleSelect(
            placeholder="2. Choisir le rôle Vérifié",
            min_values=1,
            max_values=1,
            row=1,
        )

        async def choose_role(interaction: discord.Interaction):
            self.role_id = int(role_select.values[0].id)
            await panels.editer(interaction.response, self.panel())

        role_select.callback = choose_role
        self.add_item(role_select)

        rules_button = discord.ui.Button(
            label="Écrire / modifier le règlement",
            style=discord.ButtonStyle.primary,
            row=2,
        )
        image_button = discord.ui.Button(
            label="Configurer l'image",
            style=discord.ButtonStyle.secondary,
            row=2,
        )

        async def edit_rules(interaction: discord.Interaction):
            await interaction.response.send_modal(RulesModal(self))

        async def edit_image(interaction: discord.Interaction):
            await interaction.response.send_modal(ImageModal(self))

        rules_button.callback = edit_rules
        image_button.callback = edit_image
        self.add_item(rules_button)
        self.add_item(image_button)

        captcha_button = discord.ui.Button(
            label=f"CAPTCHA : {'ACTIF' if self.captcha_enabled else 'INACTIF'}",
            style=discord.ButtonStyle.primary if self.captcha_enabled else discord.ButtonStyle.secondary,
            row=3,
        )
        attempts_button = discord.ui.Button(
            label=f"Tentatives : {self.captcha_max_attempts}",
            style=discord.ButtonStyle.secondary,
            row=3,
        )

        async def toggle_captcha(interaction: discord.Interaction):
            self.captcha_enabled = not self.captcha_enabled
            await panels.editer(interaction.response, self.panel())

        async def cycle_attempts(interaction: discord.Interaction):
            choices = (1, 3, 5, 10)
            try:
                self.captcha_max_attempts = choices[(choices.index(self.captcha_max_attempts) + 1) % len(choices)]
            except ValueError:
                self.captcha_max_attempts = 3
            await panels.editer(interaction.response, self.panel())

        captcha_button.callback = toggle_captcha
        attempts_button.callback = cycle_attempts
        self.add_item(captcha_button)
        self.add_item(attempts_button)

        publish_button = discord.ui.Button(
            label="Enregistrer et publier",
            style=discord.ButtonStyle.success,
            row=4,
        )
        close_button = discord.ui.Button(label="Fermer", style=discord.ButtonStyle.danger, row=4)

        async def publish_callback(interaction: discord.Interaction):
            await self.publish(interaction)

        async def close_callback(interaction: discord.Interaction):
            self.stop()
            await panels.editer(interaction.response, self.panel(closed=True, disabled=True))

        publish_button.callback = publish_callback
        close_button.callback = close_callback
        self.add_item(publish_button)
        self.add_item(close_button)

    def embed(self, *, closed: bool = False) -> discord.Embed:
        channel = self.guild.get_channel(self.channel_id) if self.channel_id else None
        role = self.guild.get_role(self.role_id) if self.role_id else None
        preview = self.rules_text.strip()
        if len(preview) > 850:
            preview = preview[:847].rstrip() + "…"
        if not preview:
            preview = "*Aucun règlement écrit pour le moment.*"
        embed = discord.Embed(
            title="Vérification & règlement",
            description=(
                "Configurez tout ici. **Le règlement est écrit par vous**, SentriX ne le génère pas.\n"
                "Le bouton **Enregistrer et publier** envoie ou met à jour le panneau dans le salon choisi."
            ),
            colour=discord.Colour(0x4DA3FF),
        )
        embed.add_field(name="Salon", value=channel.mention if channel else "Non configuré", inline=True)
        embed.add_field(name="Rôle Vérifié", value=role.mention if role else "Non configuré", inline=True)
        embed.add_field(
            name="CAPTCHA",
            value=f"ACTIF · {self.captcha_max_attempts} tentative(s)" if self.captcha_enabled else "INACTIF",
            inline=True,
        )
        embed.add_field(name="Votre règlement", value=preview, inline=False)
        embed.add_field(name="Image", value=self.image_url or "Aucune image", inline=False)
        embed.set_footer(
            text="Configurateur fermé — relancez +verify-setup pour modifier."
            if closed
            else "SentriX • Les changements sont persistés lors de la publication"
        )
        return embed

    def panel(self, *, closed: bool = False, disabled: bool = False):
        # avec_composants déplace les items dans le LayoutView final. On reconstruit donc
        # une vue source fraîche à chaque rendu avant de la convertir.
        self._build_components()
        if disabled:
            for item in self.children:
                item.disabled = True
        base = panels.depuis_embed(self.embed(closed=closed), kind="info", compact=False)
        return panels.avec_composants(base, self)

    async def refresh_message(self) -> None:
        if self.message is None:
            return
        try:
            await panels.editer(self.message, self.panel())
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass

    async def publish(self, interaction: discord.Interaction) -> None:
        from cogs.verification import role_grant_problem

        channel = self.guild.get_channel(self.channel_id) if self.channel_id else None
        role = self.guild.get_role(self.role_id) if self.role_id else None
        if not isinstance(channel, discord.TextChannel):
            return await interaction.response.send_message("Choisissez d'abord un salon textuel valide.", ephemeral=True)
        problem = role_grant_problem(self.guild, role)
        if problem:
            return await interaction.response.send_message(f"Rôle de vérification invalide : {problem}", ephemeral=True)
        rules = self.rules_text.strip()
        if not rules:
            return await interaction.response.send_message("Écrivez votre règlement avant de publier.", ephemeral=True)
        try:
            image_url = _safe_image(self.image_url)
        except ValueError as exc:
            return await interaction.response.send_message(str(exc), ephemeral=True)

        me = self.guild.me
        if me is None:
            return await interaction.response.send_message("SentriX n'est pas disponible dans le cache du serveur.", ephemeral=True)
        permissions = channel.permissions_for(me)
        if not permissions.send_messages or not permissions.embed_links:
            return await interaction.response.send_message(
                "SentriX a besoin des permissions **Envoyer des messages** et **Intégrer des liens** dans ce salon.",
                ephemeral=True,
            )

        await interaction.response.defer(ephemeral=True, thinking=True)
        await self.bot.db.execute(_SCHEMA)
        try:
            published = await _publish_public_panel(
                self.bot,
                self.guild,
                channel,
                rules=rules,
                image_url=image_url,
                previous_channel_id=self.previous_channel_id,
                message_id=self.message_id,
            )
        except discord.Forbidden:
            return await interaction.followup.send(
                "Discord a refusé la publication. Vérifiez les permissions de SentriX dans ce salon.",
                ephemeral=True,
            )
        except discord.HTTPException:
            logger.exception("V78 : publication du règlement impossible guild=%s", self.guild.id)
            return await interaction.followup.send("Discord a refusé la publication du règlement.", ephemeral=True)

        await self.bot.db.set_guild_config(self.guild.id, "verify_role", role.id)
        await self.bot.db.set_guild_config(self.guild.id, "verification_role", role.id)
        await self.bot.db.set_guild_config(self.guild.id, "verification_channel", channel.id)
        await self.bot.db.set_guild_config(self.guild.id, "verify_captcha_enabled", int(self.captcha_enabled))
        await self.bot.db.set_guild_config(self.guild.id, "verify_captcha_max_attempts", self.captcha_max_attempts)
        await self.bot.db.execute(
            "INSERT INTO dashboard_verification_panels (guild_id,rules_text,image_url,message_id,updated_at) VALUES (?,?,?,?,?) "
            "ON CONFLICT(guild_id) DO UPDATE SET rules_text=excluded.rules_text,image_url=excluded.image_url,message_id=excluded.message_id,updated_at=excluded.updated_at",
            (self.guild.id, rules, image_url or None, published.id, int(time.time())),
        )
        try:
            await self.bot.db.add_setup_history(
                self.guild.id,
                self.owner_id,
                "verification",
                "Règlement / vérification",
                f"salon={channel.id}; rôle={role.id}; captcha={self.captcha_enabled}",
            )
        except Exception:
            pass

        self.message_id = int(published.id)
        self.previous_channel_id = int(channel.id)
        await self.refresh_message()
        await interaction.followup.send(
            f"Configuration enregistrée et panneau publié dans {channel.mention}.",
            ephemeral=True,
        )

    async def on_timeout(self) -> None:
        if self.message is None:
            return
        try:
            await panels.editer(self.message, self.panel(disabled=True))
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass


async def _open_setup(ctx: commands.Context) -> None:
    if ctx.guild is None:
        return await ctx.send("Cette commande doit être utilisée sur un serveur.")
    if not (ctx.author.id == ctx.guild.owner_id or ctx.author.guild_permissions.administrator):
        return await ctx.send("Cette configuration est réservée au propriétaire ou aux administrateurs du serveur.")

    await ctx.bot.db.execute(_SCHEMA)
    conf = await ctx.bot.db.get_guild_config(ctx.guild.id)
    row = await ctx.bot.db.fetchone(
        "SELECT rules_text,image_url,message_id FROM dashboard_verification_panels WHERE guild_id = ?",
        (ctx.guild.id,),
    )
    row = dict(row) if row else {}
    view = VerifySetupView(
        ctx.bot,
        ctx.guild,
        ctx.author.id,
        channel_id=_conf(conf, "verification_channel"),
        role_id=_conf(conf, "verify_role", _conf(conf, "verification_role")),
        rules_text=row.get("rules_text") or "",
        image_url=row.get("image_url") or "",
        captcha_enabled=bool(_conf(conf, "verify_captcha_enabled", 1)),
        captcha_max_attempts=int(_conf(conf, "verify_captcha_max_attempts", 3) or 3),
        message_id=row.get("message_id"),
    )
    view.message = await panels.envoyer(ctx, view.panel())


def install(bot: commands.Bot) -> bool:
    if getattr(bot, "_sentrix_verify_setup_v78", False):
        return True
    bot.remove_command("verify-setup")
    bot.remove_command("verify-panel")
    try:
        bot.tree.remove_command("verify-setup", type=discord.AppCommandType.chat_input)
    except Exception:
        pass
    try:
        bot.tree.remove_command("verify-panel", type=discord.AppCommandType.chat_input)
    except Exception:
        pass

    command = commands.Command(
        _open_setup,
        name="verify-setup",
        help="Configurer et publier le règlement, le rôle Vérifié, l'image et le CAPTCHA.",
        description="Ouvrir le configurateur complet de vérification SentriX.",
    )
    bot.add_command(command)
    bot._sentrix_verify_setup_v78 = True
    logger.info("V78 actif : +verify-setup complet en Components V2, verify-panel supprimé.")
    return True


__all__ = ["install", "VerifySetupView", "_safe_image"]
