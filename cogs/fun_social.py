"""SentriX Fun — réactions GIF pertinentes, mini-profils et défis humoristiques.

Toutes les simulations (hack/scan/aura/ship) sont explicitement fictives.
La famille est préfixée : +fun ... et les raccourcis (+hug, +hack...).
Aucune racine slash supplémentaire n'est enregistrée : budget global préservé.
"""
from __future__ import annotations

import hashlib
import logging
import secrets
import random
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit

import aiohttp
import discord
from discord.ext import commands

from utils import sentrix_panels as panels

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


def fixed_score(guild_id: int, user_id: int, key: str, *, limit: int = 100, day: str | None = None) -> int:
    """Score de fiction stable par jour et par membre, sans données personnelles."""
    day = day or datetime.now(timezone.utc).date().isoformat()
    raw = f"sentrix-fun|{guild_id}|{user_id}|{day}|{key}".encode()
    return int.from_bytes(hashlib.sha256(raw).digest()[:8], "big") % (limit + 1)


def _hier() -> str:
    from datetime import timedelta

    return (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()


# Aura : un rang, une jauge, l'évolution depuis hier et des phrases qui changent.
_AURA_RANGS = (
    (9000, "Mythique", ("Les murs du salon vibrent légèrement.", "Même le bot baisse le volume en votre présence.")),
    (7000, "Légendaire", ("Une aura qui entre dans la pièce avant vous.", "Les notifications se mettent en mode silencieux par respect.")),
    (4000, "Épique", ("Solide, lumineuse, un peu frimeuse.", "Une présence qu'on remarque sans la chercher.")),
    (1500, "Rare", ("Discrète mais bien réelle.", "L'aura du membre fiable sur qui l'on compte.")),
    (0, "Apprenti", ("Elle charge encore, patience.", "Petite flamme, gros potentiel.")),
)


def _aura_texte(guild_id: int, user_id: int) -> tuple[str, int]:
    rng = random.SystemRandom()
    score = fixed_score(guild_id, user_id, "aura", limit=9999)
    hier = fixed_score(guild_id, user_id, "aura", limit=9999, day=_hier())
    seuil, rang, phrases = next(r for r in _AURA_RANGS if score >= r[0])
    delta = score - hier
    fleche = f"▲ +{delta:,}".replace(",", " ") if delta > 0 else f"▼ {delta:,}".replace(",", " ") if delta < 0 else "= stable"
    jauge = "▰" * (score // 1000) + "▱" * (10 - score // 1000)
    lignes = [
        f"⚡ **{score:,} points d'aura**".replace(",", " ") + f" · {fleche} depuis hier",
        f"`{jauge}`",
        f"🏅 Rang : **{rang}** — {rng.choice(phrases)}",
    ]
    if fixed_score(guild_id, user_id, "aura-rare", limit=39) == 0:
        lignes += ["", "🌌 **Éclipse d'aura** : un jour sur quarante, l'aura déborde. C'est aujourd'hui."]
    return "\n".join(lignes), score


# Ship : un nom de couple, une jauge et un message selon la compatibilité.
_SHIP_MESSAGES = (
    (100, ("Compatibilité parfaite. Le serveur peut préparer les confettis.",)),
    (80, ("Un duo qui se comprend sans finir ses phrases.", "Ça sent la complicité à plein nez.")),
    (60, ("Une belle entente, avec un peu d'entraînement.", "Prometteur : il manque juste un fou rire partagé.")),
    (40, ("Ça peut marcher… avec beaucoup de mèmes en commun.", "Des débuts timides, mais rien n'est perdu.")),
    (20, ("Plutôt amis que duo inséparable.", "Le courant passe, sur le mode économie d'énergie.")),
    (1, ("Deux planètes dans deux galaxies différentes.", "Pour l'instant, c'est un « bonjour » poli.")),
    (0, ("Zéro pile. L'algorithme lui-même s'excuse.",)),
)


def _nom_de_couple(a: str, b: str) -> str:
    a, b = a.strip() or "A", b.strip() or "B"
    return (a[: max(1, (len(a) + 1) // 2)] + b[len(b) // 2:]).capitalize()


def _ship_texte(guild_id: int, user: discord.Member, partner: discord.Member) -> str:
    rng = random.SystemRandom()
    pair = sorted((user.id, partner.id))
    score = fixed_score(guild_id, pair[0], f"ship:{pair[1]}")
    message = rng.choice(next(m for seuil, m in _SHIP_MESSAGES if score >= seuil))
    # Pas d'émoji dans la jauge : la couche d'affichage sobre les retire du texte.
    coeurs = "`" + "▰" * (score // 10) + "▱" * (10 - score // 10) + "`"
    return (
        f"{user.mention} 💞 {partner.mention}\n"
        f"Nom de couple : **{_nom_de_couple(user.display_name, partner.display_name)}**\n\n"
        f"Compatibilité du jour : **{score} %**\n{coeurs}\n_{message}_\n\n"
        "-# Simple jeu : le score change chaque jour, aucune vraie prédiction."
    )


def gif_url_is_safe(url: str, category: str) -> bool:
    try:
        parsed = urlsplit(url)
        return (
            parsed.scheme == "https" and parsed.hostname == "nekos.best"
            and parsed.port in (None, 443)
            and parsed.path.startswith(f"/api/v2/{category}/")
            and parsed.path.endswith(".gif")
            and not parsed.username and not parsed.password
        )
    except ValueError:
        return False


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
                    + " · ".join(f"`{name}`" for name in entries),
        colour=FUN_COLORS.get(page, FUN_COLORS["social"]),
    )
    embed.set_footer(text=f"{len(ACTIONS)} actions disponibles • Aucun vrai scan ni piratage")
    return embed


# --------------------------------------------------------------------------
# Faux piratage et scan : une SIMULATION crédible, différente à chaque fois.
# Aucune donnée réelle n'est lue : tout est tiré de ces listes. Pas d'identifiant,
# pas de mot de passe, pas de mention — rien qui puisse passer pour un vrai accès.
# --------------------------------------------------------------------------
_HACK_RECHERCHES = (
    "comment devenir riche rapidement ?", "est-ce que les pigeons dorment debout ?",
    "pourquoi mon wifi me déteste", "recette avec juste des pâtes et du ketchup",
    "comment avoir l'air occupé au travail", "combien de temps peut-on dormir d'affilée",
    "est-ce normal de parler à sa plante", "comment gagner un débat sans avoir raison",
    "meilleure excuse pour annuler une sortie", "les chats nous comprennent-ils vraiment",
    "comment arrêter de procrastiner (demain)", "que faire si on a oublié un anniversaire",
)
_HACK_ACTIVITE = ("Faible", "Modérée", "Élevée", "Très élevée", "Suspecte")
_HACK_DANGER = ("Faible", "Modéré", "Élevé", "Critique pour les biscuits du placard")
_HACK_ACCES = ("Réussi", "Réussi au 3ᵉ essai", "Partiel", "Refusé — défenses trop solides")
_HACK_RARES = (
    "⚠️ Contre-attaque détectée : la cible a hacké la simulation en retour.",
    "🛰️ Signal perdu : la cible s'est déconnectée pour aller manger.",
    "🏆 Profil inviolable : même la simulation abandonne.",
)


def _hack_text() -> str:
    rng = random.SystemRandom()
    lignes = [
        "**Analyse terminée**",
        f"Accès au profil : **{rng.choice(_HACK_ACCES)}**",
        f"Niveau de discrétion : **{rng.randint(12, 98)} %**",
        f"Activité détectée : **{rng.choice(_HACK_ACTIVITE)}**",
        f"Dernière recherche simulée : **« {rng.choice(_HACK_RECHERCHES)} »**",
        f"Indice de danger : **{rng.choice(_HACK_DANGER)}**",
    ]
    if rng.random() < 0.12:
        lignes.append("")
        lignes.append(rng.choice(_HACK_RARES))
    lignes.append("")
    lignes.append("-# Simulation pour rire : aucune donnée réelle n'est consultée.")
    return "\n".join(lignes)


_SCAN_PROFILS = (
    ("Le stratège", "anticipe tout, sauf ce qu'il va manger ce soir"),
    ("L'insomniaque créatif", "ses meilleures idées arrivent à 3 h du matin"),
    ("Le diplomate", "met tout le monde d'accord, surtout sur la pizza"),
    ("L'explorateur", "clique sur tous les boutons pour voir ce qu'ils font"),
    ("Le calme olympien", "rien ne l'atteint, pas même les notifications"),
    ("Le chef d'équipe", "organise un planning pour organiser le planning"),
    ("L'imprévisible", "même le scan n'a pas réussi à le cerner"),
)
_SCAN_TRAITS = ("Concentration", "Sens de l'humour", "Énergie sociale", "Créativité",
                "Patience", "Productivité", "Résistance au café", "Sens de l'orientation")


def _scan_text() -> str:
    rng = random.SystemRandom()
    nom, verdict = rng.choice(_SCAN_PROFILS)
    traits = rng.sample(_SCAN_TRAITS, 3)
    lignes = [f"Profil détecté : **{nom}**", f"_{verdict[0].upper() + verdict[1:]}._", ""]
    for trait in traits:
        valeur = rng.randint(8, 100)
        lignes.append(f"{trait} : **{valeur} %** {'▰' * (valeur // 20)}{'▱' * (5 - valeur // 20)}")
    if rng.random() < 0.1:
        lignes += ["", "✨ Résultat rare : profil jamais vu sur ce serveur."]
    lignes += ["", "-# Scan fictif pour rire : rien n'est réellement analysé."]
    return "\n".join(lignes)


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
        e.description = _aura_texte(guild_id, user.id)[0]
    elif mode == "scan":
        e.description = _scan_text()
    elif mode == "hack":
        e.description = _hack_text()
    elif mode == "ship":
        e.description = _ship_texte(guild_id, user, other or user)
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
        await panels.editer(interaction.response, panels.avec_composants(panels.depuis_embed(menu_embed("social")), self))

    @discord.ui.button(label="Animations", emoji="🎭", style=discord.ButtonStyle.secondary)
    async def animations(self, interaction: discord.Interaction, _: discord.ui.Button):
        await panels.editer(interaction.response, panels.avec_composants(panels.depuis_embed(menu_embed("solo")), self))

    @discord.ui.button(label="Tests & défis", emoji="🔮", style=discord.ButtonStyle.secondary)
    async def modes(self, interaction: discord.Interaction, _: discord.ui.Button):
        await panels.editer(interaction.response, panels.avec_composants(panels.depuis_embed(menu_embed("fun")), self))


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

    async def _aura_classement(self, guild: discord.Guild, target: discord.Member) -> str | None:
        """Les auras du jour sur ce serveur : le podium et la place du membre."""
        try:
            db = self.bot.db
            await db.execute(
                "CREATE TABLE IF NOT EXISTS fun_aura_daily (guild_id INTEGER NOT NULL, user_id INTEGER NOT NULL, "
                "day TEXT NOT NULL, score INTEGER NOT NULL, PRIMARY KEY (guild_id, user_id, day))"
            )
            day = datetime.now(timezone.utc).date().isoformat()
            score = fixed_score(guild.id, target.id, "aura", limit=9999)
            await db.execute(
                "INSERT INTO fun_aura_daily (guild_id, user_id, day, score) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(guild_id, user_id, day) DO UPDATE SET score = excluded.score",
                (guild.id, target.id, day, score),
            )
            rows = await db.fetchall(
                "SELECT user_id, score FROM fun_aura_daily WHERE guild_id = ? AND day = ? ORDER BY score DESC, user_id",
                (guild.id, day),
            )
        except Exception:
            logger.warning("Classement d'aura indisponible", exc_info=True)
            return None
        if len(rows) < 2:
            return "Premier à mesurer son aura aujourd'hui : le classement se remplit avec les suivants."
        medailles = ("1.", "2.", "3.")
        lignes = []
        for i, row in enumerate(rows[:3]):
            membre = guild.get_member(int(row["user_id"]))
            nom = membre.display_name if membre else "membre parti"
            lignes.append(f"{medailles[i]} **{nom[:32]}** — {int(row['score']):,}".replace(",", " "))
        place = next(i for i, row in enumerate(rows, start=1) if int(row["user_id"]) == target.id)
        if place > 3:
            lignes.append(f"… {target.display_name[:32]} : **#{place}** sur {len(rows)}")
        return "\n".join(lignes)

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
            # Même transport que les autres panneaux : un embed + une vue envoyés
            # en direct étaient reconvertis en carte et la vue perdait ses boutons.
            return await panels.envoyer(ctx, panels.avec_composants(panels.depuis_embed(menu_embed()), FunMenu()))
        if not ctx.guild:
            return await ctx.send("🎉 Les commandes Fun fonctionnent sur un serveur Discord.")
        if action not in ACTIONS and action != "stats":
            return await ctx.send("❓ Action inconnue. Tapez `+fun` pour voir tout le catalogue.")
        if self._throttle(ctx.guild.id, ctx.author.id):
            return await ctx.send("⏳ Patientez 4 secondes avant une autre action Fun.", delete_after=5)
        target = member or ctx.author
        if action in REACTIONS:
            if member is None:
                return await ctx.send(f"💗 Utilise `+fun {action} @membre` (ou le raccourci disponible).")
            title, emoji, verb, category = REACTIONS[action]
            body = f"{ctx.author.mention} **{verb}** {target.mention} !"
            if action == "hug":
                count = await self._count_hug(ctx.guild.id, target.id)
                if count is not None:
                    body += (f"\n💞 {target.mention} a reçu **{count} câlin{'s' if count > 1 else ''}** "
                             "au total sur ce serveur.")
            embed = discord.Embed(title=f"{emoji} {title} !", description=body, colour=FUN_COLORS["social"])
            embed.set_thumbnail(url=ctx.author.display_avatar.url)
            gif, anime = await fetch_gif(category)
            if gif:
                embed.set_image(url=gif)
            if anime:
                embed.add_field(name="🎬 Anime", value=anime, inline=False)
            # GIF indisponible : le message reste complet sans lui (brief : un GIF
            # cassé ne doit jamais abîmer la présentation).
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
        elif action in {"aura", "hack", "scan", "ship", "rate", "luck", "vibe", "mood",
                        "rizz", "brain", "chaos", "wanted", "personality"}:
            # Deux membres sont comparés sans imposer une mention supplémentaire.
            if action == "ship" and other is None and member is not None:
                other = ctx.author
            embed = _profile_embed(action, target, ctx.guild.id, other=other)
            if action == "aura":
                classement = await self._aura_classement(ctx.guild, target)
                if classement:
                    embed.add_field(name="Classement du jour", value=classement, inline=False)
            category = {"aura": "smug", "ship": "handhold", "luck": "happy",
                        "vibe": "dance", "mood": "smile", "rizz": "wink",
                        "chaos": "tableflip"}.get(action)
            if category:
                gif, anime = await fetch_gif(category)
                if gif:
                    embed.set_image(url=gif)
                if anime:
                    embed.add_field(name="🎬 Anime", value=anime, inline=False)
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
