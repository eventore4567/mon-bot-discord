"""Suggestions pendant la frappe pour les options « / » en texte libre.

Mesuré le 15/10/2026 sur l'arbre publié : 143 options texte sans aucun choix ni
suggestion. Deux causes :

1. La surface « / » est reconstruite par utils/slash_catalog.py à partir des
   commandes préfixées (sentrix_v95_runtime._make_callback). Les choix déclarés
   sur la commande d'origine (« Activer / Désactiver » de /security antispam,
   « Pierre / Feuille / Ciseaux » de /play rps…) se perdaient en route :
   il fallait taper « on » ou « pierre » à la main. Ils sont repris tels quels.
2. Les autres options n'avaient jamais rien proposé : ville de /weather, raison
   d'une sanction, durée, commande de /help, giveaway en cours, embed
   enregistré, domaine autorisé, membre banni, émoji du serveur…

Une suggestion n'empêche jamais de taper autre chose : seule l'autocomplétion
est ajoutée, jamais une liste fermée (sauf les choix d'origine, qui l'étaient
déjà). Une erreur de lecture ne renvoie simplement aucune suggestion.
"""
from __future__ import annotations

import logging
import time
import unicodedata
from typing import Any, Awaitable, Callable

import discord
from discord import app_commands

logger = logging.getLogger("bot.slash-suggestions")

MAX_CHOICES = 25  # limite Discord
Provider = Callable[[discord.Interaction, str], Awaitable[list[app_commands.Choice[str]]]]


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", str(text or "")).casefold()
    return "".join(ch for ch in text if not unicodedata.combining(ch)).strip()


def _filtrer(current: str, items: list[tuple[str, str]]) -> list[app_commands.Choice[str]]:
    """Choix (nom affiché, valeur) qui commencent par la saisie, puis ceux qui la contiennent."""
    query = _fold(current)
    debut, dedans = [], []
    for name, value in items:
        folded = _fold(name)
        if not query or folded.startswith(query) or _fold(value).startswith(query):
            debut.append((name, value))
        elif query in folded:
            dedans.append((name, value))
    choix = []
    vus = set()
    for name, value in debut + dedans:
        if value in vus or not value:
            continue
        vus.add(value)
        choix.append(app_commands.Choice(name=name[:100], value=str(value)[:100]))
        if len(choix) >= MAX_CHOICES:
            break
    return choix


def _statique(items: list[tuple[str, str]], *, garder_saisie: bool = False) -> Provider:
    async def suggest(_interaction: discord.Interaction, current: str):
        choix = _filtrer(current, items)
        if garder_saisie and current and not any(c.value == current for c in choix):
            choix = [app_commands.Choice(name=current[:100], value=current[:100])] + choix[: MAX_CHOICES - 1]
        return choix

    return suggest


# --------------------------------------------------------------- catalogues fixes

VILLES = [
    # France
    "Paris", "Marseille", "Lyon", "Toulouse", "Nice", "Nantes", "Montpellier", "Strasbourg",
    "Bordeaux", "Lille", "Rennes", "Reims", "Toulon", "Saint-Étienne", "Le Havre", "Grenoble",
    "Dijon", "Angers", "Nîmes", "Villeurbanne", "Clermont-Ferrand", "Le Mans", "Aix-en-Provence",
    "Brest", "Tours", "Amiens", "Limoges", "Annecy", "Perpignan", "Metz", "Besançon", "Orléans",
    "Rouen", "Mulhouse", "Caen", "Nancy", "Argenteuil", "Saint-Denis", "Montreuil", "Roubaix",
    "Tourcoing", "Avignon", "Poitiers", "Pau", "La Rochelle", "Calais", "Cannes", "Ajaccio",
    "Bastia", "Bayonne", "Biarritz", "Chambéry", "Valence", "Troyes", "Lorient", "Vannes",
    "Saint-Malo", "Quimper", "Colmar", "Dunkerque", "Antibes", "Béziers", "Niort", "Cergy",
    # Outre-mer
    "Fort-de-France", "Pointe-à-Pitre", "Cayenne", "Saint-Denis (La Réunion)", "Nouméa",
    "Papeete", "Mamoudzou",
    # Belgique, Suisse, Luxembourg, Monaco
    "Bruxelles", "Liège", "Charleroi", "Namur", "Anvers", "Gand", "Genève", "Lausanne",
    "Zurich", "Berne", "Bâle", "Luxembourg", "Monaco",
    # Canada
    "Montréal", "Québec", "Ottawa", "Toronto", "Vancouver", "Gatineau", "Sherbrooke",
    # Afrique
    "Alger", "Oran", "Constantine", "Tunis", "Sfax", "Casablanca", "Rabat", "Marrakech", "Fès",
    "Tanger", "Agadir", "Dakar", "Abidjan", "Bamako", "Ouagadougou", "Niamey", "Conakry",
    "Lomé", "Cotonou", "Douala", "Yaoundé", "Libreville", "Kinshasa", "Brazzaville",
    "Antananarivo", "Le Caire", "Johannesburg", "Lagos", "Nairobi",
    # Europe
    "Londres", "Berlin", "Madrid", "Barcelone", "Rome", "Milan", "Lisbonne", "Porto",
    "Amsterdam", "Vienne", "Prague", "Varsovie", "Budapest", "Athènes", "Dublin",
    "Copenhague", "Stockholm", "Oslo", "Helsinki", "Istanbul", "Moscou", "Kiev", "Bucarest",
    # Amériques, Asie, Océanie
    "New York", "Los Angeles", "Miami", "Chicago", "Mexico", "São Paulo", "Rio de Janeiro",
    "Buenos Aires", "Bogotá", "Lima", "Tokyo", "Séoul", "Pékin", "Shanghai", "Hong Kong",
    "Bangkok", "Singapour", "Dubaï", "Doha", "Riyad", "Beyrouth", "Tel Aviv", "Mumbai",
    "New Delhi", "Sydney", "Melbourne",
]

