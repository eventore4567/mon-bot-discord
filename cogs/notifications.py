"""Notifications sociales automatiques et accueil personnalisable SentriX."""

import asyncio
import logging
import re
import time
from urllib.parse import urlparse, urlunparse

import discord
from discord.ext import commands, tasks

from utils import checks, embeds
from utils import sentrix_emojis as sxemoji
from utils import sentrix_panels as panels


logger = logging.getLogger("bot.notifications")
IMAGE_FLAG_RE = re.compile(r"(?:^|\s)--image\s+(https://\S+)", re.IGNORECASE)
SUPPORTED_SOCIAL_DOMAINS = (
    "youtube.com", "youtu.be", "tiktok.com", "twitch.tv", "instagram.com",
    "x.com", "twitter.com", "facebook.com", "dailymotion.com", "vimeo.com",
    "kick.com",
)


def _valid_https_url(value: str) -> bool:
    try:
        parsed = urlparse(value.strip())
    except (TypeError, ValueError):
        return False
    return parsed.scheme == "https" and bool(parsed.hostname)


def _is_supported_social_url(value: str) -> bool:
    if not _valid_https_url(value):
        return False
    host = (urlparse(value).hostname or "").lower().removeprefix("www.")
    return any(host == domain or host.endswith(f".{domain}") for domain in SUPPORTED_SOCIAL_DOMAINS)


def _platform_details(url: str) -> tuple[str, discord.Color]:
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    if host in {"youtube.com", "youtu.be", "m.youtube.com"} or host.endswith(".youtube.com"):
        return "YouTube", discord.Color.red()
    if host == "tiktok.com" or host.endswith(".tiktok.com"):
        return "TikTok", discord.Color.from_rgb(25, 25, 30)
    if host == "twitch.tv" or host.endswith(".twitch.tv"):
        return "Twitch", discord.Color.purple()
    if host == "instagram.com" or host.endswith(".instagram.com"):
        return "Instagram", discord.Color.magenta()
    if host in {"x.com", "twitter.com"} or host.endswith(".twitter.com"):
        return "X", discord.Color.from_rgb(35, 35, 40)
    return host or "Réseau social", discord.Color.blurple()


def _normalize_source_url(url: str) -> str:
    """YouTube renvoie mieux les dernières vidéos sur l'onglet /videos."""
    parsed = urlparse(url.strip())
    host = (parsed.hostname or "").lower().removeprefix("www.")
    path = parsed.path.rstrip("/")
    if (
        (host == "youtube.com" or host.endswith(".youtube.com"))
        and path
        and not any(part in path for part in ("/watch", "/shorts/", "/live/", "/playlist"))
        and not path.endswith(("/videos", "/shorts", "/streams"))
    ):
        path += "/videos"
    return urlunparse((parsed.scheme, parsed.netloc, path or parsed.path, "", parsed.query, ""))


def _attachment_image(ctx: commands.Context) -> str | None:
    attachments = getattr(getattr(ctx, "message", None), "attachments", []) or []
    if not attachments:
        return None
    attachment = attachments[0]
    content_type = (attachment.content_type or "").lower()
    filename = attachment.filename.lower()
    if content_type.startswith("image/") or filename.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif")):
        return attachment.url
    return None


def _extract_image_flag(text: str) -> tuple[str, str | None]:
    match = IMAGE_FLAG_RE.search(text or "")
    if not match:
        return (text or "").strip(), None
    image_url = match.group(1).rstrip(">)]}")
    cleaned = IMAGE_FLAG_RE.sub("", text, count=1).strip()
    return cleaned, image_url


def _item_url(platform: str, source_url: str, item: dict) -> str:
    candidate = item.get("webpage_url") or item.get("original_url") or item.get("url")
    if isinstance(candidate, str) and candidate.startswith("http"):
        return candidate
    item_id = str(item.get("id") or "")
    if platform == "YouTube" and item_id:
        return f"https://www.youtube.com/watch?v={item_id}"
    if platform == "Twitch" and item_id:
        return f"https://www.twitch.tv/videos/{item_id}"
    return source_url


