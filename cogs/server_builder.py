"""
Configuration complète d'un serveur Discord existant.

+create-server installe un modèle complet dans le serveur courant : rôles, catégories,
salons, permissions, règlement, annonce d'ouverture et panneau de tickets. L'opération
est idempotente : les éléments portant déjà le même nom sont réutilisés et mis à jour.

Un bot Discord ne peut pas créer un nouveau serveur Discord. Cette commande configure
donc toujours le serveur dans lequel elle est lancée.
"""

import asyncio
import logging
import re

import discord
from discord import app_commands
from discord.ext import commands

from utils import checks, embeds


logger = logging.getLogger("bot.server_builder")


def _perms(**kwargs) -> discord.Permissions:
    return discord.Permissions(**kwargs)


NO_PERMISSIONS = discord.Permissions.none()
FOUNDER_PERMISSIONS = _perms(administrator=True)
DIRECTION_PERMISSIONS = _perms(
    view_audit_log=True,
    manage_guild=True,
    manage_roles=True,
    manage_channels=True,
    kick_members=True,
    ban_members=True,
    moderate_members=True,
    manage_messages=True,
    manage_threads=True,
    manage_nicknames=True,
    manage_events=True,
    move_members=True,
    mute_members=True,
    deafen_members=True,
)
ADMIN_PERMISSIONS = _perms(
    view_audit_log=True,
    manage_roles=True,
    manage_channels=True,
    kick_members=True,
    ban_members=True,
    moderate_members=True,
    manage_messages=True,
    manage_threads=True,
    manage_nicknames=True,
    manage_events=True,
    move_members=True,
    mute_members=True,
    deafen_members=True,
)
MOD_MANAGER_PERMISSIONS = _perms(
    view_audit_log=True,
    kick_members=True,
    ban_members=True,
    moderate_members=True,
    manage_messages=True,
    manage_threads=True,
    manage_nicknames=True,
    move_members=True,
    mute_members=True,
    deafen_members=True,
)
MODERATOR_PERMISSIONS = _perms(
    kick_members=True,
    moderate_members=True,
    manage_messages=True,
    manage_threads=True,
    manage_nicknames=True,
    move_members=True,
    mute_members=True,
    deafen_members=True,
)
TRIAL_MODERATOR_PERMISSIONS = _perms(
    moderate_members=True,
    manage_messages=True,
    manage_threads=True,
    move_members=True,
    mute_members=True,
)
SUPPORT_MANAGER_PERMISSIONS = _perms(
    manage_messages=True,
    manage_threads=True,
    moderate_members=True,
    manage_nicknames=True,
    move_members=True,
)
SUPPORT_PERMISSIONS = _perms(
    manage_messages=True,
    manage_threads=True,
    move_members=True,
)
EVENT_MANAGER_PERMISSIONS = _perms(
    manage_events=True,
    manage_messages=True,
    manage_threads=True,
    move_members=True,
    mute_members=True,
)
CONTENT_MANAGER_PERMISSIONS = _perms(
    manage_messages=True,
    manage_threads=True,
    manage_webhooks=True,
)


def _role(
    name: str,
    color: discord.Color,
    permissions: discord.Permissions = NO_PERMISSIONS,
    *,
    hoist: bool = False,
) -> tuple[str, discord.Color, bool, discord.Permissions]:
    return name, color, hoist, permissions


# 78 rôles. Seul Fondateur possède Administrateur. Les autres rôles sensibles ont
# uniquement les permissions nécessaires à leur mission.
COMPLETE_ROLES = [
    _role("Fondateur", discord.Color.dark_red(), FOUNDER_PERMISSIONS, hoist=True),
    _role("Cofondateur", discord.Color.red(), DIRECTION_PERMISSIONS, hoist=True),
    _role("Direction", discord.Color.from_rgb(170, 25, 55), DIRECTION_PERMISSIONS, hoist=True),
    _role("Administrateur", discord.Color.orange(), ADMIN_PERMISSIONS, hoist=True),
    _role("Responsable général", discord.Color.gold(), ADMIN_PERMISSIONS, hoist=True),
    _role("Responsable modération", discord.Color.from_rgb(230, 110, 30), MOD_MANAGER_PERMISSIONS, hoist=True),
    _role("Modérateur senior", discord.Color.from_rgb(235, 140, 50), MOD_MANAGER_PERMISSIONS, hoist=True),
    _role("Modérateur", discord.Color.from_rgb(240, 165, 70), MODERATOR_PERMISSIONS, hoist=True),
    _role("Modérateur test", discord.Color.from_rgb(245, 190, 100), TRIAL_MODERATOR_PERMISSIONS, hoist=True),
    _role("Responsable support", discord.Color.dark_teal(), SUPPORT_MANAGER_PERMISSIONS, hoist=True),
    _role("Support senior", discord.Color.teal(), SUPPORT_MANAGER_PERMISSIONS, hoist=True),
    _role("Support", discord.Color.from_rgb(70, 190, 180), SUPPORT_PERMISSIONS, hoist=True),
    _role("Responsable sécurité", discord.Color.dark_blue(), MOD_MANAGER_PERMISSIONS, hoist=True),
    _role("Sécurité", discord.Color.blue(), MODERATOR_PERMISSIONS, hoist=True),
    _role("Responsable animation", discord.Color.dark_purple(), EVENT_MANAGER_PERMISSIONS, hoist=True),
    _role("Animateur", discord.Color.purple(), EVENT_MANAGER_PERMISSIONS, hoist=True),
    _role("Responsable événements", discord.Color.magenta(), EVENT_MANAGER_PERMISSIONS, hoist=True),
    _role("Organisateur", discord.Color.from_rgb(210, 80, 180), EVENT_MANAGER_PERMISSIONS, hoist=True),
    _role("Responsable partenariats", discord.Color.from_rgb(80, 120, 220), CONTENT_MANAGER_PERMISSIONS, hoist=True),
    _role("Partenariats", discord.Color.from_rgb(100, 145, 230), CONTENT_MANAGER_PERMISSIONS, hoist=True),
    _role("Développeur", discord.Color.from_rgb(75, 90, 120), CONTENT_MANAGER_PERMISSIONS, hoist=True),
    _role("Designer", discord.Color.from_rgb(200, 90, 160), CONTENT_MANAGER_PERMISSIONS, hoist=True),
    _role("Community manager", discord.Color.from_rgb(90, 130, 210), CONTENT_MANAGER_PERMISSIONS, hoist=True),
    _role("Bots", discord.Color.dark_grey()),
    _role("Créateur de contenu", discord.Color.from_rgb(220, 70, 120), hoist=True),
    _role("Streamer", discord.Color.purple(), hoist=True),
    _role("YouTube", discord.Color.red(), hoist=True),
    _role("TikTok", discord.Color.from_rgb(30, 30, 35), hoist=True),
    _role("Partenaire", discord.Color.blue(), hoist=True),
    _role("Booster", discord.Color.magenta(), hoist=True),
    _role("Premium", discord.Color.gold(), hoist=True),
    _role("VIP", discord.Color.from_rgb(245, 205, 70), hoist=True),
    _role("Membre vérifié", discord.Color.green()),
    _role("Membre actif", discord.Color.blurple()),
    _role("Membre", discord.Color.from_rgb(120, 135, 160)),
    _role("Nouveau membre", discord.Color.light_grey()),
    _role("Muet", discord.Color.dark_grey()),
    _role("Notifications annonces", discord.Color.blue()),
    _role("Notifications événements", discord.Color.purple()),
    _role("Notifications concours", discord.Color.gold()),
    _role("Notifications mises à jour", discord.Color.teal()),
    _role("Niveau 100", discord.Color.gold(), hoist=True),
    _role("Niveau 75", discord.Color.from_rgb(230, 175, 50)),
    _role("Niveau 50", discord.Color.purple()),
    _role("Niveau 40", discord.Color.blue()),
    _role("Niveau 30", discord.Color.teal()),
    _role("Niveau 25", discord.Color.green()),
    _role("Niveau 20", discord.Color.from_rgb(95, 180, 95)),
    _role("Niveau 15", discord.Color.from_rgb(110, 165, 120)),
    _role("Niveau 10", discord.Color.from_rgb(120, 150, 150)),
    _role("Niveau 5", discord.Color.light_grey()),
    _role("PC", discord.Color.blurple()),
    _role("PlayStation", discord.Color.blue()),
    _role("Xbox", discord.Color.green()),
    _role("Nintendo", discord.Color.red()),
    _role("Mobile", discord.Color.teal()),
    _role("Roblox", discord.Color.from_rgb(180, 50, 50)),
    _role("Minecraft", discord.Color.from_rgb(70, 150, 70)),
    _role("Fortnite", discord.Color.purple()),
    _role("Valorant", discord.Color.from_rgb(245, 70, 85)),
    _role("GTA", discord.Color.dark_green()),
    _role("Rocket League", discord.Color.blue()),
    _role("Français", discord.Color.blurple()),
    _role("English", discord.Color.red()),
    _role("العربية", discord.Color.green()),
    _role("Europe", discord.Color.blue()),
    _role("Afrique", discord.Color.gold()),
    _role("Amérique", discord.Color.red()),
    _role("Rouge", discord.Color.red()),
    _role("Orange", discord.Color.orange()),
    _role("Jaune", discord.Color.gold()),
    _role("Vert", discord.Color.green()),
    _role("Bleu", discord.Color.blue()),
    _role("Violet", discord.Color.purple()),
    _role("Rose", discord.Color.magenta()),
    _role("Cyan", discord.Color.teal()),
    _role("Blanc", discord.Color.from_rgb(235, 235, 235)),
    _role("Noir", discord.Color.from_rgb(30, 30, 30)),
]


