"""Listeners Discord officiels des journaux SentriX.

Pipeline unique :
Discord Event -> Audit Log corrélé -> normalisation -> déduplication -> grand log SentriX
-> allowed mentions sécurisé -> boutons utiles -> envoi unique via utils.log_service.
"""
from __future__ import annotations

import asyncio
import io
import json
import logging
import re
import time
from types import SimpleNamespace

import discord
from discord.ext import commands

from utils import embeds, log_service
from services import voice_history

logger = logging.getLogger("bot.logs")

# Plus de table config_key -> categorie. Chaque listener passe le type d'événement
# canonique de LOG_REGISTRY, et log_service en déduit la catégorie. L'ancienne clé
# fourre-tout "log_server" faisait tomber channel_*, role_* ET guild_update dans la
# même catégorie « Serveur », alors que le registre les répartit entre Salons, Rôles
# et Serveur.

MESSAGE_CACHE_RETENTION_SECONDS = 86400
MESSAGE_CACHE_CLEANUP_EVERY = 250
MESSAGE_CACHE_SCHEMA = """
CREATE TABLE IF NOT EXISTS message_log_cache (
    message_id INTEGER PRIMARY KEY,
    guild_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    author_id INTEGER NOT NULL,
    author_name TEXT NOT NULL,
    content TEXT,
    attachments TEXT NOT NULL DEFAULT '[]',
    stored_at INTEGER NOT NULL
)
"""


def _short(value: object, limit: int = 1000) -> str:
    text = str(value or "").strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _attach_message_transcript(
    panel: discord.Embed,
    *,
    guild_id: int,
    channel_id: int,
    message_id: int,
    author_id: int,
    sections: list[tuple[str, str]],
    media_items: list[tuple[str, str, str]] | None = None,
    media_files: list[discord.File] | None = None,
) -> tuple[list[tuple[str, str, str]], list[discord.File]]:
    """Préserve le texte brut AVANT tout raccourcissement du panneau Discord.

    Le seuil tient aussi compte du Markdown échappé et des nombreuses lignes :
    un texte de moins de 1024 caractères peut dépasser la place du renderer.
    Le TXT ne transforme ni les espaces, ni Unicode, ni les mentions du message.
    """
    items, files = list(media_items or []), list(media_files or [])
    header = (
        "SentriX — Transcript intégral\n"
        f"Serveur : {guild_id}\nSalon : {channel_id}\n"
        f"Message : {message_id}\nAuteur : {author_id}\n"
        f"Lien : https://discord.com/channels/{guild_id}/{channel_id}/{message_id}\n"
    )
    body = header + "".join(f"\n===== {label} =====\n{text}\n" for label, text in sections)
    if items:
        body += "\n===== Pièces jointes (liens d’origine) =====\n"
        body += "".join(f"{filename}\n{url}\n" for url, filename, _kind in items)
    filename = f"sentrix-message-{message_id}-transcript.txt"
    transcript = discord.File(io.BytesIO(body.encode("utf-8")), filename=filename)
    panel.add_field(name="Transcript", value="Texte intégral dans le fichier joint, sans coupure.", inline=False)
    # Premier fichier/composant : jamais sacrifié aux aperçus ou à la bannière.
    return [(f"attachment://{filename}", filename, "text/plain"), *items], [transcript, *files]


_TICKET_SYSTEM_TOPIC_RE = re.compile(
    r"^Opened\s+<t:\d+:[A-Za-z]>\s+by\s+<@!?\d+>"
    r"(?:\s*[•·]\s*Claimed\s+by\s+<@!?\d+>\s+at\s+<t:\d+:[A-Za-z]>)?\s*$",
    re.IGNORECASE,
)


def _is_ticket_system_topic(value: object) -> bool:
    """Sujet technique géré par le système de tickets, déjà journalisé côté Tickets."""
    text = str(value or "").strip()
    return bool(text and _TICKET_SYSTEM_TOPIC_RE.fullmatch(text))


def _active_timeout(member: discord.Member):
    """Timeout réellement en cours (None si absent ou déjà expiré). Discord conserve
    l'ancien horodatage après expiration : sans ce filtre, un simple changement de pseudo
    ou de rôle produisait une fausse carte « Timeout retiré » signée SentriX."""
    until = getattr(member, "timed_out_until", None)
    if until is None or until <= discord.utils.utcnow():
        return None
    return until



def _timeout_duration_label(until, *, now=None) -> str | None:
    """Temps restant au moment du log (Discord fournit la fin, pas la durée initiale)."""
    if until is None:
        return None
    if now is None:
        now = discord.utils.utcnow()
    if getattr(until, "tzinfo", None) is None:
        from datetime import timezone
        until = until.replace(tzinfo=timezone.utc)
    import math
    remaining = (until - now).total_seconds()
    if remaining <= 0:
        return None
    seconds = math.ceil(remaining)
    if seconds < 60:
        return f"{seconds} s"
    total_minutes = math.ceil(seconds / 60)
    days, rest = divmod(total_minutes, 24 * 60)
    hours, minutes = divmod(rest, 60)
    if days:
        return f"{days} j" + (f" {hours} h" if hours else "")
    if hours:
        return f"{hours} h" + (f" {minutes} min" if minutes else "")
    return f"{minutes} min"


def _user_ref(user_id: int) -> str:
    return f"<@{int(user_id)}>"


def _role_ref(role_id: int) -> str:
    return f"<@&{int(role_id)}>"


#: Un champ d'embed Discord s'arrête à 1024 caractères. On tronque en le
#: disant, plutôt que de laisser l'API refuser la carte entière. La marge
#: couvre la mention de fin (« N autre(s) cible(s) modifiée(s) »).
_BUDGET_PERMS = 900
_MAX_PERMS_PAR_CIBLE = 8


def _est_categorie(salon) -> bool:
    """Le type déclaré, pas un isinstance.

    Les objets partiels que sert le cache de Discord ne sont pas toujours des
    CategoryChannel, alors qu'ils portent bien leur type.
    """
    return getattr(salon, "type", None) == discord.ChannelType.category


#: Modifier les permissions d'une catégorie synchronise ses salons : Discord
#: émet alors un CHANNEL_UPDATE pour la catégorie PUIS un par salon synchronisé.
#: Sans ce mémo, une seule édition produisait une carte par salon — exactement
#: la rafale illisible qu'on reproche aux autres bots. On ne retient que la
#: propagation : un « synchroniser ce salon » isolé n'a pas de carte de
#: catégorie récente, donc il garde la sienne. Le biais est volontaire : jamais
#: perdre un événement, quitte à en afficher un de trop.
_FENETRE_PROPAGATION_SECONDES = 15.0
_CATEGORIES_PERMS_RECENTES: dict[tuple[int, int], float] = {}


def _noter_perms_de_categorie(guild_id: int, categorie_id: int) -> None:
    maintenant = time.monotonic()
    for cle, vu in list(_CATEGORIES_PERMS_RECENTES.items()):
        if maintenant - vu > _FENETRE_PROPAGATION_SECONDES:
            del _CATEGORIES_PERMS_RECENTES[cle]
    _CATEGORIES_PERMS_RECENTES[(int(guild_id), int(categorie_id))] = maintenant


def _est_propagation_de_categorie(salon) -> bool:
    """Le salon ne fait que recevoir les permissions de sa catégorie ?"""
    categorie_id = getattr(salon, "category_id", None)
    if not categorie_id:
        return False
    vu = _CATEGORIES_PERMS_RECENTES.get((int(salon.guild.id), int(categorie_id)))
    if vu is None or time.monotonic() - vu > _FENETRE_PROPAGATION_SECONDES:
        return False
    # `permissions_synced` compare les dérogations du salon à celles de sa
    # catégorie : si elles diffèrent, le salon a sa propre configuration et ce
    # qui vient de changer lui est propre.
    return bool(getattr(salon, "permissions_synced", False))


