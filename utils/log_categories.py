"""Registre canonique des journaux SentriX.

Un événement possède un ``log_type`` explicite. Ce registre est l'unique endroit qui
transforme ce type en catégorie configurable, emoji et type de bannière.
"""
from __future__ import annotations

CATEGORIES: dict[str, str] = {
    "moderation": "Modération",
    "messages": "Messages",
    "members": "Membres",
    "channels": "Salons",
    "roles": "Rôles",
    "voice": "Vocal",
    "soundboard": "Soundboard",
    "server": "Serveur",
    "tickets": "Tickets",
    "automod": "AutoMod",
    "spam": "Anti-Spam",
    "raid": "Anti-Raid",
    "resources": "Ressources",
    "files": "Fichiers",
}
CATEGORY_ORDER = tuple(CATEGORIES)
CATEGORY_META = {key: {"label": label, "emits": True} for key, label in CATEGORIES.items()}
DEFAULT_CATEGORY = "server"

LOG_REGISTRY: dict[str, tuple[str, str, str]] = {
    "member_kick": ("moderation", "👢", "error"),
    "member_ban": ("moderation", "🔨", "error"),
    "member_unban": ("moderation", "🔓", "success"),
    "member_timeout": ("moderation", "⏱️", "warning"),
    "member_untimeout": ("moderation", "✅", "success"),
    "member_warn": ("moderation", "⚠️", "warning"),
    # Actions de modération qui changeaient le serveur SANS laisser de trace :
    # mesuré sur le bot booté (tools/log_trace_sweep.py). Leur seule preuve
    # était le message dans le salon, que son auteur peut supprimer.
    "channel_lock": ("moderation", "🔒", "warning"),
    "channel_unlock": ("moderation", "🔓", "success"),
    # Rangé en « moderation » et non en « channels » : c'est un geste de
    # modération humaine, qui doit arriver là où arrivent lock et unlock.
    # Mesuré : avec « channel_update », la fiche partait vers le journal des
    # salons et n'apparaissait pas avec les autres actions de modération.
    "channel_slowmode": ("moderation", "🐢", "warning"),
    "member_nickname": ("moderation", "✏️", "info"),
    "warnings_cleared": ("moderation", "🧹", "warning"),
    # Domaines qui n'avaient aucun événement : les catégories valides sont
    # limitées (CATEGORIES), d'où le rattachement à « server » / « members ».
    "config_update": ("server", "⚙️", "info"),
    "economy_grant": ("server", "💰", "warning"),
    "levels_xp_set": ("members", "✨", "warning"),
    "security_panic": ("raid", "🚨", "error"),
    "giveaway_blacklist": ("moderation", "🚫", "warning"),
    "member_clear": ("moderation", "🧹", "warning"),
    "message_delete": ("messages", "🗑️", "error"),
    "message_edit": ("messages", "✏️", "warning"),
    "message_bulk": ("messages", "🧹", "error"),
    "member_join": ("members", "📥", "success"),
    "member_leave": ("members", "📤", "error"),
    "member_remove": ("members", "📤", "error"),
    "member_update": ("members", "👤", "info"),
    # Un rôle donné ou retiré est un événement de MEMBRE : c'est le membre qui
    # change, pas le rôle. Ces trois-là partaient dans les logs Rôles, où l'on
    # cherche l'historique du rôle lui-même (création, permissions, suppression)
    # — et le noyaient sous les mouvements de chaque membre du serveur.
    "member_roles": ("members", "🎭", "info"),
    "role_add": ("members", "➕", "info"),
    "role_remove": ("members", "➖", "info"),
    "channel_create": ("channels", "📗", "success"),
    "channel_delete": ("channels", "📕", "error"),
    "channel_update": ("channels", "📘", "info"),
    "pins_update": ("channels", "📌", "info"),
    "role_create": ("roles", "➕", "success"),
    "role_delete": ("roles", "➖", "error"),
    "role_update": ("roles", "🛡️", "warning"),
    "voice_join": ("voice", "🔊", "success"),
    "voice_leave": ("voice", "🔇", "error"),
    "voice_move": ("voice", "↔️", "info"),
    "voice_state": ("voice", "🎙️", "info"),
    "voice_update": ("voice", "🎙️", "info"),
    "soundboard_create": ("soundboard", "🔊", "success"),
    "soundboard_update": ("soundboard", "🎚️", "warning"),
    "soundboard_delete": ("soundboard", "🔇", "error"),
    "soundboard_play": ("soundboard", "▶️", "info"),
    "guild_update": ("server", "⚙️", "info"),
    # Tickets — un événement par action réelle. Avant, TOUT passait par deux
    # types seulement : ``ticket_close`` si le titre contenait « ferm », sinon
    # ``ticket_open`` (voir cogs/ticket_claim_security.secure_log_action). Une
    # prise en charge, un renommage et un transfert arrivaient donc dans le
    # journal étiquetés « ouverture ».
    #
    # PIÈGE : un ``ticket_*`` absent de ce registre n'est PAS routé vers
    # Tickets. resolve() retombe sur DEFAULT_CATEGORY, c'est-à-dire "server" :
    # l'événement part silencieusement dans le journal Serveur, avec la
    # bannière Serveur. tests/test_ticket_events_registry.py refuse tout
    # ``ticket_*`` émis par le code et non inscrit ici.
    # Le 3ᵉ emplacement est le STYLE de bannière, pas un état : log_banners.
    # banner_kind() lit resolve()[2] et get_banner() en fait directement un nom
    # de fichier dans assets/log_banners/. "tickets" y est un style déclaré
    # (turquoise) et banner_tickets.webp existe. Les quatorze événements portent
    # donc la bannière Tickets — la bannière dit quel système a parlé, l'emoji du
    # titre dit ce qui s'est passé. C'est le motif posé par le lot anti-scam, où
    # automod_scam et automod_invite portent "security" et non un état.
    "ticket_open": ("tickets", "📬", "tickets"),
    "ticket_close": ("tickets", "🔒", "tickets"),
    "ticket_claim": ("tickets", "🙋", "tickets"),
    "ticket_unclaim": ("tickets", "↩️", "tickets"),
    "ticket_member_add": ("tickets", "➕", "tickets"),
    "ticket_member_remove": ("tickets", "➖", "tickets"),
    "ticket_rename": ("tickets", "✏️", "tickets"),
    "ticket_transfer": ("tickets", "🔀", "tickets"),
    "ticket_reopen": ("tickets", "🔓", "tickets"),
    "ticket_delete": ("tickets", "🗑️", "tickets"),
    "ticket_rating": ("tickets", "⭐", "tickets"),
    "ticket_autoclose": ("tickets", "⏱️", "tickets"),
    "ticket_note": ("tickets", "📝", "tickets"),
    "ticket_bump": ("tickets", "🔔", "tickets"),
    "automod_link": ("automod", "🔗", "error"),
    "automod_invite": ("automod", "🔗", "security"),
    "automod_scam": ("automod", "🛡️", "security"),
    "automod_word": ("automod", "🛑", "error"),
    "automod_mention": ("automod", "📣", "error"),
    "automod_spam": ("spam", "🚫", "error"),
    "spam_detected": ("spam", "🚫", "error"),
    "spam_purge": ("spam", "🧹", "warning"),
    "antiraid": ("raid", "🛡️", "error"),
    "raid_detected": ("raid", "🛡️", "error"),
    "raid_lockdown": ("raid", "🔒", "error"),
    "emoji_update": ("resources", "😀", "info"),
    "invite_create": ("resources", "🔗", "success"),
    "invite_delete": ("resources", "🔗", "error"),
    "sticker_update": ("resources", "🧩", "info"),
    "webhook_update": ("resources", "🔗", "warning"),
    "resource_add": ("resources", "📎", "success"),
    "resource_remove": ("resources", "📎", "error"),
    "file_delete": ("files", "📎", "error"),
    "file_upload": ("files", "📁", "info"),
    "file_blocked": ("files", "⛔", "error"),
}