STAFF_ROLE_NAMES = {
    "Fondateur",
    "Cofondateur",
    "Direction",
    "Administrateur",
    "Responsable général",
    "Responsable modération",
    "Modérateur senior",
    "Modérateur",
    "Modérateur test",
    "Responsable support",
    "Support senior",
    "Support",
    "Responsable sécurité",
    "Sécurité",
    "Responsable animation",
    "Animateur",
    "Responsable événements",
    "Organisateur",
    "Responsable partenariats",
    "Partenariats",
    "Développeur",
    "Designer",
    "Community manager",
}


CATEGORY_EMOJIS = {
    "ACCUEIL": "📌",
    "COMMUNAUTÉ": "💬",
    "JEUX": "🎮",
    "ÉVÉNEMENTS": "🎉",
    "ÉCONOMIE": "💰",
    "CRÉATEURS": "🎥",
    "SUPPORT": "🎫",
    "VOCAUX": "🔊",
    "PARTENAIRES": "🤝",
    "TICKETS OUVERTS": "🎫",
    "STAFF": "🔒",
    "LOGS": "📋",
    "ARCHIVES": "🗃️",
    "COMPÉTITION": "🏆",
    "ENTREPRISE": "💼",
    "SAV": "🛠️",
}

CATEGORY_ALIASES = {
    "ACCUEIL": {"accueil", "infos", "général"},
    "JEUX": {"jeux", "gaming"},
}

CHANNEL_EMOJIS = {
    "annonces": "📢",
    "règlement": "📜",
    "bienvenue": "👋",
    "départs": "🚪",
    "informations": "ℹ️",
    "choix-des-rôles": "🎭",
    "présentations": "🙋",
    "général": "💬",
    "discussion-libre": "🗣️",
    "médias": "📸",
    "clips": "🎬",
    "memes": "😂",
    "sondages": "📊",
    "suggestions": "💡",
    "commandes-bot": "🤖",
    "hors-sujet": "☕",
    "gaming": "🎮",
    "recherche-de-joueurs": "🔎",
    "actualités-jeux": "📰",
    "captures-et-clips": "📷",
    "tournois": "🏆",
    "équipes": "👥",
    "résultats": "🥇",
    "calendrier": "📅",
    "événements": "🎉",
    "inscriptions": "📝",
    "concours": "🎁",
    "gagnants": "🏅",
    "économie-commandes": "💰",
    "boutique": "🛒",
    "classement": "📈",
    "récompenses": "🎖️",
    "créations": "🎨",
    "streams": "🔴",
    "vidéos": "📺",
    "collaborations": "🤝",
    "ouvrir-un-ticket": "🎫",
    "aide": "❓",
    "questions-fréquentes": "📚",
    "statut-des-services": "📡",
    "informations-partenariats": "ℹ️",
    "demandes-partenariats": "🤝",
    "nos-partenaires": "🌐",
    "staff-général": "🔒",
    "staff-annonces": "📢",
    "signalements": "🚨",
    "sanctions": "🔨",
    "tâches": "📋",
    "réunions-staff": "📅",
    "candidatures": "📄",
    "logs-modération": "🛡️",
    "logs-serveur": "⚙️",
    "logs-rôles": "🎭",
    "logs-tickets": "🎫",
    "logs-membres": "👥",
    "logs-messages": "💬",
    "logs-vocaux": "🔊",
    "logs-sécurité": "🔐",
    "archives-tickets": "🎫",
    "archives-sanctions": "🔨",
    "archives-événements": "🎉",
    "classement-gaming": "🏆",
    "recrutement-équipes": "👥",
    "défis": "⚔️",
    "matchs": "🎮",
    "direction": "👑",
    "ressources-humaines": "👥",
    "projets": "📁",
    "documents": "📄",
    "comptes-rendus": "📝",
    "incidents-connus": "📡",
    "signaler-un-bug": "🐛",
    "facturation": "💳",
    "retours-clients": "💬",
    "guides": "📚",
}

CHANNEL_TOPICS = {
    "annonces": "Annonces officielles du serveur.",
    "règlement": "Règlement officiel à lire et à respecter.",
    "bienvenue": "Informations utiles pour bien commencer sur le serveur.",
    "départs": "Messages de départ des membres.",
    "informations": "Informations générales et fonctionnement du serveur.",
    "choix-des-rôles": "Choisissez ici vos rôles, notifications et centres d'intérêt.",
    "présentations": "Présentez-vous à la communauté.",
    "général": "Salon principal de discussion de la communauté.",
    "suggestions": "Proposez des améliorations claires et constructives.",
    "commandes-bot": "Utilisez ici les commandes de SentriX et des autres bots.",
    "ouvrir-un-ticket": "Ouvrez un ticket privé en choisissant le motif correspondant.",
    "aide": "Demandez de l'aide à la communauté sans partager d'informations privées.",
    "questions-fréquentes": "Réponses aux questions les plus fréquentes.",
    "statut-des-services": "État des services, incidents et maintenances.",
    "staff-général": "Salon privé de coordination de l'équipe.",
    "staff-annonces": "Consignes et annonces réservées à l'équipe.",
    "signalements": "Traitement privé des signalements reçus.",
    "sanctions": "Suivi interne des avertissements et sanctions.",
    "candidatures": "Étude et suivi des candidatures au staff.",
    "logs-modération": "Historique automatique des actions de modération.",
    "logs-serveur": "Créations, suppressions et modifications du serveur.",
    "logs-rôles": "Attributions et retraits de rôles.",
    "logs-tickets": "Historique automatique des tickets.",
    "logs-membres": "Arrivées, départs et changements concernant les membres.",
    "logs-messages": "Suppressions et modifications de messages.",
    "logs-vocaux": "Connexions, déplacements et déconnexions vocales.",
    "logs-sécurité": "Événements de sécurité et détections automatiques.",
}

