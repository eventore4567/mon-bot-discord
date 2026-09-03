"""
Cog VÉRIFICATION / RÔLES.
/verify-setup /verify-panel /rolepanel create|add|remove|list|delete
/reactionrole-add /reactionrole-remove /reactionrole-list (compatibilité)
/giverole /removerole /roleall /massrole
"""

import asyncio
import io
import logging
import random
import time
import unicodedata
import discord
from discord import app_commands
from discord.ext import commands

from utils import embeds, checks, design_system, visual_v5
from utils import sentrix_panels as panels
from database.db import now

logger = logging.getLogger("bot.verification")


def _emoji_parts(raw: str) -> tuple[str, str, discord.PartialEmoji]:
    """Retourne (clé stable, affichage, emoji Discord), y compris pour les GIF animés."""
    emoji = discord.PartialEmoji.from_str(raw.strip())
    if not emoji.name:
        raise ValueError("emoji vide")
    if emoji.id:
        return f"custom:{emoji.id}", str(emoji), emoji
    return f"unicode:{emoji.name}", emoji.name, emoji


def _payload_emoji_key(emoji: discord.PartialEmoji) -> str:
    return f"custom:{emoji.id}" if emoji.id else f"unicode:{emoji.name}"


def _self_role_error(guild: discord.Guild, role: discord.Role) -> str | None:
    if role.is_default():
        return "Le rôle @everyone ne peut pas être distribué par réaction."
    if role.managed:
        return "Ce rôle est géré par Discord ou une intégration."
    bot_member = guild.me
    if bot_member is None or role >= bot_member.top_role:
        return "Placez ce rôle sous le rôle du bot dans Paramètres du serveur > Rôles."
    permissions = role.permissions
    if (
        permissions.administrator
        or permissions.manage_guild
        or permissions.manage_roles
        or permissions.manage_channels
        or permissions.ban_members
        or permissions.kick_members
        or permissions.moderate_members
        or permissions.manage_webhooks
    ):
        return "Les rôles d'administration ou de modération ne peuvent pas être obtenus automatiquement."
    return None


def role_grant_problem(guild: discord.Guild, role: discord.Role | None) -> str | None:
    """Diagnostic explicite : pourquoi (ou si) SentriX ne peut pas donner ce rôle.

    Contrairement à _self_role_error (rôles en self-service, où un membre choisit lui-même
    -- les rôles d'administration y sont donc exclus par sécurité), verify_role est choisi
    par un administrateur dans /setup : seule la faisabilité TECHNIQUE compte ici. Utilisé
    à la fois par le setup (avertir avant l'envoi du panneau) et par le flux de vérification
    réel (ne jamais échouer en silence -- voir do_verify)."""
    if role is None:
        return "Le rôle de vérification configuré est introuvable (peut-être supprimé)."
    if role.is_default():
        return "Le rôle @everyone ne peut pas être utilisé comme rôle de vérification."
    if role.managed:
        return "Ce rôle est géré par Discord ou une intégration : il ne peut pas être attribué manuellement."
    me = guild.me
    if me is None:
        return "SentriX n'est pas disponible dans le cache de ce serveur."
    if not me.guild_permissions.manage_roles:
        return "SentriX n'a pas la permission **Gérer les rôles**."
    if role >= me.top_role:
        return "Le rôle de SentriX doit être placé au-dessus du rôle de vérification (Paramètres du serveur > Rôles)."
    return None


NOTIFICATION_ROLE_MARKERS = (
    "ping",
    "notif",
)


def _is_notification_role(role: discord.Role) -> bool:
    """Reconnaît uniquement les rôles destinés aux notifications/pings."""
    normalized = unicodedata.normalize("NFKD", role.name.casefold())
    normalized = "".join(character for character in normalized if not unicodedata.combining(character))
    normalized = normalized.replace("-", " ").replace("_", " ")
    # Le rôle doit dire explicitement « ping » ou « notification ». Des mots seuls
    # comme « événements » ou « streamer » peuvent désigner des postes du staff et ne
    # doivent jamais apparaître dans le sélecteur public.
    return any(marker in normalized for marker in NOTIFICATION_ROLE_MARKERS)


class SelfRoleSelect(discord.ui.Select):
    def __init__(self, options: list[discord.SelectOption] | None = None, *, handler: bool = False):
        real_options = options or [discord.SelectOption(label="Aucun rôle configuré", value="none")]
        super().__init__(
            placeholder="Choisissez vos notifications",
            min_values=1,
            max_values=min(len(real_options), 25),
            options=real_options,
            custom_id="sentrix:selfroles:select",
            disabled=not options and not handler,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction):
        if not self.values or self.values == ["none"]:
            return await interaction.response.send_message("Aucun rôle n'est encore configuré.", ephemeral=True)
        cog = interaction.client.get_cog("Verification")
        if cog is None:
            return await interaction.response.send_message("Le menu de rôles est temporairement indisponible.", ephemeral=True)
        await cog.handle_self_role_selection(interaction, self.values)


class SelfRolePublicView(discord.ui.View):
    def __init__(self, options: list[discord.SelectOption] | None = None, *, handler: bool = False):
        super().__init__(timeout=None)
        self.add_item(SelfRoleSelect(options, handler=handler))


# ---------------------------------------------------------------------------
# CAPTCHA de vérification : un défi image (code à recopier) s'intercale entre
# « J'ai lu les règles » et l'attribution réelle du rôle configuré. Simple pour un humain,
# mais impossible à résoudre sans vision (OCR) pour un bot de raid basique -- contrairement
# à un code montré en texte brut, qu'un script peut lire et retaper sans aucun effort.
# ---------------------------------------------------------------------------

_CAPTCHA_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # sans 0/O ni 1/I/L : ambigus à l'oeil
_CAPTCHA_CODE_LENGTH = 5
_CAPTCHA_TTL_SECONDS = 5 * 60
_CAPTCHA_LOCKOUT_SECONDS = 10 * 60
_CAPTCHA_CLICK_COOLDOWN_SECONDS = 3.0

# Anti-spam du bouton "J'ai lu les règles" : purement en mémoire (pas besoin de survivre à
# un redémarrage, une fenêtre de quelques secondes suffit). Clé (guild_id, user_id).
_recent_verify_clicks: dict[tuple[int, int], float] = {}


