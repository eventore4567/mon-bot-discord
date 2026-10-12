"""SentriX Fun — réactions GIF pertinentes, mini-profils et défis humoristiques.

Toutes les simulations (hack/scan/aura/ship) sont explicitement fictives.
La famille est préfixée : +fun ... et les raccourcis (+hug, +hack...).
Aucune racine slash supplémentaire n'est enregistrée : budget global préservé.
"""
from __future__ import annotations

import hashlib
import logging
import secrets
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit

import aiohttp
import discord
from discord.ext import commands

logger = logging.getLogger("bot.fun-social")

# Action -> (titre, emoji, verbe, categorie GIF). Categories officielles Nekos.best v2.
REACTIONS: dict[str, tuple[str, str, str, str]] = {
    "hug": ("Câlin", "🤗", "fait un gros câlin à", "hug"),
    "pat": ("Pat pat", "🐾", "caresse gentiment", "pat"),
    "kiss": ("Bisou", "💋", "fait un bisou à", "kiss"),
    "cuddle": ("Câlin douillet", "🧸", "se blottit contre", "cuddle"),
    "highfive": ("Check !", "🙌", "fait un high five à", "highfive"),
    "handshake": ("Poignée de main", "🤝", "serre la main de", "handshake"),
    "handhold": ("Main dans la main", "💞", "prend la main de", "handhold"),
    "poke": ("Poke", "👉", "taquine", "poke"),
    "tickle": ("Chatouilles", "😆", "chatouille", "tickle"),
    "slap": ("Petite claque", "🖐️", "donne une claque cartoon à", "slap"),
    "bonk": ("BONK", "🔨", "envoie un bonk cartoon à", "bonk"),
    "bite": ("Mordillement", "🦷", "mordille", "bite"),
    "kick": ("Coup de pied cartoon", "🦶", "fait un coup de pied cartoon à", "kick"),
    "punch": ("Coup de poing cartoon", "🥊", "fait un coup de poing cartoon à", "punch"),
    "yeet": ("YEET !", "🚀", "propulse (en cartoon)", "yeet"),
    "carry": ("Porté !", "💪", "porte", "carry"),
    "feed": ("À table", "🍙", "donne à manger à", "feed"),
    "nom": ("Nom nom", "🍪", "grignote les snacks de", "nom"),
    "wave": ("Coucou", "👋", "fait coucou à", "wave"),
    "wink": ("Clin d'œil", "😉", "fait un clin d'œil à", "wink"),
    "salute": ("Salut militaire", "🫡", "salue", "salute"),
    "blowkiss": ("Bisou volant", "💌", "envoie un bisou volant à", "blowkiss"),
    "peck": ("Petit bisou", "💕", "dépose un petit bisou sur", "peck"),
    "baka": ("Baka !", "😤", "taquine gentiment", "baka"),
    "stare": ("Regard intense", "👀", "fixe", "stare"),
    "clap": ("Applaudissements", "👏", "applaudit", "clap"),
    "comfort": ("Réconfort", "🫂", "réconforte", "hug"),
    "cheer": ("Encouragement", "📣", "encourage", "happy"),
}
SOLO: dict[str, tuple[str, str, str, str]] = {
    "dance": ("Dance !", "💃", "se lance dans une danse légendaire", "dance"),
    "cry": ("Snif...", "😭", "a besoin d'un mouchoir", "cry"),
    "laugh": ("Fou rire", "😂", "part en fou rire", "laugh"),
    "smile": ("Sourire", "😊", "affiche son meilleur sourire", "smile"),
    "blush": ("Rougissement", "😳", "rougit instantanément", "blush"),
    "happy": ("Bonne humeur", "🌈", "rayonne de bonheur", "happy"),
    "angry": ("Colère cartoon", "💢", "fait les gros yeux", "angry"),
    "facepalm": ("Facepalm", "🤦", "n'en peut plus", "facepalm"),
    "think": ("Réflexion", "🤔", "réfléchit intensément", "think"),
    "shrug": ("Bah...", "🤷", "hausse les épaules", "shrug"),
    "spin": ("Toupie", "🌀", "tourne comme une toupie", "spin"),
    "run": ("Sprint", "🏃", "part en courant", "run"),
    "sleep": ("Dodo", "😴", "s'endort paisiblement", "sleep"),
    "yawn": ("Bâillement", "🥱", "bâille très fort", "yawn"),
    "pout": ("Bouderie", "😠", "boude dans son coin", "pout"),
    "smug": ("Trop fier", "😏", "prend un air beaucoup trop sûr de soi", "smug"),
    "tableflip": ("Ragequit", "🪑", "renverse la table (en dessin animé)", "tableflip"),
    "confused": ("Perdu", "❓", "ne comprend plus rien", "confused"),
    "nod": ("J'approuve", "👍", "approuve officiellement", "nod"),
}
FUN_MODES = (
    "aura", "scan", "hack", "ship", "rate", "luck", "vibe", "mood", "rizz",
    "brain", "chaos", "wanted", "fortune", "compliment", "roast", "truth",
    "dare", "challenge", "8ball", "gift", "meme", "personality",
)
ACTIONS = frozenset(REACTIONS) | frozenset(SOLO) | frozenset(FUN_MODES)
SHORTCUTS = (
    "hug", "kiss", "pat", "slap", "cuddle", "highfive", "poke", "tickle",
    "wave", "dance", "aura", "hack", "scan", "ship", "roast", "compliment",
)
FUN_COLORS = {"social": 0xF08DAF, "solo": 0x57BAC7, "fun": 0xA879F1}
FORTUNES = (
    "Une très bonne surprise approche.", "Un nouveau fou rire t'attend.",
    "Le destin recommande une pause pizza.", "Tu vas gagner un duel... de blagues.",
    "Un ami va te faire sourire.", "Attention, niveau de charisme incontrôlable.",
    "Une journée de légende se prépare.", "Le prochain meme sera incroyable.",
)
COMPLIMENTS = (
    "a une énergie qui illumine le serveur.", "mérite un trophée de bonne humeur.",
    "a un niveau de gentillesse légendaire.", "est la définition d'une bonne vibe.",
    "rend les conversations beaucoup plus amusantes.", "a un charisme de personnage principal.",
    "mérite un câlin collectif (virtuel).", "est une vraie pépite.",
)
ROASTS = (
    "met 3 jours à répondre à un « salut ».",
    "cherche encore le bouton pour allumer son charisme.",
    "est tellement en retard que même son ombre l'attend.",
    "perdrait un duel de rapidité contre une tortue.",
    "a besoin d'un tutoriel pour ouvrir un paquet de chips.",
    "a plus d'onglets ouverts que de bonnes excuses.",
)
TRUTHS = (
    "Quelle est ta plus grande honte drôle ?", "Quelle habitude bizarre as-tu ?",
    "Quel est ton pire pseudo Discord ?", "Quel jeu t'a fait le plus rager ?",
    "Quelle chanson écoutes-tu en secret ?", "À qui donnerais-tu une médaille de gentillesse ?",
)
DARES = (
    "Écris une phrase entière avec des emojis.", "Fais un compliment sincère à quelqu'un.",
    "Raconte une blague en une seule phrase.", "Trouve un surnom drôle pour toi-même.",
    "Imite un personnage de dessin animé en vocal.", "Envoie ton GIF préféré (approprié au salon).",
)
CHALLENGES = (
    "Défi : 5 emojis, 1 histoire.", "Défi : fais rire un membre en 2 messages.",
    "Défi : invente un slogan pour le serveur.", "Défi : trouve une devinette originale.",
    "Défi : décris ton humeur avec un titre de film.", "Défi : compliments en chaîne !",
)


