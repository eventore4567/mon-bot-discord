"""SentriX V53 — sortie finale unifiée des logs et panneaux de choix.

Objectifs :
- toutes les cartes standard sont plus larges et gardent une hauteur cohérente ;
- vraies mentions Discord utilisateurs/rôles conservées, sans notification ;
- images visibles en bas de la carte ;
- surplus d'informations placé dans une pièce jointe texte native sous le log ;
- fichiers déjà présents restent sous la carte ;
- déduplication finale renforcée sans perdre le fallback en cas d'erreur ;
- menus privés Jeux/Langues/Couleurs/Notifications affichés sous un vrai grand panneau.
"""
from __future__ import annotations

import hashlib
import io
import logging
import re
import time
from typing import Any

import discord
from discord.ext import commands

from . import log_fixed_height_v50 as fixed_v50
from . import log_preferred_style_v30 as v30
from . import log_premium_v28 as v28
from . import log_rectangle_v25 as v25
from . import premium_logs_v2

logger = logging.getLogger("bot.log-output-polish-v53")
_INSTALLED = False

# Le premier essai V52 ajoutait 7 em-spaces. V53 en ajoute encore 14 sans créer de ligne
# supplémentaire : la carte gagne nettement en présence sur desktop, mais reste responsive.
EXTRA_WIDTH_EM_SPACES = 14
FINAL_DEDUPE_TTL = 20.0
OVERFLOW_MIN_TOTAL = 520
OVERFLOW_FIELD_LIMIT = 2
OVERFLOW_DESCRIPTION_LIMIT = 125

_RECENT: dict[str, float] = {}
_INFLIGHT: set[str] = set()

_IMAGE_RE = re.compile(r"https?://[^\s<>]+", re.IGNORECASE)
_IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")


def _norm(value: object) -> str:
    return v30._norm(str(value or ""))


def _embed_digest(embed: discord.Embed) -> str:
    body = [str(embed.title or ""), str(embed.description or "")]
    for field in embed.fields:
        body.append(f"{field.name}:{field.value}")
    image = getattr(getattr(embed, "image", None), "url", None)
    if image:
        body.append(str(image))
    raw = "|".join(body)
    return hashlib.sha1(raw.encode("utf-8", "ignore")).hexdigest()[:24]


def _is_image_url(url: str) -> bool:
    low = str(url or "").split("?", 1)[0].casefold()
    if low.endswith(_IMAGE_EXTENSIONS):
        return True
    return (
        "cdn.discordapp.com/attachments/" in low
        or "media.discordapp.net/attachments/" in low
    )


def _image_urls(embed: discord.Embed) -> list[str]:
    result: list[str] = []

    def add(value: object) -> None:
        url = str(value or "").strip().rstrip(".,)")
        if not url or url in result or not _is_image_url(url):
            return
        result.append(url)

    image = getattr(getattr(embed, "image", None), "url", None)
    if image:
        add(image)

    for field in embed.fields:
        name = _norm(field.name)
        if not any(token in name for token in ("piece jointe", "attachment", "image", "fichier", "media")):
            continue
        for match in _IMAGE_RE.findall(str(field.value or "")):
            add(match)
            if len(result) >= 4:
                return result
    return result[:4]


def _restore_mentions(guild: discord.Guild, source: discord.Embed) -> discord.Embed:
    """Conserve de vraies mentions de rôles dans toute la carte sans autoriser de ping."""
    embed = source.copy()

    def clean(value: object) -> str:
        text = v30._restore_role_mentions(guild, str(value or ""))
        return text.replace("@everyone", "＠everyone").replace("@here", "＠here")

    if embed.title:
        embed.title = clean(embed.title)[:256]
    if embed.description:
        embed.description = clean(embed.description)[:4096]

    for index, field in enumerate(list(embed.fields)):
        name = str(field.name or "")
        value = clean(field.value)
        normalized = _norm(name)

        # Si un champ lié à un rôle ne contient qu'un ID ou un texte avec cet ID,
        # on rajoute la vraie mention du rôle. Discord l'affichera comme une pastille,
        # mais AllowedMentions.none() empêchera toute notification.
        if "role" in normalized and "<@&" not in value:
            role_id = v28._first_id(value)
            role = guild.get_role(role_id) if role_id else None
            if role is not None:
                stripped = re.sub(r"[`*\s]", "", value)
                if stripped == str(role.id):
                    value = f"{role.mention} · `{role.id}`"
                elif role.mention not in value:
                    value = f"{role.mention} · {value}"

        embed.set_field_at(index, name=name[:256], value=value[:1024], inline=False)
    return embed