LEGACY_EVENT_ALIASES: dict[str, str] = {
    "kick": "member_kick",
    "ban": "member_ban",
    "unban": "member_unban",
    "timeout": "member_timeout",
    "untimeout": "member_untimeout",
    "warn": "member_warn",
    "clear": "member_clear",
    "bulk_delete": "message_bulk",
    "member_add": "member_join",
    "member_departure": "member_leave",
}

# Evenements qui ont CHANGE de categorie. Un serveur configure avant ce
# changement n'a pas forcement de salon pour la nouvelle categorie : sans ce
# repli, ses journaux disparaitraient en silence, car un salon absent fait
# abandonner l'envoi. Le repli s'efface de lui-meme des que la nouvelle
# categorie est configuree.
CATEGORIE_PRECEDENTE: dict[str, str] = {
    "role_add": "roles",
    "role_remove": "roles",
    "member_roles": "roles",
}

LEGACY_CATEGORY_KEYS: dict[str, str] = {
    **{key: key for key in CATEGORIES},
    "protection": "automod",
    "system": "server",
    "dossiers": "resources",
    "log_moderation": "moderation",
    "log_messages": "messages",
    "log_members": "members",
    "log_channels": "channels",
    "log_roles": "roles",
    "log_voice": "voice",
    "log_soundboard": "soundboard",
    "log_server": "server",
    "log_channel": "server",
    "ticket_log_channel": "tickets",
    "log_tickets": "tickets",
    "log_automod": "automod",
    "log_protection": "automod",
    "log_spam": "spam",
    "log_raid": "raid",
    "log_resources": "resources",
    "log_dossiers": "resources",
    "log_files": "files",
}