SLOWMODE_DELAYS = {
    "général": 2,
    "discussion-libre": 2,
    "médias": 5,
    "clips": 5,
    "memes": 5,
    "suggestions": 10,
    "présentations": 10,
    "recherche-de-joueurs": 5,
    "événements": 5,
    "concours": 10,
    "demandes-partenariats": 15,
    "signaler-un-bug": 10,
    "retours-clients": 10,
}


def _plain_discord_name(value: str) -> str:
    """Retire l'emoji décoratif initial pour comparer les anciens et nouveaux noms."""
    value = value.strip()
    if "・" in value:
        value = value.split("・", 1)[1]
    else:
        value = re.sub(r"^[^0-9A-Za-zÀ-ÖØ-öø-ÿ]+", "", value)
    return value.strip().casefold()


def _category_display_name(base_name: str) -> str:
    return f"{CATEGORY_EMOJIS.get(base_name, '📁')}・{base_name}"


def _channel_display_name(base_name: str, channel_type: str, category_name: str) -> str:
    emoji = CHANNEL_EMOJIS.get(base_name.casefold())
    if emoji is None:
        emoji = "🔊" if channel_type == "voice" else CATEGORY_EMOJIS.get(category_name, "💬")
    return f"{emoji}・{base_name}"


def _channel_topic(base_name: str, category_name: str, privacy: str) -> str:
    configured = CHANNEL_TOPICS.get(base_name.casefold())
    if configured:
        return configured
    readable = base_name.replace("-", " ").strip()
    if privacy == "staff":
        return f"Salon privé de l'équipe : {readable}."
    return f"Espace {readable} de la catégorie {category_name.title()}."


def _voice_user_limit(base_name: str) -> int:
    lowered = base_name.casefold()
    if lowered == "duo":
        return 2
    if lowered == "squad":
        return 4
    if "réunion" in lowered or "support vocal" in lowered:
        return 25
    return 0


def _find_category(guild: discord.Guild, base_name: str) -> discord.CategoryChannel | None:
    wanted = base_name.casefold()
    for category in guild.categories:
        if _plain_discord_name(category.name) == wanted:
            return category
    aliases = CATEGORY_ALIASES.get(base_name, {wanted})
    for category in guild.categories:
        if _plain_discord_name(category.name) in aliases:
            return category
    return None


def _find_channel(
    category: discord.CategoryChannel,
    base_name: str,
) -> discord.abc.GuildChannel | None:
    wanted = base_name.casefold()
    return discord.utils.find(
        lambda channel: _plain_discord_name(channel.name) == wanted,
        category.channels,
    )


BASE_CATEGORIES = [
    {
        "name": "ACCUEIL",
        "privacy": "public",
        "channels": [
            ("annonces", "readonly"),
            ("règlement", "readonly"),
            ("bienvenue", "readonly"),
            ("départs", "readonly"),
            ("informations", "readonly"),
            ("choix-des-rôles", "text"),
            ("présentations", "text"),
        ],
    },
    {
        "name": "COMMUNAUTÉ",
        "privacy": "public",
        "channels": [
            ("général", "text"),
            ("discussion-libre", "text"),
            ("médias", "text"),
            ("clips", "text"),
            ("memes", "text"),
            ("sondages", "text"),
            ("suggestions", "text"),
            ("commandes-bot", "text"),
            ("hors-sujet", "text"),
        ],
    },
    {
        "name": "JEUX",
        "privacy": "public",
        "channels": [
            ("gaming", "text"),
            ("recherche-de-joueurs", "text"),
            ("actualités-jeux", "text"),
            ("captures-et-clips", "text"),
            ("tournois", "text"),
            ("équipes", "text"),
            ("résultats", "text"),
        ],
    },
    {
        "name": "ÉVÉNEMENTS",
        "privacy": "public",
        "channels": [
            ("calendrier", "readonly"),
            ("événements", "text"),
            ("inscriptions", "text"),
            ("concours", "text"),
            ("gagnants", "readonly"),
        ],
    },
    {
        "name": "ÉCONOMIE",
        "privacy": "public",
        "channels": [
            ("économie-commandes", "text"),
            ("boutique", "readonly"),
            ("classement", "readonly"),
            ("récompenses", "readonly"),
        ],
    },
    {
        "name": "CRÉATEURS",
        "privacy": "public",
        "channels": [
            ("créations", "text"),
            ("streams", "text"),
            ("vidéos", "text"),
            ("collaborations", "text"),
        ],
    },
    {
        "name": "SUPPORT",
        "privacy": "public",
        "channels": [
            ("ouvrir-un-ticket", "readonly"),
            ("aide", "text"),
            ("questions-fréquentes", "readonly"),
            ("statut-des-services", "readonly"),
        ],
    },
    {
        "name": "VOCAUX",
        "privacy": "public",
        "channels": [
            ("Général 1", "voice"),
            ("Général 2", "voice"),
            ("Général 3", "voice"),
            ("Gaming 1", "voice"),
            ("Gaming 2", "voice"),
            ("Gaming 3", "voice"),
            ("Duo", "voice"),
            ("Squad", "voice"),
            ("Musique", "voice"),
            ("Absent", "voice"),
        ],
    },
    {
        "name": "PARTENAIRES",
        "privacy": "public",
        "channels": [
            ("informations-partenariats", "readonly"),
            ("demandes-partenariats", "text"),
            ("nos-partenaires", "readonly"),
        ],
    },
    {
        "name": "TICKETS OUVERTS",
        "privacy": "staff",
        "channels": [],
    },
    {
        "name": "STAFF",
        "privacy": "staff",
        "channels": [
            ("staff-général", "text"),
            ("staff-annonces", "readonly"),
            ("signalements", "text"),
            ("sanctions", "text"),
            ("tâches", "text"),
            ("réunions-staff", "text"),
            ("candidatures", "text"),
            ("Staff vocal", "voice"),
        ],
    },
    {
        "name": "LOGS",
        "privacy": "staff",
        "channels": [
            ("logs-serveur", "text"),
            ("logs-modération", "text"),
            ("logs-rôles", "text"),
            ("logs-tickets", "text"),
            ("logs-membres", "text"),
            ("logs-messages", "text"),
            ("logs-vocaux", "text"),
            ("logs-sécurité", "text"),
        ],
    },
    {
        "name": "ARCHIVES",
        "privacy": "staff",
        "channels": [
            ("archives-tickets", "readonly"),
            ("archives-sanctions", "readonly"),
            ("archives-événements", "readonly"),
        ],
    },
]