def _role_target_value(embed: discord.Embed) -> str | None:
    # Priorité à une vraie mention déjà présente.
    for field in embed.fields:
        if "role" not in _norm(field.name):
            continue
        value = str(field.value or "")
        match = re.search(r"<@&(\d{15,22})>", value)
        if match:
            return f"<@&{match.group(1)}>"
        role_id = v28._first_id(value)
        if role_id:
            return f"<@&{role_id}>"

    title = _norm(embed.title)
    if "role" in title:
        target_id = v25._target_id(embed)
        if target_id:
            return f"<@&{target_id}>"
    return None


def _overflow_payload(guild: discord.Guild, log_type: str, embed: discord.Embed) -> tuple[str, bytes] | None:
    """Crée le bloc noir natif Discord seulement quand le contenu dépasse la carte."""
    useful_fields: list[tuple[str, str]] = []
    for field in embed.fields:
        name = str(field.name or "Information").strip() or "Information"
        if v30._is_id_field(name):
            continue
        value = v30._restore_role_mentions(guild, str(field.value or "").strip())
        if value:
            useful_fields.append((name, value))

    description = str(embed.description or "").strip()
    total = len(description) + sum(len(name) + len(value) for name, value in useful_fields)
    needs_overflow = (
        len(description) > OVERFLOW_DESCRIPTION_LIMIT
        or len(useful_fields) > OVERFLOW_FIELD_LIMIT
        or any(len(value) > 150 for _name, value in useful_fields)
        or total > OVERFLOW_MIN_TOTAL
    )
    if not needs_overflow:
        return None

    lines = [
        "SENTRIX — DÉTAILS COMPLETS DU JOURNAL",
        f"Serveur : {guild.name} ({guild.id})",
        f"Catégorie : {log_type}",
        f"Titre : {embed.title or 'Journal SentriX'}",
        "",
    ]
    if description:
        lines.extend(["DESCRIPTION", description, ""])
    if useful_fields:
        lines.append("INFORMATIONS")
        for name, value in useful_fields:
            lines.extend([f"[{name}]", value, ""])

    image_urls = _image_urls(embed)
    if image_urls:
        lines.append("IMAGES / MÉDIAS")
        lines.extend(image_urls)
        lines.append("")

    payload = "\n".join(lines).strip().encode("utf-8", "replace")
    filename = f"sentrix-details-{re.sub(r'[^a-z0-9-]+', '-', str(log_type).casefold())}-{int(time.time())}.txt"
    return filename[:120], payload


def _channel_log_type(channel: discord.TextChannel, embed: discord.Embed | None = None) -> str:
    sample = f"{channel.name} {getattr(embed, 'title', '') or ''}".casefold()
    mapping = (
        (("ticket",), "tickets"),
        (("message",), "messages"),
        (("membre", "member"), "members"),
        (("role", "rôle"), "roles"),
        (("vocal", "voice"), "voice"),
        (("moderation", "modération", "sanction"), "moderation"),
        (("anti-raid", "raid"), "raid"),
        (("anti-spam", "spam"), "spam"),
        (("dossier", "case"), "cases"),
        (("salon", "channel", "serveur"), "server"),
        (("security", "sécurité", "automod", "protect"), "automod"),
        (("niveau", "level"), "levels"),
        (("economie", "économie", "economy"), "economy"),
        (("jeu", "game"), "games"),
        (("system", "système"), "system"),
    )
    for tokens, result in mapping:
        if any(token in sample for token in tokens):
            return result
    return "system"


def _looks_like_log(channel: discord.TextChannel, embed: discord.Embed | None, view: Any) -> bool:
    if view is not None:
        cls = view.__class__
        if (
            getattr(view, "_sentrix_is_log_layout", False)
            or getattr(cls, "_sentrix_log_layout", False)
        ):
            return True
    if embed is None:
        return False
    name = channel.name.casefold()
    if "log" in name or "journal" in name:
        return True
    sample = " ".join(
        [str(embed.title or ""), str(embed.description or ""), str(getattr(embed.footer, "text", "") or "")]
        + [str(field.name) for field in embed.fields]
    ).casefold()
    return "sentrix" in sample and any(token in sample for token in ("log", "journal", "ticket", "audit"))


def _is_transcript_file(file: discord.File | None) -> bool:
    filename = str(getattr(file, "filename", "") or "").casefold()
    return bool(filename and "transcript" in filename)


def _output_key(channel: discord.TextChannel, embed: discord.Embed | None, view: Any) -> str | None:
    if view is not None:
        fp = getattr(view, "_sentrix_log_fingerprint", None)
        digest = getattr(view, "_sentrix_v53_digest", None)
        if fp and digest:
            return f"{channel.id}:{fp}:{digest}"
        if fp:
            return f"{channel.id}:{fp}"
    if embed is not None:
        return f"{channel.id}:embed:{_embed_digest(embed)}"
    return None


def _prune_recent() -> None:
    now = time.monotonic()
    for key, expires in list(_RECENT.items())[:4000]:
        if expires <= now:
            _RECENT.pop(key, None)