# Emoji par type d'événement, indexé sur log_type. Dérivé du registre pour qu'il ne
# puisse jamais diverger de la catégorie et du style de bannière du même événement.
EVENT_EMOJI: dict[str, str] = {
    log_type: emoji for log_type, (_category, emoji, _kind) in LOG_REGISTRY.items()
}
DEFAULT_EVENT_EMOJI = "📋"

# ---------------------------------------------------------------------------
# Icônes SentriX des cartes Trace
#
# Les emojis Unicode ci-dessus restent le REPLI : ils s'affichent tant qu'une
# icône n'est pas téléversée, et pour les 40 et quelques événements que le
# pack ne couvre pas encore. Le remplacement est donc progressif, sans trou.
# ---------------------------------------------------------------------------

#: Événements dont le nom ne correspond pas directement à une icône.
#: « member_ban » doit trouver « sentrix_ban », pas « sentrix_member_ban ».
ICONES_EVENEMENTS: dict[str, str] = {
    "member_kick": "kick",
    "member_ban": "ban",
    "member_unban": "unban",
    "member_timeout": "timeout",
    "member_untimeout": "unmute",
    "member_warn": "warn",
    "channel_lock": "lock",
    "channel_unlock": "unlock",
    "channel_slowmode": "clock",
    "member_nickname": "user",
    "warnings_cleared": "trash",
    "config_update": "settings",
    "economy_grant": "wallet",
    "levels_xp_set": "level",
    "security_panic": "anti_raid",
    "giveaway_blacklist": "giveaway",
    "member_mute": "mute",
    "member_unmute": "unmute",
    "member_remove": "member_leave",
    "message_bulk": "trash",
    "ticket_release": "ticket_release",
    "ticket_delete": "trash",
    "ticket_transcript": "transcript",
    # Donner ou retirer un rôle est classé dans « members » : sans ces deux
    # lignes, la famille rendait l'icône « utilisateur » alors que l'action
    # porte sur un rôle.
    "role_add": "role",
    "role_remove": "role",
    "member_roles": "role",
}

#: Repli par famille, quand l'événement lui-même n'a pas d'icône. Les
#: catégories sont au pluriel, les icônes au singulier : une correspondance
#: automatique échouerait silencieusement sur presque toutes.
ICONES_CATEGORIES: dict[str, str] = {
    "automod": "security",
    "channels": "channel",
    "files": "file",
    "members": "user",
    "messages": "message",
    "moderation": "mod",
    "raid": "anti_raid",
    "resources": "settings",
    "roles": "role",
    "server": "settings",
    "soundboard": "voice",
    "spam": "antispam",
    "tickets": "ticket",
    "voice": "voice",
}