def fixed_score(guild_id: int, user_id: int, key: str, *, limit: int = 100) -> int:
    """Score de fiction stable par jour et par membre, sans données personnelles."""
    day = datetime.now(timezone.utc).date().isoformat()
    raw = f"sentrix-fun|{guild_id}|{user_id}|{day}|{key}".encode()
    return int.from_bytes(hashlib.sha256(raw).digest()[:8], "big") % (limit + 1)


def gif_url_is_safe(url: str, category: str) -> bool:
    parsed = urlsplit(url)
    return (
        parsed.scheme == "https" and parsed.hostname == "nekos.best"
        and parsed.port in (None, 443)
        and parsed.path.startswith(f"/api/v2/{category}/")
        and parsed.path.endswith(".gif")
        and not parsed.username and not parsed.password
    )


async def fetch_gif(category: str) -> tuple[str | None, str | None]:
    """Un GIF de la categorie voulue ; aucun remplacement trompeur par un autre GIF."""
    valid = {data[3] for data in (*REACTIONS.values(), *SOLO.values())}
    if category not in valid:
        return None, None
    timeout = aiohttp.ClientTimeout(total=5)
    headers = {"User-Agent": "SentriX-Fun (https://github.com/eventore4567/mon-bot-discord)"}
    try:
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            async with session.get(f"https://nekos.best/api/v2/{category}") as response:
                if response.status != 200:
                    return None, None
                payload = await response.json(content_type=None)
        results = payload.get("results") if isinstance(payload, dict) else None
        item = results[0] if isinstance(results, list) and results else None
        if not isinstance(item, dict):
            return None, None
        url = str(item.get("url") or "")
        if not gif_url_is_safe(url, category):
            return None, None
        return url, str(item.get("anime_name") or "")[:90] or None
    except (aiohttp.ClientError, TimeoutError, ValueError, TypeError, OverflowError):
        logger.info("GIF fun indisponible pour %s", category)
        return None, None


