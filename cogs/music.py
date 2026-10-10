"""Cog MUSIQUE — moteur multi-provider (voir utils/music/ pour l'architecture
complète : YouTube, YouTube Music, Spotify, Deezer, SoundCloud, audio direct,
recherche par titre, avec repli automatique entre sources et matching intelligent).

Ce fichier ne fait QUE la couche Discord (voix, FFmpeg, embeds, file d'attente par
serveur) : toute la logique de résolution/matching/repli vit dans utils/music/ et
est testable sans jamais toucher à Discord — voir tests/test_music_*.py.

/music play/pause/resume/skip/previous/stop/queue/nowplaying/volume/loop/shuffle/
remove/clear/seek/autoplay/join/leave — plus +play en alias préfixe direct (la
seule forme explicitement demandée en dehors du groupe /music)."""
from __future__ import annotations

import asyncio
import logging
import time

import discord
from discord import app_commands
from discord.ext import commands, tasks

from utils import design_system, premium_style
from utils import sentrix_panels as panels
from utils.music.audio_buffer import BufferedPCMAudio
from utils.music import (
    MusicEngineError,
    NoPlayableSource,
    ProviderManager,
    ResolvedRequest,
    Track,
    TrackNotFound,
)

logger = logging.getLogger("bot.music")

FFMPEG_OPTIONS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn",
}
INACTIVITY_DISCONNECT_SECONDS = 5 * 60

MUSIC_SETTINGS_SCHEMA = """
CREATE TABLE IF NOT EXISTS sentrix_music_settings (
    guild_id INTEGER PRIMARY KEY,
    enabled INTEGER NOT NULL DEFAULT 0,
    voice_channel_id INTEGER,
    updated_by INTEGER,
    updated_at INTEGER NOT NULL DEFAULT 0
)
"""

MUSIC_MEMBER_PANEL_SCHEMA = """
CREATE TABLE IF NOT EXISTS sentrix_music_member_panels (
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    updated_at INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, user_id)
)
"""


async def ensure_music_settings_schema(bot) -> None:
    await bot.db.execute(MUSIC_SETTINGS_SCHEMA)
    await bot.db.execute(MUSIC_MEMBER_PANEL_SCHEMA)


async def get_music_settings(bot, guild_id: int) -> dict:
    await ensure_music_settings_schema(bot)
    row = await bot.db.fetchone(
        "SELECT enabled,voice_channel_id,updated_by,updated_at "
        "FROM sentrix_music_settings WHERE guild_id=?",
        (int(guild_id),),
    )
    if row is None:
        return {
            "enabled": False,
            "configured": False,
            "voice_channel_id": None,
            "updated_by": None,
            "updated_at": 0,
        }
    return {
        "enabled": bool(row["enabled"]),
        "configured": True,
        "voice_channel_id": int(row["voice_channel_id"]) if row["voice_channel_id"] else None,
        "updated_by": int(row["updated_by"]) if row["updated_by"] else None,
        "updated_at": int(row["updated_at"] or 0),
    }


async def save_music_settings(
    bot,
    guild_id: int,
    *,
    enabled: bool,
    voice_channel_id: int | None,
    actor_id: int | None = None,
) -> dict:
    await ensure_music_settings_schema(bot)
    now = int(time.time())
    await bot.db.execute(
        "INSERT INTO sentrix_music_settings "
        "(guild_id,enabled,voice_channel_id,updated_by,updated_at) VALUES (?,?,?,?,?) "
        "ON CONFLICT(guild_id) DO UPDATE SET "
        "enabled=excluded.enabled,voice_channel_id=excluded.voice_channel_id,"
        "updated_by=excluded.updated_by,updated_at=excluded.updated_at",
        (
            int(guild_id),
            1 if enabled else 0,
            int(voice_channel_id) if voice_channel_id else None,
            int(actor_id) if actor_id else None,
            now,
        ),
    )
    return {
        "enabled": bool(enabled),
        "voice_channel_id": int(voice_channel_id) if voice_channel_id else None,
        "updated_by": int(actor_id) if actor_id else None,
        "updated_at": now,
    }


class GuildMusicQueue:
    """État musical d'UN serveur — jamais partagé entre serveurs (demande
    explicite : pas de file globale). Une instance par guild_id, créée à la
    demande dans Music.get_queue()."""

    def __init__(self, guild_id: int):
        self.guild_id = guild_id
        self.tracks: list[Track] = []
        self.history: list[Track] = []
        self.current: Track | None = None
        self.voice_client: discord.VoiceClient | None = None
        self.text_channel: discord.abc.Messageable | None = None
        self.volume: float = 0.5
        self.loop_track: bool = False
        self.loop_queue: bool = False
        self.autoplay: bool = False
        self.elapsed_offset: float = 0.0  # secondes déjà écoutées avant le dernier seek
        self.started_at: float = 0.0  # time.monotonic() au dernier (re)démarrage de lecture
        self.disconnect_task: asyncio.Task | None = None
        self.keep_connected: bool = False
        # Phase 6 — stabilité vocale. Chaque démarrage audio reçoit une génération :
        # un callback FFmpeg devenu obsolète après seek/skip/stop ne peut plus avancer
        # la file une deuxième fois. Le verrou sérialise les transitions d'une guilde.
        self.playback_generation: int = 0
        self.advance_lock = asyncio.Lock()
        self.recovery_key: str | None = None
        self.recovery_attempts: int = 0
        self.paused_by_user: bool = False

    def position_seconds(self) -> float:
        if not self.started_at:
            return self.elapsed_offset
        return self.elapsed_offset + (time.monotonic() - self.started_at)

    def pause_clock(self) -> None:
        if self.started_at:
            self.elapsed_offset = self.position_seconds()
            self.started_at = 0.0

    def resume_clock(self) -> None:
        if not self.started_at:
            self.started_at = time.monotonic()

    def reset_clock(self, *, offset: float = 0.0) -> None:
        self.elapsed_offset = max(0.0, float(offset))
        self.started_at = 0.0


def _track_recovery_key(track: Track) -> str:
    """Clé stable d'une piste pour borner les reprises automatiques."""
    return "|".join(
        (
            str(track.provider or ""),
            str(track.playback_provider or ""),
            str(track.original_url or ""),
            str(track.artist or ""),
            str(track.title or ""),
        )
    ).casefold()


_PROVIDER_LABELS = {
    "youtube": "YouTube",
    "youtube_music": "YouTube Music",
    "soundcloud": "SoundCloud",
    "spotify": "Spotify",
    "deezer": "Deezer",
    "direct": "Audio direct",
    "unknown": "Source inconnue",
}


def _provider_label(value: str | None) -> str:
    key = str(value or "unknown").casefold().strip()
    return _PROVIDER_LABELS.get(key, key.replace("_", " ").title() or "Source inconnue")


def _music_source_label(track: Track) -> str:
    metadata = _provider_label(track.provider)
    playback = _provider_label(track.playback_provider or track.provider)
    return metadata if metadata == playback else f"{metadata} → {playback}"


def _music_progress_text(queue: GuildMusicQueue, track: Track) -> str:
    position = max(0, int(queue.position_seconds()))
    if not track.duration:
        return premium_style.format_duration(position)
    duration = max(1, int(track.duration))
    position = min(position, duration)
    ratio = max(0.0, min(1.0, position / duration))
    filled = max(0, min(12, round(ratio * 12)))
    bar = "▰" * filled + "▱" * (12 - filled)
    return (
        f"{premium_style.format_duration(position)} / "
        f"{premium_style.format_duration(duration)} · {bar}"
    )


def _classify_engine_error(exc: MusicEngineError) -> tuple[str, str]:
    """(titre, description) à afficher — jamais un message générique quand on sait
    précisément ce qui s'est passé (demande explicite : pas de "vérifie ton lien"
    quand le lien était correct)."""
    if isinstance(exc, TrackNotFound):
        return "Introuvable", "Ce morceau n'existe plus ou a été supprimé par son auteur."
    if isinstance(exc, NoPlayableSource):
        return (
            "Lecture impossible",
            "Aucune source de lecture autorisée n'est actuellement disponible pour ce morceau.",
        )
    return "Lecture impossible", "Une erreur est survenue pendant la résolution de ce morceau."


