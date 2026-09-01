"""Panneau de suivi automatique de SentriX."""
from __future__ import annotations

import asyncio
import logging
import time

import discord
from discord.ext import commands, tasks

from utils import embeds

logger = logging.getLogger("bot.tracker")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS bot_tracker_panels (
    guild_id INTEGER PRIMARY KEY,
    channel_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    created_by INTEGER NOT NULL,
    created_at INTEGER NOT NULL
)
"""

_INSTALLED = False
_COG_NAME = "BotTracker"
_MEMBER_EVENT_TTL = 10.0
_MEMBER_EVENT_RECENT: dict[tuple[str, int, int], float] = {}


def _duration(seconds: int) -> str:
    days, rem = divmod(max(0, seconds), 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    if days:
        return f"{days}j {hours}h {minutes}m"
    if hours:
        return f"{hours}h {minutes}m {secs}s"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def _member_message(text: str, member: discord.Member) -> str:
    """Résout les variables d'accueil/départ avec une vraie mention Discord.

    ``{member}`` reste la variable historique et ``{user}`` devient un alias simple.
    On accepte aussi les anciens placeholders visuels ``(user)`` et ``[user]`` afin
    qu'un message déjà enregistré n'affiche plus littéralement « user ».
    """
    replacements = (
        ("{member}", member.mention),
        ("{user}", member.mention),
        ("(user)", member.mention),
        ("[user]", member.mention),
        ("<user>", member.mention),
        ("{username}", member.display_name),
        ("{display_name}", member.display_name),
        ("{server}", member.guild.name),
        ("{member_count}", str(member.guild.member_count or 0)),
    )
    value = str(text or "")
    for placeholder, replacement in replacements:
        value = value.replace(placeholder, replacement)
    return value


def _claim_member_event(kind: str, member: discord.Member) -> bool:
    """Déduplique les dispatchs répétés dans un même processus pendant quelques secondes."""
    now_value = time.monotonic()
    key = (str(kind), int(member.guild.id), int(member.id))
    previous = _MEMBER_EVENT_RECENT.get(key)
    if previous is not None and now_value - previous <= _MEMBER_EVENT_TTL:
        return False
    _MEMBER_EVENT_RECENT[key] = now_value
    if len(_MEMBER_EVENT_RECENT) > 4096:
        cutoff = now_value - _MEMBER_EVENT_TTL
        for stale_key, seen_at in tuple(_MEMBER_EVENT_RECENT.items()):
            if seen_at < cutoff:
                _MEMBER_EVENT_RECENT.pop(stale_key, None)
    return True


def _presence_matches(message: discord.Message, member: discord.Member, kind: str) -> bool:
    """Reconnaît uniquement un message d'accueil/départ SentriX pour CE membre."""
    blob = [str(message.content or "")]
    for embed in message.embeds:
        blob.append(str(embed.title or ""))
        blob.append(str(embed.description or ""))
        for field in embed.fields:
            blob.extend((str(field.name or ""), str(field.value or "")))
    text = "\n".join(blob)
    if member.mention not in text and str(member.id) not in text:
        return False
    lowered = text.casefold()
    if kind == "join":
        return "bienvenue" in lowered
    return "départ" in lowered or "depart" in lowered or "quitt" in lowered


async def _cleanup_presence_duplicates(
    bot: commands.Bot,
    channel: discord.TextChannel,
    member: discord.Member,
    kind: str,
) -> None:
    """Supprime le doublon même s'il vient d'un second processus avec le même bot.

    Deux processus peuvent passer une garde mémoire exactement au même instant. Discord est
    alors la source commune : après un court délai on garde le premier message SentriX et on
    retire les copies envoyées dans les 8 secondes suivantes.
    """
    await asyncio.sleep(1.25)
    bot_user = getattr(bot, "user", None)
    if bot_user is None:
        return
    now_utc = discord.utils.utcnow()
    matches: list[discord.Message] = []
    try:
        async for message in channel.history(limit=20):
            if message.author.id != bot_user.id:
                continue
            if abs((now_utc - message.created_at).total_seconds()) > 8:
                continue
            if _presence_matches(message, member, kind):
                matches.append(message)
    except (discord.Forbidden, discord.HTTPException):
        return
    if len(matches) <= 1:
        return

    keep = min(matches, key=lambda item: item.id)
    for duplicate in matches:
        if duplicate.id == keep.id:
            continue
        try:
            await duplicate.delete(reason="SentriX : suppression doublon bienvenue/départ")
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass
    logger.warning(
        "Accueil/départ dédupliqué guild=%s member=%s kind=%s copies=%s",
        member.guild.id,
        member.id,
        kind,
        len(matches),
    )