PROFILE_CATEGORIES = {
    "communaute": {
        "name": "COMPÉTITION",
        "privacy": "public",
        "channels": [
            ("classement-gaming", "readonly"),
            ("recrutement-équipes", "text"),
            ("défis", "text"),
            ("matchs", "text"),
            ("Palmarès", "voice"),
        ],
    },
    "pro": {
        "name": "ENTREPRISE",
        "privacy": "staff",
        "channels": [
            ("direction", "text"),
            ("ressources-humaines", "text"),
            ("projets", "text"),
            ("documents", "text"),
            ("comptes-rendus", "readonly"),
            ("Réunion direction", "voice"),
            ("Réunion équipe", "voice"),
        ],
    },
    "support": {
        "name": "SAV",
        "privacy": "public",
        "channels": [
            ("incidents-connus", "readonly"),
            ("signaler-un-bug", "text"),
            ("facturation", "text"),
            ("retours-clients", "text"),
            ("guides", "readonly"),
            ("Support vocal 1", "voice"),
            ("Support vocal 2", "voice"),
        ],
    },
}


def _template_categories(key: str) -> list[dict]:
    return [*BASE_CATEGORIES, PROFILE_CATEGORIES[key]]


SERVER_TEMPLATES = {
    "communaute": {
        "label": "Communauté / Gaming",
        "description": "78 rôles, 14 catégories, plus de 70 salons, tickets, règlement et annonce.",
        "roles": COMPLETE_ROLES,
        "staff_role_name": "Modérateur",
        "member_role_name": "Membre",
        "categories": _template_categories("communaute"),
    },
    "pro": {
        "label": "Professionnel / Entreprise",
        "description": "78 rôles, 14 catégories, plus de 70 salons, tickets et espaces de travail.",
        "roles": COMPLETE_ROLES,
        "staff_role_name": "Modérateur",
        "member_role_name": "Membre",
        "categories": _template_categories("pro"),
    },
    "support": {
        "label": "Support / SAV",
        "description": "78 rôles, 14 catégories, plus de 70 salons et tickets SAV prêts à utiliser.",
        "roles": COMPLETE_ROLES,
        "staff_role_name": "Support",
        "member_role_name": "Membre",
        "categories": _template_categories("support"),
    },
}


TICKET_TYPES = [
    {
        "name": "Support général",
        "description": "Question générale ou demande d'aide.",
        "button_style": "bleu",
        "name_format": "support-{pseudo}",
        "open_message": "Décrivez précisément votre demande. Un membre du support vous répondra dès que possible.",
    },
    {
        "name": "Signalement",
        "description": "Signaler un membre, un contenu ou un comportement.",
        "button_style": "rouge",
        "name_format": "signalement-{pseudo}",
        "open_message": "Expliquez les faits et joignez les preuves disponibles. Ce ticket reste privé.",
    },
    {
        "name": "Partenariat",
        "description": "Proposer un partenariat avec le serveur.",
        "button_style": "gris",
        "name_format": "partenariat-{pseudo}",
        "open_message": "Présentez votre serveur ou projet, vos statistiques et votre proposition.",
    },
    {
        "name": "Recrutement",
        "description": "Candidater pour rejoindre l'équipe.",
        "button_style": "vert",
        "name_format": "candidature-{pseudo}",
        "open_message": "Présentez-vous, indiquez votre disponibilité, votre expérience et vos motivations.",
    },
]


class TemplateSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(
                label=data["label"],
                value=key,
                description=data["description"][:100],
            )
            for key, data in SERVER_TEMPLATES.items()
        ]
        super().__init__(
            placeholder="Choisissez le type de serveur à configurer",
            options=options,
            min_values=1,
            max_values=1,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction):
        view: "ServerBuilderView" = self.view
        view.selected_template = self.values[0]
        view.confirm_btn.disabled = False
        await interaction.response.edit_message(embed=view.build_preview_embed(), view=view)


class ServerBuilderView(discord.ui.View):
    def __init__(self, bot: commands.Bot, author_id: int):
        super().__init__(timeout=180)
        self.bot = bot
        self.author_id = author_id
        self.selected_template: str | None = None
        self.add_item(TemplateSelect())
        self.confirm_btn = discord.ui.Button(
            label="Configurer le serveur",
            style=discord.ButtonStyle.success,
            disabled=True,
            row=1,
        )
        self.confirm_btn.callback = self.confirm
        self.add_item(self.confirm_btn)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "Seule la personne ayant lancé la commande peut utiliser ce menu.",
                ephemeral=True,
            )
            return False
        return True

    def build_preview_embed(self) -> discord.Embed:
        if not self.selected_template:
            return embeds.neutral(
                "Configuration complète du serveur",
                "Choisissez un modèle. La commande configure le serveur actuel ; un bot Discord "
                "ne peut pas créer un nouveau serveur à votre place.",
            )

        data = SERVER_TEMPLATES[self.selected_template]
        total_channels = sum(len(category["channels"]) for category in data["categories"])
        role_names = [role[0] for role in data["roles"]]
        category_names = [
            _category_display_name(category["name"])
            for category in data["categories"]
        ]
        preview = embeds.neutral(
            f"Aperçu — {data['label']}",
            f"Installation dans **{len(data['roles'])} rôles**, "
            f"**{len(data['categories'])} catégories** et **{total_channels} salons**. "
            "Le règlement, l'annonce d'ouverture et le panneau de tickets seront publiés automatiquement.\n\n"
            "Les éléments existants portant le même nom seront réutilisés et mis à jour, sans doublons. "
            "Seul le rôle Fondateur possède Administrateur.",
        )
        for index in range(0, len(role_names), 20):
            preview.add_field(
                name=f"Rôles {index + 1} à {min(index + 20, len(role_names))}",
                value=", ".join(role_names[index:index + 20])[:1024],
                inline=False,
            )
        preview.add_field(
            name="Catégories",
            value=", ".join(category_names)[:1024],
            inline=False,
        )
        return preview

    async def confirm(self, interaction: discord.Interaction):
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(
            embed=embeds.neutral(
                "Configuration en cours",
                "Création des rôles, salons, permissions et tickets. Cette opération peut prendre "
                "une à trois minutes selon les limites de Discord.",
            ),
            view=self,
        )
        cog = self.bot.get_cog("ServerBuilder")
        if cog is None:
            await interaction.edit_original_response(
                embed=embeds.error("Le module de configuration est indisponible."),
                view=None,
            )
            return
        try:
            summary = await cog.build_server(
                interaction.guild,
                self.selected_template,
                interaction.user,
            )
        except discord.Forbidden:
            logger.exception("Permission Discord refusée pendant create-server")
            summary = embeds.error(
                f"Discord a refusé l'étape **{cog._build_step}**. "
                "Placez le rôle SentriX au-dessus des rôles "
                "qu'il doit gérer et accordez-lui Administrateur, puis relancez +create-server."
            )
        except discord.HTTPException as exc:
            logger.exception("Erreur HTTP Discord pendant create-server")
            summary = embeds.error(
                f"Discord a interrompu l'étape **{cog._build_step}** ({exc}). "
                "Les éléments déjà créés sont "
                "conservés : relancez +create-server pour reprendre sans doublons."
            )
        except Exception as exc:
            logger.exception("Erreur inattendue pendant create-server")
            detail = (str(exc) or exc.__class__.__name__).replace("`", "'")[:300]
            summary = embeds.error(
                f"L'installation s'est arrêtée pendant **{cog._build_step}**. "
                f"Détail : `{exc.__class__.__name__}: {detail}`\n\n"
                "Les éléments déjà créés sont conservés. Relancez la commande après correction : "
                "elle reprend sans doublons."
            )
        await interaction.edit_original_response(embed=summary, view=None)
        self.stop()