def _nom_derogation(cible) -> str:
    """@everyone est écrit en toutes lettres : le mentionner pingerait tout le serveur."""
    # Les clés d'overwrites sont des rôles ou des membres. `is_default` n'existe
    # que sur un rôle : c'est ce qui les sépare, pas un isinstance (les objets
    # partiels servis par le cache de Discord ne passent pas toujours le test).
    defaut = getattr(cible, "is_default", None)
    if callable(defaut):
        return "@everyone" if defaut() else _role_ref(cible.id)
    return _user_ref(getattr(cible, "id", 0))


def _diff_derogations(avant, apres) -> list[tuple[object, list[str], list[str], list[str]]]:
    """Ce qui a changé dans les permissions d'un salon, cible par cible.

    Un PermissionOverwrite a trois états : autorisé, refusé, et non défini.
    Seules les TRANSITIONS sont intéressantes — afficher les 59 permissions
    inchangées noierait les deux qui ont bougé.

    Discord émet un évènement par dérogation modifiée. Les regrouper ici donne
    UNE carte par édition au lieu d'une carte par permission.
    """
    from utils.access_matrix import permission_label

    change: list[tuple[object, list[str], list[str], list[str]]] = []
    cibles = {c: None for c in list(avant.keys()) + list(apres.keys())}
    for cible in cibles:
        a_avant = dict(iter(avant.get(cible, discord.PermissionOverwrite())))
        a_apres = dict(iter(apres.get(cible, discord.PermissionOverwrite())))
        autorises, refuses, neutres = [], [], []
        for nom in set(a_avant) | set(a_apres):
            if a_avant.get(nom) == a_apres.get(nom):
                continue
            nouvelle = a_apres.get(nom)
            libelle = permission_label(nom)
            if nouvelle is True:
                autorises.append(libelle)
            elif nouvelle is False:
                refuses.append(libelle)
            else:
                neutres.append(libelle)
        if autorises or refuses or neutres:
            change.append((cible, sorted(autorises), sorted(refuses), sorted(neutres)))
    return change


def _texte_derogations(change) -> str:
    """Rend le diff en lignes lisibles, en restant dans le budget de Discord.

    Le budget est tenu en caractères, pas en nombre de cibles : six rôles aux
    libellés longs dépassaient les 1024 caractères d'un champ et la coupe
    tombait au milieu d'un mot. Ce qui ne rentre pas est compté, jamais perdu
    en silence.
    """
    lignes: list[str] = []
    budget = _BUDGET_PERMS
    for rang, (cible, autorises, refuses, neutres) in enumerate(change):
        morceaux = []
        for prefixe, valeurs in (("✅", autorises), ("❌", refuses), ("⬜", neutres)):
            if not valeurs:
                continue
            visibles = valeurs[:_MAX_PERMS_PAR_CIBLE]
            reste = len(valeurs) - len(visibles)
            morceaux.append(f"{prefixe} " + ", ".join(visibles) + (f" (+{reste})" if reste else ""))
        bloc = f"{_nom_derogation(cible)}\n" + "\n".join(morceaux)
        # Toujours garder la première cible : une carte qui ne nomme personne
        # ne vaudrait rien, même si son bloc dépasse à lui seul le budget.
        if rang and len(bloc) + 2 > budget:
            break
        budget -= len(bloc) + 2
        lignes.append(bloc)
    texte = "\n\n".join(lignes)
    reste_cibles = len(change) - len(lignes)
    if reste_cibles > 0:
        texte += f"\n\n*{reste_cibles} autre(s) cible(s) modifiée(s).*"
    return texte


def _channel_ref(channel_id: int) -> str:
    return f"<#{int(channel_id)}>"


def _discord_channel_url(guild_id: int, channel_id: int) -> str:
    return f"https://discord.com/channels/{int(guild_id)}/{int(channel_id)}"


def _attachment_urls(message: discord.Message) -> list[str]:
    return [attachment.url for attachment in message.attachments]


_IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".avif")
_VIDEO_EXTENSIONS = (".mp4", ".mov", ".webm", ".m4v", ".avi", ".mkv")


def _attachment_media(attachments) -> list[tuple[str, str, str]]:
    """Normalise les pièces jointes pour SentriX Trace.

    Les images peuvent ainsi être prévisualisées en bas du journal, tandis que
    chaque fichier garde une action d'ouverture dédiée.
    """
    items: list[tuple[str, str, str]] = []
    for index, attachment in enumerate(attachments or [], start=1):
        url = str(getattr(attachment, "url", attachment) or "").strip()
        if not url:
            continue
        filename = str(getattr(attachment, "filename", "") or "").strip()
        content_type = str(getattr(attachment, "content_type", "") or "").strip().casefold()
        clean_url = url.split("?", 1)[0]
        if not filename:
            filename = clean_url.rsplit("/", 1)[-1] or f"fichier-{index}"
        lower = filename.casefold()
        if not content_type:
            if lower.endswith(_IMAGE_EXTENSIONS):
                content_type = "image/unknown"
            elif lower.endswith(_VIDEO_EXTENSIONS):
                content_type = "video/unknown"
        items.append((url, filename[:120], content_type))
    return items[:10]


# Discord deleted-message CDN URLs are often revoked. Keep up to 4 image
# previews as actual, per-log attachments, never as dead external gallery URLs.
_MAX_PREVIEW_IMAGES = 4
_MAX_PREVIEW_IMAGE_BYTES = 6 * 1024 * 1024
_MAX_PREVIEW_TOTAL_BYTES = 16 * 1024 * 1024
_PREVIEW_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".webp")


async def _snapshot_deleted_images(
    attachments: list[discord.Attachment],
    media_items: list[tuple[str, str, str]],
) -> tuple[list[tuple[str, str, str]], list[discord.File]]:
    """Copy recoverable deleted-message images into the log's own attachments.

    If Discord no longer serves an image, leave its original URL as a *link*
    rather than creating an empty MediaGallery placeholder. A bounded download
    prevents deleted-image traffic from monopolising anti-spam/moderation.
    """
    previews = list(media_items)
    candidates: list[tuple[int, object, str]] = []
    for i, attachment in enumerate(list(attachments or [])[:10]):
        if i >= len(previews) or len(candidates) >= _MAX_PREVIEW_IMAGES:
            break
        _url, filename, content_type = previews[i]
        suffix = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if not content_type.startswith("image/") or suffix not in _PREVIEW_EXTENSIONS:
            continue
        try:
            if int(getattr(attachment, "size", 0) or 0) > _MAX_PREVIEW_IMAGE_BYTES:
                continue
        except (TypeError, ValueError):
            continue
        if not callable(getattr(attachment, "read", None)):
            continue
        candidates.append((i, attachment, suffix))

    async def load(candidate: tuple[int, object, str]):
        i, attachment, suffix = candidate
        try:
            async def retrieve():
                try:
                    return await attachment.read(use_cached=True)
                except (discord.HTTPException, OSError):
                    return await attachment.read(use_cached=False)
            blob = await asyncio.wait_for(retrieve(), timeout=4)
            if not isinstance(blob, bytes) or not blob or len(blob) > _MAX_PREVIEW_IMAGE_BYTES:
                return None
            return i, suffix, blob
        except (discord.HTTPException, OSError, asyncio.TimeoutError, ValueError, TypeError):
            logger.debug("Image supprimée non archivable (index=%d)", i, exc_info=True)
            return None

    results = await asyncio.gather(*(load(candidate) for candidate in candidates))
    media_files: list[discord.File] = []
    total = 0
    for item in results:
        if item is None:
            continue
        i, suffix, blob = item
        if total + len(blob) > _MAX_PREVIEW_TOTAL_BYTES:
            continue
        total += len(blob)
        new_name = f"sentrix-log-image-{i + 1}{suffix}"
        media_files.append(discord.File(io.BytesIO(blob), filename=new_name))
        _original_url, filename, content_type = previews[i]
        previews[i] = (f"attachment://{new_name}", filename, content_type)
    return previews, media_files