class MusicSearchModal(discord.ui.Modal, title="Choisir une musique"):
    recherche = discord.ui.TextInput(
        label="Titre, artiste ou lien",
        placeholder="Ex. Faded Alan Walker ou un lien YouTube / Spotify",
        max_length=1000,
    )

    def __init__(self, bot: commands.Bot, guild_id: int, voice_channel_id: int):
        super().__init__()
        self.bot = bot
        self.guild_id = int(guild_id)
        self.voice_channel_id = int(voice_channel_id)

    async def on_submit(self, interaction: discord.Interaction):
        music = self.bot.get_cog("Music")
        if music is None or interaction.guild is None:
            return await interaction.response.send_message(
                "Le lecteur musique est indisponible pour le moment.",
                ephemeral=True,
            )
        await interaction.response.defer(ephemeral=True, thinking=True)
        ok, message = await music.play_from_voice_panel(
            interaction.guild,
            interaction.user,
            self.voice_channel_id,
            str(self.recherche.value or "").strip(),
            text_channel=interaction.channel,
        )
        await panels.texte_court(
            interaction,
            message,
            ephemere=True,
            supprimer_apres=6,
        )


class MusicVoicePanel(discord.ui.View):
    def __init__(self, bot: commands.Bot, guild_id: int, voice_channel_id: int):
        super().__init__(timeout=10 * 60)
        self.bot = bot
        self.guild_id = int(guild_id)
        self.voice_channel_id = int(voice_channel_id)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        member = interaction.user
        voice = getattr(member, "voice", None)
        channel = getattr(voice, "channel", None)
        if interaction.guild_id != self.guild_id or channel is None or channel.id != self.voice_channel_id:
            await interaction.response.send_message(
                "Rejoignez ce salon vocal pour utiliser son lecteur musique.",
                ephemeral=True,
            )
            return False
        settings = await get_music_settings(self.bot, self.guild_id)
        if not settings["enabled"] or settings["voice_channel_id"] != self.voice_channel_id:
            await interaction.response.send_message(
                "Le système musique de ce salon est désactivé ou a été reconfiguré.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="Choisir une musique", style=discord.ButtonStyle.primary, row=0)
    async def choose_music(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await interaction.response.send_modal(
            MusicSearchModal(self.bot, self.guild_id, self.voice_channel_id)
        )

    @discord.ui.button(label="Pause / Reprendre", style=discord.ButtonStyle.secondary, row=0)
    async def pause_resume(self, interaction: discord.Interaction, _button: discord.ui.Button):
        music = self.bot.get_cog("Music")
        if music is None:
            return await interaction.response.send_message("Lecteur indisponible.", ephemeral=True)
        queue = music.get_queue(self.guild_id)
        voice = queue.voice_client or interaction.guild.voice_client
        if music._pause_queue(queue):
            message = "Musique mise en pause."
        elif music._resume_queue(queue):
            message = "Lecture reprise."
        else:
            message = "Aucune musique n'est en lecture."
        await interaction.response.send_message(message, ephemeral=True)

    @discord.ui.button(label="Suivant", style=discord.ButtonStyle.secondary, row=0)
    async def skip(self, interaction: discord.Interaction, _button: discord.ui.Button):
        music = self.bot.get_cog("Music")
        if music is None:
            return await interaction.response.send_message("Lecteur indisponible.", ephemeral=True)
        queue = music.get_queue(self.guild_id)
        voice = queue.voice_client or interaction.guild.voice_client
        if not voice or not (voice.is_playing() or voice.is_paused()):
            return await interaction.response.send_message("Aucune musique à passer.", ephemeral=True)
        await music._skip_queue(queue)
        await interaction.response.send_message("Passage au titre suivant.", ephemeral=True)

    @discord.ui.button(label="Stop", style=discord.ButtonStyle.danger, row=0)
    async def stop(self, interaction: discord.Interaction, _button: discord.ui.Button):
        music = self.bot.get_cog("Music")
        if music is None:
            return await interaction.response.send_message("Lecteur indisponible.", ephemeral=True)
        queue = music.get_queue(self.guild_id)
        voice = queue.voice_client or interaction.guild.voice_client
        await music._stop_queue(queue)
        await interaction.response.send_message("Lecture arrêtée et file vidée.", ephemeral=True)

    @discord.ui.button(label="Voir la file", style=discord.ButtonStyle.secondary, row=1)
    async def queue(self, interaction: discord.Interaction, _button: discord.ui.Button):
        music = self.bot.get_cog("Music")
        if music is None:
            return await interaction.response.send_message("Lecteur indisponible.", ephemeral=True)
        queue = music.get_queue(self.guild_id)
        lines = []
        if queue.current:
            lines.append(f"En cours : **{queue.current.display_title()}**")
        for index, track in enumerate(queue.tracks[:10], 1):
            lines.append(f"{index}. {track.display_title()}")
        if len(queue.tracks) > 10:
            lines.append(f"... et {len(queue.tracks) - 10} autre(s).")
        await interaction.response.send_message(
            "\n".join(lines) if lines else "La file d'attente est vide.",
            ephemeral=True,
        )


class Music(commands.Cog, name="Music"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.manager = ProviderManager()
        self.queues: dict[int, GuildMusicQueue] = {}
        self._panel_locks: dict[int, asyncio.Lock] = {}
        # Un seul panneau musique par membre présent dans le vocal configuré.
        # À la sortie on attend 2 s avant suppression : si le membre revient
        # immédiatement, on garde le même panneau et on évite le spam.
        self._join_panel_messages: dict[tuple[int, int], discord.Message] = {}
        self._join_panel_delete_tasks: dict[tuple[int, int], asyncio.Task] = {}
        self._inactivity_checker.start()

    def cog_unload(self):
        self._inactivity_checker.cancel()
        for task in list(self._join_panel_delete_tasks.values()):
            if not task.done():
                task.cancel()
        self._join_panel_delete_tasks.clear()

    def get_queue(self, guild_id: int) -> GuildMusicQueue:
        if guild_id not in self.queues:
            self.queues[guild_id] = GuildMusicQueue(guild_id)
        return self.queues[guild_id]

    async def get_system_settings(self, guild_id: int) -> dict:
        return await get_music_settings(self.bot, guild_id)

    async def configure_system(
        self,
        guild: discord.Guild,
        *,
        enabled: bool,
        voice_channel_id: int | None,
        actor_id: int | None = None,
    ) -> dict:
        channel = None
        if voice_channel_id:
            channel = guild.get_channel(int(voice_channel_id))
            if not isinstance(channel, discord.VoiceChannel):
                raise ValueError("Choisissez un salon vocal valide.")
            me = guild.me
            if me is not None:
                perms = channel.permissions_for(me)
                missing = []
                if not perms.view_channel:
                    missing.append("Voir le salon")
                if not perms.connect:
                    missing.append("Se connecter")
                if not perms.speak:
                    missing.append("Parler")
                if not getattr(perms, "send_messages", True):
                    missing.append("Envoyer des messages")
                if missing:
                    raise ValueError(
                        "SentriX n'a pas les permissions nécessaires dans ce vocal : "
                        + ", ".join(missing)
                        + "."
                    )
        if enabled and channel is None:
            raise ValueError("Choisissez le salon vocal du système musique avant de l'activer.")

        settings = await save_music_settings(
            self.bot,
            guild.id,
            enabled=bool(enabled),
            voice_channel_id=channel.id if channel else None,
            actor_id=actor_id,
        )

        persistent = getattr(self, "_sentrix_persistent_voice", None)
        if enabled and channel is not None:
            try:
                try:
                    target = self.bot.get_partial_messageable(
                        channel.id,
                        guild_id=guild.id,
                        type=discord.ChannelType.voice,
                    )
                except TypeError:
                    target = self.bot.get_partial_messageable(channel.id)

                queue = await self._connect_configured_voice(
                    guild,
                    channel,
                    text_channel=target,
                )
                queue.keep_connected = True
                if persistent is not None:
                    await persistent.remember(guild.id, channel.id, channel.id)
            except (PermissionError, RuntimeError, discord.Forbidden, discord.HTTPException, discord.ClientException) as exc:
                await save_music_settings(
                    self.bot,
                    guild.id,
                    enabled=False,
                    voice_channel_id=channel.id,
                    actor_id=actor_id,
                )
                raise ValueError(str(exc) or "SentriX n’a pas pu rejoindre le vocal musique.") from exc
        else:
            if persistent is not None:
                await persistent.forget(guild.id)
            await self.shutdown_guild_music(guild.id)

        return settings

    async def shutdown_guild_music(self, guild_id: int) -> None:
        queue = self.get_queue(guild_id)
        queue.keep_connected = False
        self._cancel_disconnect(queue)
        voice = queue.voice_client
        queue.tracks.clear()
        queue.history.clear()
        queue.loop_track = False
        queue.loop_queue = False
        queue.autoplay = False
        queue.paused_by_user = False
        self._invalidate_playback(queue)
        if voice and (voice.is_playing() or voice.is_paused()):
            voice.stop()
        queue.current = None
        queue.reset_clock()
        if voice and voice.is_connected():
            try:
                await voice.disconnect()
            except discord.HTTPException:
                pass
        queue.voice_client = None

    async def _connect_configured_voice(
        self,
        guild: discord.Guild,
        channel: discord.VoiceChannel,
        *,
        text_channel=None,
    ) -> GuildMusicQueue:
        me = guild.me
        if me is None:
            raise RuntimeError("SentriX n'est pas encore prêt sur ce serveur.")
        perms = channel.permissions_for(me)
        if not perms.view_channel or not perms.connect or not perms.speak:
            raise PermissionError("SentriX n'a pas les permissions pour rejoindre et parler dans ce vocal.")

        queue = self.get_queue(guild.id)
        voice = queue.voice_client or guild.voice_client
        if voice and voice.is_connected():
            if voice.channel.id != channel.id:
                await voice.move_to(channel)
        else:
            try:
                voice = await channel.connect(timeout=30, reconnect=True)
            except TypeError:
                # Les doubles de test plus simples n'acceptent pas ces options.
                voice = await channel.connect()
        queue.voice_client = voice
        queue.keep_connected = True
        if text_channel is not None:
            queue.text_channel = text_channel
        self._cancel_disconnect(queue)
        return queue

    async def play_from_voice_panel(
        self,
        guild: discord.Guild,
        member: discord.Member,
        voice_channel_id: int,
        query: str,
        *,
        text_channel=None,
    ) -> tuple[bool, str]:
        query = str(query or "").strip()
        if not query:
            return False, "Entre un titre, un artiste ou un lien."
        settings = await self.get_system_settings(guild.id)
        if not settings["enabled"]:
            return False, "Le système musique est désactivé."
        if settings["voice_channel_id"] != int(voice_channel_id):
            return False, "Ce vocal n'est plus le salon musique configuré."
        member_voice = getattr(member, "voice", None)
        if member_voice is None or member_voice.channel is None or member_voice.channel.id != int(voice_channel_id):
            return False, "Rejoins le vocal musique avant de choisir un titre."
        channel = guild.get_channel(int(voice_channel_id))
        if not isinstance(channel, discord.VoiceChannel):
            return False, "Le vocal musique configuré n'existe plus."

        lock = self._panel_locks.setdefault(guild.id, asyncio.Lock())
        async with lock:
            try:
                queue = await self._connect_configured_voice(
                    guild,
                    channel,
                    text_channel=text_channel,
                )
                resolved = await self.manager.resolve(query, requested_by=member.id)
            except MusicEngineError as exc:
                _title, description = _classify_engine_error(exc)
                return False, description
            except (PermissionError, RuntimeError, discord.Forbidden, discord.HTTPException) as exc:
                return False, str(exc) or "Connexion vocale impossible."

            if not resolved.tracks:
                return False, "Aucun titre jouable n'a été trouvé."
            queue.tracks.extend(resolved.tracks)
            started = False
            if not (queue.voice_client.is_playing() or queue.voice_client.is_paused()) and not queue.current:
                await self._advance(queue)
                started = queue.current is not None
            if started and queue.current:
                return True, f"Lecture démarrée : **{queue.current.display_title()}**."
            return True, f"{len(resolved.tracks)} titre(s) ajouté(s) à la file."

    async def _embed(self, guild_id: int, *, title: str, description: str | None = None, kind: str = "primary") -> discord.Embed:
        design = await self.bot.db.get_design_settings(guild_id)
        style = design_system.CATEGORY_STYLES["music"]
        colour_key = {"primary": "primary_color", "success": "success_color", "warning": "warning_color", "danger": "danger_color"}.get(kind, "primary_color")
        default_colour = style["colour"] if kind == "primary" else getattr(design_system.COLORS, kind)
        return design_system.create_embed(
            title=design_system.kind_title(title, kind=kind, category_emoji=style["emoji"]),
            description=description,
            colour=design.get(colour_key, default_colour),
            footer=design.get("footer"),
        )

    async def _error_embed(self, guild_id: int, exc: MusicEngineError) -> discord.Embed:
        title, description = _classify_engine_error(exc)
        return await self._embed(guild_id, title=title, description=description, kind="danger")

    async def _interaction_music_queue(
        self,
        interaction: discord.Interaction,
        guild_id: int,
    ) -> GuildMusicQueue | None:
        if interaction.guild is None or interaction.guild_id != int(guild_id):
            await interaction.response.send_message(
                "Ce lecteur n'appartient pas à ce serveur.",
                ephemeral=True,
            )
            return None

        queue = self.get_queue(int(guild_id))
        voice = queue.voice_client or interaction.guild.voice_client
        if voice is None or not voice.is_connected():
            await interaction.response.send_message(
                "SentriX n'est plus connecté au vocal musique.",
                ephemeral=True,
            )
            return None

        member_channel = getattr(getattr(interaction.user, "voice", None), "channel", None)
        bot_channel = getattr(voice, "channel", None)
        if (
            member_channel is None
            or bot_channel is None
            or int(member_channel.id) != int(bot_channel.id)
        ):
            await interaction.response.send_message(
                "Rejoignez le vocal de SentriX pour utiliser ce lecteur.",
                ephemeral=True,
            )
            return None

        queue.voice_client = voice
        return queue

    def _music_player_panel(self, queue: GuildMusicQueue) -> panels.Panneau:
        track = queue.current
        if track is None:
            return panels.Panneau(
                titre="Musique",
                sous_titre="Aucune musique n'est en lecture.",
                kind="musique",
                sections=[
                    panels.Section(
                        "Démarrer",
                        [panels.Ligne("/musique jouer", "Lancer un titre ou un lien")],
                    ),
                ],
                pied="Lecteur",
                timeout=15 * 60,
            )

        guild_id = int(queue.guild_id)

        async def pause_resume(interaction: discord.Interaction):
            active = await self._interaction_music_queue(interaction, guild_id)
            if active is None:
                return
            if self._pause_queue(active):
                text = "Musique mise en pause."
            elif self._resume_queue(active):
                text = "Lecture reprise."
            else:
                text = "Aucune musique n'est en lecture."
            await interaction.response.send_message(text, ephemeral=True)

        async def skip(interaction: discord.Interaction):
            active = await self._interaction_music_queue(interaction, guild_id)
            if active is None:
                return
            if await self._skip_queue(active):
                text = "Passage au titre suivant."
            else:
                text = "Aucune musique à passer."
            await interaction.response.send_message(text, ephemeral=True)

        async def stop(interaction: discord.Interaction):
            active = await self._interaction_music_queue(interaction, guild_id)
            if active is None:
                return
            await self._stop_queue(active)
            await interaction.response.send_message(
                "Lecture arrêtée et file vidée.",
                ephemeral=True,
            )

        async def show_queue(interaction: discord.Interaction):
            active = await self._interaction_music_queue(interaction, guild_id)
            if active is None:
                return
            lines = []
            if active.current:
                lines.append(f"En cours : **{active.current.display_title()}**")
            for index, item in enumerate(active.tracks[:10], 1):
                lines.append(f"{index}. {item.display_title()}")
            if len(active.tracks) > 10:
                lines.append(f"… et {len(active.tracks) - 10} autre(s).")
            await interaction.response.send_message(
                "\n".join(lines) if lines else "La file d'attente est vide.",
                ephemeral=True,
            )

        async def show_playlists(interaction: discord.Interaction):
            active = await self._interaction_music_queue(interaction, guild_id)
            if active is None:
                return
            try:
                rows = await self.bot.db.fetchall(
                    "SELECT name, items_json FROM music_playlists "
                    "WHERE guild_id=? AND user_id=? ORDER BY updated_at DESC LIMIT 10",
                    (guild_id, int(interaction.user.id)),
                )
            except Exception:
                rows = []
            if not rows:
                text = (
                    "Aucune playlist personnelle. Utilise /musique playlist sauvegarder "
                    "ou /musique playlist importer."
                )
            else:
                import json
                lines = []
                for row in rows:
                    try:
                        count = len(json.loads(row["items_json"] or "[]"))
                    except Exception:
                        count = 0
                    lines.append(f"**{row['name']}** · {count} titre(s)")
                text = "\n".join(lines)
            await interaction.response.send_message(text[:1900], ephemeral=True)

        details = [
            panels.Ligne("Titre", track.title),
            panels.Ligne("Artiste", track.artist or "Artiste inconnu"),
        ]
        if track.album:
            details.append(panels.Ligne("Album", track.album))
        if track.duration:
            details.append(
                panels.Ligne("Durée", premium_style.format_duration(track.duration))
            )

        lecture = [
            panels.Ligne("Progression", _music_progress_text(queue, track)),
            panels.Ligne("Source", _music_source_label(track)),
            panels.Ligne("Volume", f"{round(queue.volume * 100)} %"),
            panels.Ligne("File", f"{len(queue.tracks)} titre(s) en attente"),
        ]

        return panels.Panneau(
            titre="Lecture en cours",
            sous_titre=track.display_title()[:180],
            kind="musique",
            vignette=track.thumbnail,
            sections=[
                panels.Section("Piste", details),
                panels.Section("Lecture", lecture),
            ],
            boutons=[
                panels.Bouton(
                    "Pause / Reprendre",
                    custom_id=f"sentrix:music:{guild_id}:pause",
                    style=discord.ButtonStyle.primary,
                    callback=pause_resume,
                ),
                panels.Bouton(
                    "Suivant",
                    custom_id=f"sentrix:music:{guild_id}:skip",
                    callback=skip,
                ),
                panels.Bouton(
                    "Stop",
                    custom_id=f"sentrix:music:{guild_id}:stop",
                    style=discord.ButtonStyle.danger,
                    callback=stop,
                ),
                panels.Bouton(
                    "File",
                    custom_id=f"sentrix:music:{guild_id}:queue",
                    callback=show_queue,
                ),
                panels.Bouton(
                    "Playlists",
                    custom_id=f"sentrix:music:{guild_id}:playlists",
                    callback=show_playlists,
                ),
            ],
            pied="Lecteur",
            timeout=15 * 60,
        )

    # ------------------------------------------------------------ VOIX / LECTURE

    async def _ensure_voice(self, ctx: commands.Context) -> GuildMusicQueue | None:
        settings = await self.get_system_settings(ctx.guild.id)

        # Compatibilité simple : tant qu'un serveur n'a JAMAIS configuré le
        # système musique, +play / /music play rejoignent le vocal du membre.
        # Dès qu'un réglage existe, le vocal choisi dans setup/dashboard devient
        # la source de vérité et une désactivation explicite est respectée.
        if not settings.get("configured", True):
            member_voice = getattr(ctx.author, "voice", None)
            channel = getattr(member_voice, "channel", None)
            if channel is None or not hasattr(channel, "connect"):
                await panels.texte_court(
                    ctx,
                    "Rejoignez un salon vocal avant d'utiliser la musique.",
                    ephemere=bool(ctx.interaction),
                )
                return None

            queue = self.get_queue(ctx.guild.id)
            voice = queue.voice_client or getattr(ctx.guild, "voice_client", None)
            if voice and voice.is_connected():
                if getattr(getattr(voice, "channel", None), "id", None) != getattr(channel, "id", None):
                    await voice.move_to(channel)
            else:
                try:
                    voice = await channel.connect(timeout=30, reconnect=True)
                except TypeError:
                    voice = await channel.connect()
            queue.voice_client = voice
            queue.text_channel = ctx.channel
            self._cancel_disconnect(queue)
            return queue

        if not settings["enabled"]:
            await panels.texte_court(
                ctx,
                "Le système musique est désactivé.",
                ephemere=bool(ctx.interaction),
            )
            return None

        channel_id = settings["voice_channel_id"]
        channel = ctx.guild.get_channel(int(channel_id)) if channel_id else None
        if not isinstance(channel, discord.VoiceChannel):
            await panels.envoyer(
                ctx,
                panels.depuis_embed(
                    await self._embed(
                        ctx.guild.id,
                        title="Vocal musique non configuré",
                        description="Choisissez le salon vocal du système musique dans `+setup` ou le dashboard.",
                        kind="danger",
                    )
                ),
            )
            return None
        if not ctx.author.voice or ctx.author.voice.channel.id != channel.id:
            await panels.envoyer(
                ctx,
                panels.depuis_embed(
                    await self._embed(
                        ctx.guild.id,
                        title="Rejoignez le vocal musique",
                        description=f"Rejoignez **{channel.name}** pour utiliser le lecteur.",
                        kind="danger",
                    )
                ),
            )
            return None
        try:
            return await self._connect_configured_voice(
                ctx.guild,
                channel,
                text_channel=ctx.channel,
            )
        except (PermissionError, RuntimeError, discord.Forbidden, discord.HTTPException) as exc:
            await panels.envoyer(
                ctx,
                panels.depuis_embed(
                    await self._embed(
                        ctx.guild.id,
                        title="Connexion vocale impossible",
                        description=str(exc) or "SentriX ne peut pas rejoindre ce vocal.",
                        kind="danger",
                    )
                ),
            )
            return None

    def _cancel_disconnect(self, queue: GuildMusicQueue) -> None:
        if queue.disconnect_task and not queue.disconnect_task.done():
            queue.disconnect_task.cancel()
        queue.disconnect_task = None

    def _schedule_disconnect(self, queue: GuildMusicQueue) -> None:
        self._cancel_disconnect(queue)
        if queue.keep_connected:
            return

        async def _wait_then_leave():
            try:
                await asyncio.sleep(INACTIVITY_DISCONNECT_SECONDS)
            except asyncio.CancelledError:
                return
            if queue.voice_client and queue.voice_client.is_connected() and not queue.current:
                logger.info("music inactivity disconnect -> guild=%s", queue.guild_id)
                await queue.voice_client.disconnect()
                queue.voice_client = None

        queue.disconnect_task = asyncio.create_task(_wait_then_leave(), name=f"sentrix-music-disconnect-{queue.guild_id}")

    def _invalidate_playback(self, queue: GuildMusicQueue) -> None:
        """Invalide le callback audio de la source actuellement attachée."""
        queue.playback_generation += 1

    async def _notify_playback_issue(self, queue: GuildMusicQueue, message: str) -> None:
        target = queue.text_channel
        if target is None or not hasattr(target, "send"):
            return
        try:
            await target.send(
                str(message)[:1900],
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except TypeError:
            try:
                await target.send(str(message)[:1900])
            except Exception:
                logger.debug("music playback notice ignored -> guild=%s", queue.guild_id, exc_info=True)
        except (discord.Forbidden, discord.HTTPException, AttributeError):
            logger.debug("music playback notice ignored -> guild=%s", queue.guild_id, exc_info=True)

    async def _require_control_voice(
        self,
        ctx: commands.Context,
        queue: GuildMusicQueue,
    ) -> discord.VoiceClient | None:
        """Les contrôles n'agissent que depuis le même vocal que SentriX."""
        voice = queue.voice_client or getattr(ctx.guild, "voice_client", None)
        if voice is None or not voice.is_connected():
            await panels.texte_court(
                ctx,
                "SentriX n'est connecté à aucun salon vocal.",
                ephemere=bool(ctx.interaction),
            )
            return None

        member_channel = getattr(getattr(ctx.author, "voice", None), "channel", None)
        bot_channel = getattr(voice, "channel", None)
        if member_channel is None:
            await panels.texte_court(
                ctx,
                "Rejoignez le vocal de SentriX pour contrôler la musique.",
                ephemere=bool(ctx.interaction),
            )
            return None
        if bot_channel is not None and getattr(member_channel, "id", None) != getattr(bot_channel, "id", None):
            await panels.texte_court(
                ctx,
                f"Rejoignez **{getattr(bot_channel, 'name', 'le vocal de SentriX')}** pour contrôler la musique.",
                ephemere=bool(ctx.interaction),
            )
            return None
        queue.voice_client = voice
        return voice

    def _pause_queue(self, queue: GuildMusicQueue) -> bool:
        voice = queue.voice_client
        if voice and voice.is_playing():
            voice.pause()
            queue.paused_by_user = True
            queue.pause_clock()
            return True
        return False

    def _resume_queue(self, queue: GuildMusicQueue) -> bool:
        voice = queue.voice_client
        if voice and voice.is_paused():
            voice.resume()
            queue.paused_by_user = False
            queue.resume_clock()
            return True
        return False

    async def _skip_queue(self, queue: GuildMusicQueue) -> bool:
        voice = queue.voice_client
        if not voice or not (voice.is_playing() or voice.is_paused()):
            return False
        queue.loop_track = False
        queue.paused_by_user = False
        self._invalidate_playback(queue)
        voice.stop()
        await self._advance(queue)
        return True

    async def _stop_queue(self, queue: GuildMusicQueue) -> bool:
        voice = queue.voice_client
        had_activity = bool(
            queue.current
            or queue.tracks
            or (voice and (voice.is_playing() or voice.is_paused()))
        )
        queue.tracks.clear()
        queue.loop_track = False
        queue.loop_queue = False
        queue.autoplay = False
        queue.paused_by_user = False
        self._invalidate_playback(queue)
        if voice and (voice.is_playing() or voice.is_paused()):
            voice.stop()
        queue.current = None
        queue.reset_clock()
        return had_activity

    async def _play_track(
        self,
        queue: GuildMusicQueue,
        track: Track,
        *,
        seek_seconds: float = 0.0,
        recovery: bool = False,
    ) -> bool:
        """Démarre une piste avec URL fraîche et callback anti-race."""
        try:
            url = await self.manager.refresh_playable_url(track)
        except MusicEngineError as exc:
            logger.warning(
                "music playback candidate rejected at refresh -> guild=%s provider=%s error=%s",
                queue.guild_id,
                track.playback_provider,
                exc,
            )
            return False

        voice = queue.voice_client
        if not (voice and voice.is_connected()):
            logger.warning(
                "music playback deferred: voice disconnected -> guild=%s track=%s",
                queue.guild_id,
                track.display_title(),
            )
            return False

        options = dict(FFMPEG_OPTIONS)
        if seek_seconds > 0:
            options["before_options"] = f"{options['before_options']} -ss {seek_seconds:.2f}"

        source = None
        buffered_source = None
        try:
            ffmpeg_source = discord.FFmpegPCMAudio(url, **options)
            buffered_source = BufferedPCMAudio(
                ffmpeg_source,
                prebuffer_seconds=4.0,
                max_buffer_seconds=12.0,
                startup_timeout=5.0,
                label=f"guild={queue.guild_id}",
            )
            source = discord.PCMVolumeTransformer(buffered_source, volume=queue.volume)
        except (discord.ClientException, OSError, RuntimeError) as exc:
            logger.error(
                "music ffmpeg start failed -> guild=%s track=%s error=%s",
                queue.guild_id,
                track.display_title(),
                exc,
            )
            if source is not None:
                try:
                    source.cleanup()
                except Exception:
                    pass
            return False

        generation = queue.playback_generation + 1
        queue.playback_generation = generation

        def _after(error: Exception | None):
            if error:
                logger.error(
                    "music playback error -> guild=%s generation=%s: %s",
                    queue.guild_id,
                    generation,
                    error,
                )
            if buffered_source is not None and buffered_source.underruns:
                logger.warning(
                    "music jitter buffer stats -> guild=%s underruns=%s",
                    queue.guild_id,
                    buffered_source.underruns,
                )
            try:
                asyncio.run_coroutine_threadsafe(
                    self._on_track_finished(
                        queue,
                        error=error,
                        generation=generation,
                        finished_track=track,
                    ),
                    self.bot.loop,
                )
            except RuntimeError:
                logger.debug(
                    "music after callback ignored because loop is closed -> guild=%s",
                    queue.guild_id,
                )

        try:
            voice.play(source, after=_after)
        except (discord.ClientException, OSError, RuntimeError) as exc:
            logger.error(
                "music voice play failed -> guild=%s track=%s error=%s",
                queue.guild_id,
                track.display_title(),
                exc,
            )
            try:
                source.cleanup()
            except Exception:
                pass
            return False

        queue.current = track
        queue.elapsed_offset = max(0.0, float(seek_seconds))
        queue.started_at = time.monotonic()
        key = _track_recovery_key(track)
        if not recovery or queue.recovery_key != key:
            queue.recovery_key = key
            queue.recovery_attempts = 0
        logger.info(
            "playback started -> %s (metadata=%s, playback=%s, recovery=%s, generation=%s)",
            track.display_title(),
            track.provider,
            track.playback_provider,
            recovery,
            generation,
        )
        return True

    async def _notify_skipped_tracks(
        self,
        queue: GuildMusicQueue,
        skipped: list[str],
        *,
        resumed_title: str | None = None,
    ) -> None:
        if not skipped:
            return
        if resumed_title:
            message = (
                f"⚠️ SentriX a ignoré **{len(skipped)} titre(s) indisponible(s)** "
                f"et poursuit avec **{resumed_title}**."
            )
        else:
            message = (
                f"⚠️ **{len(skipped)} titre(s) indisponible(s)** ont été ignorés. "
                "La file ne contient plus de titre jouable."
            )
        await self._notify_playback_issue(queue, message)

    async def _advance(self, queue: GuildMusicQueue) -> None:
        async with queue.advance_lock:
            await self._advance_locked(queue)

    async def _advance_locked(self, queue: GuildMusicQueue) -> None:
        """Transition atomique vers la piste suivante."""
        skipped: list[str] = []
        while True:
            voice = queue.voice_client
            if not (voice and voice.is_connected()):
                logger.warning(
                    "music advance paused: voice disconnected, queue preserved -> guild=%s pending=%s",
                    queue.guild_id,
                    len(queue.tracks),
                )
                if skipped:
                    await self._notify_skipped_tracks(queue, skipped)
                return

            if queue.loop_track and queue.current:
                candidate = queue.current
            elif queue.tracks:
                candidate = queue.tracks.pop(0)
            elif queue.autoplay and queue.history:
                candidate = await self._autoplay_candidate(queue)
                if candidate is None:
                    queue.current = None
                    queue.reset_clock()
                    await self._notify_skipped_tracks(queue, skipped)
                    self._schedule_disconnect(queue)
                    return
            else:
                queue.current = None
                queue.reset_clock()
                await self._notify_skipped_tracks(queue, skipped)
                self._schedule_disconnect(queue)
                return

            previous = queue.current
            if previous and previous is not candidate:
                queue.history.append(previous)
                if queue.loop_queue and not queue.loop_track:
                    queue.tracks.append(previous)

            queue.paused_by_user = False
            started = await self._play_track(queue, candidate)
            if started:
                await self._notify_skipped_tracks(
                    queue,
                    skipped,
                    resumed_title=candidate.display_title(),
                )
                return

            if not (queue.voice_client and queue.voice_client.is_connected()):
                if candidate is not queue.current:
                    queue.tracks.insert(0, candidate)
                else:
                    queue.current = candidate
                logger.warning(
                    "music candidate preserved during voice outage -> guild=%s track=%s",
                    queue.guild_id,
                    candidate.display_title(),
                )
                await self._notify_playback_issue(
                    queue,
                    "⚠️ Connexion vocale interrompue. La file est conservée et SentriX tente de se reconnecter.",
                )
                return

            skipped.append(candidate.display_title())
            logger.warning(
                "music track auto-skipped, source unavailable -> guild=%s track=%s",
                queue.guild_id,
                candidate.display_title(),
            )
            queue.current = None
            queue.reset_clock()
            if queue.loop_track:
                queue.loop_track = False
            if len(skipped) % 10 == 0:
                await asyncio.sleep(0)

    async def _autoplay_candidate(self, queue: GuildMusicQueue) -> Track | None:
        last = queue.history[-1] if queue.history else None
        if last is None or not last.artist:
            return None
        try:
            result = await self.manager.resolve(f"{last.artist}", requested_by=last.requested_by)
        except MusicEngineError:
            return None
        for track in result.tracks:
            if track.title.casefold() != last.title.casefold():
                return track
        return None

    async def _on_track_finished(
        self,
        queue: GuildMusicQueue,
        *,
        error: Exception | None = None,
        generation: int | None = None,
        finished_track: Track | None = None,
    ) -> None:
        async with queue.advance_lock:
            if generation is not None and generation != queue.playback_generation:
                logger.debug(
                    "music stale after callback ignored -> guild=%s callback_generation=%s current_generation=%s",
                    queue.guild_id,
                    generation,
                    queue.playback_generation,
                )
                return

            track = finished_track or queue.current
            played_seconds = queue.position_seconds() if track is not None else 0.0

            if (
                error is None
                and track is not None
                and not track.is_live
                and track.duration
                and played_seconds + 8.0 < float(track.duration)
            ):
                error = RuntimeError(
                    f"flux interrompu à {played_seconds:.1f}s sur {track.duration}s"
                )

            if error is not None and track is not None:
                resume_at = max(0.0, played_seconds)
                if track.duration:
                    resume_at = min(resume_at, max(0.0, float(track.duration) - 1.0))
                queue.elapsed_offset = resume_at
                queue.started_at = 0.0

                voice = queue.voice_client
                if not (voice and voice.is_connected()):
                    queue.current = track
                    logger.warning(
                        "music playback suspended during voice outage -> guild=%s track=%s position=%.1f",
                        queue.guild_id,
                        track.display_title(),
                        resume_at,
                    )
                    await self._notify_playback_issue(
                        queue,
                        "⚠️ Connexion vocale perdue. La piste et la file sont conservées pendant la reconnexion.",
                    )
                    persistent = getattr(self, "_sentrix_persistent_voice", None)
                    if persistent is not None:
                        try:
                            asyncio.create_task(
                                persistent.restore_all(),
                                name=f"sentrix-music-recover-voice-{queue.guild_id}",
                            )
                        except RuntimeError:
                            pass
                    return

                key = _track_recovery_key(track)
                if queue.recovery_key != key:
                    queue.recovery_key = key
                    queue.recovery_attempts = 0

                if queue.recovery_attempts < 1:
                    queue.recovery_attempts += 1
                    logger.warning(
                        "music ffmpeg recovery attempt -> guild=%s track=%s position=%.1f",
                        queue.guild_id,
                        track.display_title(),
                        resume_at,
                    )
                    await self._notify_playback_issue(
                        queue,
                        f"⚠️ Coupure audio détectée sur **{track.display_title()}**. SentriX relance le flux automatiquement.",
                    )
                    restarted = await self._play_track(
                        queue,
                        track,
                        seek_seconds=resume_at,
                        recovery=True,
                    )
                    if restarted:
                        if queue.paused_by_user and queue.voice_client:
                            queue.voice_client.pause()
                            queue.pause_clock()
                        return

                logger.error(
                    "music ffmpeg recovery exhausted -> guild=%s track=%s",
                    queue.guild_id,
                    track.display_title(),
                )
                await self._notify_playback_issue(
                    queue,
                    f"⚠️ Impossible de reprendre **{track.display_title()}**. Passage automatique au titre suivant.",
                )
                queue.loop_track = False
                queue.current = None
                queue.paused_by_user = False
                queue.reset_clock()
                if not queue.history or queue.history[-1] is not track:
                    queue.history.append(track)
                await self._advance_locked(queue)
                return

            await self._advance_locked(queue)

    async def resume_after_voice_reconnect(self, queue: GuildMusicQueue) -> bool:
        """Restaure la piste courante après reconnexion Discord, sans doubler la lecture."""
        async with queue.advance_lock:
            voice = queue.voice_client
            track = queue.current
            if not (voice and voice.is_connected()) or track is None:
                return False
            if voice.is_playing() or voice.is_paused():
                return True

            resume_at = max(0.0, queue.position_seconds())
            if track.duration:
                resume_at = min(resume_at, max(0.0, float(track.duration) - 1.0))

            self._invalidate_playback(queue)
            restarted = await self._play_track(
                queue,
                track,
                seek_seconds=resume_at,
                recovery=True,
            )
            if restarted:
                if queue.paused_by_user:
                    voice.pause()
                    queue.pause_clock()
                    state = "restaurée en pause"
                else:
                    state = "reprise"
                logger.warning(
                    "music playback restored after voice reconnect -> guild=%s track=%s position=%.1f",
                    queue.guild_id,
                    track.display_title(),
                    resume_at,
                )
                await self._notify_playback_issue(
                    queue,
                    f"✅ Connexion vocale rétablie. Lecture {state} : **{track.display_title()}**.",
                )
                return True

            failed = track
            queue.current = None
            queue.paused_by_user = False
            queue.reset_clock()
            logger.error(
                "music reconnect restored voice but not track -> guild=%s track=%s",
                queue.guild_id,
                failed.display_title(),
            )
            await self._notify_playback_issue(
                queue,
                f"⚠️ Connexion vocale rétablie, mais **{failed.display_title()}** n'est plus lisible. Passage au suivant.",
            )
            await self._advance_locked(queue)
            return False

    async def _voice_chat_target(self, guild_id: int, channel_id: int):
        try:
            return self.bot.get_partial_messageable(
                int(channel_id),
                guild_id=int(guild_id),
                type=discord.ChannelType.voice,
            )
        except TypeError:
            return self.bot.get_partial_messageable(int(channel_id))

    async def _delete_saved_member_panel(self, guild_id: int, member_id: int) -> None:
        await ensure_music_settings_schema(self.bot)
        row = await self.bot.db.fetchone(
            "SELECT channel_id,message_id FROM sentrix_music_member_panels "
            "WHERE guild_id=? AND user_id=?",
            (int(guild_id), int(member_id)),
        )
        if row is not None:
            channel_id = int(row["channel_id"])
            message_id = int(row["message_id"])
            deleted = False
            try:
                target = await self._voice_chat_target(guild_id, channel_id)
                partial = target.get_partial_message(message_id)
                await partial.delete()
                deleted = True
            except (discord.NotFound, discord.Forbidden, discord.HTTPException, AttributeError):
                pass
            if not deleted:
                try:
                    await self.bot.http.delete_message(channel_id, message_id)
                    deleted = True
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    pass
            logger.info(
                "music member panel cleanup -> guild=%s user=%s message=%s deleted=%s",
                guild_id,
                member_id,
                message_id,
                deleted,
            )
        await self.bot.db.execute(
            "DELETE FROM sentrix_music_member_panels WHERE guild_id=? AND user_id=?",
            (int(guild_id), int(member_id)),
        )

    async def _save_member_panel(self, guild_id: int, member_id: int, channel_id: int, message_id: int) -> None:
        await ensure_music_settings_schema(self.bot)
        await self.bot.db.execute(
            "INSERT INTO sentrix_music_member_panels "
            "(guild_id,user_id,channel_id,message_id,updated_at) VALUES (?,?,?,?,?) "
            "ON CONFLICT(guild_id,user_id) DO UPDATE SET "
            "channel_id=excluded.channel_id,message_id=excluded.message_id,updated_at=excluded.updated_at",
            (
                int(guild_id),
                int(member_id),
                int(channel_id),
                int(message_id),
                int(time.time()),
            ),
        )

    async def _ensure_member_music_panel(
        self,
        member: discord.Member,
        channel: discord.VoiceChannel,
    ) -> None:
        key = (member.guild.id, member.id)

        pending = self._join_panel_delete_tasks.pop(key, None)
        if pending is not None and not pending.done():
            pending.cancel()
        if key in self._join_panel_messages:
            return

        # Nettoie un ancien message laissé par un redémarrage/failover avant d'en
        # publier un nouveau.
        await self._delete_saved_member_panel(member.guild.id, member.id)

        me = member.guild.me
        if me is None:
            return
        perms = channel.permissions_for(me)
        if not perms.view_channel or not getattr(perms, "send_messages", False):
            logger.warning(
                "music voice panel skipped: missing chat permission guild=%s channel=%s",
                member.guild.id,
                channel.id,
            )
            return

        try:
            target = await self._voice_chat_target(member.guild.id, channel.id)
            embed = await self._embed(
                member.guild.id,
                title="Lecteur musique",
                description=(
                    "Bienvenue dans le vocal musique.\n"
                    "Choisissez un titre avec le lecteur ci-dessous."
                ),
                kind="primary",
            )
            message = await target.send(
                content=member.mention,
                embed=embed,
                view=MusicVoicePanel(self.bot, member.guild.id, channel.id),
                allowed_mentions=discord.AllowedMentions(
                    users=[member],
                    roles=False,
                    everyone=False,
                    replied_user=False,
                ),
            )
            self._join_panel_messages[key] = message
            await self._save_member_panel(
                member.guild.id,
                member.id,
                channel.id,
                message.id,
            )
            logger.info(
                "music member panel shown -> guild=%s user=%s channel=%s message=%s",
                member.guild.id,
                member.id,
                channel.id,
                message.id,
            )
        except (discord.Forbidden, discord.HTTPException, AttributeError):
            logger.exception(
                "Impossible d'envoyer le panneau musique dans le chat vocal guild=%s channel=%s",
                member.guild.id,
                channel.id,
            )

    async def ensure_panels_for_current_members(
        self,
        guild: discord.Guild,
        channel: discord.VoiceChannel,
    ) -> None:
        for member in list(channel.members):
            if member.bot:
                continue
            try:
                await self._ensure_member_music_panel(member, channel)
            except Exception:
                logger.exception(
                    "music panel reconcile failed -> guild=%s user=%s channel=%s",
                    guild.id,
                    member.id,
                    channel.id,
                )

    async def _delete_member_music_panel_after_leave(
        self,
        guild_id: int,
        member_id: int,
        configured_channel_id: int,
    ) -> None:
        key = (int(guild_id), int(member_id))
        try:
            await asyncio.sleep(2)
            guild = self.bot.get_guild(int(guild_id))
            channel = guild.get_channel(int(configured_channel_id)) if guild is not None else None
            still_inside = bool(
                channel is not None
                and any(int(m.id) == int(member_id) for m in getattr(channel, "members", ()))
            )

            # Retour dans les 2 secondes : on conserve le panneau existant.
            if still_inside:
                return

            message = self._join_panel_messages.pop(key, None)
            if message is not None:
                try:
                    await message.delete()
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    pass
            await self._delete_saved_member_panel(guild_id, member_id)
        except asyncio.CancelledError:
            return
        finally:
            task = self._join_panel_delete_tasks.get(key)
            if task is asyncio.current_task():
                self._join_panel_delete_tasks.pop(key, None)

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ):
        if member.bot:
            return
        if (
            before.channel is not None
            and after.channel is not None
            and before.channel.id == after.channel.id
        ):
            return

        settings = await self.get_system_settings(member.guild.id)
        configured_id = settings["voice_channel_id"]
        if not configured_id:
            return

        configured_id = int(configured_id)
        key = (member.guild.id, member.id)
        left_configured = before.channel is not None and before.channel.id == configured_id
        joined_configured = after.channel is not None and after.channel.id == configured_id

        # Sortie du vocal musique : suppression différée de 2 secondes.
        # Cela absorbe les déconnexions/reconnexions rapides sans créer plusieurs panneaux.
        if left_configured and not joined_configured:
            previous = self._join_panel_delete_tasks.pop(key, None)
            if previous is not None and not previous.done():
                previous.cancel()
            self._join_panel_delete_tasks[key] = asyncio.create_task(
                self._delete_member_music_panel_after_leave(
                    member.guild.id,
                    member.id,
                    configured_id,
                ),
                name=f"sentrix-music-panel-leave-{member.guild.id}-{member.id}",
            )
            return

        if not joined_configured or not settings["enabled"]:
            return

        await self._ensure_member_music_panel(member, after.channel)

    @tasks.loop(minutes=1)
    async def _inactivity_checker(self):
        """Filet de sécurité : si le bot se retrouve seul dans un salon vocal
        (tout le monde est parti) alors qu'aucune déconnexion n'est déjà
        programmée, on en programme une — le callback after= ne se déclenche pas
        si personne ne skip/stop manuellement une file vide."""
        for queue in list(self.queues.values()):
            vc = queue.voice_client
            if not vc or not vc.is_connected():
                continue

            settings = await self.get_system_settings(queue.guild_id)
            configured_id = settings.get("voice_channel_id")
            if (
                settings.get("enabled")
                and configured_id
                and int(configured_id) == int(vc.channel.id)
            ):
                queue.keep_connected = True
                self._cancel_disconnect(queue)
                continue

            queue.keep_connected = False
            humans = [m for m in vc.channel.members if not m.bot]
            if not humans and not queue.disconnect_task:
                self._schedule_disconnect(queue)

    @_inactivity_checker.before_loop
    async def _before_inactivity_checker(self):
        await self.bot.wait_until_ready()

    # ------------------------------------------------------------ RÉSOLUTION + AJOUT

    async def _resolve_and_queue(self, ctx: commands.Context, query: str) -> None:
        queue = await self._ensure_voice(ctx)
        if queue is None:
            return
        if ctx.interaction:
            await ctx.defer()

        try:
            result: ResolvedRequest = await self.manager.resolve(query, requested_by=ctx.author.id)
        except MusicEngineError as exc:
            return await panels.envoyer(ctx, panels.depuis_embed(await self._error_embed(ctx.guild.id, exc)))

        queue.tracks.extend(result.tracks)
        started_now = False
        if not (queue.voice_client.is_playing() or queue.voice_client.is_paused()) and not queue.current:
            await self._advance(queue)
            started_now = queue.current is not None

        if result.is_playlist:
            description = f"➕ **{len(result.tracks)}** titre(s) ajoutés depuis la playlist."
            if result.skipped:
                description += f"\n⚠️ {len(result.skipped)} titre(s) non trouvé(s), ignoré(s)."
            return await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id, title="Playlist ajoutée", description=description, kind="success")))

        track = result.tracks[0]
        if started_now:
            await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id, title="Lecture en cours", description=f"▶️ **{track.display_title()}**", kind="success")))
        else:
            await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id, title="Ajouté à la file", description=f"➕ **{track.display_title()}** ajouté à la file d'attente.", kind="success")))

    # ------------------------------------------------------------ COMMANDES

    @commands.hybrid_group(name="music", description="Commandes musique de SentriX.")
    async def music(self, ctx: commands.Context):
        if ctx.invoked_subcommand is None:
            await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id, title="Musique", description="Utilisez `/music play <titre ou lien>` pour commencer.", kind="primary")))

    @music.command(name="play", description="Jouer un titre (nom, artiste, ou lien YouTube/Spotify/Deezer/SoundCloud).")
    @app_commands.describe(recherche="Titre + artiste, ou un lien YouTube/YouTube Music/Spotify/Deezer/SoundCloud/audio direct")
    async def music_play(self, ctx: commands.Context, *, recherche: str):
        await self._resolve_and_queue(ctx, recherche)

    @commands.hybrid_command(name="play", description="Jouer un titre (alias direct de /music play).")
    @app_commands.describe(recherche="Titre + artiste, ou un lien YouTube/YouTube Music/Spotify/Deezer/SoundCloud/audio direct")
    async def play_alias(self, ctx: commands.Context, *, recherche: str):
        """+play reste un alias préfixe direct (demande explicite), sans consommer
        de racine slash : /music play couvre déjà le côté /."""
        await self._resolve_and_queue(ctx, recherche)

    @music.command(name="join", description="Faire rejoindre le bot à votre salon vocal.")
    async def music_join(self, ctx: commands.Context):
        queue = await self._ensure_voice(ctx)
        if queue is None:
            return
        await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id, title="Salon rejoint", description=f"J'ai rejoint **{queue.voice_client.channel.name}**.", kind="success")))

    @music.command(name="leave", description="Faire quitter le bot du salon vocal.")
    async def music_leave(self, ctx: commands.Context):
        queue = self.get_queue(ctx.guild.id)
        voice = queue.voice_client or getattr(ctx.guild, "voice_client", None)
        if not voice:
            return await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id, title="Aucun salon vocal", description="Je ne suis dans aucun salon vocal.", kind="danger")))
        self._cancel_disconnect(queue)
        self._invalidate_playback(queue)
        if voice.is_playing() or voice.is_paused():
            voice.stop()
        try:
            await voice.disconnect()
        except discord.HTTPException:
            pass
        queue.voice_client = None
        queue.tracks.clear()
        queue.history.clear()
        queue.current = None
        queue.paused_by_user = False
        queue.reset_clock()
        await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id, title="Salon quitté", description="J'ai quitté le salon vocal.", kind="success")))

    @music.command(name="pause", description="Mettre la musique en pause.")
    async def music_pause(self, ctx: commands.Context):
        queue = self.get_queue(ctx.guild.id)
        if await self._require_control_voice(ctx, queue) is None:
            return
        if self._pause_queue(queue):
            await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id, title="Musique en pause", kind="primary")))
        else:
            await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id, title="Rien à mettre en pause", description="Aucune musique en cours de lecture.", kind="danger")))

    @music.command(name="resume", description="Reprendre la lecture.")
    async def music_resume(self, ctx: commands.Context):
        queue = self.get_queue(ctx.guild.id)
        if await self._require_control_voice(ctx, queue) is None:
            return
        if self._resume_queue(queue):
            await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id, title="Lecture reprise", kind="primary")))
        else:
            await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id, title="Rien à reprendre", description="La musique n'est pas en pause.", kind="danger")))

    @music.command(name="skip", description="Passer à la musique suivante.")
    async def music_skip(self, ctx: commands.Context):
        queue = self.get_queue(ctx.guild.id)
        if await self._require_control_voice(ctx, queue) is None:
            return
        if await self._skip_queue(queue):
            await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id, title="Musique passée", kind="success")))
        else:
            await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id, title="Rien à passer", description="Aucune musique en cours de lecture.", kind="danger")))

    @music.command(name="previous", description="Revenir au titre précédent.")
    async def music_previous(self, ctx: commands.Context):
        queue = self.get_queue(ctx.guild.id)
        voice = await self._require_control_voice(ctx, queue)
        if voice is None:
            return
        if not queue.history:
            return await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id, title="Rien avant", description="Aucun titre précédent dans cette session.", kind="danger")))
        previous_track = queue.history.pop()
        current = queue.current
        if current:
            queue.tracks.insert(0, current)
        queue.tracks.insert(0, previous_track)
        queue.loop_track = False
        queue.paused_by_user = False
        self._invalidate_playback(queue)
        if voice.is_playing() or voice.is_paused():
            voice.stop()
        queue.current = None
        queue.reset_clock()
        await self._advance(queue)
        await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id, title="Retour en arrière", description=f"⏮️ **{previous_track.display_title()}**", kind="success")))

    @music.command(name="stop", description="Arrêter la musique et vider la file d'attente.")
    async def music_stop(self, ctx: commands.Context):
        queue = self.get_queue(ctx.guild.id)
        if await self._require_control_voice(ctx, queue) is None:
            return
        await self._stop_queue(queue)
        await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id, title="Musique arrêtée", description="File d'attente vidée.", kind="success")))

    @music.command(name="queue", description="Afficher la file d'attente musicale.")
    async def music_queue(self, ctx: commands.Context):
        queue = self.get_queue(ctx.guild.id)
        if not queue.tracks and not queue.current:
            return await panels.envoyer(
                ctx,
                panels.Panneau(
                    titre="SentriX — File d'attente", sous_titre="Rien n'est en lecture et la file est vide.", kind="info",
                    sections=[panels.Section("Lancer la musique", [
                        panels.Ligne("`/music play <titre ou lien>`", "Ajoute un titre et démarre la lecture"),
                    ])],
                    pied="SentriX • Musique",
                ),
            )
        sections = []
        if queue.current:
            en_cours = [panels.Ligne("Titre", queue.current.display_title())]
            if queue.current.duration:
                en_cours.append(panels.Ligne("Position", f"{premium_style.format_duration(int(queue.position_seconds()))} / {premium_style.format_duration(queue.current.duration)}"))
            en_cours.append(panels.Ligne("Source", queue.current.playback_provider or queue.current.provider))
            en_cours.append(panels.Ligne("Boucle", "piste" if queue.loop_track else ("file" if queue.loop_queue else "désactivée")))
            sections.append(panels.Section("En lecture", en_cours))
        if queue.tracks:
            sections.append(panels.Section(
                f"À suivre ({len(queue.tracks)})",
                [panels.Ligne(f"{i}", piste.display_title()[:70]) for i, piste in enumerate(queue.tracks[:8], 1)],
                aligne=True,
            ))
            restants = max(0, len(queue.tracks) - 8)
            duree = sum(int(p.duration or 0) for p in queue.tracks)
            recap = []
            if restants:
                recap.append(panels.Ligne("Non affichés", f"{restants} titre{'s' if restants > 1 else ''}"))
            if duree:
                recap.append(panels.Ligne("Durée totale", premium_style.format_duration(duree)))
            if recap:
                sections.append(panels.Section("Résumé", recap))
        await panels.envoyer(ctx, panels.Panneau(titre="SentriX — File d'attente", sous_titre=f"**{len(queue.tracks)}** titre(s) en attente.", kind="info", sections=sections, pied="SentriX • Musique"))

    @music.command(name="nowplaying", description="Afficher la musique en cours.")
    async def music_nowplaying(self, ctx: commands.Context):
        queue = self.get_queue(ctx.guild.id)
        await panels.envoyer(ctx, self._music_player_panel(queue))

    @music.command(name="volume", description="Régler le volume (0 à 100).")
    @app_commands.describe(niveau="Le niveau de volume entre 0 et 100")
    async def music_volume(self, ctx: commands.Context, niveau: commands.Range[int, 0, 100]):
        # commands.Range (pas app_commands.Range) : le transformer slash n'a pas de
        # convertisseur préfixe, `+music volume 50` répondait « Argument invalide ».
        queue = self.get_queue(ctx.guild.id)
        queue.volume = niveau / 100
        if queue.voice_client and queue.voice_client.source:
            queue.voice_client.source.volume = queue.volume
        await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id, title="Volume réglé", description=f"Volume réglé sur **{niveau}%**.", kind="success")))

    _LOOP_ALIASES = {
        "off": "off", "désactivé": "off", "desactive": "off", "non": "off", "stop": "off", "0": "off",
        "track": "track", "piste": "track", "titre": "track", "morceau": "track", "1": "track",
        "queue": "queue", "file": "queue", "liste": "queue", "all": "queue", "tout": "queue",
    }

    @music.command(name="loop", description="Répéter la piste actuelle, toute la file, ou désactiver.")
    @app_commands.choices(mode=[
        app_commands.Choice(name="Désactivé", value="off"),
        app_commands.Choice(name="Piste actuelle", value="track"),
        app_commands.Choice(name="File d'attente", value="queue"),
    ])
    async def music_loop(self, ctx: commands.Context, mode: str):
        queue = self.get_queue(ctx.guild.id)
        # `str` + @app_commands.choices : le slash garde ses trois choix, le préfixe
        # accepte les mêmes valeurs et leurs équivalents français.
        raw = (mode.value if isinstance(mode, app_commands.Choice) else str(mode)).casefold().strip()
        value = self._LOOP_ALIASES.get(raw)
        if value is None:
            return await panels.envoyer(ctx, panels.depuis_embed(await self._embed(
                ctx.guild.id, title="Mode inconnu",
                description="Choisissez **off**, **piste** ou **file** (ex. `+music loop piste`).", kind="danger")))
        queue.loop_track = value == "track"
        queue.loop_queue = value == "queue"
        label = {"off": "désactivée", "track": "piste actuelle", "queue": "file d'attente"}[value]
        await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id, title="Répétition", description=f"Répétition : **{label}**.", kind="success")))

    @music.command(name="shuffle", description="Mélanger la file d'attente.")
    async def music_shuffle(self, ctx: commands.Context):
        import random
        queue = self.get_queue(ctx.guild.id)
        random.shuffle(queue.tracks)
        await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id, title="File d'attente mélangée", kind="success")))

    @music.command(name="remove", description="Retirer un titre de la file d'attente.")
    @app_commands.describe(position="Position dans la file (voir /music queue)")
    async def music_remove(self, ctx: commands.Context, position: int):
        queue = self.get_queue(ctx.guild.id)
        if position < 1 or position > len(queue.tracks):
            return await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id, title="Position invalide", kind="danger")))
        removed = queue.tracks.pop(position - 1)
        await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id, title="Retiré de la file", description=f"🗑️ **{removed.display_title()}** retiré de la file d'attente.", kind="success")))

    @music.command(name="clear", description="Vider la file d'attente sans arrêter la musique en cours.")
    async def music_clear(self, ctx: commands.Context):
        queue = self.get_queue(ctx.guild.id)
        queue.tracks.clear()
        await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id, title="File d'attente vidée", kind="success")))

    @music.command(name="seek", description="Aller à une position précise dans la piste en cours (en secondes).")
    @app_commands.describe(secondes="Position cible en secondes depuis le début de la piste")
    async def music_seek(self, ctx: commands.Context, secondes: commands.Range[int, 0, 36000]):
        queue = self.get_queue(ctx.guild.id)
        voice = await self._require_control_voice(ctx, queue)
        if voice is None or not queue.current:
            return await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id, title="Rien à avancer", description="Aucune musique en cours de lecture.", kind="danger")))
        if queue.current.duration and secondes > queue.current.duration:
            return await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id, title="Position invalide", description=f"Cette piste dure {premium_style.format_duration(queue.current.duration)}.", kind="danger")))
        track = queue.current
        self._invalidate_playback(queue)
        if voice.is_playing() or voice.is_paused():
            voice.stop()
        queue.paused_by_user = False
        started = await self._play_track(queue, track, seek_seconds=float(secondes))
        if not started:
            queue.current = None
            queue.reset_clock()
            return await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id, title="Lecture impossible", description="La source de cette piste n'est plus disponible.", kind="danger")))
        await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id, title="Position modifiée", description=f"⏩ Lecture reprise à **{premium_style.format_duration(secondes)}**.", kind="success")))

    @music.command(name="autoplay", description="Activer ou désactiver la lecture automatique quand la file se vide.")
    async def music_autoplay(self, ctx: commands.Context):
        queue = self.get_queue(ctx.guild.id)
        queue.autoplay = not queue.autoplay
        await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id, title="Autoplay", description=f"Autoplay {('activé' if queue.autoplay else 'désactivé')}.", kind="success")))


async def setup(bot: commands.Bot):
    await bot.add_cog(Music(bot))
