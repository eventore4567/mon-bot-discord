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
            "voice_channel_id": None,
            "updated_by": None,
            "updated_at": 0,
        }
    return {
        "enabled": bool(row["enabled"]),
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

    def position_seconds(self) -> float:
        if not self.started_at:
            return self.elapsed_offset
        return self.elapsed_offset + (time.monotonic() - self.started_at)


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
                "Rejoins ce salon vocal pour utiliser son lecteur musique.",
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
        if voice and voice.is_playing():
            voice.pause()
            message = "Musique mise en pause."
        elif voice and voice.is_paused():
            voice.resume()
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
        queue.loop_track = False
        voice.stop()
        await interaction.response.send_message("Passage au titre suivant.", ephemeral=True)

    @discord.ui.button(label="Stop", style=discord.ButtonStyle.danger, row=0)
    async def stop(self, interaction: discord.Interaction, _button: discord.ui.Button):
        music = self.bot.get_cog("Music")
        if music is None:
            return await interaction.response.send_message("Lecteur indisponible.", ephemeral=True)
        queue = music.get_queue(self.guild_id)
        voice = queue.voice_client or interaction.guild.voice_client
        queue.tracks.clear()
        queue.loop_track = False
        queue.loop_queue = False
        queue.autoplay = False
        if voice and (voice.is_playing() or voice.is_paused()):
            voice.stop()
        queue.current = None
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
        queue.current = None
        if voice and (voice.is_playing() or voice.is_paused()):
            voice.stop()
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

    # ------------------------------------------------------------ VOIX / LECTURE

    async def _ensure_voice(self, ctx: commands.Context) -> GuildMusicQueue | None:
        settings = await self.get_system_settings(ctx.guild.id)
        if not settings["enabled"]:
            await panels.envoyer(
                ctx,
                panels.depuis_embed(
                    await self._embed(
                        ctx.guild.id,
                        title="Musique désactivée",
                        description="Activez d'abord le système musique dans `+setup` ou le dashboard.",
                        kind="danger",
                    )
                ),
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

    async def _play_track(self, queue: GuildMusicQueue, track: Track, *, seek_seconds: float = 0.0) -> bool:
        """Démarre réellement la lecture d'une piste déjà résolue (playable_url
        connu). Ré-résout une URL de flux fraîche juste avant (les URLs signées
        expirent). Retourne False si la piste doit être écartée (source devenue
        indisponible) — l'appelant doit alors passer à la suivante."""
        try:
            url = await self.manager.refresh_playable_url(track)
        except MusicEngineError as exc:
            logger.warning("music playback candidate rejected at refresh -> %s (%s)", track.playback_provider, exc)
            return False

        options = dict(FFMPEG_OPTIONS)
        if seek_seconds > 0:
            options["before_options"] = f"{options['before_options']} -ss {seek_seconds:.2f}"

        ffmpeg_source = discord.FFmpegPCMAudio(url, **options)
        buffered_source = BufferedPCMAudio(
            ffmpeg_source,
            prebuffer_seconds=4.0,
            max_buffer_seconds=12.0,
            startup_timeout=5.0,
            label=f"guild={queue.guild_id}",
        )
        source = discord.PCMVolumeTransformer(buffered_source, volume=queue.volume)

        def _after(error: Exception | None):
            if error:
                logger.error("music playback error -> guild=%s: %s", queue.guild_id, error)
            if buffered_source.underruns:
                logger.warning(
                    "music jitter buffer stats -> guild=%s underruns=%s",
                    queue.guild_id,
                    buffered_source.underruns,
                )
            asyncio.run_coroutine_threadsafe(self._on_track_finished(queue), self.bot.loop)

        if not (queue.voice_client and queue.voice_client.is_connected()):
            source.cleanup()
            return False
        queue.voice_client.play(source, after=_after)
        queue.current = track
        queue.elapsed_offset = seek_seconds
        queue.started_at = time.monotonic()
        logger.info(
            "playback started -> %s (metadata=%s, playback=%s, jitter_buffer=4s/12s)",
            track.display_title(), track.provider, track.playback_provider,
        )
        return True

    async def _advance(self, queue: GuildMusicQueue) -> None:
        """Choisit et démarre la piste suivante (boucle piste > file > boucle file
        > autoplay > rien). Écarte silencieusement (avec log) toute piste dont la
        source est devenue indisponible entre la résolution et la lecture, et
        essaie la suivante — jamais d'arrêt complet à cause d'UNE piste cassée."""
        while True:
            if queue.loop_track and queue.current:
                candidate = queue.current
            elif queue.tracks:
                candidate = queue.tracks.pop(0)
            elif queue.autoplay and queue.history:
                candidate = await self._autoplay_candidate(queue)
                if candidate is None:
                    queue.current = None
                    self._schedule_disconnect(queue)
                    return
            else:
                queue.current = None
                self._schedule_disconnect(queue)
                return

            previous = queue.current
            if previous and previous is not candidate:
                queue.history.append(previous)
                if queue.loop_queue and not queue.loop_track:
                    queue.tracks.append(previous)

            started = await self._play_track(queue, candidate)
            if started:
                return
            logger.warning("music track skipped, source unavailable -> %s", candidate.display_title())
            queue.current = None
            if queue.loop_track:
                queue.loop_track = False

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

    async def _on_track_finished(self, queue: GuildMusicQueue) -> None:
        # Une seule source de notification publique :
        # sentrix_music_playlists_v108 envoie le message texte final avec la mention.
        # On ne renvoie donc plus ici d'embed "File d'attente terminée" ni
        # d'embed "Lecture en cours", ce qui supprimait le doublon visible.
        await self._advance(queue)

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
                    "Choisis un titre avec le lecteur ci-dessous."
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
        if not queue.voice_client:
            return await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id, title="Aucun salon vocal", description="Je ne suis dans aucun salon vocal.", kind="danger")))
        self._cancel_disconnect(queue)
        await queue.voice_client.disconnect()
        queue.voice_client = None
        queue.tracks.clear()
        queue.history.clear()
        queue.current = None
        await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id, title="Salon quitté", description="J'ai quitté le salon vocal.", kind="success")))

    @music.command(name="pause", description="Mettre la musique en pause.")
    async def music_pause(self, ctx: commands.Context):
        queue = self.get_queue(ctx.guild.id)
        if queue.voice_client and queue.voice_client.is_playing():
            queue.voice_client.pause()
            await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id, title="Musique en pause", kind="primary")))
        else:
            await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id, title="Rien à mettre en pause", description="Aucune musique en cours de lecture.", kind="danger")))

    @music.command(name="resume", description="Reprendre la lecture.")
    async def music_resume(self, ctx: commands.Context):
        queue = self.get_queue(ctx.guild.id)
        if queue.voice_client and queue.voice_client.is_paused():
            queue.voice_client.resume()
            await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id, title="Lecture reprise", kind="primary")))
        else:
            await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id, title="Rien à reprendre", description="La musique n'est pas en pause.", kind="danger")))

    @music.command(name="skip", description="Passer à la musique suivante.")
    async def music_skip(self, ctx: commands.Context):
        queue = self.get_queue(ctx.guild.id)
        if queue.voice_client and (queue.voice_client.is_playing() or queue.voice_client.is_paused()):
            queue.loop_track = False
            queue.voice_client.stop()
            await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id, title="Musique passée", kind="success")))
        else:
            await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id, title="Rien à passer", description="Aucune musique en cours de lecture.", kind="danger")))

    @music.command(name="previous", description="Revenir au titre précédent.")
    async def music_previous(self, ctx: commands.Context):
        queue = self.get_queue(ctx.guild.id)
        if not queue.history:
            return await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id, title="Rien avant", description="Aucun titre précédent dans cette session.", kind="danger")))
        previous_track = queue.history.pop()
        if queue.current:
            queue.tracks.insert(0, queue.current)
        queue.tracks.insert(0, previous_track)
        queue.loop_track = False
        if queue.voice_client and (queue.voice_client.is_playing() or queue.voice_client.is_paused()):
            queue.voice_client.stop()
        else:
            await self._advance(queue)
        await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id, title="Retour en arrière", description=f"⏮️ **{previous_track.display_title()}**", kind="success")))

    @music.command(name="stop", description="Arrêter la musique et vider la file d'attente.")
    async def music_stop(self, ctx: commands.Context):
        queue = self.get_queue(ctx.guild.id)
        queue.tracks.clear()
        queue.loop_track = False
        queue.loop_queue = False
        queue.autoplay = False
        if queue.voice_client:
            queue.voice_client.stop()
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
        if not queue.current:
            return await panels.envoyer(
                ctx,
                panels.Panneau(
                    titre="SentriX — Lecture", sous_titre="Aucune lecture en cours.", kind="info",
                    sections=[panels.Section("Démarrer", [panels.Ligne("`/music play <titre ou lien>`", "Lance la lecture dans votre salon vocal")])],
                    pied="SentriX • Musique",
                ),
            )
        piste = queue.current
        lien = piste.original_url
        details = [panels.Ligne("Titre", f"[{piste.display_title()}]({lien})" if lien else piste.display_title())]
        if piste.duration:
            details.append(panels.Ligne("Position", f"{premium_style.format_duration(int(queue.position_seconds()))} / {premium_style.format_duration(piste.duration)}"))
        details.append(panels.Ligne("Source des métadonnées", piste.provider))
        details.append(panels.Ligne("Source de lecture", piste.playback_provider or "—"))
        lecteur = [
            panels.Ligne("Volume", f"{round(queue.volume * 100)} %"),
            panels.Ligne("Boucle", "piste" if queue.loop_track else ("file" if queue.loop_queue else "désactivée")),
            panels.Ligne("Autoplay", "activé" if queue.autoplay else "désactivé"),
            panels.Ligne("En attente", f"{len(queue.tracks)} titre(s)"),
        ]
        await panels.envoyer(ctx, panels.Panneau(titre="SentriX — En lecture", sous_titre=piste.display_title()[:180], kind="info", vignette=piste.thumbnail, sections=[panels.Section("Piste", details), panels.Section("Lecteur", lecteur, aligne=True)], pied="SentriX • Musique"))

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
        if not queue.current or not queue.voice_client:
            return await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id, title="Rien à avancer", description="Aucune musique en cours de lecture.", kind="danger")))
        if queue.current.duration and secondes > queue.current.duration:
            return await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id, title="Position invalide", description=f"Cette piste dure {premium_style.format_duration(queue.current.duration)}.", kind="danger")))
        track = queue.current
        queue.voice_client.stop()
        started = await self._play_track(queue, track, seek_seconds=float(secondes))
        if not started:
            return await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id, title="Lecture impossible", description="La source de cette piste n'est plus disponible.", kind="danger")))
        await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id, title="Position modifiée", description=f"⏩ Lecture reprise à **{premium_style.format_duration(secondes)}**.", kind="success")))

    @music.command(name="autoplay", description="Activer ou désactiver la lecture automatique quand la file se vide.")
    async def music_autoplay(self, ctx: commands.Context):
        queue = self.get_queue(ctx.guild.id)
        queue.autoplay = not queue.autoplay
        await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id, title="Autoplay", description=f"Autoplay {('activé' if queue.autoplay else 'désactivé')}.", kind="success")))


async def setup(bot: commands.Bot):
    await bot.add_cog(Music(bot))
