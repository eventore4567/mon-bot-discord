"""Notifications sociales automatiques et accueil personnalisable SentriX."""

import asyncio
import logging
import re
import time
from urllib.parse import urlparse, urlunparse

import discord

import config
from discord.ext import commands, tasks

from services import social_providers
from utils import checks, embeds
from utils import sentrix_emojis as sxemoji
from utils import sentrix_panels as panels


logger = logging.getLogger("bot.notifications")


class _YTDLPCaptureLogger:
    """Capture yt-dlp sans polluer stderr.

    yt-dlp imprime certains états normaux (ex. Twitch hors ligne) directement
    en ERROR même avec quiet=True. On capture donc ces lignes, puis le code
    appelant décide si c'est une vraie panne ou un état normal.
    """

    def __init__(self):
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def debug(self, message):
        return None

    def info(self, message):
        return None

    def warning(self, message):
        self.warnings.append(str(message))

    def error(self, message):
        self.errors.append(str(message))


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


#: Un identifiant de chaîne YouTube, qui ne doit JAMAIS servir d'identifiant
#: de publication : il ne change jamais, donc le bot ne notifierait plus
#: jamais après l'avoir enregistré une fois.
_ID_CHAINE_YOUTUBE = re.compile(r"^UC[A-Za-z0-9_-]{22}$")


def _url_a_interroger(source_url: str) -> str:
    """URL réellement interrogée pour trouver la dernière publication.

    Une URL de chaîne YouTube nue (« /@MrBeast ») ne rend PAS ses vidéos :
    yt-dlp y voit une page qui contient plusieurs onglets, et renvoie la
    chaîne elle-même. Le bot enregistrait donc l'identifiant de la chaîne
    comme « dernière publication vue », et comme il ne change jamais, YouTube
    ne notifiait plus jamais. Mesuré :

        /@MrBeast          -> id = UCX6OQ3DkcsbYNE6H8uQQuVA  (la chaîne)
        /@MrBeast/videos   -> id = v9QtM6qnG50               (une vidéo)

    L'onglet « videos » contient aussi les directs terminés et les directs en
    cours, donc une seule URL suffit pour les deux usages.
    """
    url = str(source_url or "").strip()
    hote = urlparse(url).hostname or ""
    if "youtube.com" not in hote.casefold():
        return url
    chemin = urlparse(url).path.rstrip("/")
    # Déjà un onglet ou une vidéo précise : on n'y touche pas.
    if any(chemin.endswith(f"/{onglet}") for onglet in
           ("videos", "streams", "shorts", "live", "featured", "playlists")):
        return url
    if "/watch" in chemin or "/playlist" in chemin:
        return url
    if chemin.startswith("/@") or "/channel/" in chemin or "/c/" in chemin or "/user/" in chemin:
        return f"{url.rstrip('/')}/videos"
    return url


def _extract_latest_sync(source_url: str) -> dict | None:
    """Extraction bloquante isolée dans asyncio.to_thread par l'appelant."""
    import yt_dlp

    capture = _YTDLPCaptureLogger()
    options = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": "in_playlist",
        "playlistend": 3,
        "ignoreerrors": True,
        "socket_timeout": 12,
        "logger": capture,
    }
    with yt_dlp.YoutubeDL(options) as downloader:
        info = downloader.extract_info(_url_a_interroger(source_url), download=False)
    if not info:
        if capture.errors:
            raise RuntimeError(capture.errors[-1])
        return None
    entries = info.get("entries")
    if entries:
        for entry in entries:
            if entry and _id_de_publication(entry.get("id")):
                return entry
        return None
    return info if _id_de_publication(info.get("id")) else None


def _id_de_publication(valeur: object) -> str:
    """L'identifiant d'une VRAIE publication, ou une chaîne vide.

    Un identifiant de chaîne enregistré comme « dernière publication vue »
    éteint définitivement les notifications de ce serveur, sans la moindre
    erreur pour le signaler. Ce filet aurait attrapé le défaut YouTube seul.
    """
    identifiant = str(valeur or "").strip()
    if not identifiant or _ID_CHAINE_YOUTUBE.match(identifiant):
        return ""
    return identifiant


async def _extract_latest(source_url: str) -> dict | None:
    return await asyncio.wait_for(
        asyncio.to_thread(_extract_latest_sync, source_url),
        timeout=25,
    )