def _unwrap_v3(function):
    """Retire uniquement les wrappers legacy explicitement marqués Create SentriX V3."""
    current = function
    changed = False
    seen: set[int] = set()
    while callable(current) and id(current) not in seen:
        seen.add(id(current))
        if not (
            getattr(current, "_sentrix_v3_router", False)
            or getattr(current, "_sentrix_v3_no_fallback", False)
        ):
            break
        previous = getattr(current, "_sentrix_previous", None)
        if not callable(previous) or previous is current:
            break
        current = previous
        changed = True
    return current, changed


def _restore_canonical_log_pipeline() -> bool:
    """Rend cogs.logs + utils.log_service à nouveau seuls propriétaires du routage.

    ``create_sentrix_v3`` est chargé après le logger moderne et son ancien ``final_send``
    interprète les types modernes (member_join, role_add, channel_create...) comme une clé
    inconnue, donc les redirige vers ``server``. Cette garde s'exécute après READY afin de
    retirer uniquement ces wrappers V3, sans toucher aux autres systèmes du bot.
    """
    try:
        from cogs import logs as logs_cog
        from utils import log_categories, log_service
    except Exception:
        logger.exception("Impossible de restaurer le pipeline canonique des logs.")
        return False

    changed = False

    restored, did_change = _unwrap_v3(getattr(logs_cog.Logs, "_send", None))
    if did_change and callable(restored):
        logs_cog.Logs._send = restored
        changed = True

    restored, did_change = _unwrap_v3(getattr(log_service, "send_log", None))
    if did_change and callable(restored):
        log_service.send_log = restored
        changed = True

    restored, did_change = _unwrap_v3(getattr(log_service, "get_log_setting", None))
    if did_change and callable(restored):
        log_service.get_log_setting = restored
        changed = True

    # ``dossiers`` était une ancienne catégorie V3 supplémentaire. Le registre moderne
    # possède déjà ``resources`` et conserve ``dossiers`` uniquement comme alias legacy.
    if "dossiers" in log_categories.CATEGORIES:
        log_categories.CATEGORIES.pop("dossiers", None)
        changed = True
    log_categories.CATEGORY_ORDER = tuple(log_categories.CATEGORIES)

    expected_invites = {
        "invite_create": ("resources", "🔗", "success"),
        "invite_delete": ("resources", "🔗", "error"),
    }
    for event_name, expected in expected_invites.items():
        if log_categories.LOG_REGISTRY.get(event_name) != expected:
            log_categories.LOG_REGISTRY[event_name] = expected
            changed = True

    if "dossiers" in log_service.LOG_TYPES:
        log_service.LOG_TYPES.pop("dossiers", None)
        changed = True
    for key, label in log_categories.CATEGORIES.items():
        meta = log_service.LOG_TYPES.get(key)
        if meta is None:
            legacy_column = getattr(log_service, "_LEGACY_COLUMNS", {}).get(key)
            log_service.LOG_TYPES[key] = {
                "label": label,
                "category": label,
                "legacy_column": legacy_column,
                "emits": True,
            }
            changed = True
            continue
        if meta.get("label") != label or meta.get("category") != label or not meta.get("emits", True):
            meta["label"] = label
            meta["category"] = label
            meta["emits"] = True
            changed = True
    log_service.CATEGORY_ORDER = [
        log_categories.CATEGORIES[key]
        for key in log_categories.CATEGORY_ORDER
        if key in log_categories.CATEGORIES
    ]

    return changed