def _extract_latest_sync(source_url: str) -> dict | None:
    """Extraction bloquante isolée dans asyncio.to_thread par l'appelant."""
    import yt_dlp

    options = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": "in_playlist",
        "playlistend": 3,
        "ignoreerrors": True,
        "socket_timeout": 12,
    }
    with yt_dlp.YoutubeDL(options) as downloader:
        info = downloader.extract_info(source_url, download=False)
    if not info:
        return None
    entries = info.get("entries")
    if entries:
        for entry in entries:
            if entry and entry.get("id"):
                return entry
        return None
    return info if info.get("id") else None


async def _extract_latest(source_url: str) -> dict | None:
    return await asyncio.wait_for(
        asyncio.to_thread(_extract_latest_sync, source_url),
        timeout=25,
    )


def _extract_details_sync(item_url: str) -> dict | None:
    """Charge les métadonnées complètes UNIQUEMENT pour une nouvelle publication.

    Le scan périodique reste léger grâce à extract_flat. Quand l'identifiant change,
    on effectue alors un second passage ciblé afin d'obtenir la vraie miniature,
    le vrai titre et l'URL canonique. TikTok est précisément l'une des plateformes
    dont les entrées plates omettent souvent la miniature.
    """
    import yt_dlp

    options = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "ignoreerrors": True,
        "socket_timeout": 12,
    }
    with yt_dlp.YoutubeDL(options) as downloader:
        info = downloader.extract_info(item_url, download=False)
    return info if isinstance(info, dict) else None


async def _extract_details(item_url: str) -> dict | None:
    return await asyncio.wait_for(
        asyncio.to_thread(_extract_details_sync, item_url),
        timeout=20,
    )


def _best_thumbnail(item: dict, custom_url: str | None = None) -> str | None:
    """Retourne une image exploitable, sans laisser une URL vide casser la carte."""
    candidates = [
        custom_url,
        item.get("thumbnail"),
    ]
    thumbnails = item.get("thumbnails") or []
    if isinstance(thumbnails, list):
        for thumb in reversed(thumbnails):
            if isinstance(thumb, dict):
                candidates.append(thumb.get("url"))
    for candidate in candidates:
        if isinstance(candidate, str) and _valid_https_url(candidate):
            return candidate
    return None


class SocialNotificationPanel(discord.ui.LayoutView):
    """Carte sociale premium sans embed, bannière, liseré latéral ni signature lourde."""

    def __init__(
        self,
        *,
        platform: str,
        title: str,
        description: str,
        link: str,
        image_url: str | None,
    ):
        super().__init__(timeout=None)
        container = discord.ui.Container()

        icon = sxemoji.emoji("video")
        heading = f"{icon} {title}".strip() if icon else title
        container.add_item(discord.ui.TextDisplay(f"## {heading[:220]}"))

        body = str(description or "").strip()
        if body:
            container.add_item(discord.ui.TextDisplay(body[:900]))

        if image_url:
            try:
                gallery = discord.ui.MediaGallery()
                gallery.add_item(media=image_url)
                container.add_item(gallery)
            except Exception:
                logger.debug("Miniature sociale refusée : %s", image_url, exc_info=True)

        row = discord.ui.ActionRow()
        row.add_item(
            discord.ui.Button(
                label=f"Voir sur {platform}"[:80],
                url=link,
                emoji=sxemoji.partiel("video"),
            )
        )
        container.add_item(row)
        container.add_item(
            discord.ui.TextDisplay(f"-# SentriX · {platform} · publication automatique")
        )
        self.add_item(container)