def _extract_details_sync(item_url: str) -> dict | None:
    """Charge les métadonnées complètes UNIQUEMENT pour une nouvelle publication."""
    import yt_dlp

    capture = _YTDLPCaptureLogger()
    options = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "ignoreerrors": True,
        "socket_timeout": 12,
        "logger": capture,
    }
    with yt_dlp.YoutubeDL(options) as downloader:
        info = downloader.extract_info(item_url, download=False)
    if not isinstance(info, dict) and capture.errors:
        raise RuntimeError(capture.errors[-1])
    return info if isinstance(info, dict) else None


async def _extract_details(item_url: str) -> dict | None:
    return await asyncio.wait_for(
        asyncio.to_thread(_extract_details_sync, item_url),
        timeout=20,
    )


def _best_thumbnail(
    item: dict,
    custom_url: str | None = None,
    *,
    platform: str | None = None,
) -> str | None:
    """Retourne la vraie miniature du contenu avec un fallback YouTube fiable."""
    candidates = [
        custom_url,
        item.get("thumbnail"),
        item.get("cover"),
        item.get("cover_url"),
        item.get("image"),
        item.get("image_url"),
    ]
    thumbnails = item.get("thumbnails") or []
    if isinstance(thumbnails, list):
        for thumb in reversed(thumbnails):
            if isinstance(thumb, dict):
                candidates.append(thumb.get("url"))

    for candidate in candidates:
        if isinstance(candidate, str) and _valid_https_url(candidate):
            return candidate

    # Les entrées YouTube "flat" n'incluent pas toujours thumbnails. L'ID vidéo
    # suffit pourtant à obtenir la miniature officielle, y compris pour Shorts.
    if platform == "YouTube":
        item_id = _id_de_publication(item.get("id"))
        if item_id:
            return f"https://i.ytimg.com/vi/{item_id}/hqdefault.jpg"
    return None