def _install_member_presence_mentions(bot: commands.Bot) -> None:
    """Rend les messages d'arrivée/départ cohérents et pingue le vrai membre.

    Le handler principal historique envoyait la bienvenue uniquement dans un embed : une
    mention dans un embed n'est pas un ping fiable. Il utilisait aussi ``str(member)`` au
    départ, et ne connaissait pas ``{user}``. On remplace seulement les deux handlers du
    Bot ; les listeners des autres cogs (logs, invites, niveaux...) continuent d'être
    dispatchés normalement par discord.py.
    """
    if getattr(bot, "_sentrix_member_presence_mentions_installed", False):
        return

    bot._sentrix_original_on_member_join = getattr(bot, "on_member_join", None)
    bot._sentrix_original_on_member_remove = getattr(bot, "on_member_remove", None)

    async def on_member_join(member: discord.Member):
        if not _claim_member_event("join", member):
            logger.warning("Bienvenue doublon ignoré guild=%s member=%s", member.guild.id, member.id)
            return

        conf = await bot.db.get_guild_config(member.guild.id)
        if not conf:
            return

        if conf["autorole"]:
            role = member.guild.get_role(conf["autorole"])
            if role:
                try:
                    await member.add_roles(role, reason="Rôle automatique à l'arrivée")
                except discord.Forbidden:
                    pass

        if not conf["welcome_channel"]:
            return
        channel = member.guild.get_channel(conf["welcome_channel"])
        if channel is None:
            return

        raw_text = conf["welcome_message"] or "Bienvenue {member} sur **{server}** !"
        text = _member_message(raw_text, member)
        try:
            welcome_embed = embeds.success(text, title=f"Bienvenue {member.display_name}")
            welcome_embed.set_thumbnail(url=member.display_avatar.url)
            if conf["welcome_image_url"]:
                welcome_embed.set_image(url=conf["welcome_image_url"])

            # Le ping est placé dans le contenu du message, pas seulement dans l'embed.
            # AllowedMentions limite strictement la notification à ce membre : un texte
            # personnalisé ne peut donc pas déclencher @everyone ou un rôle par accident.
            ping = None if member.bot else member.mention
            allowed = discord.AllowedMentions(
                everyone=False,
                roles=False,
                users=[] if member.bot else [member],
                replied_user=False,
            )
            await channel.send(content=ping, embed=welcome_embed, allowed_mentions=allowed)
            asyncio.create_task(
                _cleanup_presence_duplicates(bot, channel, member, "join"),
                name=f"sentrix-dedupe-welcome-{member.guild.id}-{member.id}",
            )
        except discord.HTTPException:
            pass

    async def on_member_remove(member: discord.Member):
        if not _claim_member_event("leave", member):
            logger.warning("Départ doublon ignoré guild=%s member=%s", member.guild.id, member.id)
            return

        conf = await bot.db.get_guild_config(member.guild.id)
        if not conf or not conf["goodbye_channel"]:
            return
        channel = member.guild.get_channel(conf["goodbye_channel"])
        if channel is None:
            return

        raw_text = conf["goodbye_message"] or "{member} a quitté **{server}**."
        text = _member_message(raw_text, member)
        try:
            # La mention reste réelle/clickable dans le message de départ. Discord ne peut
            # toutefois pas garantir une notification à quelqu'un qui a déjà quitté le
            # serveur au moment où l'événement member_remove est reçu.
            ping = None if member.bot else member.mention
            allowed = discord.AllowedMentions(
                everyone=False,
                roles=False,
                users=[] if member.bot else [member],
                replied_user=False,
            )
            await channel.send(
                content=ping,
                embed=embeds.neutral("Départ", text),
                allowed_mentions=allowed,
            )
            asyncio.create_task(
                _cleanup_presence_duplicates(bot, channel, member, "leave"),
                name=f"sentrix-dedupe-goodbye-{member.guild.id}-{member.id}",
            )
        except discord.HTTPException:
            pass

    bot.on_member_join = on_member_join
    bot.on_member_remove = on_member_remove
    bot._sentrix_member_presence_mentions_installed = True
    logger.info("Accueil/départ : vraie mention membre, alias {user} et anti-doublon activés.")


