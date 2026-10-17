"""Source unique des catégories de commandes SentriX.

Mesuré le 2026-10-17 sur la surface réellement publiée (327 commandes
préfixées) : **47 catégories distinctes**, dont une vingtaine sont des noms
de modules internes qui fuyaient jusqu'à l'utilisateur — « SentriXV21 »,
« BotV10 », « V17TicketsLogs », « Autres ». Les jeux étaient éclatés en sept
catégories, la sécurité en cinq.

Deux surfaces affichaient des catégories différentes pour la même commande :
``/help`` passait par la table de ``cogs/help_components_v77`` (29 cogs
couverts sur 47), et la page web ``/commands`` affichait le ``cog_name`` brut.
Résultat mesuré : **66 commandes sur 327 (20 %)** tombaient dans le repli
« Administration » — dont ``+starboard-setup``, ``+snipe``, ``+translate``,
``+poll``, ``+suggest``, ``+market`` et ``+incident``, qui n'ont rien
d'administratif.

Ce module est la seule table. ``cogs/help_components_v77`` et
``web/public_commands_v46`` la consultent tous les deux.

Deux niveaux, parce qu'un cog n'est pas toujours homogène : ``SentriXPlus``
contient à la fois le starboard (communauté) et la santé du serveur
(utilitaires). ``PAR_COMMANDE`` tranche ces cas, ``PAR_COG`` fait le reste.
"""
from __future__ import annotations

from collections import OrderedDict

#: Clé → (emoji, libellé, description). L'ordre est celui de l'affichage.
CATEGORIES = OrderedDict(
    (
        ("moderation", ("🛡️", "Modération", "Ban, kick, mute, warn, clear et gestion des sanctions.")),
        ("security", ("🔒", "Sécurité", "Anti-spam, anti-raid, vérification et protections du serveur.")),
        ("tickets", ("🎫", "Tickets", "Support, panels, tickets et outils liés aux demandes.")),
        ("community", ("👋", "Bienvenue & rôles", "Bienvenue, rôles, autorôles et outils de communauté.")),
        ("logs", ("📜", "Logs", "Journaux du serveur, historique et suivi des actions.")),
        ("economy", ("🪙", "Économie & niveaux", "Argent, banque, boutique, XP, niveaux et progression.")),
        ("ai", ("🧠", "Intelligence artificielle", "Assistant SentriX, recherche, mémoire et génération d'images.")),
        ("notifications", ("🔔", "Notifications", "YouTube, TikTok, Twitch et rôles de notification.")),
        ("games", ("🎮", "Jeux & événements", "Mini-jeux, giveaways, activités et divertissement.")),
        ("music", ("🎵", "Musique", "Lecture et commandes musicales disponibles sur SentriX.")),
        ("utility", ("🛠️", "Utilitaires", "Informations, statistiques, serveur, membre et outils pratiques.")),
        ("administration", ("⚙️", "Administration", "Configuration et outils avancés pour gérer le serveur.")),
    )
)

DEFAUT = "utility"