class UnifiedWideLogV53(fixed_v50.FixedHeightLogV50):
    _sentrix_log_layout = True
    _sentrix_rectangle_v25 = True
    _sentrix_reference_v26 = True
    _sentrix_unified_v27 = True
    _sentrix_premium_v28 = True
    _sentrix_fixed_height_v50 = True
    _sentrix_wide_v53 = True

    def __init__(
        self,
        bot: commands.Bot,
        guild: discord.Guild,
        log_type: str,
        embed: discord.Embed,
        buttons: list[tuple[str, int]],
    ):
        normalized = _restore_mentions(guild, embed)
        super().__init__(bot, guild, log_type, normalized, buttons)
        self._sentrix_v53_digest = _embed_digest(normalized)
        self._sentrix_overflow = _overflow_payload(guild, str(log_type), normalized)

        urls = _image_urls(normalized)
        if urls and self.children:
            container = self.children[0]
            try:
                gallery = discord.ui.MediaGallery()
                for url in urls[:4]:
                    gallery.add_item(media=url, description="Pièce jointe du journal SentriX")
                container.add_item(discord.ui.Separator())
                container.add_item(gallery)
            except Exception:
                logger.debug("V53 : galerie image indisponible pour %s.", guild.id, exc_info=True)


def _patch_width_and_role_target() -> None:
    if not getattr(fixed_v50, "_sentrix_wider_v53", False):
        previous_description = fixed_v50._description

        def wider_description(embed: discord.Embed) -> str:
            return previous_description(embed) + ("\u2003" * EXTRA_WIDTH_EM_SPACES)

        fixed_v50._description = wider_description
        fixed_v50._sentrix_wider_v53 = True

    if not getattr(fixed_v50, "_sentrix_role_target_v53", False):
        previous_target = fixed_v50._target_value

        def role_aware_target(embed: discord.Embed) -> str:
            role_value = _role_target_value(embed)
            return role_value or previous_target(embed)

        fixed_v50._target_value = role_aware_target
        fixed_v50._sentrix_role_target_v53 = True


def _patch_ticket_width() -> None:
    try:
        from . import ticket_transcript_logs_v34 as ticket_v34
    except Exception:
        return
    original = ticket_v34.TicketClosureLogView
    if getattr(original, "_sentrix_wide_v53", False):
        return

    class WideTicketClosureLogV53(original):
        _sentrix_wide_v53 = True
        _sentrix_log_layout = True
        _sentrix_rectangle_v25 = True
        _sentrix_reference_v26 = True

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            if not self.children:
                return
            try:
                container = self.children[0]
                # Une seule ligne discrète force la largeur du ticket/transcript au niveau
                # des autres logs, sans modifier son contenu métier.
                container.add_item(discord.ui.TextDisplay("-# " + ("\u2003" * 22)))
            except Exception:
                pass

    ticket_v34.TicketClosureLogView = WideTicketClosureLogV53