class ServerBuilder(commands.Cog, name="ServerBuilder"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._build_step = "initialisation"

    @staticmethod
    def _desired_category_overwrites(
        guild: discord.Guild,
        role_map: dict[str, discord.Role],
        privacy: str,
    ) -> dict:
        overwrites: dict = {}
        muted_role = role_map.get("Muet")
        if muted_role:
            overwrites[muted_role] = discord.PermissionOverwrite(
                send_messages=False,
                add_reactions=False,
                speak=False,
                connect=False,
                create_public_threads=False,
                create_private_threads=False,
                send_messages_in_threads=False,
            )
        if privacy == "staff":
            overwrites[guild.default_role] = discord.PermissionOverwrite(view_channel=False)
            for role_name in STAFF_ROLE_NAMES:
                role = role_map.get(role_name)
                if role:
                    overwrites[role] = discord.PermissionOverwrite(
                        view_channel=True,
                        send_messages=True,
                        read_message_history=True,
                        connect=True,
                        speak=True,
                    )
        overwrites[guild.me] = discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            connect=True,
            speak=True,
            manage_channels=True,
            manage_messages=True,
        )
        return overwrites

    @staticmethod
    def _readonly_overwrites(
        guild: discord.Guild,
        role_map: dict[str, discord.Role],
        current: dict,
    ) -> dict:
        overwrites = dict(current)
        default_current = overwrites.get(guild.default_role, discord.PermissionOverwrite())
        default_current.send_messages = False
        default_current.add_reactions = False
        default_current.create_public_threads = False
        default_current.create_private_threads = False
        default_current.send_messages_in_threads = False
        overwrites[guild.default_role] = default_current
        for role_name in STAFF_ROLE_NAMES:
            role = role_map.get(role_name)
            if not role:
                continue
            staff_current = overwrites.get(role, discord.PermissionOverwrite())
            staff_current.view_channel = True
            staff_current.send_messages = True
            staff_current.read_message_history = True
            staff_current.add_reactions = True
            overwrites[role] = staff_current
        bot_current = overwrites.get(guild.me, discord.PermissionOverwrite())
        bot_current.view_channel = True
        bot_current.send_messages = True
        bot_current.read_message_history = True
        bot_current.manage_messages = True
        overwrites[guild.me] = bot_current
        return overwrites

    @staticmethod
    def _capacity_error(guild: discord.Guild, data: dict) -> str | None:
        missing_roles = sum(
            1 for name, *_ in data["roles"] if discord.utils.get(guild.roles, name=name) is None
        )
        missing_categories = 0
        missing_channels = 0
        for category_data in data["categories"]:
            category = _find_category(guild, category_data["name"])
            if category is None:
                missing_categories += 1
                missing_channels += len(category_data["channels"])
            else:
                missing_channels += sum(
                    1
                    for name, _ in category_data["channels"]
                    if _find_channel(category, name) is None
                )
        if len(guild.roles) + missing_roles > 250:
            return (
                f"Il manque {missing_roles} rôles, mais Discord limite un serveur à 250 rôles. "
                "Supprimez quelques rôles inutilisés puis relancez la commande."
            )
        required_channel_slots = missing_categories + missing_channels
        if len(guild.channels) + required_channel_slots > 500:
            return (
                f"Il manque {required_channel_slots} emplacements de salons/catégories, mais "
                "Discord limite un serveur à 500. Supprimez les salons inutilisés puis relancez."
            )
        return None

    async def _ensure_roles(
        self,
        guild: discord.Guild,
        data: dict,
        reason: str,
    ) -> tuple[dict[str, discord.Role], int, int]:
        role_map: dict[str, discord.Role] = {}
        created = 0
        updated = 0
        for name, color, hoist, permissions in data["roles"]:
            role = discord.utils.get(guild.roles, name=name)
            if role is None:
                role = await guild.create_role(
                    name=name,
                    color=color,
                    hoist=hoist,
                    permissions=permissions,
                    reason=reason,
                )
                created += 1
                await asyncio.sleep(0.15)
            elif not role.managed and role < guild.me.top_role:
                if (
                    role.color != color
                    or role.hoist != hoist
                    or role.permissions != permissions
                ):
                    await role.edit(
                        color=color,
                        hoist=hoist,
                        permissions=permissions,
                        reason=reason,
                    )
                    updated += 1
                    await asyncio.sleep(0.12)
            role_map[name] = role
        return role_map, created, updated

    async def _ensure_structure(
        self,
        guild: discord.Guild,
        data: dict,
        role_map: dict[str, discord.Role],
        reason: str,
    ) -> tuple[
        dict[str, discord.CategoryChannel],
        dict[str, discord.abc.GuildChannel],
        int,
        int,
        int,
        int,
    ]:
        category_map: dict[str, discord.CategoryChannel] = {}
        channel_map: dict[str, discord.abc.GuildChannel] = {}
        categories_created = 0
        categories_updated = 0
        channels_created = 0
        channels_updated = 0

        for category_data in data["categories"]:
            base_category_name = category_data["name"]
            display_category_name = _category_display_name(base_category_name)
            desired = self._desired_category_overwrites(
                guild,
                role_map,
                category_data["privacy"],
            )
            category = _find_category(guild, base_category_name)
            if category is None:
                category = await guild.create_category(
                    display_category_name,
                    overwrites=desired,
                    reason=reason,
                )
                categories_created += 1
                await asyncio.sleep(0.15)
            else:
                merged = dict(category.overwrites)
                merged.update(desired)
                if (
                    category.name != display_category_name
                    or merged != category.overwrites
                ):
                    await category.edit(
                        name=display_category_name,
                        overwrites=merged,
                        reason=reason,
                    )
                    categories_updated += 1
                    await asyncio.sleep(0.12)
            category_map[base_category_name] = category

            for channel_name, channel_type in category_data["channels"]:
                display_channel_name = _channel_display_name(
                    channel_name,
                    channel_type,
                    base_category_name,
                )
                channel = _find_channel(category, channel_name)
                if channel is None:
                    if channel_type == "voice":
                        channel = await guild.create_voice_channel(
                            display_channel_name,
                            category=category,
                            bitrate=int(min(96000, guild.bitrate_limit)),
                            user_limit=_voice_user_limit(channel_name),
                            reason=reason,
                        )
                    else:
                        text_options = {
                            "category": category,
                            "topic": _channel_topic(
                                channel_name,
                                base_category_name,
                                category_data["privacy"],
                            ),
                            "slowmode_delay": SLOWMODE_DELAYS.get(
                                channel_name.casefold(),
                                0,
                            ),
                            "nsfw": False,
                            "reason": reason,
                        }
                        if channel_type == "readonly":
                            text_options["overwrites"] = self._readonly_overwrites(
                                guild,
                                role_map,
                                category.overwrites,
                            )
                        channel = await guild.create_text_channel(
                            display_channel_name,
                            **text_options,
                        )
                    channels_created += 1
                    await asyncio.sleep(0.15)
                elif isinstance(channel, discord.TextChannel) and channel_type != "voice":
                    topic = _channel_topic(
                        channel_name,
                        base_category_name,
                        category_data["privacy"],
                    )
                    slowmode = SLOWMODE_DELAYS.get(channel_name.casefold(), 0)
                    text_changes = {
                        "name": display_channel_name,
                        "topic": topic,
                        "slowmode_delay": slowmode,
                        "nsfw": False,
                        "reason": reason,
                    }
                    should_update = (
                        channel.name != display_channel_name
                        or channel.topic != topic
                        or channel.slowmode_delay != slowmode
                        or channel.nsfw
                    )
                    if channel_type == "readonly":
                        desired_readonly = self._readonly_overwrites(
                            guild,
                            role_map,
                            channel.overwrites,
                        )
                        text_changes["overwrites"] = desired_readonly
                        should_update = (
                            should_update
                            or desired_readonly != channel.overwrites
                        )
                    if should_update:
                        await channel.edit(**text_changes)
                        channels_updated += 1
                        await asyncio.sleep(0.12)
                elif isinstance(channel, discord.VoiceChannel) and channel_type == "voice":
                    bitrate = int(min(96000, guild.bitrate_limit))
                    user_limit = _voice_user_limit(channel_name)
                    if (
                        channel.name != display_channel_name
                        or channel.bitrate != bitrate
                        or channel.user_limit != user_limit
                    ):
                        await channel.edit(
                            name=display_channel_name,
                            bitrate=bitrate,
                            user_limit=user_limit,
                            reason=reason,
                        )
                        channels_updated += 1
                        await asyncio.sleep(0.12)
                channel_map[channel_name] = channel

        return (
            category_map,
            channel_map,
            categories_created,
            categories_updated,
            channels_created,
            channels_updated,
        )

    async def _configure_bot_channels(
        self,
        guild: discord.Guild,
        role_map: dict[str, discord.Role],
        category_map: dict[str, discord.CategoryChannel],
        channel_map: dict[str, discord.abc.GuildChannel],
        staff_role_name: str,
    ) -> int:
        """Relie les salons créés aux fonctions SentriX, sans commande manuelle."""
        configured = 0
        role_settings = {
            "mod_role": role_map.get(staff_role_name),
            "admin_role": role_map.get("Administrateur"),
            "autorole": role_map.get("Membre"),
            "member_role": role_map.get("Membre"),
            "verify_role": role_map.get("Membre vérifié"),
            "verification_role": role_map.get("Membre vérifié"),
            "booster_role": role_map.get("Booster"),
            "mute_role": role_map.get("Muet"),
        }
        channel_settings = {
            "welcome_channel": channel_map.get("bienvenue"),
            "goodbye_channel": channel_map.get("départs"),
            "rules_channel": channel_map.get("règlement"),
            "verification_channel": channel_map.get("choix-des-rôles"),
            "announce_channel": channel_map.get("annonces"),
            "suggest_channel": channel_map.get("suggestions"),
            "giveaway_channel": channel_map.get("concours"),
            "bot_commands_channel": channel_map.get("commandes-bot"),
            "report_channel": channel_map.get("signalements"),
            "partner_channel": channel_map.get("demandes-partenariats"),
            "level_channel": channel_map.get("récompenses"),
            "stats_channel": channel_map.get("classement"),
            "afk_channel": channel_map.get("Absent"),
            "error_channel": channel_map.get("logs-sécurité"),
            "log_channel": channel_map.get("logs-modération"),
            "ticket_log_channel": channel_map.get("logs-tickets"),
            "ticket_category": category_map.get("TICKETS OUVERTS"),
            "log_server": channel_map.get("logs-serveur"),
            "log_messages": channel_map.get("logs-messages"),
            "log_members": channel_map.get("logs-membres"),
            "log_voice": channel_map.get("logs-vocaux"),
            "log_roles": channel_map.get("logs-rôles"),
            "log_moderation": channel_map.get("logs-modération"),
            "log_automod": channel_map.get("logs-sécurité"),
        }
        for setting, target in {**role_settings, **channel_settings}.items():
            if target is None:
                continue
            await self.bot.db.set_guild_config(guild.id, setting, target.id)
            configured += 1
        return configured

    @staticmethod
    async def _publish_once(
        channel: discord.TextChannel | None,
        marker: str,
        embed: discord.Embed,
    ) -> bool:
        if channel is None:
            return False
        try:
            async for message in channel.history(limit=50):
                if message.author.id != channel.guild.me.id or not message.embeds:
                    continue
                footer = message.embeds[0].footer.text
                if footer == marker:
                    await message.edit(embed=embed)
                    return False
        except discord.HTTPException:
            logger.warning("Impossible de parcourir l'historique de %s", channel.id)
        await channel.send(embed=embed)
        return True

    async def _publish_welcome_content(
        self,
        guild: discord.Guild,
        channel_map: dict[str, discord.abc.GuildChannel],
    ) -> int:
        rules_channel = channel_map.get("règlement")
        announcements_channel = channel_map.get("annonces")
        welcome_channel = channel_map.get("bienvenue")
        information_channel = channel_map.get("informations")
        roles_channel = channel_map.get("choix-des-rôles")
        faq_channel = channel_map.get("questions-fréquentes")
        status_channel = channel_map.get("statut-des-services")
        ticket_channel = channel_map.get("ouvrir-un-ticket")

        rules_ref = rules_channel.mention if rules_channel else "le salon règlement"
        roles_ref = roles_channel.mention if roles_channel else "le salon des rôles"
        ticket_ref = ticket_channel.mention if ticket_channel else "le salon des tickets"

        rules = discord.Embed(
            title="Règlement du serveur",
            description=(
                "**1. Respect**\n"
                "Respectez chaque membre. Le harcèlement, les insultes, la haine et les menaces sont interdits.\n\n"
                "**2. Contenu approprié**\n"
                "Aucun contenu sexuel, explicite, choquant ou concernant les parties intimes.\n\n"
                "**3. Messages propres**\n"
                "Pas de spam, flood, majuscules abusives, publicité répétée ou contournement des filtres.\n\n"
                "**4. Liens et sécurité**\n"
                "Les liens, invitations, arnaques, fichiers suspects et tentatives de phishing sont interdits.\n\n"
                "**5. Vie privée**\n"
                "Ne publiez aucune information personnelle sans autorisation.\n\n"
                "**6. Organisation**\n"
                "Utilisez le bon salon et suivez les consignes données par l'équipe.\n\n"
                "**7. Identité**\n"
                "L'usurpation d'identité, les faux comptes et la tromperie sont interdits.\n\n"
                "**8. Sanctions et recours**\n"
                "Les sanctions dépendent de la gravité. Ouvrez un ticket pour faire appel calmement.\n\n"
                "**9. Conditions Discord**\n"
                "Les règles et conditions d'utilisation de Discord restent applicables."
            ),
            color=discord.Color.blurple(),
        )
        rules.set_footer(text="SentriX • Règlement automatique v2")

        announcement = discord.Embed(
            title="Ouverture du serveur",
            description=(
                f"Bienvenue sur **{guild.name}**. La structure du serveur est maintenant prête.\n\n"
                f"Commencez par lire {rules_ref}, utilisez {roles_ref} puis présentez-vous. "
                f"Pour contacter l'équipe, ouvrez une demande dans {ticket_ref}.\n\n"
                "Nous vous souhaitons une excellente expérience parmi nous."
            ),
            color=discord.Color.green(),
        )
        announcement.set_footer(text="SentriX • Annonce automatique v2")

        welcome = discord.Embed(
            title="Bienvenue",
            description=(
                "Lisez le règlement, choisissez vos rôles et utilisez les salons correspondant "
                "à votre demande. L'équipe reste disponible par ticket."
            ),
            color=discord.Color.blurple(),
        )
        welcome.set_footer(text="SentriX • Bienvenue automatique v2")

        information = discord.Embed(
            title="Guide du serveur",
            description=(
                f"**Règlement :** {rules_ref}\n"
                f"**Rôles :** {roles_ref}\n"
                f"**Assistance privée :** {ticket_ref}\n\n"
                "Chaque salon possède un sujet, des permissions et un délai adaptés. "
                "Utilisez les salons de la bonne catégorie afin de garder le serveur organisé."
            ),
            color=discord.Color.blurple(),
        )
        information.set_footer(text="SentriX • Guide automatique v2")

        faq = discord.Embed(
            title="Questions fréquentes",
            description=(
                f"**Comment contacter le staff ?**\nUtilisez {ticket_ref}.\n\n"
                f"**Où lire les règles ?**\nDans {rules_ref}.\n\n"
                "**Pourquoi mon message a été supprimé ?**\n"
                "Les liens, le spam, les insultes et le contenu explicite sont filtrés automatiquement.\n\n"
                "**Comment contester une sanction ?**\n"
                "Ouvrez un ticket et expliquez calmement la situation avec les preuves utiles."
            ),
            color=discord.Color.blurple(),
        )
        faq.set_footer(text="SentriX • FAQ automatique v2")

        status = discord.Embed(
            title="État des services",
            description=(
                "**SentriX :** opérationnel\n"
                "**Tickets :** opérationnels\n"
                "**Modération automatique :** opérationnelle\n\n"
                "Les incidents et maintenances seront annoncés dans ce salon."
            ),
            color=discord.Color.green(),
        )
        status.set_footer(text="SentriX • Statut automatique v2")

        published = 0
        if isinstance(rules_channel, discord.TextChannel):
            published += await self._publish_once(
                rules_channel,
                "SentriX • Règlement automatique v2",
                rules,
            )
        if isinstance(announcements_channel, discord.TextChannel):
            published += await self._publish_once(
                announcements_channel,
                "SentriX • Annonce automatique v2",
                announcement,
            )
        if isinstance(welcome_channel, discord.TextChannel):
            published += await self._publish_once(
                welcome_channel,
                "SentriX • Bienvenue automatique v2",
                welcome,
            )
        if isinstance(information_channel, discord.TextChannel):
            published += await self._publish_once(
                information_channel,
                "SentriX • Guide automatique v2",
                information,
            )
        if isinstance(faq_channel, discord.TextChannel):
            published += await self._publish_once(
                faq_channel,
                "SentriX • FAQ automatique v2",
                faq,
            )
        if isinstance(status_channel, discord.TextChannel):
            published += await self._publish_once(
                status_channel,
                "SentriX • Statut automatique v2",
                status,
            )
        return published

    async def _configure_tickets(
        self,
        guild: discord.Guild,
        role_map: dict[str, discord.Role],
        category_map: dict[str, discord.CategoryChannel],
        channel_map: dict[str, discord.abc.GuildChannel],
        staff_role_name: str,
    ) -> str:
        ticket_cog = self.bot.get_cog("Tickets")
        if ticket_cog is None:
            return "module de tickets indisponible"

        panel_channel = channel_map.get("ouvrir-un-ticket")
        ticket_category = category_map.get("TICKETS OUVERTS")
        log_channel = channel_map.get("logs-tickets")
        staff_role = role_map.get(staff_role_name) or role_map.get("Modérateur")
        if (
            not isinstance(panel_channel, discord.TextChannel)
            or ticket_category is None
            or staff_role is None
        ):
            return "salon, catégorie ou rôle requis introuvable"

        panel_name = "Support serveur"
        panel = await ticket_cog.get_panel_by_name(guild.id, panel_name)
        if panel is None:
            panel_id = await ticket_cog.create_panel(guild.id, panel_name)
            previous_channel_id = None
            previous_message_id = None
        else:
            panel_id = panel["id"]
            previous_channel_id = panel["channel_id"]
            previous_message_id = panel["message_id"]

        await self.bot.db.execute(
            "UPDATE ticket_panels_v2 SET title = ?, description = ?, color = ?, "
            "footer_text = ?, style = ?, enabled = 1, channel_id = ? WHERE id = ?",
            (
                "Centre de support",
                "Choisissez le motif correspondant à votre demande. Un salon privé sera créé automatiquement.",
                discord.Color.blurple().value,
                "SentriX • Support",
                "button",
                panel_channel.id,
                panel_id,
            ),
        )

        existing_types = {
            ticket_type["name"]: ticket_type
            for ticket_type in await ticket_cog.get_panel_types(panel_id)
        }
        log_channel_id = log_channel.id if isinstance(log_channel, discord.TextChannel) else None
        for position, type_data in enumerate(TICKET_TYPES):
            ticket_type = existing_types.get(type_data["name"])
            if ticket_type is None:
                type_id = await ticket_cog.add_type(guild.id, panel_id, type_data["name"])
            else:
                type_id = ticket_type["id"]
            await self.bot.db.execute(
                "UPDATE ticket_types SET description = ?, emoji = NULL, button_label = ?, "
                "button_style = ?, staff_role_id = ?, category_id = ?, name_format = ?, "
                "open_message = ?, max_per_member = 1, autoclose_hours = 72, "
                "log_channel_id = ?, mention_staff = 1, use_form = 0, position = ? WHERE id = ?",
                (
                    type_data["description"],
                    type_data["name"],
                    type_data["button_style"],
                    staff_role.id,
                    ticket_category.id,
                    type_data["name_format"],
                    type_data["open_message"],
                    log_channel_id,
                    position,
                    type_id,
                ),
            )

        from cogs.tickets import TicketPanelView

        panel = await ticket_cog.get_panel(panel_id)
        ticket_types = await ticket_cog.get_panel_types(panel_id)
        view = TicketPanelView(panel, ticket_types)
        old_message = None
        old_channel = guild.get_channel(previous_channel_id) if previous_channel_id else None
        if previous_message_id and isinstance(old_channel, discord.TextChannel):
            try:
                old_message = await old_channel.fetch_message(previous_message_id)
            except discord.HTTPException:
                old_message = None

        if old_message and old_channel.id == panel_channel.id:
            await old_message.edit(embed=ticket_cog.build_panel_embed(panel), view=view)
            message = old_message
        else:
            if old_message:
                try:
                    await old_message.delete()
                except discord.HTTPException:
                    pass
            message = await panel_channel.send(
                embed=ticket_cog.build_panel_embed(panel),
                view=view,
            )
        await self.bot.db.execute(
            "UPDATE ticket_panels_v2 SET message_id = ?, channel_id = ? WHERE id = ?",
            (message.id, panel_channel.id, panel_id),
        )
        return f"configurés avec {len(ticket_types)} motifs"

    async def build_server(
        self,
        guild: discord.Guild,
        template_key: str,
        author: discord.Member,
    ) -> discord.Embed:
        data = SERVER_TEMPLATES[template_key]
        self._build_step = "vérification des limites Discord"
        capacity_error = self._capacity_error(guild, data)
        if capacity_error:
            return embeds.error(capacity_error)

        reason = f"Configuration complète {data['label']} demandée par {author}"
        self._build_step = "création et mise à jour des rôles"
        role_map, roles_created, roles_updated = await self._ensure_roles(
            guild,
            data,
            reason,
        )
        staff_role = role_map[data["staff_role_name"]]
        member_role = role_map[data["member_role_name"]]
        self._build_step = "création et configuration des catégories et salons"
        (
            category_map,
            channel_map,
            categories_created,
            categories_updated,
            channels_created,
            channels_updated,
        ) = await self._ensure_structure(
            guild,
            data,
            role_map,
            reason,
        )

        self._build_step = "liaison des salons avec les fonctions SentriX"
        settings_configured = await self._configure_bot_channels(
            guild,
            role_map,
            category_map,
            channel_map,
            data["staff_role_name"],
        )

        self._build_step = "publication du règlement et des guides"
        messages_published = await self._publish_welcome_content(guild, channel_map)
        self._build_step = "configuration du panneau de tickets"
        try:
            ticket_status = await self._configure_tickets(
                guild,
                role_map,
                category_map,
                channel_map,
                data["staff_role_name"],
            )
        except Exception:
            logger.exception("Échec de la configuration automatique des tickets")
            ticket_status = "erreur pendant la configuration ; utilisez +ticketsetup"

        self._build_step = "finalisation"
        total_channels = sum(len(category["channels"]) for category in data["categories"])
        result = embeds.success(
            f"Le serveur **{guild.name}** est configuré avec le modèle **{data['label']}**.\n\n"
            f"**Rôles :** {len(data['roles'])} prévus, {roles_created} créés, {roles_updated} mis à jour.\n"
            f"**Structure :** {len(data['categories'])} catégories et {total_channels} salons prévus ; "
            f"{categories_created} catégorie(s) créée(s), {categories_updated} renommée(s)/configurée(s), "
            f"{channels_created} salon(s) créé(s) et {channels_updated} configuré(s).\n"
            f"**Réglages SentriX :** {settings_configured} rôles/salons reliés automatiquement.\n"
            f"**Messages :** règlement, annonce, accueil, guide, FAQ et statut installés "
            f"({messages_published} nouveau(x)).\n"
            f"**Tickets :** {ticket_status}.\n"
            f"**Configuration SentriX :** rôle staff {staff_role.mention}, autorôle {member_role.mention}.\n\n"
            "La commande peut être relancée : elle met à jour l'installation sans créer de doublons.",
            title="Configuration terminée",
        )
        result.add_field(
            name="Sécurité des permissions",
            value=(
                "Seul Fondateur possède Administrateur. Les rôles de direction, modération "
                "et support utilisent des permissions adaptées à leurs fonctions."
            ),
            inline=False,
        )
        return result

    @commands.hybrid_command(
        name="create-server",
        description="Configurer le serveur actuel avec rôles, salons, règlement, annonce et tickets.",
    )
    @checks.is_owner_or_admin_for("configuration")
    async def create_server(self, ctx: commands.Context):
        if ctx.guild is None:
            return await ctx.send(embed=embeds.error("Cette commande doit être lancée dans un serveur."))
        if ctx.interaction:
            await ctx.defer()
        me = ctx.guild.me
        if not me.guild_permissions.administrator:
            return await ctx.send(
                embed=embeds.error(
                    "Pour installer plus de 50 rôles avec leurs permissions, les salons privés "
                    "et les tickets, SentriX doit avoir la permission **Administrateur**. Placez "
                    "aussi son rôle au-dessus des rôles qu'il doit gérer, puis relancez +create-server."
                )
            )
        view = ServerBuilderView(self.bot, ctx.author.id)
        await ctx.send(embed=view.build_preview_embed(), view=view)

    @commands.hybrid_command(
        name="delete-channel",
        description="Supprimer un salon précis du serveur.",
    )
    @app_commands.describe(salon="Le salon à supprimer", raison="La raison (optionnel)")
    @checks.is_owner_or_admin_for("configuration")
    async def delete_channel(
        self,
        ctx: commands.Context,
        salon: discord.TextChannel,
        *,
        raison: str = "Aucune raison fournie",
    ):
        if salon.id == ctx.channel.id:
            return await ctx.send(
                embed=embeds.error(
                    "Vous ne pouvez pas supprimer le salon depuis lequel vous lancez cette commande."
                )
            )
        name = salon.name
        try:
            await salon.delete(reason=f"{ctx.author} : {raison}")
        except discord.Forbidden:
            return await ctx.send(embed=embeds.error("Je n'ai pas la permission de supprimer ce salon."))
        await ctx.send(
            embed=embeds.success(f"Le salon **{name}** a été supprimé.\nRaison : {raison}")
        )

    @commands.hybrid_command(
        name="wipe-server",
        description="[DANGER] Supprimer tous les salons du serveur après confirmation.",
        with_app_command=False,
    )
    @checks.is_owner_or_admin_for("complete")
    async def wipe_server(self, ctx: commands.Context):
        guild = ctx.guild
        total = len(guild.channels)
        if total == 0:
            return await ctx.send(embed=embeds.info("Il n'y a aucun salon à supprimer."))
        warning = embeds.error(
            f"Vous êtes sur le point de supprimer **{total}** salon(s) ou catégorie(s) sur "
            f"**{guild.name}**. Cette action est irréversible.\n\n"
            "Les rôles et les membres ne sont pas touchés. Cliquez ci-dessous puis tapez "
            "le nom exact du serveur pour confirmer.",
            title="Suppression totale des salons",
        )
        view = WipeConfirmView(ctx.author.id, guild, ctx.channel.id)
        await ctx.send(embed=warning, view=view)