RAISONS = [
    "Spam", "Flood", "Insultes", "Harcèlement", "Propos haineux", "Publicité non autorisée",
    "Lien malveillant / arnaque", "Contenu inapproprié", "Contenu NSFW", "Usurpation d'identité",
    "Compte suspect (raid)", "Mentions abusives", "Non-respect du règlement", "Comportement toxique",
    "Contournement de sanction", "Double compte", "Pseudo ou avatar inapproprié",
]

# Une option « raison » n'est pas toujours un motif de sanction. /afk demande
# pourquoi on s'absente, /rep pourquoi on remercie quelqu'un, /invites bonus
# pourquoi on crédite des invitations. Proposer « Compte suspect (raid) » ou
# « Usurpation d'identité » à quelqu'un qui part manger n'a aucun sens, et
# c'est ce que faisait la règle générale sur le nom d'option.
RAISONS_ABSENCE = [
    "Je reviens vite", "Pause", "Repas", "Au travail", "En cours", "En révisions",
    "Je dors", "Occupé", "En déplacement", "Pas devant l'écran", "En jeu",
]

RAISONS_REPUTATION = [
    "Merci pour l'aide", "Toujours disponible", "Bon conseil", "Super accueil",
    "A résolu mon problème", "Très patient", "Bonne ambiance", "Beau geste",
]

RAISONS_INVITATIONS = [
    "Récompense d'événement", "Correction d'un comptage", "Participation au concours",
    "Compensation", "Invitations frauduleuses", "Parrainage",
]

DUREES = [
    ("1 minute", "1m"), ("5 minutes", "5m"), ("10 minutes", "10m"), ("30 minutes", "30m"),
    ("1 heure", "1h"), ("3 heures", "3h"), ("6 heures", "6h"), ("12 heures", "12h"),
    ("1 jour", "1j"), ("3 jours", "3j"), ("7 jours", "7j"), ("14 jours", "14j"), ("28 jours", "28j"),
]

DUREES_MODE_LENT = [
    ("Désactiver le mode lent", "off"), ("5 secondes", "5s"), ("10 secondes", "10s"),
    ("30 secondes", "30s"), ("1 minute", "1m"), ("5 minutes", "5m"), ("10 minutes", "10m"),
    ("30 minutes", "30m"), ("1 heure", "1h"), ("6 heures (maximum)", "6h"),
]

PREFIXES = [("+", "+"), ("!", "!"), ("?", "?"), (".", "."), ("$", "$"), ("-", "-"), (";", ";"), (">", ">")]

DOMAINES_COURANTS = [
    "youtube.com", "youtu.be", "twitch.tv", "tiktok.com", "instagram.com", "x.com", "twitter.com",
    "reddit.com", "github.com", "wikipedia.org", "spotify.com", "soundcloud.com", "medal.tv",
    "tenor.com", "giphy.com", "imgur.com", "steamcommunity.com", "store.steampowered.com",
    "roblox.com", "epicgames.com", "google.com", "docs.google.com", "drive.google.com",
]


# --------------------------------------------------------------- suggestions vivantes

_CACHE: dict[tuple[str, int], tuple[float, list[tuple[str, str]]]] = {}
_CACHE_TTL = 60.0


async def _cache(kind: str, guild_id: int, charger: Callable[[], Awaitable[list[tuple[str, str]]]]):
    now = time.monotonic()
    hit = _CACHE.get((kind, guild_id))
    if hit and hit[0] > now:
        return hit[1]
    try:
        items = await charger()
    except Exception:
        logger.debug("Suggestions %s illisibles guild=%s", kind, guild_id, exc_info=True)
        items = []
    if len(_CACHE) > 4000:
        _CACHE.clear()
    _CACHE[(kind, guild_id)] = (now + _CACHE_TTL, items)
    return items