def menu_embed(page: str = "social") -> discord.Embed:
    pages = {
        "social": ("💗 Réactions & câlins", REACTIONS, "Utilisation : +hug @membre ou +fun hug @membre"),
        "solo": ("🎭 Émotions & animations", SOLO, "Utilisation : +dance ou +fun laugh"),
        "fun": ("🔮 Tests & délires", {s: () for s in FUN_MODES}, "Utilisation : +aura @membre ou +fun fortune"),
    }
    title, entries, example = pages.get(page, pages["social"])
    embed = discord.Embed(
        title=f"🎉 SentriX Fun  •  {title}",
        description="Un catalogue de jeux sociaux, de GIFs anime adaptés et de défis.\n"
                    f"**{example}**\n\n"
                    + " · ".join(f"\`{name}\`" for name in entries),
        colour=FUN_COLORS.get(page, FUN_COLORS["social"]),
    )
    embed.set_footer(text=f"{len(ACTIONS)} actions disponibles • Aucun vrai scan ni piratage")
    return embed


def _profile_embed(mode: str, user: discord.Member, guild_id: int, *,
                   other: discord.Member | None = None) -> discord.Embed:
    """Construit des fiches humoristiques : les valeurs ne proviennent pas de Discord."""
    score = fixed_score(guild_id, user.id, mode, limit=9999 if mode == "aura" else 100)
    score2 = fixed_score(guild_id, user.id, f"{mode}-2")
    score3 = fixed_score(guild_id, user.id, f"{mode}-3")
    titles = {
        "aura": ("✨ Aura", 0xA879F1), "scan": ("🔬 Scan fictif", 0x41B5CA),
        "hack": ("💻 Faux piratage", 0x45D58A), "ship": ("💞 Compatibilité", 0xF08DAF),
        "rate": ("⭐ Note", 0xF2C36A), "luck": ("🍀 Chance", 0x55CA78),
        "vibe": ("🌊 Vibe", 0x48B7D4), "mood": ("🎭 Humeur", 0x7B8FE9),
        "rizz": ("😎 Charisme", 0xE9AE75), "brain": ("🧠 Cerveau", 0x92B0EB),
        "chaos": ("🌪️ Chaos", 0xD388EC), "wanted": ("🕵️ Avis de recherche", 0xE6A56D),
        "personality": ("🧬 Personnalité", 0x9CC8A1),
    }
    title, colour = titles.get(mode, ("🎉 SentriX Fun", FUN_COLORS["fun"]))
    e = discord.Embed(title=f"{title} • {user.display_name[:60]}", colour=colour)
    e.set_thumbnail(url=user.display_avatar.url)
    if mode == "aura":
        rank = ("Mythique" if score >= 9000 else "Légendaire" if score >= 7000
                else "Épique" if score >= 4000 else "Rare" if score >= 1500 else "Apprenti")
        e.description = f"⚡ **{score:,} points d'aura**\n🏅 Rang : **{rank}**\n{'🟪' * min(10, max(1, score // 1000))}"
    elif mode == "scan":
        e.description = (
            f"🧠 Intelligence imaginaire : **{score}%**\n"
            f"😎 Charisme cosmique : **{score2}%**\n"
            f"🍕 Passion pizza : **{score3}%**\n"
            f"⚡ Énergie : **{fixed_score(guild_id, user.id, 'energy')}%**\n"
            f"🐱 Animal totem : **{('chat', 'renard', 'panda', 'capybara')[score % 4]}**"
        )
    elif mode == "hack":
        e.description = (
            "🎭 **SIMULATION HUMORISTIQUE — aucune donnée réelle.**\n\n"
            f"🔓 Accès au royaume des memes : **réussi**\n"
            f"🍪 Cookies imaginaires : **{score}**\n"
            f"🖥️ Onglets interdimensionnels : **{score2}**\n"
            f"🔎 Dernière recherche fictive : **comment devenir une légende ?**\n"
            f"🛡️ Mot de passe imaginaire : **croissant-magique**\n"
            f"💥 Niveau de chaos : **{score3}%**"
        )
    elif mode == "ship":
        partner = other or user
        pair = sorted((user.id, partner.id))
        compatibility = fixed_score(guild_id, pair[0], f"ship:{pair[1]}")
        e.description = (
            f"{user.mention} 💞 {partner.mention}\n"
            f"Compatibilité fictive : **{compatibility}%**\n"
            + "💗" * max(1, compatibility // 10)
            + "\n*Simple jeu, aucune vraie prédiction.*"
        )
    elif mode == "wanted":
        e.description = (
            f"🚨 Recherché pour : **avoir volé {score2} cookies au serveur**\n"
            f"💰 Prime fictive : **{score * 17} biscuits**\n"
            f"🕶️ Danger : **{score3}% de swag**"
        )
    elif mode == "personality":
        role = ("Le Sage", "Le Blagueur", "L'Explorateur", "Le Stratège", "Le Chill")[score % 5]
        e.description = (f"🧬 Archétype : **{role}**\n"
                         f"😆 Humour : **{score}%**\n"
                         f"🤝 Esprit d'équipe : **{score2}%**\n"
                         f"🔥 Énergie : **{score3}%**")
    else:
        names = {"rate": "Note", "luck": "Chance", "vibe": "Bonnes vibes", "mood": "Bonne humeur",
                 "rizz": "Charisme", "brain": "Réflexes mentaux", "chaos": "Chaos"}
        e.description = f"✨ **{names.get(mode, 'Score')} : {score}%**\n" + "▰" * (score // 10) + "▱" * (10 - score // 10)
    e.set_footer(text="SentriX Fun • 100 % inventé, pour rire")
    return e


class FunMenu(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)

    @discord.ui.button(label="Réactions", emoji="💗", style=discord.ButtonStyle.primary)
    async def reactions(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.edit_message(embed=menu_embed("social"), view=self)

    @discord.ui.button(label="Animations", emoji="🎭", style=discord.ButtonStyle.secondary)
    async def animations(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.edit_message(embed=menu_embed("solo"), view=self)

    @discord.ui.button(label="Tests & défis", emoji="🔮", style=discord.ButtonStyle.secondary)
    async def modes(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.edit_message(embed=menu_embed("fun"), view=self)


class FunSocial(commands.Cog, name="FunSocial"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.last_action: dict[tuple[int, int], float] = {}

    def _throttle(self, guild_id: int, user_id: int) -> bool:
        now = time.monotonic()
        key = (guild_id, user_id)
        last = self.last_action.get(key, 0.0)
        if now - last < 4:
            return True
        self.last_action[key] = now
        if len(self.last_action) > 5000:
            self.last_action = {k: t for k, t in self.last_action.items() if now - t < 180}
        return False

    async def _count_hug(self, guild_id: int, user_id: int) -> int | None:
        try:
            db = getattr(self.bot, "db", None)
            if db is None:
                return None
            await db.execute(
                "INSERT INTO fun_social_totals (guild_id, user_id, action, total) "
                "VALUES (?, ?, 'hug', 1) "
                "ON CONFLICT(guild_id, user_id, action) DO UPDATE SET total=total+1",
                (guild_id, user_id),
            )
            row = await db.fetchone(
                "SELECT total FROM fun_social_totals WHERE guild_id=? AND user_id=? AND action='hug'",
                (guild_id, user_id),
            )
            return int(row["total"]) if row else None
        except Exception:
            logger.warning("Compteur de câlins indisponible", exc_info=True)
            return None

    async def run_action(self, ctx: commands.Context, action: str,
                         member: discord.Member | None = None,
                         other: discord.Member | None = None) -> None:
        action = action.strip().lower()
        if action in {"help", "menu", "list", "liste"}:
            return await ctx.send(embed=menu_embed(), view=FunMenu())
        if not ctx.guild:
            return await ctx.send("🎉 Les commandes Fun fonctionnent sur un serveur Discord.")
        if action not in ACTIONS and action != "stats":
            return await ctx.send("❓ Action inconnue. Tape \`+fun\` pour voir tout le catalogue.")
        if self._throttle(ctx.guild.id, ctx.author.id):
            return await ctx.send("⏳ Patiente 4 secondes avant une autre action Fun.", delete_after=5)
        target = member or ctx.author
        if action in REACTIONS:
            if member is None:
                return await ctx.send(f"💗 Utilise \`+fun {action} @membre\` (ou le raccourci disponible).")
            title, emoji, verb, category = REACTIONS[action]
            body = f"{ctx.author.mention} **{verb}** {target.mention} !"
            if action == "hug":
                count = await self._count_hug(ctx.guild.id, target.id)
                if count is not None:
                    body += f"\n💞 {target.mention} a reçu **{count} câlins** au total sur ce serveur."
            embed = discord.Embed(title=f"{emoji} {title} !", description=body, colour=FUN_COLORS["social"])
            embed.set_thumbnail(url=ctx.author.display_avatar.url)
            gif, anime = await fetch_gif(category)
            if gif:
                embed.set_image(url=gif)
            if anime:
                embed.add_field(name="🎬 Anime", value=anime, inline=False)
            if not gif:
                embed.add_field(name="🎞️ Animation", value="GIF temporairement indisponible.", inline=False)
        elif action in SOLO:
            title, emoji, verb, category = SOLO[action]
            embed = discord.Embed(title=f"{emoji} {title}", description=f"{ctx.author.mention} **{verb}** !",
                                  colour=FUN_COLORS["solo"])
            gif, anime = await fetch_gif(category)
            if gif:
                embed.set_image(url=gif)
            if anime:
                embed.add_field(name="🎬 Anime", value=anime, inline=False)
            if not gif:
                embed.set_thumbnail(url=ctx.author.display_avatar.url)
                embed.add_field(name="🎞️ Animation", value="GIF temporairement indisponible.", inline=False)
        elif action in {"aura", "hack", "scan", "ship", "rate", "luck", "vibe", "mood",
                        "rizz", "brain", "chaos", "wanted", "personality"}:
            embed = _profile_embed(action, target, ctx.guild.id, other=other)
        elif action == "stats":
            try:
                row = await self.bot.db.fetchone(
                    "SELECT COALESCE(SUM(total), 0) AS n FROM fun_social_totals "
                    "WHERE guild_id=? AND user_id=?", (ctx.guild.id, target.id),
                )
                total = int(row["n"]) if row else 0
            except Exception:
                total = 0
            embed = discord.Embed(title=f"💞 Compteur de câlins de {target.display_name[:60]}",
                                  description=f"🤗 **{total}** câlin(s) reçu(s) sur ce serveur.",
                                  colour=FUN_COLORS["social"])
            embed.set_thumbnail(url=target.display_avatar.url)
        else:
            pool = {
                "fortune": FORTUNES, "compliment": COMPLIMENTS, "roast": ROASTS,
                "truth": TRUTHS, "dare": DARES, "challenge": CHALLENGES,
                "8ball": FORTUNES, "gift": ("🎁 Un cadeau virtuel surprise !", "🍪 Un cookie géant !",
                                         "💎 Une gemme imaginaire !", "🧸 Une peluche toute douce !"),
                "meme": ("Quand le bot fonctionne du premier coup 😎",
                         "Moi : encore 5 minutes. Aussi moi : 3 heures après.",
                         "Ce moment où le Wi-Fi décide de prendre des vacances."),
            }
            choice = secrets.choice(pool[action])
            if action in {"compliment", "roast"}:
                msg = f"{target.mention} {choice}"
            elif action == "gift":
                msg = f"{ctx.author.mention} offre à {target.mention} : **{choice}**"
            else:
                msg = f"**{choice}**"
            names = {"fortune": "🔮 Fortune", "compliment": "💚 Compliment",
                     "roast": "😈 Petite vanne", "truth": "🎤 Vérité",
                     "dare": "🔥 Action", "challenge": "🏆 Défi", "8ball": "🎱 Boule magique",
                     "gift": "🎁 Cadeau", "meme": "😂 Meme"}
            embed = discord.Embed(title=names.get(action, "🎉 Fun"), description=msg,
                                  colour=FUN_COLORS["fun"])
            embed.set_thumbnail(url=target.display_avatar.url)
        embed.set_footer(text="SentriX Fun • bonne humeur, respect et animations adaptées")
        await ctx.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())

    @commands.command(name="fun", aliases=["social"], help="Centre Fun : +fun hug @membre, +fun aura @membre.")
    async def fun(self, ctx: commands.Context, action: str = "menu",
                  membre: discord.Member | None = None, autre: discord.Member | None = None):
        await self.run_action(ctx, action, membre, autre)

    @commands.command(name="hug")
    async def hug(self, ctx: commands.Context, membre: discord.Member | None = None):
        await self.run_action(ctx, "hug", membre)

    @commands.command(name="kiss")
    async def kiss(self, ctx: commands.Context, membre: discord.Member | None = None):
        await self.run_action(ctx, "kiss", membre)

    @commands.command(name="pat")
    async def pat(self, ctx: commands.Context, membre: discord.Member | None = None):
        await self.run_action(ctx, "pat", membre)

    @commands.command(name="slap")
    async def slap(self, ctx: commands.Context, membre: discord.Member | None = None):
        await self.run_action(ctx, "slap", membre)

    @commands.command(name="cuddle")
    async def cuddle(self, ctx: commands.Context, membre: discord.Member | None = None):
        await self.run_action(ctx, "cuddle", membre)

    @commands.command(name="highfive")
    async def highfive(self, ctx: commands.Context, membre: discord.Member | None = None):
        await self.run_action(ctx, "highfive", membre)

    @commands.command(name="poke")
    async def poke(self, ctx: commands.Context, membre: discord.Member | None = None):
        await self.run_action(ctx, "poke", membre)

    @commands.command(name="tickle")
    async def tickle(self, ctx: commands.Context, membre: discord.Member | None = None):
        await self.run_action(ctx, "tickle", membre)

    @commands.command(name="wave")
    async def wave(self, ctx: commands.Context, membre: discord.Member | None = None):
        await self.run_action(ctx, "wave", membre)

    @commands.command(name="dance")
    async def dance(self, ctx: commands.Context):
        await self.run_action(ctx, "dance")

    @commands.command(name="aura")
    async def aura(self, ctx: commands.Context, membre: discord.Member | None = None):
        await self.run_action(ctx, "aura", membre)

    @commands.command(name="hack")
    async def hack(self, ctx: commands.Context, membre: discord.Member | None = None):
        await self.run_action(ctx, "hack", membre)

    @commands.command(name="scan")
    async def scan(self, ctx: commands.Context, membre: discord.Member | None = None):
        await self.run_action(ctx, "scan", membre)

    @commands.command(name="ship")
    async def ship(self, ctx: commands.Context, membre: discord.Member | None = None,
                   autre: discord.Member | None = None):
        # +ship @A @B ou +ship @A => compatibilité entre auteur et @A
        first = membre or ctx.author
        second = autre or (ctx.author if membre else first)
        await self.run_action(ctx, "ship", first, second)

    @commands.command(name="roast")
    async def roast(self, ctx: commands.Context, membre: discord.Member | None = None):
        await self.run_action(ctx, "roast", membre)

    @commands.command(name="compliment")
    async def compliment(self, ctx: commands.Context, membre: discord.Member | None = None):
        await self.run_action(ctx, "compliment", membre)


async def setup(bot: commands.Bot) -> None:
    # Idempotent et isolé : ne modifie pas l'économie ou les tables des autres jeux.
    try:
        await bot.db.execute(
            "CREATE TABLE IF NOT EXISTS fun_social_totals ("
            "guild_id INTEGER NOT NULL, user_id INTEGER NOT NULL, "
            "action TEXT NOT NULL, total INTEGER NOT NULL DEFAULT 0, "
            "PRIMARY KEY(guild_id, user_id, action))"
        )
    except Exception:
        logger.warning("Compteurs Fun non persistants pour cette session", exc_info=True)
    await bot.add_cog(FunSocial(bot))