class BotTracker(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.started_at = int(time.time())
        self.refresh_panels.start()

    async def cog_unload(self):
        self.refresh_panels.cancel()

    @commands.Cog.listener()
    async def on_ready(self):
        # create_sentrix_v3 possède encore un on_ready historique qui peut réinstaller son
        # routeur après le chargement des extensions. On repasse légèrement après lui à
        # chaque connexion/reconnexion pour garantir une seule autorité de logs.
        await asyncio.sleep(1.0)
        changed = _restore_canonical_log_pipeline()
        if changed:
            logger.warning("Pipeline logs canonique restauré après les wrappers V3 legacy.")
        else:
            logger.info("Pipeline logs canonique déjà autoritaire.")

    def build_embed(self, guild: discord.Guild | None = None) -> discord.Embed:
        online = self.bot.is_ready()
        latency = round(self.bot.latency * 1000) if online else None
        total_members = sum(g.member_count or 0 for g in self.bot.guilds)
        command_count = sum(1 for _ in self.bot.walk_commands())
        uptime = _duration(int(time.time()) - self.started_at)
        now = int(time.time())

        embed = discord.Embed(
            title="Suivi de SentriX",
            description="État automatique du bot et de ses services Discord.",
            color=0x57F287 if online else 0xED4245,
        )
        embed.add_field(name="État", value="● En ligne" if online else "● Indisponible", inline=True)
        embed.add_field(name="Latence", value=f"{latency} ms" if latency is not None else "Indisponible", inline=True)
        embed.add_field(name="Uptime", value=uptime, inline=True)
        embed.add_field(name="Serveurs", value=f"{len(self.bot.guilds):,}".replace(",", " "), inline=True)
        embed.add_field(name="Membres", value=f"{total_members:,}".replace(",", " "), inline=True)
        embed.add_field(name="Commandes", value=str(command_count), inline=True)
        if guild is not None:
            embed.add_field(
                name="Serveur actuel",
                value=f"{guild.name} • {guild.member_count or 0} membre(s)",
                inline=False,
            )
        embed.add_field(name="Dernière actualisation", value=f"<t:{now}:R>", inline=False)
        embed.set_footer(text="SentriX • Suivi automatique • actualisation chaque minute")
        if self.bot.user:
            embed.set_thumbnail(url=self.bot.user.display_avatar.url)
        return embed

    async def _save_panel(self, guild_id: int, channel_id: int, message_id: int, creator_id: int):
        await self.bot.db.execute(
            "INSERT INTO bot_tracker_panels (guild_id, channel_id, message_id, created_by, created_at) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(guild_id) DO UPDATE SET "
            "channel_id=excluded.channel_id, message_id=excluded.message_id, created_by=excluded.created_by",
            (guild_id, channel_id, message_id, creator_id, int(time.time())),
        )

    @commands.command(
        name="suivi-bot",
        aliases=["suivibot", "bot-tracker", "bot-suivi"],
        help="Créer un panneau de suivi automatique de SentriX.",
    )
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def suivi_bot(self, ctx: commands.Context):
        row = await self.bot.db.fetchone(
            "SELECT * FROM bot_tracker_panels WHERE guild_id = ?",
            (ctx.guild.id,),
        )
        if row:
            old_channel = ctx.guild.get_channel(int(row["channel_id"]))
            if isinstance(old_channel, discord.TextChannel):
                try:
                    old_message = await old_channel.fetch_message(int(row["message_id"]))
                    if old_channel.id == ctx.channel.id:
                        await old_message.edit(embed=self.build_embed(ctx.guild))
                        return await ctx.send("Le panneau de suivi SentriX a été actualisé.")
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    pass

        message = await ctx.send(embed=self.build_embed(ctx.guild))
        await self._save_panel(ctx.guild.id, ctx.channel.id, message.id, ctx.author.id)

    @tasks.loop(minutes=1)
    async def refresh_panels(self):
        try:
            rows = await self.bot.db.fetchall("SELECT * FROM bot_tracker_panels")
        except Exception:
            logger.exception("Lecture des panneaux de suivi impossible.")
            return

        for row in rows:
            guild = self.bot.get_guild(int(row["guild_id"]))
            if guild is None:
                continue
            channel = guild.get_channel(int(row["channel_id"]))
            if not isinstance(channel, discord.TextChannel):
                continue
            try:
                message = await channel.fetch_message(int(row["message_id"]))
                await message.edit(embed=self.build_embed(guild))
            except discord.NotFound:
                await self.bot.db.execute(
                    "DELETE FROM bot_tracker_panels WHERE guild_id = ?",
                    (guild.id,),
                )
            except (discord.Forbidden, discord.HTTPException):
                continue

    @refresh_panels.before_loop
    async def before_refresh_panels(self):
        await self.bot.wait_until_ready()


async def install(bot: commands.Bot) -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    await bot.db.execute(_SCHEMA)
    _install_member_presence_mentions(bot)
    if bot.get_cog(_COG_NAME) is None:
        await bot.add_cog(BotTracker(bot))
    _INSTALLED = True
    logger.info("Panneau de suivi SentriX activé.")