def _vivant(kind: str, charger_pour: Callable[[discord.Interaction], Awaitable[list[tuple[str, str]]]]) -> Provider:
    async def suggest(interaction: discord.Interaction, current: str):
        guild = interaction.guild
        if guild is None:
            return []
        items = await _cache(kind, guild.id, lambda: charger_pour(interaction))
        return _filtrer(current, items)

    return suggest


async def _giveaways(interaction: discord.Interaction, actifs: bool) -> list[tuple[str, str]]:
    db = interaction.client.db
    statut = "status='actif'" if actifs else "status!='actif'"
    rows: list[Any] = []
    for table in ("giveaways_v2", "giveaways"):
        try:
            rows += list(await db.fetchall(
                f"SELECT message_id, prize FROM {table} WHERE guild_id=? AND {statut} "
                "ORDER BY end_at DESC LIMIT 25",
                (interaction.guild.id,),
            ))
        except Exception:
            continue
    return [(f"{str(r['prize'] or 'Giveaway')[:70]} · {r['message_id']}", str(r["message_id"])) for r in rows
            if r["message_id"]]


async def _embeds(interaction: discord.Interaction) -> list[tuple[str, str]]:
    rows = await interaction.client.db.fetchall(
        "SELECT name FROM embed_templates WHERE guild_id=? ORDER BY name LIMIT 100", (interaction.guild.id,)
    )
    return [(r["name"], r["name"]) for r in rows if r["name"]]


async def _domaines_autorises(interaction: discord.Interaction) -> list[tuple[str, str]]:
    automod = interaction.client.get_cog("Automod")
    domaines = await automod.get_whitelist_domains_cached(interaction.guild.id) if automod else []
    return [(d, d) for d in domaines]


async def _mots_interdits(interaction: discord.Interaction) -> list[tuple[str, str]]:
    automod = interaction.client.get_cog("Automod")
    mots = await automod.get_blacklist_words_cached(interaction.guild.id) if automod else []
    return [(m, m) for m in mots]


async def _bannis(interaction: discord.Interaction) -> list[tuple[str, str]]:
    items = []
    async for entry in interaction.guild.bans(limit=200):
        items.append((f"{entry.user.name} · {entry.user.id}", str(entry.user.id)))
    return items


async def _emojis(interaction: discord.Interaction) -> list[tuple[str, str]]:
    return [(e.name, e.name) for e in interaction.guild.emojis]


async def _commandes(interaction: discord.Interaction, current: str):
    bot = interaction.client
    noms = sorted(
        c.qualified_name for c in bot.walk_commands() if not getattr(c, "hidden", False)
    )
    return _filtrer(current, [(n, n) for n in noms])


async def _evenements_logs(interaction: discord.Interaction, current: str):
    from utils import log_service

    items = []
    for key, meta in getattr(log_service, "LOG_TYPES", {}).items():
        label = str((meta or {}).get("label") or key) if isinstance(meta, dict) else str(key)
        items.append((f"{label} ({key})" if label != key else key, key))
    return _filtrer(current, items)


async def _statuts_suggestion(interaction: discord.Interaction, current: str):
    from services import suggestions as svc

    noms = {"pending": "En attente", "planned": "Prévue", "accepted": "Acceptée",
            "implemented": "Réalisée", "rejected": "Refusée"}
    return _filtrer(current, [(noms.get(s, s), s) for s in svc.STATUSES])


async def _references(interaction: discord.Interaction) -> list[tuple[str, str]]:
    rows = await interaction.client.db.fetchall(
        "SELECT ref, command FROM sentrix_traces WHERE guild_id=? ORDER BY created_at DESC LIMIT 25",
        (interaction.guild.id,),
    )
    return [(f"{r['ref']} · {r['command']}", str(r["ref"])) for r in rows if r["ref"]]


MONTANT_TOUT = _statique([("Tout (all)", "all")], garder_saisie=True)