def _attachment_summary(items: list[tuple[str, str, str]]) -> str | None:
    if not items:
        return None
    names = ", ".join(filename for _url, filename, _type in items[:5])
    suffix = f" +{len(items) - 5}" if len(items) > 5 else ""
    label = "fichier" if len(items) == 1 else "fichiers"
    return _short(f"{len(items)} {label} · {names}{suffix}", 300)


def _attachment_links(items: list[tuple[str, str, str]]) -> list[tuple[str, str]]:
    links: list[tuple[str, str]] = []
    for index, (url, _filename, content_type) in enumerate(items[:8], start=1):
        if not url.startswith(("https://", "http://")):
            continue  # Les fichiers attachment:// utilisent un composant File, pas un bouton URL.
        if content_type.startswith("image/"):
            label = f"Ouvrir image {index}"
        elif content_type.startswith("video/"):
            label = f"Ouvrir vidéo {index}"
        else:
            label = f"Ouvrir fichier {index}"
        links.append((label, url))
    return links


def _permission_names(perms: discord.Permissions) -> set[str]:
    return {name for name, enabled in perms if enabled}


def _permission_label(name: str) -> str:
    return name.replace("_", " ").capitalize()


def _permission_badge_fields(
    title: str,
    names: list[str],
    *,
    limit: int = 1024,
) -> list[tuple[str, str, bool]]:
    """Affiche chaque permission dans son propre code inline Discord.

    Discord rend `Attach files` dans une pastille grise. Un tronquage brut
    en plein `...` casserait le Markdown : les longues listes sont donc
    réparties en champs complets, sans perdre de permission.
    """
    if not names:
        return []
    chunks: list[str] = []
    current = ""
    on_line = 0
    for name in names:
        label = _permission_label(name).replace("`", "")[:120]
        badge = f"`{label}`"
        separator = (chr(10) if on_line and on_line % 4 == 0 else "  ") if current else ""
        if current and len(current) + len(separator) + len(badge) > limit:
            chunks.append(current)
            current = badge
            on_line = 1
        else:
            current += separator + badge
            on_line += 1
    if current:
        chunks.append(current)
    return [
        (title if idx == 0 else f"{title} (suite {idx + 1})", chunk, False)
        for idx, chunk in enumerate(chunks)
    ]


def _stay_of(member) -> int | None:
    """Le séjour d'un membre : sa date d'arrivée en millisecondes (None si inconnue)."""
    joined = getattr(member, "joined_at", None)
    return int(joined.timestamp() * 1000) if joined is not None else None


