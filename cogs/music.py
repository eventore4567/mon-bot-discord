"""
Cog MUSIQUE.
/join /leave /play /pause /resume /skip /stop /queue /nowplaying /volume
/loop /shuffle /remove-from-queue /clear-queue /playlist-save /playlist-load
"""

import asyncio
import discord
from discord import app_commands
from discord.ext import commands

from utils import embeds, design_system, premium_style

FFMPEG_OPTIONS = {
    "before_options": "-reconnect 1 -reconnect_streamretries 5 -reconnect_delay_max 5",
    "options": "-vn",
}
YTDL_OPTIONS = {
    "format": "bestaudio/best",
    "noplaylist": True,
    "quiet": True,
    "default_search": "ytsearch",
    "source_address": "0.0.0.0",
}


class GuildMusicState:
    def __init__(self):
        self.queue: list[dict] = []
        self.voice_client: discord.VoiceClient | None = None
        self.current: dict | None = None
        self.volume: float = 0.5
        self.loop: bool = False


class Music(commands.Cog, name="Music"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.states: dict[int, GuildMusicState] = {}

    def get_state(self, guild_id: int) -> GuildMusicState:
        if guild_id not in self.states:
            self.states[guild_id] = GuildMusicState()
        return self.states[guild_id]

    async def _embed(self, guild_id: int, *, title: str, description: str = None, kind: str = "primary") -> discord.Embed:
        """Construit un embed musique cohérent avec +designsetup. `kind` choisit la
        couleur (primary/success/warning/danger) parmi les réglages du serveur ; le style
        (emoji 🎵) vient toujours de CATEGORY_STYLES["music"]."""
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

    async def ytdl_extract(self, query: str) -> dict:
        import yt_dlp
        loop = asyncio.get_event_loop()
        with yt_dlp.YoutubeDL(YTDL_OPTIONS) as ydl:
            info = await loop.run_in_executor(None, lambda: ydl.extract_info(query, download=False))
        if "entries" in info:
            info = info["entries"][0]
        return {
            "title": info.get("title", "Titre inconnu"),
            "url": info["url"],
            "webpage_url": info.get("webpage_url", ""),
            "thumbnail": info.get("thumbnail", ""),
            "duration": info.get("duration", 0),
        }

    def play_next(self, guild: discord.Guild):
        state = self.get_state(guild.id)
        if state.loop and state.current:
            state.queue.insert(0, state.current)
        if not state.queue:
            state.current = None
            return
        state.current = state.queue.pop(0)
        source = discord.PCMVolumeTransformer(discord.FFmpegPCMAudio(state.current["url"], **FFMPEG_OPTIONS), volume=state.volume)

        def after(err):
            self.play_next(guild)

        if state.voice_client and state.voice_client.is_connected():
            state.voice_client.play(source, after=after)

    @commands.hybrid_command(name="join", description="Faire rejoindre le bot à votre salon vocal.")
    async def join(self, ctx: commands.Context):
        if not ctx.author.voice:
            return await ctx.send(embed=await self._embed(ctx.guild.id, title="Salon vocal requis", description="Vous devez être dans un salon vocal.", kind="danger"))
        channel = ctx.author.voice.channel
        state = self.get_state(ctx.guild.id)
        if state.voice_client:
            await state.voice_client.move_to(channel)
        else:
            state.voice_client = await channel.connect()
        await ctx.send(embed=await self._embed(ctx.guild.id, title="Salon rejoint", description=f"J'ai rejoint **{channel.name}**.", kind="success"))

    @commands.hybrid_command(name="leave", description="Faire quitter le bot du salon vocal.")
    async def leave(self, ctx: commands.Context):
        state = self.get_state(ctx.guild.id)
        if not state.voice_client:
            return await ctx.send(embed=await self._embed(ctx.guild.id, title="Aucun salon vocal", description="Je ne suis dans aucun salon vocal.", kind="danger"))
        await state.voice_client.disconnect()
        state.voice_client = None
        state.queue.clear()
        state.current = None
        await ctx.send(embed=await self._embed(ctx.guild.id, title="Salon quitté", description="J'ai quitté le salon vocal.", kind="success"))

    @commands.hybrid_command(name="play", description="Jouer une musique (nom ou lien).")
    @app_commands.describe(recherche="Le nom de la musique ou un lien")
    async def play(self, ctx: commands.Context, *, recherche: str):
        if not ctx.author.voice:
            return await ctx.send(embed=await self._embed(ctx.guild.id, title="Salon vocal requis", description="Vous devez être dans un salon vocal.", kind="danger"))
        if ctx.interaction:
            await ctx.defer()

        state = self.get_state(ctx.guild.id)
        if not state.voice_client:
            state.voice_client = await ctx.author.voice.channel.connect()

        try:
            track = await self.ytdl_extract(recherche)
        except Exception:
            return await ctx.send(embed=await self._embed(ctx.guild.id, title="Lecture impossible", description="Impossible de trouver ou lire cette musique.", kind="danger"))

        state.queue.append(track)
        if not state.voice_client.is_playing() and not state.current:
            self.play_next(ctx.guild)
            await ctx.send(embed=await self._embed(ctx.guild.id, title="Lecture en cours", description=f"▶️ Lecture de **{track['title']}**", kind="success"))
        else:
            await ctx.send(embed=await self._embed(ctx.guild.id, title="Ajouté à la file", description=f"➕ **{track['title']}** ajouté à la file d'attente.", kind="success"))

    @commands.hybrid_command(name="pause", description="Mettre la musique en pause.")
    async def pause(self, ctx: commands.Context):
        state = self.get_state(ctx.guild.id)
        if state.voice_client and state.voice_client.is_playing():
            state.voice_client.pause()
            await ctx.send(embed=await self._embed(ctx.guild.id, title="Musique en pause", kind="primary"))
        else:
            await ctx.send(embed=await self._embed(ctx.guild.id, title="Rien à mettre en pause", description="Aucune musique en cours de lecture.", kind="danger"))

    @commands.hybrid_command(name="resume", description="Reprendre la lecture.")
    async def resume(self, ctx: commands.Context):
        state = self.get_state(ctx.guild.id)
        if state.voice_client and state.voice_client.is_paused():
            state.voice_client.resume()
            await ctx.send(embed=await self._embed(ctx.guild.id, title="Lecture reprise", kind="primary"))
        else:
            await ctx.send(embed=await self._embed(ctx.guild.id, title="Rien à reprendre", description="La musique n'est pas en pause.", kind="danger"))

    @commands.hybrid_command(name="skip", description="Passer à la musique suivante.")
    async def skip(self, ctx: commands.Context):
        state = self.get_state(ctx.guild.id)
        if state.voice_client and (state.voice_client.is_playing() or state.voice_client.is_paused()):
            state.voice_client.stop()
            await ctx.send(embed=await self._embed(ctx.guild.id, title="Musique passée", kind="success"))
        else:
            await ctx.send(embed=await self._embed(ctx.guild.id, title="Rien à passer", description="Aucune musique en cours de lecture.", kind="danger"))

    @commands.hybrid_command(name="stop", description="Arrêter la musique et vider la file d'attente.")
    async def stop(self, ctx: commands.Context):
        state = self.get_state(ctx.guild.id)
        state.queue.clear()
        state.loop = False
        if state.voice_client:
            state.voice_client.stop()
        await ctx.send(embed=await self._embed(ctx.guild.id, title="Musique arrêtée", description="File d'attente vidée.", kind="success"))

    @commands.hybrid_command(name="queue", description="Afficher la file d'attente musicale.")
    async def queue(self, ctx: commands.Context):
        state = self.get_state(ctx.guild.id)
        if not state.queue and not state.current:
            return await ctx.send(embed=await self._embed(ctx.guild.id, title="File d'attente vide"))
        lines = []
        if state.current:
            lines.append(f"**En cours :** {state.current['title']}")
        for i, track in enumerate(state.queue[:8], 1):
            lines.append(f"{i}. {track['title']}")
        hidden = max(0, len(state.queue) - 8)
        if hidden:
            lines.append(f"+{hidden} titre{'s' if hidden > 1 else ''} dans la file")
        await ctx.send(embed=await self._embed(
            ctx.guild.id,
            title="File d'attente",
            description="\n".join(lines),
        ))

    @commands.hybrid_command(name="nowplaying", description="Afficher la musique en cours.")
    async def nowplaying(self, ctx: commands.Context):
        state = self.get_state(ctx.guild.id)
        if not state.current:
            return await ctx.send(embed=await self._embed(ctx.guild.id, title="Aucune lecture en cours"))
        track = state.current
        title = track["title"]
        url = track.get("webpage_url")
        description = f"[{title}]({url})" if url else title
        if track.get("duration"):
            description += f"\nDurée • {premium_style.format_duration(track['duration'])}"
        embed = await self._embed(ctx.guild.id, title="En cours", description=description)
        if track.get("thumbnail"):
            embed.set_thumbnail(url=track["thumbnail"])
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="volume", description="Régler le volume (0 à 100).")
    @app_commands.describe(niveau="Le niveau de volume entre 0 et 100")
    async def volume(self, ctx: commands.Context, niveau: app_commands.Range[int, 0, 100]):
        state = self.get_state(ctx.guild.id)
        state.volume = niveau / 100
        if state.voice_client and state.voice_client.source:
            state.voice_client.source.volume = state.volume
        await ctx.send(embed=await self._embed(ctx.guild.id, title="Volume réglé", description=f"Volume réglé sur **{niveau}%**.", kind="success"))

    @commands.hybrid_command(name="loop", description="Activer ou désactiver la répétition de la musique en cours.")
    async def loop(self, ctx: commands.Context):
        state = self.get_state(ctx.guild.id)
        state.loop = not state.loop
        await ctx.send(embed=await self._embed(ctx.guild.id, title="Répétition", description=f"Répétition {'activée' if state.loop else 'désactivée'}.", kind="success"))

    @commands.hybrid_command(name="shuffle", description="Mélanger la file d'attente.", with_app_command=False)
    async def shuffle(self, ctx: commands.Context):
        import random
        state = self.get_state(ctx.guild.id)
        random.shuffle(state.queue)
        await ctx.send(embed=await self._embed(ctx.guild.id, title="File d'attente mélangée", kind="success"))

    @commands.hybrid_command(name="remove-from-queue", description="Retirer une musique de la file d'attente.", with_app_command=False)
    @app_commands.describe(position="Position dans la file (voir /queue)")
    async def remove_from_queue(self, ctx: commands.Context, position: int):
        state = self.get_state(ctx.guild.id)
        if position < 1 or position > len(state.queue):
            return await ctx.send(embed=await self._embed(ctx.guild.id, title="Position invalide", kind="danger"))
        removed = state.queue.pop(position - 1)
        await ctx.send(embed=await self._embed(ctx.guild.id, title="Retiré de la file", description=f"🗑️ **{removed['title']}** retiré de la file d'attente.", kind="success"))

    @commands.hybrid_command(name="clear-queue", description="Vider la file d'attente sans arrêter la musique en cours.", with_app_command=False)
    async def clear_queue(self, ctx: commands.Context):
        state = self.get_state(ctx.guild.id)
        state.queue.clear()
        await ctx.send(embed=await self._embed(ctx.guild.id, title="File d'attente vidée", kind="success"))

    @commands.hybrid_command(name="playlist-save", description="Sauvegarder la file d'attente actuelle comme playlist.", with_app_command=False)
    @app_commands.describe(nom="Le nom de la playlist")
    async def playlist_save(self, ctx: commands.Context, *, nom: str):
        import json
        state = self.get_state(ctx.guild.id)
        if not state.queue:
            return await ctx.send(embed=await self._embed(ctx.guild.id, title="File d'attente vide", kind="danger"))
        await self.bot.db.execute(
            "INSERT INTO playlists (guild_id, user_id, name, tracks) VALUES (?, ?, ?, ?)",
            (ctx.guild.id, ctx.author.id, nom, json.dumps(state.queue)),
        )
        await ctx.send(embed=await self._embed(ctx.guild.id, title="Playlist sauvegardée", description=f"💾 Playlist **{nom}** sauvegardée ({len(state.queue)} titres).", kind="success"))

    @commands.hybrid_command(name="playlist-load", description="Charger une playlist sauvegardée dans la file d'attente.", with_app_command=False)
    @app_commands.describe(nom="Le nom de la playlist")
    async def playlist_load(self, ctx: commands.Context, *, nom: str):
        import json
        row = await self.bot.db.fetchone(
            "SELECT * FROM playlists WHERE guild_id = ? AND name = ?", (ctx.guild.id, nom)
        )
        if not row:
            return await ctx.send(embed=await self._embed(ctx.guild.id, title="Playlist introuvable", kind="danger"))
        tracks = json.loads(row["tracks"])
        state = self.get_state(ctx.guild.id)
        state.queue.extend(tracks)
        await ctx.send(embed=await self._embed(ctx.guild.id, title="Playlist chargée", description=f"📂 Playlist **{nom}** chargée ({len(tracks)} titres ajoutés).", kind="success"))

async def setup(bot: commands.Bot):
    await bot.add_cog(Music(bot))