def _patch_role_panels() -> None:
    """Le grand texte reste visible ; les éléments à choisir sont toujours en dessous."""
    try:
        from . import server_choice_roles
        from . import rolepanel_notifications
    except Exception:
        logger.debug("V53 : modules rolepanel pas encore importables.", exc_info=True)
        return

    if not getattr(server_choice_roles.ServerSelfRoleView, "_sentrix_bottom_choices_v53", False):
        async def open_group(self, interaction: discord.Interaction, group_key: str):
            if interaction.guild is None or not isinstance(interaction.user, discord.Member):
                return await interaction.response.send_message("Serveur introuvable.", ephemeral=True)
            label, _names = server_choice_roles.ROLE_GROUPS[group_key]
            member = interaction.user
            try:
                member = await interaction.guild.fetch_member(interaction.user.id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass

            icon = {"games": "🎮", "languages": "🌍", "colors": "🎨"}.get(group_key, "⚙️")
            embed = discord.Embed(
                title=f"{icon} {label}",
                description=(
                    "Choisis uniquement ce que tu veux ajouter ou retirer.\n\n"
                    "Le panneau principal reste inchangé et **tes choix sont privés**. "
                    "Les menus de sélection sont placés juste en dessous de ce texte."
                ),
                colour=0x5865F2,
            )
            embed.set_footer(text=f"SentriX • {interaction.guild.name}")
            await interaction.response.send_message(
                embed=embed,
                view=server_choice_roles.GroupPrivateView(interaction.guild, member, group_key),
                ephemeral=True,
            )

        server_choice_roles.ServerSelfRoleView._open = open_group
        server_choice_roles.ServerSelfRoleView._sentrix_bottom_choices_v53 = True

    if not getattr(rolepanel_notifications.NotificationRoleView, "_sentrix_bottom_choices_v53", False):
        async def open_notifications(self, interaction: discord.Interaction, mode: str) -> None:
            if interaction.guild is None or not isinstance(interaction.user, discord.Member):
                if not interaction.response.is_done():
                    await interaction.response.send_message("Serveur introuvable.", ephemeral=True)
                return

            await interaction.response.defer(ephemeral=True, thinking=True)
            role_ids = self._resolved_role_ids(interaction.guild)
            if not role_ids:
                return await interaction.edit_original_response(
                    content="Aucun rôle de notification n'est disponible sur ce serveur.",
                    embed=None,
                    view=None,
                )

            title = "🔔 Ajouter des notifications" if mode == "add" else "🔕 Retirer des notifications"
            description = (
                "Sélectionne les notifications que tu veux recevoir. Les rôles déjà pris sont masqués."
                if mode == "add"
                else "Sélectionne les notifications à retirer. Seuls les rôles que tu possèdes sont proposés."
            )
            embed = discord.Embed(
                title=title,
                description=(
                    description
                    + "\n\nLe grand panneau reste visible ; **le menu de choix est placé en dessous**."
                ),
                colour=0x5865F2,
            )
            embed.set_footer(text=f"SentriX • {interaction.guild.name}")
            await interaction.edit_original_response(
                content=None,
                embed=embed,
                view=rolepanel_notifications.PersonalNotificationView(
                    interaction.guild,
                    interaction.user,
                    role_ids,
                    mode=mode,
                ),
            )

        rolepanel_notifications.NotificationRoleView._open = open_notifications
        rolepanel_notifications.NotificationRoleView._sentrix_bottom_choices_v53 = True


def install(bot: commands.Bot, extension_name: str = "") -> None:
    del extension_name
    global _INSTALLED

    _patch_width_and_role_target()
    _patch_ticket_width()
    _patch_role_panels()
    premium_logs_v2.PremiumLogLayout = UnifiedWideLogV53

    if _INSTALLED:
        return

    previous_send = discord.TextChannel.send
    if getattr(previous_send, "_sentrix_output_polish_v53", False):
        _INSTALLED = True
        return

    async def send_final(self: discord.TextChannel, *args, **kwargs):
        embed = kwargs.get("embed")
        if embed is None:
            for arg in args:
                if isinstance(arg, discord.Embed):
                    embed = arg
                    break
        view = kwargs.get("view")
        file = kwargs.get("file")
        is_log = _looks_like_log(self, embed if isinstance(embed, discord.Embed) else None, view)

        if not is_log:
            return await previous_send(self, *args, **kwargs)

        kwargs["allowed_mentions"] = discord.AllowedMentions.none()

        # Tout fichier de log non-transcript garde la pièce jointe native en bas mais reçoit
        # la même grande carte Components V2. Les transcripts restent gérés par V34.
        if (
            isinstance(embed, discord.Embed)
            and isinstance(file, discord.File)
            and not _is_transcript_file(file)
            and view is None
        ):
            log_type = _channel_log_type(self, embed)
            normalized = _restore_mentions(self.guild, embed)
            try:
                buttons = v30._button_items(self.guild, log_type, normalized)
            except Exception:
                buttons = []
            kwargs.pop("embed", None)
            kwargs["view"] = UnifiedWideLogV53(bot, self.guild, log_type, normalized, buttons)
            view = kwargs["view"]
            embed = None

        # Si la carte est standard et qu'il y a trop d'informations, la partie complète
        # apparaît comme le bloc noir .txt sous la carte, exactement après le grand texte.
        if view is not None and not kwargs.get("file") and not kwargs.get("files"):
            overflow = getattr(view, "_sentrix_overflow", None)
            if overflow:
                filename, payload = overflow
                kwargs["file"] = discord.File(io.BytesIO(payload), filename=filename)

        key = _output_key(self, embed if isinstance(embed, discord.Embed) else None, view)
        if key:
            _prune_recent()
            now = time.monotonic()
            if key in _INFLIGHT or _RECENT.get(key, 0.0) > now:
                logger.debug("V53 : doublon final bloqué dans #%s (%s).", self.name, key)
                return None
            _INFLIGHT.add(key)

        try:
            result = await previous_send(self, *args, **kwargs)
        except Exception:
            if key:
                _INFLIGHT.discard(key)
            raise
        else:
            if key:
                _INFLIGHT.discard(key)
                if result is not None:
                    _RECENT[key] = time.monotonic() + FINAL_DEDUPE_TTL
            return result

    send_final._sentrix_output_polish_v53 = True
    send_final._sentrix_original = previous_send
    discord.TextChannel.send = send_final

    _INSTALLED = True
    logger.info(
        "V53 logs : largeur renforcée, images/fichiers dessous, overflow .txt, mentions réelles sans ping, déduplication finale."
    )


__all__ = ["install", "UnifiedWideLogV53"]
