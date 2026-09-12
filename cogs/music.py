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


class Music(commands.Cog, name="Music"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.manager = ProviderManager()
        self.queues: dict[int, GuildMusicQueue] = {}
        self._inactivity_checker.start()

    def cog_unload(self):
        self._inactivity_checker.cancel()

    def get_queue(self, guild_id: int) -> GuildMusicQueue:
        if guild_id not in self.queues:
            self.queues[guild_id] = GuildMusicQueue(guild_id)
        return self.queues[guild_id]

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
        if not ctx.author.voice:
            await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id, title="Salon vocal requis", description="Vous devez être dans un salon vocal.", kind="danger")))
            return None
        queue = self.get_queue(ctx.guild.id)
        queue.text_channel = ctx.channel
        if queue.voice_client and queue.voice_client.is_connected():
            if queue.voice_client.channel.id != ctx.author.voice.channel.id:
                await queue.voice_client.move_to(ctx.author.voice.channel)
        else:
            queue.voice_client = await ctx.author.voice.channel.connect()
        self._cancel_disconnect(queue)
        return queue

    def _cancel_disconnect(self, queue: GuildMusicQueue) -> None:
        if queue.disconnect_task and not queue.disconnect_task.done():
            queue.disconnect_task.cancel()
        queue.disconnect_task = None

    def _schedule_disconnect(self, queue: GuildMusicQueue) -> None:
        self._cancel_disconnect(queue)

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
        finished = queue.current
        await self._advance(queue)
        if queue.current is None and queue.text_channel is not None and finished is not None:
            try:
                embed = await self._embed(
                    queue.guild_id, title="File d'attente terminée",
                    description="Plus rien à jouer — utilisez `/music play` pour ajouter des titres.",
                    kind="primary",
                )
                await queue.text_channel.send(embed=embed)
            except discord.HTTPException:
                pass
        elif queue.current is not None and queue.text_channel is not None and finished is not queue.current:
            try:
                embed = await self._embed(queue.guild_id, title="Lecture en cours", description=f"▶️ **{queue.current.display_title()}**", kind="success")
                await queue.text_channel.send(embed=embed)
            except discord.HTTPException:
                pass

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
    async def music_volume(self, ctx: commands.Context, niveau: app_commands.Range[int, 0, 100]):
        queue = self.get_queue(ctx.guild.id)
        queue.volume = niveau / 100
        if queue.voice_client and queue.voice_client.source:
            queue.voice_client.source.volume = queue.volume
        await panels.envoyer(ctx, panels.depuis_embed(await self._embed(ctx.guild.id, title="Volume réglé", description=f"Volume réglé sur **{niveau}%**.", kind="success")))

    @music.command(name="loop", description="Répéter la piste actuelle, toute la file, ou désactiver.")
    @app_commands.choices(mode=[
        app_commands.Choice(name="Désactivé", value="off"),
        app_commands.Choice(name="Piste actuelle", value="track"),
        app_commands.Choice(name="File d'attente", value="queue"),
    ])
    async def music_loop(self, ctx: commands.Context, mode: app_commands.Choice[str]):
        queue = self.get_queue(ctx.guild.id)
        value = mode.value if isinstance(mode, app_commands.Choice) else mode
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
    async def music_seek(self, ctx: commands.Context, secondes: app_commands.Range[int, 0, 36000]):
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