#: Cog → catégorie. Couvre les 47 cogs réellement publiés le 2026-10-17.
PAR_COG = {
    # — modération et staff
    "Moderation": "moderation",
    "StaffSuite": "moderation",
    "DirectMessage": "moderation",
    "Snipe": "moderation",
    # — sécurité
    "Automod": "security",
    "Security": "security",
    "SecurityTools": "security",
    "SecurityHardening": "security",
    "Verification": "security",
    "VerificationConfigV96": "security",
    "ProofVerification": "security",
    "ForbiddenWordsUI": "security",
    "BotV10": "security",
    # — tickets
    "Tickets": "tickets",
    "V17TicketsLogs": "tickets",
    # — communauté
    "Welcome": "community",
    "Roles": "community",
    "RolePanel": "community",
    "ReactionRoles": "community",
    "NotificationRolePanels": "community",
    "Suggestions": "community",
    "PollUI": "community",
    "SentriXPlus": "community",
    # — logs
    "Logs": "logs",
    "Trace": "logs",
    # — économie et niveaux
    "Economy": "economy",
    "Levels": "economy",
    "GamesEconomy": "economy",
    "SentriXV2": "economy",
    "SentriXV21": "economy",
    # — IA
    "Ai": "ai",
    "AI": "ai",
    # — notifications
    "Notifications": "notifications",
    # — jeux
    "Minigames": "games",
    "Events": "games",
    "GamesArcade": "games",
    "GamesRapides": "games",
    "GamesSolo": "games",
    "GamesCommunity": "games",
    "GamesDuels": "games",
    "GamesPlayerCommands": "games",
    "GiveawayCenter": "games",
    # — musique
    "Music": "music",
    # — utilitaires
    "Utility": "utility",
    "Stats": "utility",
    "Invites": "utility",
    "Translation": "utility",
    "SentriXUltimate": "utility",
    "Autres": "utility",
    # — administration
    "Configuration": "administration",
    "ServerBuilder": "administration",
    "Owner": "administration",
    "EmbedBuilder": "administration",
    "Design": "administration",
    "SystemFeatures": "administration",
    "SentriXSetup": "administration",
    "SentriXOpsV111": "administration",
    "PermissionsExplain": "administration",
}

#: Exceptions par commande, pour les cogs qui mélangent plusieurs sujets.
PAR_COMMANDE = {
    # SentriXPlus est classé « communauté » pour starboard/sticky/schedule…
    "server-health": "utility",
    # …SentriXV2 et V21 « économie », mais ces deux-là n'en sont pas.
    "modcenter": "moderation",
    "systemstatus": "utility",
    "profilecard": "utility",
    # Autres : l'aide est un utilitaire, pas une catégorie fourre-tout.
    "server-managed": "administration",
    # Invites est utilitaire, mais créditer des invitations est une action staff.
    "addbonusinvites": "moderation",
    "removebonusinvites": "moderation",
}


def resoudre(cog_name: str | None, command_name: str | None = None) -> str:
    """Catégorie d'une commande. Jamais d'exception : au pire, le défaut."""
    nom = str(command_name or "").strip().lstrip("/+").split()[0] if command_name else ""
    if nom and nom in PAR_COMMANDE:
        return PAR_COMMANDE[nom]
    cog = str(cog_name or "").strip()
    if cog in PAR_COG:
        return PAR_COG[cog]
    return _deviner(cog)


def _deviner(cog: str) -> str:
    """Repli pour un cog ajouté après coup, pour qu'il ne finisse pas « Administration ».

    Le défaut est « Utilitaires » et non « Administration » : une commande non
    classée est bien plus souvent un outil qu'un réglage de serveur, et la
    ranger dans Administration la rend invisible aux membres.
    """
    f = cog.casefold()
    for mots, cle in (
        (("moder", "staff"), "moderation"),
        (("secur", "automod", "verif", "antinuke", "antiraid"), "security"),
        (("ticket",), "tickets"),
        (("welcome", "role", "community", "suggest", "poll"), "community"),
        (("log", "trace", "audit"), "logs"),
        (("econom", "level", "shop", "market"), "economy"),
        (("notif",), "notifications"),
        (("game", "event", "giveaway", "minigame", "fun"), "games"),
        (("music",), "music"),
        (("owner", "config", "setup", "admin"), "administration"),
    ):
        if any(m in f for m in mots):
            return cle
    if f in {"ai", "ia"} or "artificial" in f:
        return "ai"
    return DEFAUT


def libelle(cle: str) -> str:
    """Libellé affichable d'une catégorie, emoji compris."""
    emoji, nom, _ = CATEGORIES.get(cle, CATEGORIES[DEFAUT])
    return f"{emoji} {nom}"


def nom_simple(cle: str) -> str:
    """Libellé sans emoji, pour les surfaces qui n'en veulent pas."""
    return CATEGORIES.get(cle, CATEGORIES[DEFAUT])[1]


__all__ = [
    "CATEGORIES", "DEFAUT", "PAR_COG", "PAR_COMMANDE",
    "resoudre", "libelle", "nom_simple",
]