class WipeConfirmModal(discord.ui.Modal, title="Confirmation de suppression totale"):
    def __init__(self, guild: discord.Guild, invoker_channel_id: int):
        super().__init__()
        self.guild = guild
        self.invoker_channel_id = invoker_channel_id
        self.confirm_input = discord.ui.TextInput(
            label="Nom exact du serveur",
            placeholder=guild.name,
            required=True,
            max_length=100,
        )
        self.add_item(self.confirm_input)

    async def on_submit(self, interaction: discord.Interaction):
        if self.confirm_input.value.strip() != self.guild.name:
            return await interaction.response.send_message(
                "Nom incorrect : suppression annulée, aucun salon n'a été touché.",
                ephemeral=True,
            )
        await interaction.response.defer()
        deleted = 0
        failed = 0
        for channel in list(self.guild.channels):
            if channel.id == self.invoker_channel_id:
                continue
            try:
                await channel.delete(reason=f"Suppression totale demandée par {interaction.user}")
                deleted += 1
                await asyncio.sleep(0.4)
            except discord.HTTPException:
                failed += 1
        description = f"**{deleted}** salon(s) ou catégorie(s) supprimé(s)."
        if failed:
            description += f" {failed} opération(s) ont échoué."
        description += "\n\nLe salon actuel a été conservé pour afficher ce résultat."
        await interaction.followup.send(
            embed=embeds.success(description, title="Suppression terminée")
        )


class WipeConfirmView(discord.ui.View):
    def __init__(
        self,
        author_id: int,
        guild: discord.Guild,
        invoker_channel_id: int,
    ):
        super().__init__(timeout=60)
        self.author_id = author_id
        self.guild = guild
        self.invoker_channel_id = invoker_channel_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "Seule la personne ayant lancé la commande peut confirmer.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(
        label="Confirmer la suppression totale",
        style=discord.ButtonStyle.danger,
    )
    async def confirm(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        await interaction.response.send_modal(
            WipeConfirmModal(self.guild, self.invoker_channel_id)
        )
        self.stop()


async def setup(bot: commands.Bot):
    await bot.add_cog(ServerBuilder(bot))