def _click_is_spam(guild_id: int, user_id: int) -> bool:
    key = (int(guild_id), int(user_id))
    now_value = time.monotonic()
    last = _recent_verify_clicks.get(key)
    _recent_verify_clicks[key] = now_value
    if len(_recent_verify_clicks) > 8192:
        cutoff = now_value - 60.0
        for stale_key, seen_at in tuple(_recent_verify_clicks.items()):
            if seen_at < cutoff:
                _recent_verify_clicks.pop(stale_key, None)
    return last is not None and (now_value - last) < _CAPTCHA_CLICK_COOLDOWN_SECONDS


def _generate_captcha_code() -> str:
    return "".join(random.choices(_CAPTCHA_ALPHABET, k=_CAPTCHA_CODE_LENGTH))


def _render_captcha_image(code: str) -> bytes:
    """PNG avec bruit/distorsion : lisible en quelques secondes par un humain, illisible
    par un simple parseur de texte puisque le code n'apparaît jamais en clair."""
    from PIL import Image, ImageDraw

    width, height = 260, 100
    image = Image.new("RGB", (width, height), (244, 245, 250))
    draw = ImageDraw.Draw(image)

    for _ in range(6):
        draw.line(
            (random.randint(0, width), random.randint(0, height), random.randint(0, width), random.randint(0, height)),
            fill=(200, 205, 218), width=2,
        )
    for _ in range(140):
        draw.point((random.randint(0, width - 1), random.randint(0, height - 1)), fill=(188, 193, 205))

    font = visual_v5._font(50, bold=True)
    char_width = width // len(code)
    colours = ((60, 55, 130), (95, 40, 120), (35, 90, 130), (110, 60, 40), (40, 110, 80))
    for index, character in enumerate(code):
        layer = Image.new("RGBA", (char_width, height), (0, 0, 0, 0))
        layer_draw = ImageDraw.Draw(layer)
        layer_draw.text((char_width // 2, height // 2), character, font=font, fill=random.choice(colours), anchor="mm")
        rotated = layer.rotate(random.randint(-30, 30), expand=False, resample=Image.BICUBIC)
        image.paste(rotated, (index * char_width, random.randint(-8, 8)), rotated)

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer.read()


async def _get_captcha_session(bot, guild_id: int, user_id: int) -> dict | None:
    row = await bot.db.fetchone(
        "SELECT * FROM verification_captcha_sessions WHERE guild_id = ? AND user_id = ?",
        (guild_id, user_id),
    )
    return dict(row) if row else None


async def _start_captcha_session(bot, guild_id: int, user_id: int) -> str:
    code = _generate_captcha_code()
    created_at = int(time.time())
    await bot.db.execute(
        "INSERT INTO verification_captcha_sessions (guild_id, user_id, code, attempts, created_at, expires_at, locked_until) "
        "VALUES (?, ?, ?, 0, ?, ?, NULL) "
        "ON CONFLICT(guild_id, user_id) DO UPDATE SET code = excluded.code, attempts = 0, "
        "created_at = excluded.created_at, expires_at = excluded.expires_at, locked_until = NULL",
        (guild_id, user_id, code, created_at, created_at + _CAPTCHA_TTL_SECONDS),
    )
    return code


async def _clear_captcha_session(bot, guild_id: int, user_id: int) -> None:
    await bot.db.execute(
        "DELETE FROM verification_captcha_sessions WHERE guild_id = ? AND user_id = ?",
        (guild_id, user_id),
    )


async def _fail_captcha_attempt(bot, guild_id: int, user_id: int, max_attempts: int) -> tuple[bool, str | None, int]:
    """Incrémente les tentatives et régénère TOUJOURS un nouveau code pour la prochaine
    (un bot qui aurait mémorisé l'image précédente ne peut pas juste réessayer le même
    OCR). Renvoie (verrouillé, nouveau_code_ou_None_si_verrouille, tentatives_utilisees)."""
    session = await _get_captcha_session(bot, guild_id, user_id)
    attempts = (int(session["attempts"]) if session else 0) + 1
    if attempts >= max(1, int(max_attempts)):
        locked_until = int(time.time()) + _CAPTCHA_LOCKOUT_SECONDS
        await bot.db.execute(
            "UPDATE verification_captcha_sessions SET attempts = ?, locked_until = ? WHERE guild_id = ? AND user_id = ?",
            (attempts, locked_until, guild_id, user_id),
        )
        return True, None, attempts
    new_code = _generate_captcha_code()
    await bot.db.execute(
        "UPDATE verification_captcha_sessions SET code = ?, attempts = ? WHERE guild_id = ? AND user_id = ?",
        (new_code, attempts, guild_id, user_id),
    )
    return False, new_code, attempts


async def _captcha_file_and_embed(cog: "Verification", guild_id: int, code: str, *, title: str, description: str, kind: str = "primary"):
    image_bytes = _render_captcha_image(code)
    file = discord.File(io.BytesIO(image_bytes), filename="captcha.png")
    embed = await cog._embed(guild_id, title=title, description=description, kind=kind)
    embed.set_image(url="attachment://captcha.png")
    return file, embed


class CaptchaModal(discord.ui.Modal, title="Vérification — Entrez le code"):
    code_input = discord.ui.TextInput(label="Code affiché sur l'image", max_length=10, placeholder="Ex : 7K3PL")

    def __init__(self, cog: "Verification"):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        await self.cog.handle_captcha_submission(interaction, str(self.code_input.value))


class CaptchaOpenModalView(discord.ui.View):
    """Vue éphémère à courte durée de vie (liée à une session CAPTCHA de quelques minutes) :
    n'a pas besoin d'un custom_id persistant. Le bouton "J'ai lu les règles" sur le panneau
    permanent, lui (VerifyView plus bas), reste enregistré comme vue persistante et survit
    donc normalement à un redémarrage -- relancer le défi après un redémarrage revient
    simplement à recliquer ce bouton-là."""

    def __init__(self, cog: "Verification", author_id: int):
        super().__init__(timeout=_CAPTCHA_TTL_SECONDS)
        self.cog = cog
        self.author_id = int(author_id)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Ce défi ne vous appartient pas.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Entrer le code", style=discord.ButtonStyle.primary)
    async def open_modal(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(CaptchaModal(self.cog))


class VerifyView(discord.ui.View):
    """Vue persistante affichée sur le panneau de vérification (bouton pour obtenir le rôle vérifié)."""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="● Je certifie avoir lu les règles", style=discord.ButtonStyle.success, custom_id="verify_panel_btn")
    async def verify(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog: "Verification" = interaction.client.get_cog("Verification")
        await cog.do_verify(interaction)


class Verification(commands.Cog, name="Verification"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        if not getattr(self.bot, "_sentrix_self_role_view_registered", False):
            self.bot.add_view(SelfRolePublicView(handler=True))
            self.bot._sentrix_self_role_view_registered = True
        self._self_role_refresh_task = asyncio.create_task(self._refresh_self_role_panels_after_ready())

    async def cog_unload(self):
        task = getattr(self, "_self_role_refresh_task", None)
        if task:
            task.cancel()

    async def _embed(self, guild_id: int, *, title: str, description: str = None, kind: str = "primary") -> discord.Embed:
        """Embed cohérent avec +designsetup (catégorie CATEGORY_STYLES["verification"])."""
        style = design_system.CATEGORY_STYLES["verification"]
        colour_key = {"primary": "primary_color", "success": "success_color", "warning": "warning_color", "danger": "danger_color"}.get(kind, "primary_color")
        default_colour = style["colour"] if kind == "primary" else getattr(design_system.COLORS, kind)
        design = await self.bot.db.get_design_settings(guild_id)
        return design_system.create_embed(
            title=design_system.kind_title(title, kind=kind, category_emoji=style["emoji"]),
            description=description,
            colour=design.get(colour_key, default_colour),
            footer=design.get("footer"),
        )

    async def _self_role_options(self, guild: discord.Guild, panel_message_id: int) -> list[discord.SelectOption]:
        options = []
        for role in reversed(guild.roles):
            if not _is_notification_role(role) or _self_role_error(guild, role):
                continue
            options.append(discord.SelectOption(label=role.name[:100], value=str(role.id)))
        return options[:25]

    async def _self_role_embed(self, guild: discord.Guild, panel, options: list[discord.SelectOption]) -> discord.Embed:
        if options:
            roles = "\n".join(f"• {option.label}" for option in options)
            description = (
                "Choisissez les notifications que vous souhaitez recevoir.\n"
                "Choisir une notification l'ajoute ; la choisir une seconde fois la retire.\n\n"
                f"**Notifications disponibles**\n{roles}"
            )
        else:
            description = (
                "Aucun rôle de notification n'est disponible.\n"
                "Créez un rôle contenant par exemple `Ping`, `Notifications`, `Annonces`, `Giveaways` ou `Événements` dans son nom."
            )
        return await self._embed(guild.id, title=panel["title"], description=description)

    async def _refresh_self_role_panel(self, guild: discord.Guild, message_id: int):
        panel = await self.bot.db.fetchone(
            "SELECT * FROM self_role_panels WHERE guild_id = ? AND message_id = ?",
            (guild.id, message_id),
        )
        if not panel:
            return
        channel = guild.get_channel(panel["channel_id"]) or self.bot.get_channel(panel["channel_id"])
        if channel is None:
            return
        options = await self._self_role_options(guild, message_id)
        try:
            message = await channel.fetch_message(message_id)
            embed = await self._self_role_embed(guild, panel, options)
            view = SelfRolePublicView(options)
            # Une référence Discord ne peut pas être retirée par edit(). On republie
            # donc une fois les anciens panneaux créés comme réponses afin que la
            # suppression de la commande n'affiche plus « message original supprimé ».
            if message.reference is not None:
                replacement = await panels.envoyer(channel, panels.avec_composants(panels.depuis_embed(embed), view))
                await self.bot.db.execute(
                    "INSERT INTO self_role_panels (guild_id, channel_id, message_id, title, created_by, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        guild.id,
                        channel.id,
                        replacement.id,
                        panel["title"],
                        panel["created_by"],
                        panel["created_at"],
                    ),
                )
                await self.bot.db.execute(
                    "DELETE FROM self_role_panels WHERE guild_id = ? AND message_id = ?",
                    (guild.id, message_id),
                )
                await self.bot.db.execute(
                    "DELETE FROM self_role_items WHERE guild_id = ? AND panel_message_id = ?",
                    (guild.id, message_id),
                )
                try:
                    await message.delete()
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    pass
                return
            await message.edit(
                embed=embed,
                view=view,
            )
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return

    async def _refresh_self_role_panels_after_ready(self):
        await self.bot.wait_until_ready()
        panels = await self.bot.db.fetchall("SELECT guild_id, message_id FROM self_role_panels")
        for panel in panels:
            guild = self.bot.get_guild(panel["guild_id"])
            if guild:
                await self._refresh_self_role_panel(guild, panel["message_id"])

    async def _create_self_role_panel(self, ctx: commands.Context, title: str):
        title = title.strip()[:256] or "Choisissez vos notifications"
        temporary_panel = {"title": title}
        options = await self._self_role_options(ctx.guild, 0)
        message = await panels.envoyer(ctx.channel, panels.avec_composants(panels.depuis_embed(await self._self_role_embed(ctx.guild, temporary_panel, options)), SelfRolePublicView(options)))
        await self.bot.db.execute(
            "INSERT INTO self_role_panels (guild_id, channel_id, message_id, title, created_by, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(guild_id, message_id) DO NOTHING",
            (ctx.guild.id, ctx.channel.id, message.id, title, ctx.author.id, now()),
        )

    async def handle_self_role_selection(self, interaction: discord.Interaction, raw_role_ids: list[str]):
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("Ce menu fonctionne uniquement dans un serveur.", ephemeral=True)
        panel = await self.bot.db.fetchone(
            "SELECT 1 FROM self_role_panels WHERE guild_id = ? AND message_id = ?",
            (interaction.guild.id, interaction.message.id),
        )
        if not panel:
            return await interaction.response.send_message("Ce panneau n'est plus configuré.", ephemeral=True)
        allowed = {
            role.id for role in interaction.guild.roles
            if _is_notification_role(role) and not _self_role_error(interaction.guild, role)
        }
        chosen = []
        for raw_role_id in raw_role_ids:
            try:
                role_id = int(raw_role_id)
            except ValueError:
                continue
            if role_id not in allowed:
                continue
            role = interaction.guild.get_role(role_id)
            if role and _is_notification_role(role) and not _self_role_error(interaction.guild, role):
                chosen.append(role)
        if not chosen:
            return await interaction.response.send_message("Aucun de ces rôles n'est encore disponible.", ephemeral=True)

        await interaction.response.defer(ephemeral=True, thinking=True)
        added = [role for role in chosen if role not in interaction.user.roles]
        removed = [role for role in chosen if role in interaction.user.roles]
        try:
            if added:
                await interaction.user.add_roles(*added, reason="Choix dans le panneau de rôles SentriX")
            if removed:
                await interaction.user.remove_roles(*removed, reason="Choix dans le panneau de rôles SentriX")
        except (discord.Forbidden, discord.HTTPException):
            return await interaction.followup.send(
                "Discord refuse de modifier un de ces rôles. Le rôle du bot doit être placé au-dessus.",
                ephemeral=True,
            )
        lines = []
        if added:
            lines.append("Ajouté : " + ", ".join(role.mention for role in added))
        if removed:
            lines.append("Retiré : " + ", ".join(role.mention for role in removed))
        await interaction.followup.send("\n".join(lines), ephemeral=True)

    async def _grant_verified_role(self, interaction: discord.Interaction, role: discord.Role) -> None:
        """Point d'écriture UNIQUE du rôle vérifié — appelé aussi bien sans CAPTCHA
        (désactivé) qu'après un CAPTCHA réussi. Ne échoue jamais en silence : Discord
        refuse ? Le membre ET les logs le savent, avec la cause exacte."""
        member = interaction.user
        try:
            await member.add_roles(role, reason="Vérification via panneau SentriX")
        except discord.Forbidden:
            logger.error(
                "Attribution du rôle de vérification refusée guild=%s user=%s role=%s : "
                "permission Discord manquante ou hiérarchie insuffisante malgré la vérification préalable.",
                interaction.guild.id, member.id, role.id,
            )
            return await interaction.response.send_message(
                "Discord a refusé l'attribution du rôle. Un administrateur doit vérifier que le rôle de "
                "SentriX est bien placé au-dessus du rôle de vérification, puis relancer la vérification.",
                ephemeral=True,
            )
        await self.bot.db.execute(
            "INSERT OR IGNORE INTO verified_users (guild_id, user_id, verified_at) VALUES (?, ?, strftime('%s','now'))",
            (interaction.guild.id, member.id),
        )
        await interaction.response.send_message("● Vous avez été vérifié avec succès !", ephemeral=True)

    async def _send_captcha_challenge(self, interaction: discord.Interaction, *, new_session: bool) -> None:
        guild, member = interaction.guild, interaction.user
        if new_session:
            code = await _start_captcha_session(self.bot, guild.id, member.id)
        else:
            session = await _get_captcha_session(self.bot, guild.id, member.id)
            code = session["code"] if session else await _start_captcha_session(self.bot, guild.id, member.id)
        file, embed = await _captcha_file_and_embed(
            self, guild.id, code,
            title="Vérification — CAPTCHA",
            description=(
                "Recopiez le code affiché sur l'image ci-dessous, puis cliquez sur **Entrer le code**.\n"
                "Ce défi expire dans quelques minutes et n'est visible que par vous."
            ),
        )
        await interaction.response.send_message(embed=embed, file=file, view=CaptchaOpenModalView(self, member.id), ephemeral=True)

    async def do_verify(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        member = interaction.user
        if guild is None or not isinstance(member, discord.Member):
            return await interaction.response.send_message("Cette action doit se faire sur un serveur.", ephemeral=True)

        # Anti-spam du bouton lui-même, avant toute lecture DB : un clic répété très
        # rapproché n'a aucune raison légitime et ne doit pas régénérer d'image à chaque fois.
        if _click_is_spam(guild.id, member.id):
            return await interaction.response.send_message(
                "Vous venez déjà de cliquer. Patientez quelques secondes avant de réessayer.",
                ephemeral=True,
            )

        conf = await self.bot.db.get_guild_config(guild.id)
        role_id = conf["verify_role"] if conf else None
        if not role_id:
            return await interaction.response.send_message("Aucun rôle de vérification n'est configuré sur ce serveur.", ephemeral=True)
        role = guild.get_role(int(role_id))
        problem = role_grant_problem(guild, role)
        if problem:
            logger.warning("Vérification bloquée guild=%s role=%s : %s", guild.id, role_id, problem)
            return await interaction.response.send_message(f"Vérification impossible pour le moment : {problem}", ephemeral=True)
        if role in member.roles:
            await _clear_captcha_session(self.bot, guild.id, member.id)
            return await interaction.response.send_message("Vous êtes déjà vérifié !", ephemeral=True)

        captcha_on = bool(conf["verify_captcha_enabled"]) if conf and "verify_captcha_enabled" in conf.keys() else True
        if not captcha_on:
            return await self._grant_verified_role(interaction, role)

        session = await _get_captcha_session(self.bot, guild.id, member.id)
        now_value = int(time.time())
        if session and session.get("locked_until") and int(session["locked_until"]) > now_value:
            minutes = max(1, (int(session["locked_until"]) - now_value) // 60)
            return await interaction.response.send_message(
                f"Trop de tentatives incorrectes. Réessayez dans environ {minutes} minute(s), "
                "ou contactez un membre du staff.",
                ephemeral=True,
            )
        # Une session valide et pas verrouillée deja en cours ? Reaffiche EXACTEMENT le meme
        # defi (meme code, memes tentatives deja utilisees) au lieu d'en redemarrer une
        # nouvelle a chaque clic : sinon, spammer ce bouton reinitialiserait indefiniment le
        # compteur de tentatives et contournerait la limite.
        has_live_session = bool(session) and int(session["expires_at"]) > now_value and not session.get("locked_until")
        await self._send_captcha_challenge(interaction, new_session=not has_live_session)

    async def handle_captcha_submission(self, interaction: discord.Interaction, submitted: str) -> None:
        guild = interaction.guild
        member = interaction.user
        if guild is None or not isinstance(member, discord.Member):
            return await interaction.response.send_message("Cette action doit se faire sur un serveur.", ephemeral=True)

        conf = await self.bot.db.get_guild_config(guild.id)
        role_id = conf["verify_role"] if conf else None
        role = guild.get_role(int(role_id)) if role_id else None
        problem = role_grant_problem(guild, role)
        if problem:
            return await interaction.response.send_message(f"Vérification impossible pour le moment : {problem}", ephemeral=True)
        if role in member.roles:
            await _clear_captcha_session(self.bot, guild.id, member.id)
            return await interaction.response.send_message("Vous êtes déjà vérifié !", ephemeral=True)

        session = await _get_captcha_session(self.bot, guild.id, member.id)
        now_value = int(time.time())
        if not session:
            return await interaction.response.send_message(
                "Ce défi n'existe plus. Cliquez de nouveau sur le bouton du panneau de règles pour en obtenir un nouveau.",
                ephemeral=True,
            )
        if int(session["expires_at"]) < now_value:
            await _clear_captcha_session(self.bot, guild.id, member.id)
            return await interaction.response.send_message(
                "Ce code a expiré. Cliquez de nouveau sur le bouton du panneau de règles pour en obtenir un nouveau.",
                ephemeral=True,
            )
        if session.get("locked_until") and int(session["locked_until"]) > now_value:
            minutes = max(1, (int(session["locked_until"]) - now_value) // 60)
            return await interaction.response.send_message(
                f"Trop de tentatives incorrectes. Réessayez dans environ {minutes} minute(s).",
                ephemeral=True,
            )

        if submitted.strip().upper() != str(session["code"]).upper():
            max_attempts = int(conf["verify_captcha_max_attempts"]) if conf and conf["verify_captcha_max_attempts"] else 3
            locked, new_code, attempts = await _fail_captcha_attempt(self.bot, guild.id, member.id, max_attempts)
            if locked:
                return await interaction.response.send_message(
                    f"Code incorrect ({attempts}/{max_attempts} tentative(s)). Trop d'essais : réessayez dans "
                    f"environ {_CAPTCHA_LOCKOUT_SECONDS // 60} minutes, ou contactez un membre du staff.",
                    ephemeral=True,
                )
            file, embed = await _captcha_file_and_embed(
                self, guild.id, new_code,
                title="Code incorrect",
                description=f"Ce n'était pas le bon code ({attempts}/{max_attempts} tentative(s) utilisée(s)). Voici un nouveau défi :",
                kind="warning",
            )
            return await interaction.response.send_message(
                embed=embed, file=file, view=CaptchaOpenModalView(self, member.id), ephemeral=True,
            )

        await _clear_captcha_session(self.bot, guild.id, member.id)
        await self._grant_verified_role(interaction, role)

    @commands.hybrid_command(name="verify-setup", description="Définir le rôle attribué lors de la vérification.")
    @app_commands.describe(role="Le rôle à attribuer aux membres vérifiés")
    @checks.is_owner_or_admin()
    async def verify_setup(self, ctx: commands.Context, role: discord.Role):
        await self.bot.db.set_guild_config(ctx.guild.id, "verify_role", role.id)
        await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id, title='Rôle défini', description=f'Rôle de vérification défini sur {role.mention}.', kind='success')))

    @commands.hybrid_command(name="verify-panel", description="Poster le panneau de vérification dans ce salon.")
    @checks.is_owner_or_admin()
    async def verify_panel(self, ctx: commands.Context):
        e = await self._embed(ctx.guild.id, title="Vérification", description="Cliquez sur le bouton ci-dessous après avoir lu les règles du serveur pour obtenir l'accès complet.")
        await panels.envoyer(ctx, panels.avec_composants(panels.depuis_embed(e), VerifyView()))

    async def _panel_and_message(self, guild: discord.Guild, message_id: int):
        panel = await self.bot.db.fetchone(
            "SELECT * FROM reaction_role_panels WHERE guild_id = ? AND message_id = ?",
            (guild.id, message_id),
        )
        if not panel:
            return None, None
        channel = guild.get_channel(panel["channel_id"]) or self.bot.get_channel(panel["channel_id"])
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(panel["channel_id"])
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                return panel, None
        try:
            message = await channel.fetch_message(message_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return panel, None
        return panel, message

    async def _refresh_role_panel(self, guild: discord.Guild, panel, message: discord.Message):
        # La commande historique +reactionrole-add peut viser un message écrit par un
        # membre. Les réactions fonctionnent dessus, mais le bot ne doit pas tenter de
        # modifier un message qui ne lui appartient pas.
        if self.bot.user is None or message.author.id != self.bot.user.id:
            return
        rows = await self.bot.db.fetchall(
            "SELECT * FROM reaction_roles WHERE guild_id = ? AND message_id = ? ORDER BY rowid ASC",
            (guild.id, message.id),
        )
        description = panel["description"] or "Réagissez avec l'emoji correspondant pour recevoir ou retirer un rôle."
        lines = []
        for row in rows:
            role = guild.get_role(row["role_id"])
            role_text = role.mention if role else "Rôle supprimé"
            label = row["label"] or (role.name if role else "Indisponible")
            lines.append(f"{row['emoji']} **{label}** — {role_text}")
        listing = "\n".join(lines) if lines else "Aucun rôle n'est encore configuré."
        embed = await self._embed(
            guild.id,
            title=panel["title"],
            description=f"{description}\n\n**Rôles disponibles**\n{listing}"[:4096],
        )
        try:
            await message.edit(embed=embed)
        except (discord.Forbidden, discord.NotFound, discord.HTTPException):
            return

    async def _register_panel_if_needed(self, ctx: commands.Context, message: discord.Message):
        panel = await self.bot.db.fetchone(
            "SELECT * FROM reaction_role_panels WHERE guild_id = ? AND message_id = ?",
            (ctx.guild.id, message.id),
        )
        if panel:
            return panel
        title = message.embeds[0].title if message.embeds and message.embeds[0].title else "Choisissez vos rôles"
        await self.bot.db.execute(
            "INSERT INTO reaction_role_panels "
            "(guild_id, channel_id, message_id, title, description, created_by, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                ctx.guild.id,
                message.channel.id,
                message.id,
                title[:256],
                "Réagissez avec l'emoji correspondant pour recevoir ou retirer un rôle.",
                ctx.author.id,
                now(),
            ),
        )
        return await self.bot.db.fetchone(
            "SELECT * FROM reaction_role_panels WHERE guild_id = ? AND message_id = ?",
            (ctx.guild.id, message.id),
        )

    async def _add_reaction_role(
        self,
        ctx: commands.Context,
        message: discord.Message,
        emoji_text: str,
        role: discord.Role,
        label: str = "",
    ):
        role_error = _self_role_error(ctx.guild, role)
        if role_error:
            return await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id, title='Rôle refusé', description=role_error, kind='danger')))
        try:
            emoji_key, emoji_display, emoji = _emoji_parts(emoji_text)
        except ValueError:
            return await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id, title='Emoji invalide', description='Utilisez un emoji Unicode ou un emoji personnalisé du serveur.', kind='danger')))
        count_row = await self.bot.db.fetchone(
            "SELECT COUNT(*) AS total FROM reaction_roles WHERE guild_id = ? AND message_id = ?",
            (ctx.guild.id, message.id),
        )
        existing = await self.bot.db.fetchone(
            "SELECT rowid FROM reaction_roles WHERE guild_id = ? AND message_id = ? AND emoji_key = ?",
            (ctx.guild.id, message.id, emoji_key),
        )
        if not existing and count_row and count_row["total"] >= 20:
            return await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id, title='Limite atteinte', description='Un panneau Discord accepte au maximum 20 réactions différentes.', kind='danger')))
        try:
            await message.add_reaction(emoji)
        except (discord.Forbidden, discord.NotFound, discord.HTTPException) as exc:
            return await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id, title='Emoji refusé', description=f"Discord refuse cet emoji. Vérifiez qu'il appartient à un serveur accessible au bot et qu'il n'a pas été supprimé. (`{exc}`)", kind='danger')))
        panel = await self._register_panel_if_needed(ctx, message)
        await self.bot.db.execute(
            "DELETE FROM reaction_roles WHERE guild_id = ? AND message_id = ? AND "
            "(emoji_key = ? OR (emoji_key IS NULL AND emoji = ?))",
            (ctx.guild.id, message.id, emoji_key, emoji_display),
        )
        await self.bot.db.execute(
            "INSERT INTO reaction_roles "
            "(guild_id, channel_id, message_id, emoji, emoji_key, role_id, label, created_by) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                ctx.guild.id,
                message.channel.id,
                message.id,
                emoji_display,
                emoji_key,
                role.id,
                (label.strip() or role.name)[:100],
                ctx.author.id,
            ),
        )
        await self._refresh_role_panel(ctx.guild, panel, message)
        await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id, title='Rôle ajouté au panneau', description=f'{emoji_display} donnera ou retirera automatiquement {role.mention}.', kind='success')))

    @commands.group(name="rolepanel", aliases=["rolespanel", "role-menu"], invoke_without_command=True)
    @checks.is_owner_or_admin()
    async def rolepanel(self, ctx: commands.Context):
        """Crée un panneau public limité aux rôles de notification."""
        await self._create_self_role_panel(ctx, "Choisissez vos notifications")

    @rolepanel.command(name="create", aliases=["creer"])
    @checks.is_owner_or_admin()
    async def rolepanel_create(self, ctx: commands.Context, *, title: str = "Choisissez vos notifications"):
        await self._create_self_role_panel(ctx, title)

    @commands.command(name="rolepanel-refresh", aliases=["rolespanel-refresh"])
    @checks.is_owner_or_admin()
    async def rolepanel_refresh(self, ctx: commands.Context):
        """Actualise les panneaux après la création ou le renommage d'une notification."""
        panels = await self.bot.db.fetchall(
            "SELECT message_id FROM self_role_panels WHERE guild_id = ?",
            (ctx.guild.id,),
        )
        for panel in panels:
            await self._refresh_self_role_panel(ctx.guild, panel["message_id"])
        await ctx.channel.send("Panneaux de notifications actualisés.", delete_after=10)

    @rolepanel.command(name="add", aliases=["ajouter"])
    @checks.is_owner_or_admin()
    async def rolepanel_add(
        self,
        ctx: commands.Context,
        message_id: int,
        emoji: str,
        role: discord.Role,
        *,
        label: str = "",
    ):
        panel, message = await self._panel_and_message(ctx.guild, message_id)
        if not panel:
            return await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id, title='Panneau inconnu', description="Créez d'abord le panneau avec `+rolepanel create`.", kind='danger')))
        if message is None:
            return await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id, title='Message introuvable', description="Le message du panneau a été supprimé ou n'est plus accessible.", kind='danger')))
        await self._add_reaction_role(ctx, message, emoji, role, label)

    @rolepanel.command(name="remove", aliases=["retirer"])
    @checks.is_owner_or_admin()
    async def rolepanel_remove(self, ctx: commands.Context, message_id: int, emoji: str):
        try:
            emoji_key, emoji_display, parsed_emoji = _emoji_parts(emoji)
        except ValueError:
            return await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id, title='Emoji invalide', kind='danger')))
        panel, message = await self._panel_and_message(ctx.guild, message_id)
        if not panel:
            return await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id, title='Panneau inconnu', kind='danger')))
        cursor = await self.bot.db.execute(
            "DELETE FROM reaction_roles WHERE guild_id = ? AND message_id = ? AND "
            "(emoji_key = ? OR (emoji_key IS NULL AND emoji = ?))",
            (ctx.guild.id, message_id, emoji_key, emoji_display),
        )
        if cursor.rowcount < 1:
            return await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id, title='Association introuvable', kind='danger')))
        if message:
            try:
                await message.clear_reaction(parsed_emoji)
            except (discord.Forbidden, discord.NotFound, discord.HTTPException):
                pass
            await self._refresh_role_panel(ctx.guild, panel, message)
        await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id, title='Association retirée', kind='success')))

    @rolepanel.command(name="list", aliases=["liste"])
    @checks.is_owner_or_admin()
    async def rolepanel_list(self, ctx: commands.Context):
        panneaux = await self.bot.db.fetchall(
            "SELECT p.*, COUNT(r.message_id) AS role_count FROM reaction_role_panels p "
            "LEFT JOIN reaction_roles r ON r.guild_id = p.guild_id AND r.message_id = p.message_id "
            "WHERE p.guild_id = ? GROUP BY p.id ORDER BY p.id DESC",
            (ctx.guild.id,),
        )
        if not panneaux:
            return await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id, title='Aucun panneau configuré')))
        lines = [
            f"<#{panel['channel_id']}> — **{panel['title']}** — `{panel['message_id']}` — {panel['role_count']} rôle(s)"
            for panel in panneaux
        ]
        await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id, title='Panneaux de rôles', description='\n'.join(lines))))

    @rolepanel.command(name="delete", aliases=["supprimer"])
    @checks.is_owner_or_admin()
    async def rolepanel_delete(self, ctx: commands.Context, message_id: int):
        panel, message = await self._panel_and_message(ctx.guild, message_id)
        if not panel:
            return await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id, title='Panneau inconnu', kind='danger')))
        await self.bot.db.execute(
            "DELETE FROM reaction_roles WHERE guild_id = ? AND message_id = ?",
            (ctx.guild.id, message_id),
        )
        await self.bot.db.execute(
            "DELETE FROM reaction_role_panels WHERE guild_id = ? AND message_id = ?",
            (ctx.guild.id, message_id),
        )
        if message:
            try:
                await message.delete()
            except (discord.Forbidden, discord.NotFound, discord.HTTPException):
                pass
        await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id, title='Panneau supprimé', kind='success')))

    @commands.hybrid_command(name="reactionrole-add", description="Ajouter un rôle sur réaction à un message.")
    @app_commands.describe(message_id="L'identifiant du message", emoji="L'emoji à utiliser", role="Le rôle à attribuer")
    @checks.is_owner_or_admin()
    async def reactionrole_add(self, ctx: commands.Context, message_id: str, emoji: str, role: discord.Role):
        try:
            mid = int(message_id)
        except ValueError:
            return await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id, title='Identifiant invalide', description='Identifiant de message invalide.', kind='danger')))
        try:
            msg = await ctx.channel.fetch_message(mid)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id, title='Message introuvable', description='Message introuvable dans ce salon.', kind='danger')))
        await self._add_reaction_role(ctx, msg, emoji, role)

    @commands.hybrid_command(name="reactionrole-remove", description="Retirer une association rôle/réaction.", with_app_command=False)
    @app_commands.describe(message_id="L'identifiant du message", emoji="L'emoji concerné")
    @checks.is_owner_or_admin()
    async def reactionrole_remove(self, ctx: commands.Context, message_id: str, emoji: str):
        try:
            mid = int(message_id)
        except ValueError:
            return await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id, title='Identifiant invalide', description='Identifiant de message invalide.', kind='danger')))
        try:
            emoji_key, emoji_display, _ = _emoji_parts(emoji)
        except ValueError:
            return await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id, title='Emoji invalide', kind='danger')))
        await self.bot.db.execute(
            "DELETE FROM reaction_roles WHERE guild_id = ? AND message_id = ? AND "
            "(emoji_key = ? OR (emoji_key IS NULL AND emoji = ?))",
            (ctx.guild.id, mid, emoji_key, emoji_display),
        )
        await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id, title='Association retirée', kind='success')))

    @commands.hybrid_command(name="reactionrole-list", description="Lister les rôles sur réaction configurés.", with_app_command=False)
    @checks.is_owner_or_admin_for("configuration")
    async def reactionrole_list(self, ctx: commands.Context):
        rows = await self.bot.db.fetchall("SELECT * FROM reaction_roles WHERE guild_id = ?", (ctx.guild.id,))
        if not rows:
            return await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id, title='Aucune association', description='Aucun rôle sur réaction configuré.')))
        lines = []
        for r in rows:
            role = ctx.guild.get_role(r["role_id"])
            lines.append(f"{r['emoji']} → {role.mention if role else 'Rôle supprimé'} (msg `{r['message_id']}`)")
        await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id, title='Rôles sur réaction', description='\n'.join(lines))))

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if payload.member is None or payload.member.bot:
            return
        emoji_key = _payload_emoji_key(payload.emoji)
        row = await self.bot.db.fetchone(
            "SELECT * FROM reaction_roles WHERE guild_id = ? AND message_id = ? AND "
            "(emoji_key = ? OR (emoji_key IS NULL AND emoji = ?))",
            (payload.guild_id, payload.message_id, emoji_key, str(payload.emoji)),
        )
        if not row:
            return
        guild = self.bot.get_guild(payload.guild_id)
        role = guild.get_role(row["role_id"]) if guild else None
        if role:
            try:
                await payload.member.add_roles(role, reason="Rôle sur réaction")
            except (discord.Forbidden, discord.HTTPException):
                pass

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        if self.bot.user and payload.user_id == self.bot.user.id:
            return
        emoji_key = _payload_emoji_key(payload.emoji)
        row = await self.bot.db.fetchone(
            "SELECT * FROM reaction_roles WHERE guild_id = ? AND message_id = ? AND "
            "(emoji_key = ? OR (emoji_key IS NULL AND emoji = ?))",
            (payload.guild_id, payload.message_id, emoji_key, str(payload.emoji)),
        )
        if not row:
            return
        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return
        member = guild.get_member(payload.user_id)
        if member is None:
            try:
                member = await guild.fetch_member(payload.user_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                return
        if member.bot:
            return
        role = guild.get_role(row["role_id"])
        if member and role:
            try:
                await member.remove_roles(role, reason="Retrait rôle sur réaction")
            except (discord.Forbidden, discord.HTTPException):
                pass

    # Note : configurer le rôle automatique se fait via /setautorole (cog Configuration)
    # ou directement dans l'assistant /setup — pas besoin d'une commande en double ici.

    @commands.hybrid_command(name="giverole", aliases=["addrole"], description="Donner un rôle à un membre.")
    @app_commands.describe(membre="Le membre visé", role="Le rôle à donner")
    # AUTORISATION -> utils/access_matrix.py (matrice unique).
    # VALIDATION METIER -> le bot doit réellement posséder la permission Discord.
    @checks.action_validation(bot_permissions=("manage_roles",), target="role_target")
    async def giverole(self, ctx: commands.Context, membre: discord.Member, role: discord.Role):
        # check_hierarchy bloque toute action "sur soi-même" — pertinent pour une sanction
        # (on ne se bannit pas soi-même), mais pas pour un rôle : un membre autorisé à gérer
        # les rôles doit pouvoir se donner un rôle à lui-même (rôle couleur, self-service...).
        # On ne saute le contrôle QUE quand la cible est l'auteur ; toute autre cible reste
        # protégée par la hiérarchie normale.
        error = None
        if membre.id != ctx.author.id and isinstance(ctx.author, discord.Member):
            error = checks.check_hierarchy(ctx.author, membre)
        # VALIDATION METIER : le rôle lui-même est-il gérable ?
        if not error and isinstance(ctx.author, discord.Member):
            error = checks.check_role_target(ctx.author, role)
        if error and ctx.author.id != ctx.guild.owner_id:
            return await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id, title='Action refusée', description=error, kind='danger')))
        try:
            await membre.add_roles(role, reason=f"Ajouté par {ctx.author}")
        except discord.Forbidden:
            return await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id, title='Permission manquante', description="Je n'ai pas la permission d'attribuer ce rôle.", kind='danger')))
        await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id, title='Rôle attribué', description=f'Rôle {role.mention} donné à {membre.mention}.', kind='success')))

    @commands.hybrid_command(name="removerole", aliases=["delrole"], description="Retirer un rôle à un membre.")
    @app_commands.describe(membre="Le membre visé", role="Le rôle à retirer")
    # AUTORISATION -> utils/access_matrix.py (matrice unique).
    # VALIDATION METIER -> le bot doit réellement posséder la permission Discord.
    @checks.action_validation(bot_permissions=("manage_roles",), target="role_target")
    async def removerole(self, ctx: commands.Context, membre: discord.Member, role: discord.Role):
        # VALIDATION METIER : hiérarchie sur la cible puis sur le rôle visé.
        error = None
        if membre.id != ctx.author.id and isinstance(ctx.author, discord.Member):
            error = checks.check_hierarchy(ctx.author, membre)
        if not error and isinstance(ctx.author, discord.Member):
            error = checks.check_role_target(ctx.author, role)
        if error and ctx.author.id != ctx.guild.owner_id:
            return await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id, title='Action refusée', description=error, kind='danger')))
        try:
            await membre.remove_roles(role, reason=f"Retiré par {ctx.author}")
        except discord.Forbidden:
            return await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id, title='Permission manquante', description="Je n'ai pas la permission de retirer ce rôle.", kind='danger')))
        await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id, title='Rôle retiré', description=f'Rôle {role.mention} retiré à {membre.mention}.', kind='success')))

    @commands.hybrid_command(name="roleall", description="Donner un rôle à tous les membres du serveur.", with_app_command=False)
    @app_commands.describe(role="Le rôle à attribuer à tout le monde")
    @checks.is_owner_or_admin()
    async def roleall(self, ctx: commands.Context, role: discord.Role):
        # Sur un très gros serveur (ex: 200 000 membres), traiter les membres un par un,
        # en attendant chaque requête l'une après l'autre, prendrait des HEURES (chaque
        # aller-retour vers Discord coûte ~200-300ms). On traite donc les membres par
        # petits lots envoyés en concurrence : Discord limite toujours le débit global,
        # mais son limiteur interne (discord.py) répartit ces lots bien plus efficacement
        # qu'une file strictement séquentielle.
        BATCH_SIZE = 15
        progress_msg = await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id, title='Attribution en cours', description=f"⏳ Attribution du rôle {role.mention} à ~{ctx.guild.member_count} membres en cours. Sur un très gros serveur, ça peut prendre un moment — un message de progression s'affichera régulièrement, merci de patienter...")))
        count = 0
        failed = 0
        processed = 0

        async def apply_role(member: discord.Member):
            nonlocal count, failed
            if member.bot or role in member.roles:
                return
            try:
                await member.add_roles(role, reason=f"Attribution en masse par {ctx.author}")
                count += 1
            except discord.HTTPException:
                failed += 1

        batch = []
        async for member in ctx.guild.fetch_members(limit=None):
            batch.append(member)
            if len(batch) >= BATCH_SIZE:
                await asyncio.gather(*(apply_role(m) for m in batch))
                processed += len(batch)
                batch = []
                if processed % 2000 == 0:
                    try:
                        await panels.editer(progress_msg, panels.depuis_embed(await self._embed(ctx.guild.id, title='Progression', description=f"⏳ Progression : **{processed}/{ctx.guild.member_count}** membres traités, **{count}** rôle(s) attribué(s) jusqu'ici...")))
                    except discord.HTTPException:
                        pass
        if batch:
            await asyncio.gather(*(apply_role(m) for m in batch))

        result = await self._embed(ctx.guild.id, title="Attribution terminée", description=f"Rôle {role.mention} attribué à **{count}** membre(s).", kind="success")
        if failed:
            result.add_field(name="⚠️ Échecs", value=f"{failed} membre(s) n'ont pas pu recevoir le rôle (permissions insuffisantes).", inline=False)
        await panels.envoyer(ctx, panels.depuis_embed(result))

    @commands.hybrid_command(name="massrole", description="Ajouter ou retirer un rôle sur une liste de membres.", with_app_command=False)
    @app_commands.describe(role="Le rôle concerné", action="add ou remove", membres="Membres séparés par des espaces (mentions)")
    @app_commands.choices(action=[app_commands.Choice(name="Ajouter", value="add"), app_commands.Choice(name="Retirer", value="remove")])
    @checks.is_owner_or_admin()
    async def massrole(self, ctx: commands.Context, role: discord.Role, action: str, membres: commands.Greedy[discord.Member]):
        if not membres:
            return await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id, title='Membres manquants', description='Mentionnez au moins un membre.', kind='danger')))
        count = 0
        for m in membres:
            try:
                if action == "add":
                    await m.add_roles(role, reason=f"Massrole par {ctx.author}")
                else:
                    await m.remove_roles(role, reason=f"Massrole par {ctx.author}")
                count += 1
            except discord.Forbidden:
                pass
        verb = "ajouté" if action == "add" else "retiré"
        await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id, title='Massrole terminé', description=f'Rôle {role.mention} {verb} pour **{count}** membre(s).', kind='success')))


async def setup(bot: commands.Bot):
    await bot.add_cog(Verification(bot))