class Logs(commands.Cog, name="Logs"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._cache_writes = 0

    async def _send(
        self,
        guild: discord.Guild,
        log_type: str,
        embed: discord.Embed,
        *,
        view: discord.ui.View | None = None,
        event_key: str | None = None,
        media_items: list[tuple[str, str, str]] | None = None,
        media_files: list[discord.File] | None = None,
    ) -> bool:
        logger.debug(
            "SXTRACE 2 CALL guild=%s log_type=%s category=%s event_key=%s target=%s.%s",
            getattr(guild, "id", None), log_type,
            log_service.category_for(log_type), event_key,
            getattr(log_service.send_log, "__module__", "?"),
            getattr(log_service.send_log, "__name__", "?"),
        )
        return await log_service.send_log(
            self.bot,
            guild,
            log_type,
            embed,
            view=view,
            event_key=event_key,
            media_items=media_items,
            media_files=media_files,
        )

    @staticmethod
    def _embed(
        title: str,
        *,
        identity=None,
        fields=(),
        description: str = "",
    ) -> discord.Embed:
        avatar = None
        identity_text = ""
        if identity is not None:
            identity_id = getattr(identity, "id", None)
            identity_name = (
                getattr(identity, "display_name", None)
                or getattr(identity, "name", None)
                or str(identity)
            )
            identity_text = f"**{identity_name}**"
            if identity_id:
                identity_text += f"\nID : `{identity_id}`"
            asset = getattr(identity, "display_avatar", None)
            if asset is not None:
                avatar = str(asset.url)
        body = identity_text
        if description:
            body = f"{body}\n\n{description}" if body else description
        panel = embeds.canonical_log_embed(title, fields=fields, description=body)
        if avatar:
            panel.set_thumbnail(url=avatar)
        return panel

    async def _resolve_actor(
        self,
        guild: discord.Guild,
        action: discord.AuditLogAction,
        target_id: int,
    ) -> tuple[discord.abc.User | discord.Object | None, discord.AuditLogEntry | None]:
        """L'auteur réel d'une modification de membre.

        Le journal d'audit nomme celui qui a APPELÉ Discord. Pour une action passée
        par une commande SentriX, c'est le bot : la commande a donc noté le vrai
        modérateur avant l'appel (utils.audit_trail.noter_acteur), et on le
        préfère ici. Sans permission « Voir le journal d'audit », c'est même la
        seule source.
        """
        from utils import audit_trail

        actor, audit = await self._audit_actor(guild, action, target_id)
        bot_id = getattr(getattr(self.bot, "user", None), "id", None)
        local_id = audit_trail.acteur_local(self.bot, guild.id, target_id, action.name)
        if local_id and (actor is None or getattr(actor, "id", None) == bot_id):
            actor = guild.get_member(local_id) or discord.Object(id=local_id)
        return actor, audit

    async def _audit_actor(
        self,
        guild: discord.Guild,
        action: discord.AuditLogAction,
        target_id: int,
        *,
        max_age_seconds: int = 10,
    ) -> tuple[discord.abc.User | None, discord.AuditLogEntry | None]:
        """Corrèle type + cible + timestamp ; jamais simplement la dernière entrée."""
        from utils.audit_correlation import correlate_audit_entry

        result = await correlate_audit_entry(
            guild,
            action,
            target_id=target_id,
            max_age_seconds=max_age_seconds,
        )
        return result.actor, result.entry

    async def _message_delete_actor(
        self,
        guild: discord.Guild,
        author_id: int,
        channel_id: int,
        *,
        message_id: int | None = None,
    ) -> tuple[discord.abc.User | None, discord.AuditLogEntry | None]:
        """Essaie d'identifier qui a supprimé le message.

        Discord ne fournit pas l'ID du message dans l'audit log. On corrèle donc
        strictement l'auteur cible + le salon + une fenêtre très courte. Une
        suppression faite par l'auteur lui-même ne produit pas d'entrée d'audit :
        dans ce cas on laisse explicitement l'exécuteur inconnu au lieu d'inventer.
        """
        # Les suppressions effectuées directement par SentriX sont marquées par
        # les moteurs internes avant l'appel Discord : attribution exacte, même
        # sans permission Voir le journal d'audit.
        if message_id is not None:
            local = getattr(self.bot, "_sentrix_local_message_deleters", None)
            if isinstance(local, dict):
                marker = local.pop(int(message_id), None)
                if marker and time.monotonic() - float(marker[0]) <= 8:
                    actor_id = int(marker[1] or 0)
                    actor = guild.get_member(actor_id) or self.bot.get_user(actor_id)
                    if actor is not None:
                        return actor, None

        if guild.me is None or not guild.me.guild_permissions.view_audit_log:
            return None, None

        for delay in (0.15, 0.45, 0.85):
            if delay:
                await asyncio.sleep(delay)
            now = discord.utils.utcnow()
            try:
                async for entry in guild.audit_logs(
                    limit=12,
                    action=discord.AuditLogAction.message_delete,
                ):
                    if getattr(entry.target, "id", None) != int(author_id):
                        continue
                    if abs((now - entry.created_at).total_seconds()) > 4:
                        continue
                    extra_channel = getattr(getattr(entry, "extra", None), "channel", None)
                    extra_channel_id = getattr(extra_channel, "id", None)
                    if extra_channel_id is not None and int(extra_channel_id) != int(channel_id):
                        continue
                    return entry.user, entry
            except (discord.Forbidden, discord.HTTPException):
                return None, None
        return None, None

    @staticmethod
    def _delete_actor_text(actor) -> str:
        if actor is None:
            return "Exécuteur inconnu · suppression par l’auteur possible"
        actor_id = getattr(actor, "id", None)
        name = getattr(actor, "display_name", None) or getattr(actor, "name", None) or str(actor)
        if actor_id:
            return f"{getattr(actor, 'mention', name)}\nID : `{actor_id}`"
        return str(name)

    async def _cache_message(self, message: discord.Message) -> None:
        if message.guild is None or message.author.bot:
            return
        try:
            await self.bot.db.execute(
                """
                INSERT INTO message_log_cache
                    (message_id, guild_id, channel_id, author_id, author_name, content, attachments, stored_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(message_id) DO UPDATE SET
                    guild_id = excluded.guild_id,
                    channel_id = excluded.channel_id,
                    author_id = excluded.author_id,
                    author_name = excluded.author_name,
                    content = excluded.content,
                    attachments = excluded.attachments,
                    stored_at = excluded.stored_at
                """,
                (
                    message.id,
                    message.guild.id,
                    message.channel.id,
                    message.author.id,
                    str(message.author),
                    message.content or "",
                    json.dumps(_attachment_urls(message), ensure_ascii=False),
                    int(time.time()),
                ),
            )
            self._cache_writes += 1
            if self._cache_writes % MESSAGE_CACHE_CLEANUP_EVERY == 0:
                await self.bot.db.execute(
                    "DELETE FROM message_log_cache WHERE stored_at < ?",
                    (int(time.time()) - MESSAGE_CACHE_RETENTION_SECONDS,),
                )
        except Exception:
            logger.warning("Étape non critique ignorée dans _cache_message", exc_info=True)

    async def _cached_message_row(self, guild_id: int, message_id: int):
        try:
            return await self.bot.db.fetchone(
                "SELECT * FROM message_log_cache WHERE guild_id = ? AND message_id = ?",
                (guild_id, message_id),
            )
        except Exception:
            return None

    async def _forget_cached_message(self, message_id: int) -> None:
        try:
            await self.bot.db.execute(
                "DELETE FROM message_log_cache WHERE message_id = ?",
                (message_id,),
            )
        except Exception:
            logger.warning("Étape non critique ignorée dans _forget_cached_message", exc_info=True)

    async def _log_deleted_from_row(
        self,
        guild: discord.Guild,
        row,
        *,
        fallback_channel_id: int | None = None,
    ) -> bool:
        message_id = int(row["message_id"])
        channel_id = int(row["channel_id"] or fallback_channel_id or 0)
        author_id = int(row["author_id"])
        content = row["content"] or ""
        try:
            attachments = json.loads(row["attachments"] or "[]")
        except (TypeError, ValueError, json.JSONDecodeError):
            attachments = []
        media_items = _attachment_media(attachments)
        actor, audit = await self._message_delete_actor(
            guild,
            author_id,
            channel_id,
            message_id=message_id,
        ) if channel_id else (None, None)
        fields = [
            ("Auteur", _user_ref(author_id), True),
            ("Supprimé par", self._delete_actor_text(actor), True),
            ("Salon", _channel_ref(channel_id) if channel_id else None, True),
            ("Contenu", _short(content, 1024) if content else None, False),
            ("Pièces jointes", _attachment_summary(media_items), False),
        ]
        member = guild.get_member(author_id)
        identity = member
        if identity is None:
            cached_name = str(row["author_name"] or "").strip()
            if cached_name:
                identity = SimpleNamespace(
                    id=author_id,
                    display_name=cached_name,
                    name=cached_name,
                    display_avatar=None,
                )
        panel = self._embed("Message supprimé", identity=identity, fields=fields)
        media_items, transcript_files = _attach_message_transcript(
            panel, guild_id=guild.id, channel_id=channel_id, message_id=message_id,
            author_id=author_id, sections=[("Contenu", content)], media_items=media_items,
        )
        links = [
            ("Accéder au salon", _discord_channel_url(guild.id, channel_id))
        ] if channel_id else []
        links.extend(_attachment_links(media_items))
        view = log_service.log_actions(
            ids=[
                ("Copier l'ID de l'auteur", author_id),
                ("Copier l'ID du message", message_id),
            ],
            links=links,
        )
        key = log_service.make_event_key(
            guild.id,
            "message_delete",
            target_id=author_id,
            message_id=message_id,
        )
        return await self._send(
            guild,
            "message_delete",
            panel,
            view=view,
            event_key=key,
            media_items=media_items,
            media_files=transcript_files,
        )

    # ---------------------------------------------------------------- MESSAGES

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        await self._cache_message(message)

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        logger.debug(
            "SXTRACE 1 LISTENER event=on_message_delete cog=cogs.logs guild=%s channel=%s "
            "message=%s author=%s author_bot=%s",
            getattr(message.guild, "id", None),
            getattr(message.channel, "id", None),
            message.id,
            getattr(message.author, "id", None),
            getattr(message.author, "bot", None),
        )
        if message.guild is None or message.author.bot:
            logger.debug(
                "SXTRACE 1 LISTENER skipped=GUILD_NONE_OR_BOT_AUTHOR message=%s", message.id
            )
            return
        if log_service.is_purged(message.id):
            # Supprimé par +clear : le récapitulatif de purge remplace la carte individuelle.
            return
        actor, audit = await self._message_delete_actor(
            message.guild,
            message.author.id,
            message.channel.id,
            message_id=message.id,
        )
        media_items = _attachment_media(message.attachments)
        preview_items, media_files = await _snapshot_deleted_images(message.attachments, media_items)
        fields = [
            ("Auteur", _user_ref(message.author.id), True),
            ("Supprimé par", self._delete_actor_text(actor), True),
            ("Salon", _channel_ref(message.channel.id), True),
            ("Contenu", _short(message.content, 1024) if message.content else None, False),
            ("Pièces jointes", _attachment_summary(media_items), False),
        ]
        panel = self._embed("Message supprimé", identity=message.author, fields=fields)
        preview_items, media_files = _attach_message_transcript(
            panel, guild_id=message.guild.id, channel_id=message.channel.id,
            message_id=message.id, author_id=message.author.id,
            sections=[("Contenu", message.content or "")],
            media_items=preview_items, media_files=media_files,
        )
        view = log_service.log_actions(
            ids=[
                ("Copier l'ID de l'auteur", message.author.id),
                ("Copier l'ID du message", message.id),
            ],
            links=_attachment_links(media_items),
        )
        key = log_service.make_event_key(
            message.guild.id,
            "message_delete",
            target_id=message.author.id,
            message_id=message.id,
        )
        sent = await self._send(
            message.guild,
            "message_delete",
            panel,
            view=view,
            event_key=key,
            media_items=preview_items,
            media_files=media_files,
        )
        if sent:
            await self._forget_cached_message(message.id)

    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload: discord.RawMessageDeleteEvent):
        logger.debug(
            "SXTRACE 1 LISTENER event=on_raw_message_delete cog=cogs.logs guild=%s channel=%s "
            "message=%s cached=%s",
            payload.guild_id,
            payload.channel_id,
            payload.message_id,
            payload.cached_message is not None,
        )
        if log_service.is_purged(payload.message_id):
            return
        if payload.guild_id is None or payload.cached_message is not None:
            logger.debug(
                "SXTRACE 1 LISTENER skipped=NO_GUILD_OR_ALREADY_CACHED message=%s",
                payload.message_id,
            )
            return
        guild = self.bot.get_guild(payload.guild_id)
        if guild is None:
            return
        row = await self._cached_message_row(payload.guild_id, payload.message_id)
        if row is not None:
            sent = await self._log_deleted_from_row(
                guild,
                row,
                fallback_channel_id=payload.channel_id,
            )
            if sent:
                await self._forget_cached_message(payload.message_id)
            return
        panel = self._embed(
            "Message supprimé",
            fields=(("Salon", _channel_ref(payload.channel_id), True),),
            description="Le contenu n’était pas disponible dans le cache SentriX.",
        )
        view = log_service.log_actions(
            ids=[("Copier l'ID du message", payload.message_id)],
            links=[(
                "Accéder au salon",
                _discord_channel_url(guild.id, payload.channel_id),
            )],
        )
        key = log_service.make_event_key(
            guild.id,
            "message_delete",
            message_id=payload.message_id,
        )
        await self._send(guild, "message_delete", panel, view=view, event_key=key)

    @commands.Cog.listener()
    async def on_raw_bulk_message_delete(self, payload: discord.RawBulkMessageDeleteEvent):
        if payload.guild_id is None:
            return
        guild = self.bot.get_guild(payload.guild_id)
        if guild is None:
            return

        for message_id in payload.message_ids:
            # Un lot peut mélanger des messages supprimés par +clear et d'autres
            # suppressions. Tester seulement "all(...)" reloggait les messages du
            # clear dès qu'un seul message du lot venait d'une autre source.
            if log_service.is_purged(message_id):
                continue

            try:
                row = await self._cached_message_row(payload.guild_id, message_id)
                if row is None:
                    continue
                sent = await self._log_deleted_from_row(
                    guild,
                    row,
                    fallback_channel_id=payload.channel_id,
                )
                if sent:
                    await self._forget_cached_message(message_id)
            except Exception:
                # Une entrée de cache invalide ou un échec de log ne doit jamais
                # empêcher les autres messages du même lot d'être traités.
                logger.exception(
                    "Journal bulk delete impossible guild=%s message=%s ; poursuite du lot.",
                    payload.guild_id,
                    message_id,
                )

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if after.guild is not None:
            await self._cache_message(after)
        if (
            before.guild is None
            or before.author.bot
            or before.content == after.content
        ):
            return
        panel = self._embed(
            "Message modifié",
            identity=after.author,
            fields=(
                ("Auteur", _user_ref(after.author.id), True),
                ("Salon", _channel_ref(after.channel.id), True),
                ("Avant", _short(before.content, 1024) or "Contenu vide", False),
                ("Après", _short(after.content, 1024) or "Contenu vide", False),
            ),
        )
        transcript_media, transcript_files = _attach_message_transcript(
            panel, guild_id=after.guild.id, channel_id=after.channel.id,
            message_id=after.id, author_id=after.author.id,
            sections=[("Avant", before.content or ""), ("Après", after.content or "")],
            media_items=_attachment_media(getattr(after, "attachments", [])),
        )
        view = log_service.log_actions(
            jump_url=after.jump_url,
            ids=[
                ("Copier l'ID de l'auteur", after.author.id),
                ("Copier l'ID du message", after.id),
            ],
        )
        key = log_service.make_event_key(
            after.guild.id,
            "message_edit",
            target_id=after.author.id,
            message_id=after.id,
            discriminator=int(after.edited_at.timestamp()) if after.edited_at else time.time_ns(),
        )
        await self._send(
            after.guild, "message_edit", panel, view=view, event_key=key,
            media_items=transcript_media, media_files=transcript_files,
        )

    # ---------------------------------------------------------------- MEMBRES / MODÉRATION

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        fields = [
            ("Membre", _user_ref(member.id), True),
            ("Compte créé", discord.utils.format_dt(member.created_at, "F"), True),
            ("Arrivée", discord.utils.format_dt(member.joined_at or discord.utils.utcnow(), "F"), True),
        ]
        if not member.bot:
            # Ce que le serveur sait déjà de cette personne : départs passés,
            # sanctions liées à son identifiant, compte récent.
            from utils import sentrix_trace

            try:
                memory = await sentrix_trace.join_memory(self.bot, member.guild, member)
            except Exception:
                logger.exception("Mémoire d'arrivée illisible guild=%s user=%s", member.guild.id, member.id)
                memory = ""
            if memory:
                fields.append(("Mémoire", memory, False))
        panel = self._embed("Membre arrivé", identity=member, fields=fields)
        view = log_service.log_actions(ids=[("Copier l'ID du membre", member.id)])
        # Chaque séjour a sa propre date d'arrivée Discord : un même événement reçu
        # deux fois garde la même clé, un départ suivi d'un retour en moins de 8 s
        # (motif d'un raid) donne deux cartes au lieu d'une.
        key = log_service.make_event_key(
            member.guild.id, "member_join", target_id=member.id, discriminator=_stay_of(member),
        )
        await self._send(member.guild, "member_join", panel, view=view, event_key=key)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        # Un ban ne doit pas produire un second log « Membre parti ».
        if log_service.is_recent_sanction(member.guild.id, member.id, "ban"):
            return
        roles_before = [
            f"{role.mention} ({role.name})"
            for role in member.roles
            if role.id != member.guild.default_role.id
        ]
        roles_snapshot = ", ".join(roles_before)[:990] or "Aucun rôle attribué"
        # Un kick déclenche aussi on_member_remove. On le reconnaît par Audit Log afin
        # d'éviter le doublon « Membre expulsé » + « Membre parti ».
        actor, audit = await self._audit_actor(
            member.guild,
            discord.AuditLogAction.kick,
            member.id,
        )
        if audit is not None:
            if log_service.is_recent_sanction(member.guild.id, member.id, "kick"):
                return  # +kick : le dossier de modération est le seul log
            fields = [
                ("Membre", _user_ref(member.id), True),
                ("Rôles avant le départ", roles_snapshot, False),
            ]
            if actor:
                fields.append(("Modérateur", _user_ref(actor.id), True))
            if audit.reason:
                fields.append(("Raison", _short(audit.reason, 1024), False))
            panel = self._embed("Membre expulsé", identity=member, fields=fields)
            ids = [("Copier l'ID du membre", member.id)]
            if actor:
                ids.append(("Copier l'ID du modérateur", actor.id))
            view = log_service.log_actions(ids=ids)
            key = log_service.make_event_key(
                member.guild.id,
                "kick",
                target_id=member.id,
                executor_id=getattr(actor, "id", None),
                audit_log_id=audit.id,
            )
            await self._send(
                member.guild,
                "member_kick",
                panel,
                view=view,
                event_key=key,
            )
            return

        fields = [
            ("Membre", _user_ref(member.id), True),
            ("Rôles avant le départ", roles_snapshot, False),
        ]
        if member.joined_at:
            duration = discord.utils.utcnow() - member.joined_at
            fields.append(("Présence", f"{max(0, duration.days)} jour(s)", True))
        panel = self._embed("Membre parti", identity=member, fields=fields)
        view = log_service.log_actions(ids=[("Copier l'ID du membre", member.id)])
        key = log_service.make_event_key(
            member.guild.id, "member_leave", target_id=member.id, discriminator=_stay_of(member),
        )
        await self._send(member.guild, "member_leave", panel, view=view, event_key=key)

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        if before.nick != after.nick:
            actor, audit = await self._resolve_actor(
                after.guild,
                discord.AuditLogAction.member_update,
                after.id,
            )
            fields = [
                ("Membre", _user_ref(after.id), True),
                ("Avant", before.display_name, True),
                ("Après", after.display_name, True),
            ]
            if actor:
                fields.append(("Responsable", _user_ref(actor.id), True))
            panel = self._embed("Surnom modifié", identity=after, fields=fields)
            ids = [("Copier l'ID du membre", after.id)]
            if actor:
                ids.append(("Copier l'ID du responsable", actor.id))
            key = log_service.make_event_key(
                after.guild.id,
                "nickname_update",
                target_id=after.id,
                executor_id=getattr(actor, "id", None),
                audit_log_id=getattr(audit, "id", None),
                discriminator=after.display_name,
            )
            await self._send(
                after.guild,
                "member_update",
                panel,
                view=log_service.log_actions(ids=ids),
                event_key=key,
            )

        before_roles = {role.id: role for role in before.roles[1:]}
        after_roles = {role.id: role for role in after.roles[1:]}
        added = [role for role_id, role in after_roles.items() if role_id not in before_roles]
        removed = [role for role_id, role in before_roles.items() if role_id not in after_roles]
        actor, audit = (None, None)
        if added or removed:
            actor, audit = await self._resolve_actor(
                after.guild,
                discord.AuditLogAction.member_role_update,
                after.id,
            )

        for event_name, roles in (("Rôle ajouté", added), ("Rôle retiré", removed)):
            event_type = "role_add" if event_name == "Rôle ajouté" else "role_remove"
            for role in roles:
                fields = [
                    ("Membre", _user_ref(after.id), True),
                    ("Rôle", _role_ref(role.id), True),
                ]
                if actor:
                    fields.append(("Modérateur", _user_ref(actor.id), True))
                panel = self._embed(event_name, identity=after, fields=fields)
                ids = [
                    ("Copier l'ID du membre", after.id),
                    ("Copier l'ID du rôle", role.id),
                ]
                if actor:
                    ids.append(("Copier l'ID du modérateur", actor.id))
                key = log_service.make_event_key(
                    after.guild.id,
                    event_type,
                    target_id=after.id,
                    executor_id=getattr(actor, "id", None),
                    audit_log_id=getattr(audit, "id", None),
                    discriminator=role.id,
                )
                await self._send(
                    after.guild,
                    event_type,
                    panel,
                    view=log_service.log_actions(ids=ids),
                    event_key=key,
                )

        if _active_timeout(before) != _active_timeout(after):
            if log_service.is_recent_sanction(after.guild.id, after.id, "timeout"):
                # +mute / +unmute : le dossier de modération est LE log (modérateur réel,
                # durée, raison). Pas de seconde carte « Modérateur : SentriX ».
                return
            actor, audit = await self._audit_actor(
                after.guild,
                discord.AuditLogAction.member_update,
                after.id,
            )
            fields = [("Membre", _user_ref(after.id), True)]
            if actor:
                fields.append(("Modérateur", _user_ref(actor.id), True))
            fin = _active_timeout(after)
            if fin:
                duree = _timeout_duration_label(fin)
                if duree:
                    fields.append(("Durée restante", duree, True))
                fields.append(("Fin prévue", discord.utils.format_dt(fin, "F"), True))
            panel = self._embed(
                "Timeout appliqué" if fin else "Timeout retiré",
                identity=after,
                fields=fields,
            )
            ids = [("Copier l'ID du membre", after.id)]
            if actor:
                ids.append(("Copier l'ID du modérateur", actor.id))
            key = log_service.make_event_key(
                after.guild.id,
                "timeout",
                target_id=after.id,
                executor_id=getattr(actor, "id", None),
                audit_log_id=getattr(audit, "id", None),
                discriminator=int(fin.timestamp()) if fin else 0,
            )
            await self._send(
                after.guild,
                "member_timeout",
                panel,
                view=log_service.log_actions(ids=ids),
                event_key=key,
            )

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User | discord.Member):
        if log_service.is_recent_sanction(guild.id, user.id, "ban"):
            return  # +ban / +tempban : le dossier de modération est le seul log
        actor, audit = await self._audit_actor(guild, discord.AuditLogAction.ban, user.id)
        fields = [("Membre", _user_ref(user.id), True)]
        if actor:
            fields.append(("Modérateur", _user_ref(actor.id), True))
        if audit and audit.reason:
            fields.append(("Raison", _short(audit.reason, 1024), False))
        panel = self._embed("Membre banni", identity=user, fields=fields)
        ids = [("Copier l'ID du membre", user.id)]
        if actor:
            ids.append(("Copier l'ID du modérateur", actor.id))
        key = log_service.make_event_key(
            guild.id,
            "ban",
            target_id=user.id,
            executor_id=getattr(actor, "id", None),
            audit_log_id=getattr(audit, "id", None),
        )
        await self._send(
            guild,
            "member_ban",
            panel,
            view=log_service.log_actions(ids=ids),
            event_key=key,
        )

    @commands.Cog.listener()
    async def on_member_unban(self, guild: discord.Guild, user: discord.User):
        if log_service.is_recent_sanction(guild.id, user.id, "unban"):
            return  # +unban : le dossier de modération est le seul log
        actor, audit = await self._audit_actor(guild, discord.AuditLogAction.unban, user.id)
        fields = [("Utilisateur", _user_ref(user.id), True)]
        if actor:
            fields.append(("Modérateur", _user_ref(actor.id), True))
        if audit and audit.reason:
            fields.append(("Raison", _short(audit.reason, 1024), False))
        panel = self._embed("Membre débanni", identity=user, fields=fields)
        ids = [("Copier l'ID du membre", user.id)]
        if actor:
            ids.append(("Copier l'ID du modérateur", actor.id))
        key = log_service.make_event_key(
            guild.id,
            "unban",
            target_id=user.id,
            executor_id=getattr(actor, "id", None),
            audit_log_id=getattr(audit, "id", None),
        )
        await self._send(
            guild,
            "member_unban",
            panel,
            view=log_service.log_actions(ids=ids),
            event_key=key,
        )

    # ---------------------------------------------------------------- VOCAL

    @commands.Cog.listener()
    async def on_ready(self):
        """Preserve ongoing sessions after a restart without counting downtime as fact."""
        if not log_service.is_primary_process():
            return
        for guild in self.bot.guilds:
            try:
                await voice_history.reconcile_guild(self.bot, guild)
            except Exception:
                logger.exception("Impossible de réconcilier le suivi vocal guild=%s", guild.id)

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ):
        if (
            before.channel == after.channel
            and before.self_mute == after.self_mute
            and before.self_deaf == after.self_deaf
        ):
            return
        fields = [("Membre", _user_ref(member.id), True)]
        if before.channel != after.channel:
            fields.extend(
                (
                    ("Avant", _channel_ref(before.channel.id) if before.channel else "Hors vocal", True),
                    ("Après", _channel_ref(after.channel.id) if after.channel else "Hors vocal", True),
                )
            )
        if before.self_mute != after.self_mute:
            fields.append(("Micro", "Coupé" if after.self_mute else "Activé", True))
        if before.self_deaf != after.self_deaf:
            fields.append(("Casque", "Désactivé" if after.self_deaf else "Activé", True))
        if before.channel is None and after.channel is not None:
            voice_type = "voice_join"
        elif before.channel is not None and after.channel is None:
            voice_type = "voice_leave"
        elif before.channel != after.channel:
            voice_type = "voice_move"
        else:
            voice_type = "voice_state"
        transition = None
        if (voice_type in {"voice_join", "voice_move", "voice_leave"}
                and not member.bot and log_service.is_primary_process()):
            try:
                transition = await voice_history.record_transition(
                    self.bot, member.guild.id, member.id,
                    before.channel.id if before.channel else None,
                    after.channel.id if after.channel else None,
                )
                if transition and transition.duration_seconds is not None:
                    fields.append((
                        "Durée de la session",
                        voice_history.duration_label(transition.duration_seconds),
                        True,
                    ))
                if (transition and transition.segment_seconds is not None
                        and voice_type == "voice_move"):
                    fields.append((
                        "Temps dans le salon précédent",
                        voice_history.duration_label(transition.segment_seconds),
                        True,
                    ))
            except Exception:
                logger.exception(
                    "Suivi vocal impossible : guild=%s member=%s",
                    member.guild.id, member.id,
                )
        if transition and voice_type == "voice_move" and not transition.archive:
            # Le staff a explicitement désactivé les déplacements dans
            # /config logs. Garder la base de session à jour pour les durées,
            # mais ne pas publier ni archiver ce déplacement.
            return
        panel = self._embed("Activité vocale", identity=member, fields=fields)
        key = log_service.make_event_key(
            member.guild.id,
            voice_type,
            target_id=member.id,
            discriminator=f"{getattr(after.channel, 'id', 0)}:{after.self_mute}:{after.self_deaf}",
        )
        delivered = await self._send(member.guild, voice_type, panel, event_key=key)
        # /config logs peut activer l'archivage staff sans activer de salon
        # public de logs. Ne jamais doubler les événements déjà envoyés.
        if transition and transition.archive and not delivered:
            try:
                await voice_history.archive_undelivered_event(
                    member.guild.id, voice_type, panel,
                )
            except Exception:
                logger.exception(
                    "Impossible d'archiver l'événement vocal guild=%s member=%s",
                    member.guild.id, member.id,
                )

    # ---------------------------------------------------------------- SALONS

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel):
        actor, audit = await self._audit_actor(
            channel.guild,
            discord.AuditLogAction.channel_create,
            channel.id,
        )
        est_categorie = _est_categorie(channel)
        nom = "Catégorie" if est_categorie else "Salon"
        fields = [(nom, _channel_ref(channel.id), True), ("Type", str(channel.type), True)]
        if actor:
            fields.append(("Responsable", _user_ref(actor.id), True))
        panel = self._embed("Catégorie créée" if est_categorie else "Salon créé", fields=fields)
        ids = [("Copier l'ID de la catégorie" if est_categorie else "Copier l'ID du salon", channel.id)]
        if actor:
            ids.append(("Copier l'ID du responsable", actor.id))
        key = log_service.make_event_key(
            channel.guild.id,
            "channel_create",
            target_id=channel.id,
            executor_id=getattr(actor, "id", None),
            audit_log_id=getattr(audit, "id", None),
        )
        await self._send(
            channel.guild,
            "channel_create",
            panel,
            view=log_service.log_actions(
                ids=ids,
                links=[("Accéder au salon", _discord_channel_url(channel.guild.id, channel.id))],
            ),
            event_key=key,
        )

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel):
        actor, audit = await self._audit_actor(
            channel.guild,
            discord.AuditLogAction.channel_delete,
            channel.id,
        )
        est_categorie = _est_categorie(channel)
        fields = [("Catégorie" if est_categorie else "Salon", f"`{channel.name}`", True)]
        if actor:
            fields.append(("Responsable", _user_ref(actor.id), True))
        panel = self._embed(
            "Catégorie supprimée" if est_categorie else "Salon supprimé", fields=fields
        )
        ids = [("Copier l'ID de la catégorie" if est_categorie else "Copier l'ID du salon", channel.id)]
        if actor:
            ids.append(("Copier l'ID du responsable", actor.id))
        key = log_service.make_event_key(
            channel.guild.id,
            "channel_delete",
            target_id=channel.id,
            executor_id=getattr(actor, "id", None),
            audit_log_id=getattr(audit, "id", None),
        )
        await self._send(
            channel.guild,
            "channel_delete",
            panel,
            view=log_service.log_actions(ids=ids),
            event_key=key,
        )

    @commands.Cog.listener()
    async def on_guild_channel_update(
        self,
        before: discord.abc.GuildChannel,
        after: discord.abc.GuildChannel,
    ):
        # Une catégorie passe par le même évènement qu'un salon. L'annoncer comme
        # un « salon » ferait chercher un salon qui n'existe pas.
        est_categorie = _est_categorie(after)
        fields = [("Catégorie" if est_categorie else "Salon", _channel_ref(after.id), True)]
        if before.name != after.name:
            fields.append(("Nom", f"`{before.name}` → `{after.name}`", False))
        if before.category_id != after.category_id:
            before_category = _channel_ref(before.category_id) if before.category_id else "Aucune"
            after_category = _channel_ref(after.category_id) if after.category_id else "Aucune"
            # Libellé distinct du champ d'identité : sur la carte d'une catégorie,
            # deux champs « Catégorie » rendaient la lecture ambiguë.
            fields.append(("Dans la catégorie", f"{before_category} → {after_category}", False))
        if getattr(before, "topic", None) != getattr(after, "topic", None):
            before_topic = getattr(before, "topic", None)
            after_topic = getattr(after, "topic", None)
            # Les tickets mettent à jour leur sujet interne ("Opened … · Claimed …").
            # Le journal Tickets couvre déjà ces actions ; les recopier dans Salons
            # exposait du texte technique et créait un log CH-UPD inutile.
            if not (
                _is_ticket_system_topic(before_topic)
                and _is_ticket_system_topic(after_topic)
            ):
                fields.append(
                    (
                        "Sujet",
                        f"`{_short(before_topic or 'Vide', 400)}` → "
                        f"`{_short(after_topic or 'Vide', 400)}`",
                        False,
                    )
                )
        if getattr(before, "slowmode_delay", None) != getattr(after, "slowmode_delay", None):
            fields.append(
                (
                    "Slowmode",
                    f"`{getattr(before, 'slowmode_delay', 0)} s` → "
                    f"`{getattr(after, 'slowmode_delay', 0)} s`",
                    False,
                )
            )
        # Les permissions : jusqu'ici un changement de dérogation ne produisait
        # AUCUN log. Un staff pouvait ouvrir un salon privé à un rôle sans
        # qu'il en reste la moindre trace, alors que renommer le salon en
        # laissait une.
        try:
            change_perms = _diff_derogations(
                getattr(before, "overwrites", {}) or {},
                getattr(after, "overwrites", {}) or {},
            )
        except Exception:
            logger.exception("Comparaison des dérogations impossible (salon=%s).", after.id)
            change_perms = []
        if change_perms and est_categorie:
            _noter_perms_de_categorie(after.guild.id, after.id)
        if change_perms and len(fields) == 1 and not est_categorie:
            if _est_propagation_de_categorie(after):
                logger.debug(
                    "Permissions propagées depuis la catégorie %s : carte du salon %s "
                    "inutile, celle de la catégorie la porte déjà.",
                    getattr(after, "category_id", None), after.id,
                )
                return
        if change_perms:
            fields.append(
                ("Permissions", _short(_texte_derogations(change_perms), 1000), False)
            )
            if est_categorie and getattr(after, "channels", None):
                synchronises = sum(
                    1 for salon in after.channels
                    if getattr(salon, "permissions_synced", False)
                )
                if synchronises:
                    fields.append(
                        (
                            "Propagation",
                            f"Appliqué aux {synchronises} salon(s) synchronisé(s) "
                            "de cette catégorie.",
                            False,
                        )
                    )

        if len(fields) == 1:
            return
        actor, audit = await self._audit_actor(
            after.guild,
            discord.AuditLogAction.channel_update
            if len(fields) > 2 or not change_perms
            else discord.AuditLogAction.overwrite_update,
            after.id,
        )
        if actor:
            fields.append(("Responsable", _user_ref(actor.id), True))
        panel = self._embed(
            "Catégorie modifiée" if est_categorie else "Salon modifié", fields=fields
        )
        ids = [("Copier l'ID de la catégorie" if est_categorie else "Copier l'ID du salon", after.id)]
        if actor:
            ids.append(("Copier l'ID du responsable", actor.id))
        key = log_service.make_event_key(
            after.guild.id,
            "channel_update",
            target_id=after.id,
            executor_id=getattr(actor, "id", None),
            audit_log_id=getattr(audit, "id", None),
            discriminator=":".join(str(field[1]) for field in fields),
        )
        await self._send(
            after.guild,
            "channel_update",
            panel,
            view=log_service.log_actions(
                ids=ids,
                links=[("Accéder au salon", _discord_channel_url(after.guild.id, after.id))],
            ),
            event_key=key,
        )

    # ---------------------------------------------------------------- RÔLES

    @commands.Cog.listener()
    async def on_guild_role_create(self, role: discord.Role):
        actor, audit = await self._audit_actor(
            role.guild,
            discord.AuditLogAction.role_create,
            role.id,
        )
        fields = [("Rôle", _role_ref(role.id), True)]
        if actor:
            fields.append(("Responsable", _user_ref(actor.id), True))
        panel = self._embed("Rôle créé", fields=fields)
        ids = [("Copier l'ID du rôle", role.id)]
        if actor:
            ids.append(("Copier l'ID du responsable", actor.id))
        key = log_service.make_event_key(
            role.guild.id,
            "role_create",
            target_id=role.id,
            executor_id=getattr(actor, "id", None),
            audit_log_id=getattr(audit, "id", None),
        )
        await self._send(
            role.guild,
            "role_create",
            panel,
            view=log_service.log_actions(ids=ids),
            event_key=key,
        )

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role):
        actor, audit = await self._audit_actor(
            role.guild,
            discord.AuditLogAction.role_delete,
            role.id,
        )
        fields = [("Rôle", f"`{role.name}`", True)]
        if actor:
            fields.append(("Responsable", _user_ref(actor.id), True))
        panel = self._embed("Rôle supprimé", fields=fields)
        ids = [("Copier l'ID du rôle", role.id)]
        if actor:
            ids.append(("Copier l'ID du responsable", actor.id))
        key = log_service.make_event_key(
            role.guild.id,
            "role_delete",
            target_id=role.id,
            executor_id=getattr(actor, "id", None),
            audit_log_id=getattr(audit, "id", None),
        )
        await self._send(
            role.guild,
            "role_delete",
            panel,
            view=log_service.log_actions(ids=ids),
            event_key=key,
        )

    @commands.Cog.listener()
    async def on_guild_role_update(self, before: discord.Role, after: discord.Role):
        fields = [("Rôle", _role_ref(after.id), True)]
        if before.name != after.name:
            fields.append(("Nom", f"`{before.name}` → `{after.name}`", False))
        if before.colour != after.colour:
            fields.append(
                (
                    "Couleur",
                    f"`#{before.colour.value:06X}` → `#{after.colour.value:06X}`",
                    False,
                )
            )
        before_permissions = _permission_names(before.permissions)
        after_permissions = _permission_names(after.permissions)
        added = sorted(after_permissions - before_permissions)
        removed = sorted(before_permissions - after_permissions)
        if added:
            fields.extend(_permission_badge_fields("Permissions ajoutées", added))
        if removed:
            fields.extend(_permission_badge_fields("Permissions supprimées", removed))
        if len(fields) == 1:
            return
        actor, audit = await self._audit_actor(
            after.guild,
            discord.AuditLogAction.role_update,
            after.id,
        )
        if actor:
            fields.append(("Responsable", _user_ref(actor.id), True))
        panel = self._embed("Rôle modifié", fields=fields)
        ids = [("Copier l'ID du rôle", after.id)]
        if actor:
            ids.append(("Copier l'ID du responsable", actor.id))
        key = log_service.make_event_key(
            after.guild.id,
            "role_update",
            target_id=after.id,
            executor_id=getattr(actor, "id", None),
            audit_log_id=getattr(audit, "id", None),
            discriminator=":".join(str(field[1]) for field in fields),
        )
        await self._send(
            after.guild,
            "role_update",
            panel,
            view=log_service.log_actions(ids=ids),
            event_key=key,
        )

    # ---------------------------------------------------------------- SERVEUR

    @commands.Cog.listener()
    async def on_guild_update(self, before: discord.Guild, after: discord.Guild):
        fields = []
        if before.name != after.name:
            fields.append(("Nom", f"`{before.name}` → `{after.name}`", False))
        if before.verification_level != after.verification_level:
            fields.append(
                (
                    "Niveau de vérification",
                    f"`{before.verification_level}` → `{after.verification_level}`",
                    False,
                )
            )
        if before.afk_timeout != after.afk_timeout:
            fields.append(
                (
                    "Délai AFK",
                    f"`{before.afk_timeout} s` → `{after.afk_timeout} s`",
                    False,
                )
            )
        if not fields:
            return
        actor, audit = await self._audit_actor(
            after,
            discord.AuditLogAction.guild_update,
            after.id,
        )
        if actor:
            fields.append(("Responsable", _user_ref(actor.id), True))
        panel = self._embed("Serveur modifié", fields=fields)
        ids = []
        if actor:
            ids.append(("Copier l'ID du responsable", actor.id))
        key = log_service.make_event_key(
            after.id,
            "guild_update",
            target_id=after.id,
            executor_id=getattr(actor, "id", None),
            audit_log_id=getattr(audit, "id", None),
            discriminator=":".join(str(field[1]) for field in fields),
        )
        await self._send(
            after,
            "guild_update",
            panel,
            view=log_service.log_actions(ids=ids),
            event_key=key,
        )


async def setup(bot: commands.Bot):
    await bot.db.execute(MESSAGE_CACHE_SCHEMA)
    await bot.db.execute(
        "CREATE INDEX IF NOT EXISTS idx_message_log_cache_stored_at "
        "ON message_log_cache(stored_at)"
    )
    await bot.db.execute(
        "DELETE FROM message_log_cache WHERE stored_at < ?",
        (int(time.time()) - MESSAGE_CACHE_RETENTION_SECONDS,),
    )
    await bot.add_cog(Logs(bot))