class Notifications(commands.Cog, name="Notifications"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.social_monitor.start()

    def cog_unload(self):
        self.social_monitor.cancel()

    @tasks.loop(minutes=5)
    async def social_monitor(self):
        rows = await self.bot.db.fetchall(
            "SELECT * FROM social_notifications WHERE enabled = 1 ORDER BY id ASC"
        )
        semaphore = asyncio.Semaphore(3)

        async def check(row):
            async with semaphore:
                await self._check_subscription(row)

        await asyncio.gather(*(check(row) for row in rows), return_exceptions=True)

    @social_monitor.before_loop
    async def before_social_monitor(self):
        await self.bot.wait_until_ready()

    @social_monitor.error
    async def social_monitor_error(self, error: Exception):
        logger.error(
            "Erreur du moniteur de réseaux sociaux",
            exc_info=(type(error), error, error.__traceback__),
        )

    async def _check_subscription(self, row):
        guild = self.bot.get_guild(row["guild_id"])
        if guild is None:
            return
        channel = guild.get_channel(row["discord_channel_id"])
        role = guild.get_role(row["role_id"])
        if channel is None or role is None:
            await self.bot.db.execute(
                "UPDATE social_notifications SET enabled = 0 WHERE id = ?",
                (row["id"],),
            )
            return

        try:
            item = await _extract_latest(row["source_url"])
        except Exception:
            logger.warning("Lecture impossible de l'abonnement social %s", row["id"], exc_info=True)
            return
        if not item:
            return

        item_id = str(item.get("id") or "")
        if not item_id:
            return
        if not row["last_item_id"]:
            await self._update_last_item(row["id"], item_id, row["source_url"])
            return
        if item_id == str(row["last_item_id"]):
            return

        platform = row["platform"]
        link = _item_url(platform, row["source_url"], item)

        # Les entrées "plates" sont suffisantes pour détecter une nouveauté mais
        # pas pour l'afficher joliment (TikTok n'y expose souvent aucune image).
        # On enrichit seulement la NOUVELLE publication afin de ne pas alourdir
        # le scan de cinq minutes.
        try:
            details = await _extract_details(link)
        except Exception:
            details = None
            logger.debug(
                "Métadonnées détaillées indisponibles pour l'abonnement social %s",
                row["id"],
                exc_info=True,
            )
        if details:
            merged = dict(item)
            merged.update({k: v for k, v in details.items() if v not in (None, "", [], {})})
            item = merged
            link = _item_url(platform, row["source_url"], item)

        title = (item.get("title") or f"Nouvelle publication sur {platform}")[:220]
        description = row["custom_text"] or "Une nouvelle publication vient d’être publiée."
        image_url = _best_thumbnail(item, row["image_url"])
        notification = SocialNotificationPanel(
            platform=platform,
            title=title,
            description=description,
            link=link,
            image_url=image_url,
        )

        try:
            # Le ping reste réel mais ne pollue plus la carte : le petit message
            # de mention disparaît automatiquement, seule l'interface premium reste.
            await channel.send(
                content=role.mention,
                allowed_mentions=discord.AllowedMentions(
                    everyone=False,
                    users=False,
                    roles=[role],
                    replied_user=False,
                ),
                delete_after=3,
            )
            await channel.send(view=notification)
        except discord.HTTPException:
            # Ne jamais marquer la publication comme traitée si Discord n'a pas pu
            # l'envoyer : le prochain passage pourra la retenter au lieu de la perdre.
            logger.warning("Envoi impossible pour l'abonnement social %s", row["id"], exc_info=True)
            return

        await self._update_last_item(row["id"], item_id, link)

    async def _update_last_item(self, subscription_id: int, item_id: str, item_url: str):
        await self.bot.db.execute(
            "UPDATE social_notifications SET last_item_id = ?, last_item_url = ?, last_checked_at = ? WHERE id = ?",
            (item_id, item_url, int(time.time()), subscription_id),
        )

    @commands.hybrid_command(
        name="notifs-ping",
        aliases=["notif-ping", "notfis-ping"],
        description="Surveiller une chaîne sociale et ping un rôle lors d'une nouveauté.",
        with_app_command=False,
    )
    @checks.is_owner_or_admin_for("configuration")
    async def notifs_ping(
        self,
        ctx: commands.Context,
        role: discord.Role,
        lien: str,
        *,
        texte: str = "",
    ):
        """+notifs-ping @Rôle lien_de_chaine [texte] [--image URL]."""
        if ctx.guild is None:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Cette commande doit être utilisée dans un serveur.')))
        if role.is_default():
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Choisissez un rôle précis : @everyone est interdit.')))
        if not _is_supported_social_url(lien):
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error("Utilisez le lien HTTPS public d'une chaîne YouTube, TikTok, Twitch, Instagram, X, Facebook, Dailymotion, Vimeo ou Kick.")))

        me = ctx.guild.me
        permissions = ctx.channel.permissions_for(me)
        if not role.mentionable and not permissions.mention_everyone:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error(f"Le rôle {role.mention} n'est pas mentionnable. Rendez-le mentionnable ou autorisez SentriX à mentionner les rôles.")))

        texte, image_flag = _extract_image_flag(texte)
        image_url = _attachment_image(ctx) or image_flag
        if image_url and not _valid_https_url(image_url):
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error("L'image doit être jointe au message ou utiliser une URL HTTPS.")))
        if len(texte) > 600:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Le texte de notification est limité à 600 caractères.')))

        source_url = _normalize_source_url(lien)
        platform, _ = _platform_details(source_url)
        status = await panels.envoyer(ctx, panels.depuis_embed(embeds.info(f'Vérification de la chaîne {platform}…')))
        try:
            latest = await _extract_latest(source_url)
        except asyncio.TimeoutError:
            return await panels.editer(status, panels.depuis_embed(embeds.error('La plateforme met trop de temps à répondre. Réessayez dans quelques instants.')))
        except Exception:
            logger.warning("Impossible de configurer la source sociale %s", source_url, exc_info=True)
            return await panels.editer(status, panels.depuis_embed(embeds.error('Impossible de lire cette chaîne. Vérifiez que le lien est public et complet.')))
        if not latest or not latest.get("id"):
            return await panels.editer(status, panels.depuis_embed(embeds.error("Aucune publication publique n'a été trouvée sur cette chaîne.")))

        latest_id = str(latest["id"])
        latest_url = _item_url(platform, source_url, latest)
        await self.bot.db.execute(
            "INSERT INTO social_notifications "
            "(guild_id, source_url, platform, discord_channel_id, role_id, custom_text, image_url, "
            "last_item_id, last_item_url, enabled, created_at, last_checked_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?) "
            "ON CONFLICT(guild_id, source_url) DO UPDATE SET "
            "platform = excluded.platform, discord_channel_id = excluded.discord_channel_id, "
            "role_id = excluded.role_id, custom_text = excluded.custom_text, image_url = excluded.image_url, "
            "last_item_id = excluded.last_item_id, last_item_url = excluded.last_item_url, "
            "enabled = 1, last_checked_at = excluded.last_checked_at",
            (
                ctx.guild.id, source_url, platform, ctx.channel.id, role.id, texte or None,
                image_url, latest_id, latest_url, int(time.time()), int(time.time()),
            ),
        )
        await panels.editer(status, panels.depuis_embed(embeds.success(f'Surveillance **{platform}** activée.\n**Rôle pingé :** {role.mention}\n**Salon des notifications :** {ctx.channel.mention}\n**Vérification :** toutes les 5 minutes\n' + ('**Image personnalisée :** activée' if image_url else '**Image personnalisée :** automatique ou aucune'))))

    @commands.hybrid_command(name="notifs-list", description="Afficher les chaînes sociales surveillées.", with_app_command=False)
    @checks.is_owner_or_admin_for("configuration")
    async def notifs_list(self, ctx: commands.Context):
        if ctx.guild is None:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Cette commande doit être utilisée dans un serveur.')))
        rows = await self.bot.db.fetchall(
            "SELECT * FROM social_notifications WHERE guild_id = ? ORDER BY id ASC",
            (ctx.guild.id,),
        )
        if not rows:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.info("Aucune chaîne sociale n'est surveillée sur ce serveur.")))
        lines = [
            f"**#{row['id']} • {row['platform']}** — <#{row['discord_channel_id']}> — <@&{row['role_id']}> — "
            f"{'active' if row['enabled'] else 'inactive'}\n{row['source_url']}"
            for row in rows
        ]
        await panels.envoyer(ctx, panels.depuis_embed(embeds.info('\n\n'.join(lines)[:4000], title='Notifications automatiques')))

    @commands.hybrid_command(name="notifs-remove", description="Supprimer une surveillance sociale.", with_app_command=False)
    @checks.is_owner_or_admin_for("configuration")
    async def notifs_remove(self, ctx: commands.Context, identifiant: int):
        if ctx.guild is None:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Cette commande doit être utilisée dans un serveur.')))
        row = await self.bot.db.fetchone(
            "SELECT id FROM social_notifications WHERE id = ? AND guild_id = ?",
            (identifiant, ctx.guild.id),
        )
        if not row:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Surveillance introuvable. Utilisez `+notifs-list`.')))
        await self.bot.db.execute(
            "DELETE FROM social_notifications WHERE id = ? AND guild_id = ?",
            (identifiant, ctx.guild.id),
        )
        await panels.envoyer(ctx, panels.depuis_embed(embeds.success(f'La surveillance **#{identifiant}** a été supprimée.')))

    @commands.hybrid_command(
        name="welcome-config",
        description="Configurer le salon, le texte et l'image facultative d'arrivée.",
        with_app_command=False,
    )
    @checks.is_owner_or_admin_for("configuration")
    async def welcome_config(
        self,
        ctx: commands.Context,
        salon: discord.TextChannel,
        *,
        message: str,
    ):
        """+welcome-config #salon texte [--image URL], ou joignez directement l'image."""
        if ctx.guild is None:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Cette commande doit être utilisée dans un serveur.')))

        message, image_flag = _extract_image_flag(message)
        image_url = _attachment_image(ctx) or image_flag
        if not message:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error("Écrivez le message d'arrivée après le salon.")))
        if len(message) > 1000:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error("Le message d'arrivée est limité à 1 000 caractères.")))
        if image_url and not _valid_https_url(image_url):
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error("L'image doit être jointe au message ou utiliser une URL HTTPS.")))

        await self.bot.db.set_guild_config(ctx.guild.id, "welcome_channel", salon.id)
        await self.bot.db.set_guild_config(ctx.guild.id, "welcome_message", message)
        await self.bot.db.set_guild_config(ctx.guild.id, "welcome_image_url", image_url)

        preview_text = (
            message.replace("{member}", ctx.author.mention)
            .replace("{username}", ctx.author.display_name)
            .replace("{server}", ctx.guild.name)
            .replace("{member_count}", str(ctx.guild.member_count or 0))
        )
        preview = embeds.success(preview_text, title=f"Bienvenue {ctx.author.display_name}")
        preview.set_thumbnail(url=ctx.author.display_avatar.url)
        if image_url:
            preview.set_image(url=image_url)
        preview.add_field(
            name="Configuration enregistrée",
            value=f"Les nouveaux membres seront accueillis dans {salon.mention}. "
            + ("L'image d'arrivée est activée." if image_url else "Aucune image d'arrivée ne sera affichée."),
            inline=False,
        )
        await panels.envoyer(ctx, panels.depuis_embed(preview))


async def setup(bot: commands.Bot):
    await bot.add_cog(Notifications(bot))