class SocialNotificationPanel(discord.ui.LayoutView):
    """Carte sociale commune YouTube/TikTok/Twitch, proche du style natif premium."""

    def __init__(
        self,
        *,
        platform: str,
        title: str,
        description: str,
        link: str,
        image_url: str | None,
        creator: str | None = None,
        kind: str = "post",
        published_at: int | None = None,
    ):
        super().__init__(timeout=None)
        container = discord.ui.Container()

        creator_name = str(creator or platform).strip()
        if kind == "short":
            headline = f"**{creator_name}** vient de sortir un nouveau Short sur **{platform}** !"
        elif kind == "live":
            headline = f"🔴 **{creator_name}** est en LIVE sur **{platform}** !"
        elif platform == "TikTok":
            headline = f"**{creator_name}** vient de publier un nouveau TikTok !"
        elif kind == "video":
            headline = f"**{creator_name}** vient de sortir une nouvelle vidéo sur **{platform}** !"
        else:
            headline = f"**{creator_name}** vient de publier sur **{platform}** !"

        container.add_item(discord.ui.TextDisplay(f"## {headline}"))

        clean_title = str(title or "").strip()
        if clean_title:
            container.add_item(discord.ui.TextDisplay(f"### [{clean_title[:220]}]({link})"))

        body = str(description or "").strip()
        if body:
            container.add_item(discord.ui.TextDisplay(body[:700]))

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

        if published_at:
            container.add_item(
                discord.ui.TextDisplay(f"-# Publié <t:{int(published_at)}:R>")
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

        results = await asyncio.gather(
            *(check(row) for row in rows),
            return_exceptions=True,
        )
        # L'ancienne version avalait silencieusement les exceptions de gather().
        for row, result in zip(rows, results):
            if isinstance(result, BaseException):
                logger.error(
                    "Échec non géré du moniteur social abonnement=%s plateforme=%s",
                    row["id"],
                    row["platform"],
                    exc_info=(type(result), result, result.__traceback__),
                )

    @social_monitor.before_loop
    async def before_social_monitor(self):
        await self.bot.wait_until_ready()

    @social_monitor.error
    async def social_monitor_error(self, error: Exception):
        logger.error(
            "Erreur du moniteur de réseaux sociaux",
            exc_info=(type(error), error, error.__traceback__),
        )

    async def _surface_state(self, subscription_id: int, surface: str):
        return await self.bot.db.fetchone(
            "SELECT * FROM social_notification_state "
            "WHERE subscription_id=? AND surface=?",
            (subscription_id, surface),
        )

    async def _update_surface_state(
        self,
        subscription_id: int,
        surface: str,
        item_id: str,
        item_url: str,
    ):
        timestamp = int(time.time())
        await self.bot.db.execute(
            "INSERT INTO social_notification_state "
            "(subscription_id,surface,last_item_id,last_item_url,last_checked_at) "
            "VALUES (?,?,?,?,?) "
            "ON CONFLICT(subscription_id,surface) DO UPDATE SET "
            "last_item_id=excluded.last_item_id,last_item_url=excluded.last_item_url,"
            "last_checked_at=excluded.last_checked_at",
            (subscription_id, surface, item_id, item_url, timestamp),
        )

    async def _touch_surface(self, subscription_id: int, surface: str):
        await self.bot.db.execute(
            "UPDATE social_notification_state SET last_checked_at=? "
            "WHERE subscription_id=? AND surface=?",
            (int(time.time()), subscription_id, surface),
        )

    async def _item_event(
        self,
        row,
        item: dict,
        *,
        kind: str,
        provider: str = "fallback",
    ) -> social_providers.SocialEvent:
        platform = row["platform"]
        link = _item_url(platform, row["source_url"], item)

        # Une nouvelle publication seulement : enrichissement coûteux à ce moment,
        # jamais pendant les scans qui n'ont rien détecté.
        try:
            details = await _extract_details(link)
        except Exception:
            details = None
            logger.info(
                "Métadonnées détaillées indisponibles abonnement=%s provider=%s",
                row["id"],
                provider,
                exc_info=True,
            )
        if details:
            merged = dict(item)
            merged.update(
                {k: v for k, v in details.items() if v not in (None, "", [], {})}
            )
            item = merged
            link = _item_url(platform, row["source_url"], item)

        creator = (
            item.get("uploader")
            or item.get("channel")
            or item.get("creator")
            or item.get("uploader_id")
        )
        published_at = (
            item.get("timestamp")
            or item.get("release_timestamp")
            or item.get("modified_timestamp")
        )
        try:
            published_at = int(published_at) if published_at else None
        except (TypeError, ValueError):
            published_at = None

        if platform == "Twitch" and kind == "live":
            link = row["source_url"]

        return social_providers.SocialEvent(
            provider=provider,
            platform=platform,
            item_id=str(item.get("id") or ""),
            url=link,
            title=(item.get("title") or f"Nouvelle publication sur {platform}")[:300],
            creator=str(creator) if creator else None,
            creator_url=item.get("channel_url") or item.get("uploader_url"),
            thumbnail_url=_best_thumbnail(
                item,
                row["image_url"],
                platform=platform,
            ),
            published_at=published_at,
            kind=kind,
        )

    async def _send_social_event(self, row, event: social_providers.SocialEvent) -> bool:
        guild = self.bot.get_guild(int(row["guild_id"]))
        if guild is None:
            return False
        channel = guild.get_channel(int(row["discord_channel_id"]))
        role = guild.get_role(int(row["role_id"]))
        if channel is None or role is None:
            await self.bot.db.execute(
                "UPDATE social_notifications SET enabled=0 WHERE id=?",
                (row["id"],),
            )
            logger.warning(
                "Abonnement social désactivé : salon/rôle introuvable id=%s",
                row["id"],
            )
            return False

        description = row["custom_text"] or ""
        notification = SocialNotificationPanel(
            platform=event.platform,
            title=event.title,
            description=description,
            link=event.url,
            image_url=row["image_url"] or event.thumbnail_url,
            creator=event.creator,
            kind=event.kind,
            published_at=event.published_at,
        )
        try:
            await channel.send(view=notification)
            await channel.send(
                content=role.mention,
                allowed_mentions=discord.AllowedMentions(
                    everyone=False,
                    users=False,
                    roles=[role],
                    replied_user=False,
                ),
                delete_after=5,
            )
        except discord.HTTPException:
            logger.warning(
                "Envoi impossible abonnement=%s provider=%s item=%s",
                row["id"],
                event.provider,
                event.item_id,
                exc_info=True,
            )
            return False
        return True

    async def _check_subscription(self, row):
        guild = self.bot.get_guild(row["guild_id"])
        if guild is None:
            return
        if guild.get_channel(row["discord_channel_id"]) is None or guild.get_role(row["role_id"]) is None:
            await self.bot.db.execute(
                "UPDATE social_notifications SET enabled=0 WHERE id=?",
                (row["id"],),
            )
            return

        surfaces = social_providers.source_surfaces(
            row["source_url"],
            row["platform"],
        )
        for surface, poll_url, kind in surfaces:
            try:
                item = await _extract_latest(poll_url)
            except Exception as exc:
                message = str(exc).casefold()
                # Twitch hors ligne est un état normal, pas une panne. L'ancien
                # moteur écrivait un WARNING toutes les 5 minutes pour chaque
                # chaîne offline et noyait les vraies erreurs.
                if (
                    row["platform"] == "Twitch"
                    and (
                        "not currently live" in message
                        or "channel is offline" in message
                        or "offline" in message
                    )
                ):
                    continue
                logger.warning(
                    "Lecture impossible abonnement=%s plateforme=%s surface=%s url=%s",
                    row["id"],
                    row["platform"],
                    surface,
                    poll_url,
                    exc_info=True,
                )
                continue
            if not item:
                continue

            item_id = _id_de_publication(item.get("id"))
            if not item_id:
                logger.warning(
                    "Publication sans ID exploitable abonnement=%s surface=%s",
                    row["id"],
                    surface,
                )
                continue
            item_url = _item_url(row["platform"], poll_url, item)
            state = await self._surface_state(int(row["id"]), surface)

            if state is None:
                # Compatibilité des abonnements existants : l'ancien last_item_id
                # correspond à la surface principale. Les nouvelles surfaces
                # Shorts/streams sont initialisées sans spammer de vieux contenus.
                legacy_id = (
                    str(row["last_item_id"] or "")
                    if surface in {"default", "videos"}
                    else ""
                )
                if legacy_id and legacy_id != item_id:
                    event = await self._item_event(row, item, kind=kind)
                    if await self._send_social_event(row, event):
                        await self._update_surface_state(
                            int(row["id"]), surface, item_id, event.url
                        )
                        await self._update_last_item(row["id"], item_id, event.url)
                else:
                    await self._update_surface_state(
                        int(row["id"]), surface, item_id, item_url
                    )
                continue

            previous = str(state["last_item_id"] or "")
            if item_id == previous:
                await self._touch_surface(int(row["id"]), surface)
                continue

            event = await self._item_event(row, item, kind=kind)
            if await self._send_social_event(row, event):
                await self._update_surface_state(
                    int(row["id"]), surface, item_id, event.url
                )
                await self._update_last_item(row["id"], item_id, event.url)

    async def handle_provider_webhook(
        self,
        payload: dict,
        *,
        provider: str = "phyllo",
    ) -> int:
        if provider != "phyllo":
            return 0
        events = social_providers.parse_phyllo_webhook(payload)
        if not events:
            return 0

        rows = await self.bot.db.fetchall(
            "SELECT * FROM social_notifications WHERE enabled=1 ORDER BY id ASC"
        )
        delivered = 0
        for event in events:
            for row in rows:
                if str(row["platform"]).casefold() != event.platform.casefold():
                    continue
                if not social_providers.same_creator(row["source_url"], event):
                    continue

                surface = (
                    "shorts"
                    if event.kind == "short"
                    else "streams"
                    if event.kind == "live"
                    else "videos"
                    if event.platform == "YouTube"
                    else "default"
                )
                state = await self._surface_state(int(row["id"]), surface)
                if state and str(state["last_item_id"] or "") == event.item_id:
                    continue

                # L'image personnalisée de l'abonnement garde la priorité.
                if await self._send_social_event(row, event):
                    await self._update_surface_state(
                        int(row["id"]), surface, event.item_id, event.url
                    )
                    await self._update_last_item(
                        int(row["id"]), event.item_id, event.url
                    )
                    delivered += 1
        return delivered

    async def _update_last_item(self, subscription_id: int, item_id: str, item_url: str):
        await self.bot.db.execute(
            "UPDATE social_notifications SET last_item_id=?, last_item_url=?, "
            "last_checked_at=? WHERE id=?",
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
        status = await panels.envoyer(
            ctx,
            panels.depuis_embed(embeds.info(f"Vérification de la chaîne {platform}…")),
        )

        baselines: list[tuple[str, str, str, dict]] = []
        surfaces = social_providers.source_surfaces(source_url, platform)
        for surface, poll_url, kind in surfaces:
            try:
                latest = await _extract_latest(poll_url)
            except asyncio.TimeoutError:
                logger.warning(
                    "Timeout configuration source=%s surface=%s",
                    source_url,
                    surface,
                )
                continue
            except Exception:
                logger.warning(
                    "Impossible de lire source=%s surface=%s",
                    source_url,
                    surface,
                    exc_info=True,
                )
                continue
            if latest and _id_de_publication(latest.get("id")):
                baselines.append((surface, poll_url, kind, latest))

        if not baselines:
            return await panels.editer(
                status,
                panels.depuis_embed(
                    embeds.error(
                        "Aucune publication publique n'a été trouvée sur cette chaîne."
                    )
                ),
            )

        primary_surface, primary_url, _kind, primary = baselines[0]
        latest_id = _id_de_publication(primary["id"])
        latest_url = _item_url(platform, primary_url, primary)
        timestamp = int(time.time())
        await self.bot.db.execute(
            "INSERT INTO social_notifications "
            "(guild_id,source_url,platform,discord_channel_id,role_id,custom_text,image_url,"
            "last_item_id,last_item_url,enabled,created_at,last_checked_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,1,?,?) "
            "ON CONFLICT(guild_id,source_url) DO UPDATE SET "
            "platform=excluded.platform,discord_channel_id=excluded.discord_channel_id,"
            "role_id=excluded.role_id,custom_text=excluded.custom_text,image_url=excluded.image_url,"
            "last_item_id=excluded.last_item_id,last_item_url=excluded.last_item_url,"
            "enabled=1,last_checked_at=excluded.last_checked_at",
            (
                ctx.guild.id,
                source_url,
                platform,
                ctx.channel.id,
                role.id,
                texte or None,
                image_url,
                latest_id,
                latest_url,
                timestamp,
                timestamp,
            ),
        )
        saved = await self.bot.db.fetchone(
            "SELECT * FROM social_notifications WHERE guild_id=? AND source_url=?",
            (ctx.guild.id, source_url),
        )
        if saved:
            for surface, poll_url, _kind, latest in baselines:
                item_id = _id_de_publication(latest.get("id"))
                item_url = _item_url(platform, poll_url, latest)
                await self._update_surface_state(
                    int(saved["id"]), surface, item_id, item_url
                )

        surfaces_label = (
            "vidéos + Shorts + lives"
            if platform == "YouTube"
            else "publications / live"
        )
        await panels.editer(
            status,
            panels.depuis_embed(
                embeds.success(
                    f"Surveillance **{platform}** activée.\n"
                    f"**Formats :** {surfaces_label}\n"
                    f"**Rôle pingé :** {role.mention}\n"
                    f"**Salon :** {ctx.channel.mention}\n"
                    "**Fallback :** vérification toutes les 5 minutes\n"
                    + (
                        "**Image personnalisée :** activée"
                        if image_url
                        else "**Image :** miniature automatique"
                    )
                )
            ),
        )

    @commands.hybrid_command(
        name="notifs-status",
        description="Afficher l'état du moteur de notifications sociales.",
        with_app_command=False,
    )
    @checks.is_owner_or_admin_for("configuration")
    async def notifs_status(self, ctx: commands.Context):
        if ctx.guild is None:
            return await panels.envoyer(
                ctx,
                panels.depuis_embed(
                    embeds.error("Cette commande doit être utilisée dans un serveur.")
                ),
            )

        rows = await self.bot.db.fetchall(
            "SELECT * FROM social_notifications WHERE guild_id=? ORDER BY id ASC",
            (ctx.guild.id,),
        )
        active = sum(1 for row in rows if row["enabled"])
        states = 0
        if rows:
            placeholders = ",".join("?" for _ in rows)
            state_row = await self.bot.db.fetchone(
                f"SELECT COUNT(*) AS n FROM social_notification_state "
                f"WHERE subscription_id IN ({placeholders})",
                tuple(int(row["id"]) for row in rows),
            )
            states = int(state_row["n"] if state_row else 0)

        provider = (
            f"Phyllo {config.PHYLLO_ENVIRONMENT} prêt"
            if config.PHYLLO_ENABLED
            else "Phyllo non configuré — fallback actif"
        )
        webhook = (
            "Webhook signé prêt"
            if config.PHYLLO_WEBHOOK_ENABLED
            else "Webhook Phyllo non configuré"
        )
        body = (
            f"**Provider** · {provider}\n"
            f"**Webhook** · {webhook}\n"
            f"**Fallback** · yt-dlp/API toutes les 5 minutes\n"
            f"**Surveillances** · {active}/{len(rows)} actives\n"
            f"**États multi-format** · {states}\n"
            f"**YouTube** · vidéos + Shorts + lives séparés"
        )
        await panels.envoyer(
            ctx,
            panels.depuis_embed(
                embeds.info(body, title="Notifications sociales")
            ),
        )

    @commands.hybrid_command(
        name="notifs-test",
        description="Prévisualiser une notification avec titre et miniature réels.",
        with_app_command=False,
    )
    @checks.is_owner_or_admin_for("configuration")
    async def notifs_test(
        self,
        ctx: commands.Context,
        plateforme: str = "YouTube",
        type_contenu: str = "video",
        lien: str = "",
    ):
        platform_key = str(plateforme or "").strip().casefold()
        platform = {
            "youtube": "YouTube",
            "yt": "YouTube",
            "tiktok": "TikTok",
            "tt": "TikTok",
            "twitch": "Twitch",
            "instagram": "Instagram",
            "insta": "Instagram",
            "x": "X",
            "twitter": "X",
        }.get(platform_key)
        if platform is None:
            return await panels.texte_court(
                ctx,
                "Plateforme valide : YouTube, TikTok, Twitch, Instagram ou X.",
                ephemere=bool(ctx.interaction),
            )

        kind = str(type_contenu or "").strip().casefold()
        if kind not in {"video", "short", "live", "post"}:
            return await panels.texte_court(
                ctx,
                "Type valide : video, short, live ou post.",
                ephemere=bool(ctx.interaction),
            )

        link = str(lien or "").strip()
        title = "Exemple de nouvelle publication SentriX"
        creator = "Créateur"
        image_url = None
        published_at = int(time.time())

        # Avec un lien réel, le test affiche exactement les mêmes métadonnées que
        # la notification automatique : titre, créateur et miniature réels.
        if link:
            if not _is_supported_social_url(link):
                return await panels.texte_court(
                    ctx,
                    "Le lien doit être une URL publique YouTube, TikTok, Twitch, Instagram ou X.",
                    ephemere=bool(ctx.interaction),
                )
            detected_platform, _ = _platform_details(link)
            if detected_platform != "Réseau social":
                platform = detected_platform

            path = (urlparse(link).path or "").casefold()
            if platform == "YouTube" and "/shorts/" in path:
                kind = "short"
            elif platform == "YouTube" and "/live/" in path:
                kind = "live"
            elif platform == "Twitch":
                kind = "live"

            try:
                details = await _extract_details(link)
            except Exception:
                details = None
                logger.info(
                    "Prévisualisation sociale : métadonnées indisponibles pour %s",
                    link,
                    exc_info=True,
                )

            if details:
                title = str(
                    details.get("title")
                    or details.get("fulltitle")
                    or title
                )[:300]
                creator = str(
                    details.get("uploader")
                    or details.get("channel")
                    or details.get("creator")
                    or details.get("uploader_id")
                    or creator
                )[:120]
                image_url = _best_thumbnail(
                    details,
                    platform=platform,
                )
                timestamp = (
                    details.get("timestamp")
                    or details.get("release_timestamp")
                    or details.get("modified_timestamp")
                )
                try:
                    published_at = int(timestamp) if timestamp else published_at
                except (TypeError, ValueError):
                    pass
            elif platform == "YouTube":
                match = re.search(
                    r"(?:youtu\.be/|v=|/shorts/|/live/)([A-Za-z0-9_-]{6,})",
                    link,
                )
                if match:
                    image_url = f"https://i.ytimg.com/vi/{match.group(1)}/hqdefault.jpg"
        else:
            # Sans lien, on montre quand même le rendu complet avec une vraie
            # miniature HTTP pour que le test ne paraisse plus vide.
            sample_links = {
                "YouTube": "https://www.youtube.com/watch?v=aqz-KE-bpKQ",
                "TikTok": "https://www.tiktok.com/",
                "Twitch": "https://www.twitch.tv/",
                "Instagram": "https://www.instagram.com/",
                "X": "https://x.com/",
            }
            link = sample_links[platform]
            if platform == "YouTube":
                title = (
                    "Buddha V1 VERSUS V2 — exemple de Short"
                    if kind == "short"
                    else "Exemple de nouvelle vidéo YouTube"
                )
                image_url = "https://i.ytimg.com/vi/aqz-KE-bpKQ/hqdefault.jpg"
            elif platform == "TikTok":
                title = "Exemple de nouveau TikTok"
            elif platform == "Twitch":
                title = "Exemple de nouveau live Twitch"
            else:
                title = f"Exemple de nouvelle publication {platform}"

        preview = SocialNotificationPanel(
            platform=platform,
            title=title,
            description="",
            link=link,
            image_url=image_url,
            creator=creator,
            kind=kind,
            published_at=published_at,
        )
        await ctx.send(view=preview)

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