# Par (commande publiée, option) d'abord, puis par nom d'option.
PAR_COMMANDE: dict[tuple[str, str], Provider] = {
    ("giveaway end", "message_id"): _vivant("giveaways-actifs", lambda i: _giveaways(i, True)),
    ("giveaway cancel", "message_id"): _vivant("giveaways-actifs", lambda i: _giveaways(i, True)),
    ("giveaway reroll", "message_id"): _vivant("giveaways-finis", lambda i: _giveaways(i, False)),
    ("protection link-deny", "domaine"): _vivant("domaines", _domaines_autorises),
    ("protection link-allow", "domaine"): _statique([(d, d) for d in DOMAINES_COURANTS], garder_saisie=True),
    ("protection blacklist-remove", "mot"): _vivant("mots", _mots_interdits),
    ("protection word-remove", "mot"): _vivant("mots", _mots_interdits),
    ("unban", "user_id"): _vivant("bannis", _bannis),
    ("server emoji-remove", "emoji"): _vivant("emojis", _emojis),
    ("suggestions status", "status"): _statuts_suggestion,
    ("economy deposit", "montant"): MONTANT_TOUT,
    ("economy withdraw", "montant"): MONTANT_TOUT,
    ("logs trace", "reference"): _vivant("references", _references),
    ("moderation slowmode", "duree"): _statique(DUREES_MODE_LENT, garder_saisie=True),
    ("logs enable", "evenement"): _evenements_logs,
    ("logs disable", "evenement"): _evenements_logs,
}

PAR_OPTION: dict[str, Provider] = {
    "ville": _statique([(v, v) for v in VILLES], garder_saisie=True),
    "duree": _statique(DUREES, garder_saisie=True),
    "prefixe": _statique(PREFIXES, garder_saisie=True),
    "commande": _commandes,
}

# Les embeds enregistrés : toutes les commandes /embeds qui désignent un embed par son nom.
for _path in ("embeds edit", "embeds preview", "embeds send", "embeds delete", "embeds duplicate",
              "embeds export"):
    PAR_COMMANDE[(_path, "nom")] = _vivant("embeds", _embeds)
PAR_COMMANDE[("embeds rename", "ancien_nom")] = _vivant("embeds", _embeds)

# « raison » n'est plus une règle générale sur le nom d'option : chaque famille
# reçoit la sienne. Une commande absente de ces listes garde un champ libre
# sans suggestion, ce qui vaut mieux qu'une suggestion à côté de la plaque.
_SANCTIONS = (
    "ban", "unban", "kick", "warn", "timeout", "untimeout",
    "moderation hackban", "moderation tempban", "moderation lock",
    "security isolate", "protection block",
)
for _chemin in _SANCTIONS:
    PAR_COMMANDE[(_chemin, "raison")] = _statique([(r, r) for r in RAISONS], garder_saisie=True)

for _chemin in ("afk",):
    PAR_COMMANDE[(_chemin, "raison")] = _statique(
        [(r, r) for r in RAISONS_ABSENCE], garder_saisie=True
    )

for _chemin in ("rep give",):
    PAR_COMMANDE[(_chemin, "raison")] = _statique(
        [(r, r) for r in RAISONS_REPUTATION], garder_saisie=True
    )

for _chemin in ("invites bonus", "invites deduct"):
    PAR_COMMANDE[(_chemin, "raison")] = _statique(
        [(r, r) for r in RAISONS_INVITATIONS], garder_saisie=True
    )


# --------------------------------------------------------------- branchement

def _lier(autocomplete: Any, binding: Any) -> Provider:
    """Une autocomplétion de cog (méthode) appelée hors de son cog d'origine."""
    if getattr(autocomplete, "pass_command_binding", False):
        async def suggest(interaction: discord.Interaction, current: str):
            return await autocomplete(binding, interaction, current)

        return suggest
    return autocomplete


def enrichir(bot: Any, leaf: Any, source: str, path: str) -> int:
    """Ajoute choix et suggestions aux options texte de ``leaf`` ; rend le nombre d'options enrichies."""
    if not isinstance(leaf, app_commands.Command):
        return 0
    origine = {}
    prefix = bot.get_command(source) if hasattr(bot, "get_command") else None
    hybrid = getattr(prefix, "app_command", None)
    if isinstance(hybrid, app_commands.Command):
        # Les paramètres internes : sur les publics, ``autocomplete`` n'est qu'un booléen.
        origine = dict(getattr(hybrid, "_params", {}))
    count = 0
    for name, param in getattr(leaf, "_params", {}).items():
        if param.type is not discord.AppCommandOptionType.string or param.choices or param.autocomplete:
            continue
        source_param = origine.get(name)
        if source_param is not None and source_param.choices:
            param.choices = list(source_param.choices)
            count += 1
            continue
        if source_param is not None and callable(source_param.autocomplete) and hybrid.binding is not None:
            param.autocomplete = _lier(source_param.autocomplete, hybrid.binding)
            count += 1
            continue
        provider = PAR_COMMANDE.get((path, name)) or PAR_OPTION.get(name)
        if provider is not None:
            param.autocomplete = provider
            count += 1
    return count


__all__ = [
    "enrichir", "VILLES", "RAISONS", "RAISONS_ABSENCE", "RAISONS_REPUTATION",
    "RAISONS_INVITATIONS", "DUREES", "PAR_COMMANDE", "PAR_OPTION",
]