def marqueur_evenement(evenement: str, *, defaut: str = "") -> str:
    """Icône SentriX de cet événement, ou son emoji Unicode de repli.

    Quatre niveaux, du plus précis au plus général :

    1. ``sentrix_<evenement>`` — « message_delete » trouve son icône seul ;
    2. ``ICONES_EVENEMENTS`` — pour « member_ban » → « ban » ;
    3. ``ICONES_CATEGORIES`` — toute la famille partage une icône ;
    4. l'emoji Unicode existant, inchangé.

    Rend toujours quelque chose d'affichable : tant que la synchronisation
    n'a pas eu lieu, c'est le niveau 4, et la carte reste identique à avant.
    """
    from utils.sentrix_emojis import emoji as _icone

    evenement = str(evenement or "")
    for candidat in (evenement, ICONES_EVENEMENTS.get(evenement, "")):
        if candidat and (rendu := _icone(candidat)):
            return rendu
    famille = ICONES_CATEGORIES.get(category_for(evenement), "")
    if famille and (rendu := _icone(famille)):
        return rendu
    return defaut or EVENT_EMOJI.get(evenement, DEFAULT_EVENT_EMOJI)

LOGS = LOG_REGISTRY


def _norm(value: object) -> str:
    return str(value or "").strip().casefold().replace("-", "_").replace(" ", "_")


def _canonical_category(value: str) -> str:
    key = _norm(value)
    # Alias legacy AVANT CATEGORIES : même si un ancien runtime rajoute temporairement
    # ``dossiers`` au dictionnaire, il reste canoniquement ``resources``.
    if key in LEGACY_CATEGORY_KEYS:
        return LEGACY_CATEGORY_KEYS[key]
    if key in CATEGORIES:
        return key
    return DEFAULT_CATEGORY


def canonical_event_type(log_type: str, title: str = "", description: str = "") -> str:
    key = LEGACY_EVENT_ALIASES.get(_norm(log_type), _norm(log_type))
    if key in LOG_REGISTRY or key in CATEGORIES or key in LEGACY_CATEGORY_KEYS:
        return key
    sample = f"{title} {description}".casefold()
    checks = (
        ("message supprim", "message_delete"),
        ("message modifi", "message_edit"),
        ("membre arriv", "member_join"),
        ("membre parti", "member_leave"),
        ("expuls", "member_kick"),
        ("débanni", "member_unban"),
        ("banni", "member_ban"),
        ("salon créé", "channel_create"),
        ("salon supprim", "channel_delete"),
        ("salon modifi", "channel_update"),
        ("rôle créé", "role_create"),
        ("rôle supprim", "role_delete"),
        ("rôle modifi", "role_update"),
        ("invitation créée", "invite_create"),
        ("invitation supprim", "invite_delete"),
    )
    for token, event in checks:
        if token in sample:
            return event
    return key or "guild_update"


def category_for(log_type: str, title: str = "", description: str = "") -> str:
    key = canonical_event_type(log_type, title, description)
    if key in LOG_REGISTRY:
        return _canonical_category(LOG_REGISTRY[key][0])
    return _canonical_category(key)


def resolve(log_type: str, title: str = "", description: str = "") -> tuple[str, str, str]:
    key = canonical_event_type(log_type, title, description)
    if key in LOG_REGISTRY:
        category, emoji, kind = LOG_REGISTRY[key]
        return _canonical_category(category), emoji, kind
    return _canonical_category(key), "📋", "info"


def legacy_to_category(value: str) -> str | None:
    key = _norm(value)
    if not key:
        return None
    if key in LEGACY_CATEGORY_KEYS:
        return LEGACY_CATEGORY_KEYS[key]
    if key in LOG_REGISTRY:
        return _canonical_category(LOG_REGISTRY[key][0])
    if key in CATEGORIES:
        return _canonical_category(key)
    if key.startswith("log_"):
        tail = key[4:]
        if tail in LEGACY_CATEGORY_KEYS:
            return LEGACY_CATEGORY_KEYS[tail]
        if tail in LOG_REGISTRY:
            return _canonical_category(LOG_REGISTRY[tail][0])
    return None


__all__ = [
    "CATEGORIES", "CATEGORY_META", "CATEGORY_ORDER", "DEFAULT_CATEGORY",
    "DEFAULT_EVENT_EMOJI", "EVENT_EMOJI", "ICONES_CATEGORIES",
    "ICONES_EVENEMENTS", "marqueur_evenement", "LEGACY_CATEGORY_KEYS", "LEGACY_EVENT_ALIASES",
    "LOG_REGISTRY", "LOGS",
    "canonical_event_type", "category_for", "legacy_to_category", "resolve",
]
