"""SentriX V110 — surface de commandes courte, canonique et sans doublons visibles.

Le runtime historique conserve ses callbacks et ses anciens noms pour compatibilité,
mais l'interface publique utilise un seul nom court par action :
- les commandes préfixées reçoivent un alias canonique court, utilisé par +help ;
- les slash reprennent le même vocabulaire court ;
- les commandes déjà fusionnées dans setup/ticket/giveaway/security ne sont plus
  republiées comme des slash séparés ;
- les collisions restantes reçoivent un suffixe numérique lisible plutôt qu'un hash.

Cette couche ne duplique aucune logique métier : elle ne fait que normaliser le routage
public au-dessus des commandes existantes.
"""
from __future__ import annotations

import logging
import re

import sentrix_v95_runtime as v95

logger = logging.getLogger("bot.command-surface-v110")

# Les racines les plus utilisées suivent le vocabulaire courant des bots Discord.
COMPACT_ROOT_NAMES: dict[str, str] = {
    "moderation": "mod",
    "notifications": "notify",
}

# Noms publics explicitement simplifiés. Les commandes déjà courtes et universelles
# (ban, kick, warn, mute, help, ping, play, shop...) restent inchangées.
COMPACT_COMMAND_NAMES: dict[str, str] = {
    "userinfo": "user",
    "membercount": "members",
    "setprefix": "prefix",
    "setmodrole": "modrole",
    "clearwarnings": "clearwarns",
    "nickname": "nick",
    "resetnick": "unnick",
    "giverole": "roleadd",
    "removerole": "roledel",
    "blacklist-add": "linkadd",
    "blacklist-users": "blusers",
    "syncbl": "blsync",
    "ai-translate": "aitranslate",
    "chat-reset": "aireset",
    "economyleaderboard": "moneytop",
    "leaderboard-money": "moneytop",
    "leaderboard-levels": "leveltop",
    "set-xp": "setxp",
    "add-xp": "addxp",
    "set-level-role": "levelrole",
    "remove-level-role": "unlevelrole",
    "reset-levels": "resetlevels",
    "giveaway-reroll": "reroll",
    "verification": "verify",
    "permission-audit": "perms",
    "server-backup": "backup",
    "server-restore": "restore",
    "role-snapshot": "rolesave",
    "role-restore": "roleload",
    "lockdown-server": "lockdown",
    "unlock-server": "unlockdown",
    "proofexample-remove": "proofremove",
    "invite-leaderboard": "invitetop",
    "invitebonushistory": "invitehistory",
    "addbonusinvites": "addinvites",
    "removebonusinvites": "delinvites",
    "notifs-ping": "pingrole",
    "notifs-list": "list",
    "notifs-remove": "remove",
    "welcome-config": "welcome",
    "automod-exempt-role-add": "exemptadd",
    "automod-exempt-role-remove": "exemptremove",
    "automod-history": "history",
    "automod-status": "status",
    "security-check": "check",
    "security-level": "level",
    "security-repair": "repair",
    "whitelist-domain": "domainadd",
    "unwhitelist-domain": "domaindel",
    "ticket-reopen": "reopen",
    "tickettranscript": "transcript",
    "nowplaying": "now",
    "remove-from-queue": "remove",
    "clear-queue": "clear",
    "playlist-save": "save",
    "playlist-load": "load",
    "guess-number": "guess",
    "math-quiz": "math",
    "create-server": "setupserver",
    "delete-channel": "delchannel",
    "disablecommand": "disablecmd",
    "enablecommand": "enablecmd",
    "ignorechannel": "ignore",
    "unignorechannel": "unignore",
    "setwarnrole": "warnrole",
    "setwarnbanthreshold": "warnlimit",
    "designsetup": "design",
    "embedconfig": "embedsettings",
    "rolepanel": "roles",
    "rolepanel-refresh": "refresh",
    "reactionrole-add": "rradd",
    "reactionrole-remove": "rrdel",
    "reactionrole-list": "rrlist",
    "aisetup": "aiconfig",
    "diagnostic": "diagnose",
    "reset-economy": "reseteconomy",
    "status-rotate": "statusrotate",
    "bot-servers": "servers",
    "bot-leave": "leave",
    "wipe-server": "wipe",
}

_TOKEN_SHORTENING = {
    "leaderboard": "top",
    "leaderboards": "top",
    "configuration": "config",
    "notifications": "notifs",
    "notification": "notif",
    "verification": "verify",
    "permissions": "perms",
    "permission": "perms",
    "statistics": "stats",
    "automatic": "auto",
    "application": "app",
}

_MAX_PUBLIC_LEAF = 20
_ORIGINAL_GROUP_FOR = v95._group_for
_ORIGINAL_SHOULD_EXPOSE = v95._should_expose
_ORIGINAL_UNIQUE_LEAF = v95._unique_leaf
_INSTALLED = False


def _normalise_public_leaf(value: object) -> str:
    text = str(value or "").casefold().strip().replace("_", "-").replace(" ", "-")
    text = re.sub(r"[^a-z0-9-]+", "-", text)
    parts = [part for part in re.split(r"-+", text) if part]
    parts = [_TOKEN_SHORTENING.get(part, part) for part in parts]

    # Retire les répétitions créées par d'anciens noms du type ticket-ticket-... .
    compact: list[str] = []
    for part in parts:
        if not compact or compact[-1] != part:
            compact.append(part)
    candidate = "-".join(compact) or "command"
    if len(candidate) <= _MAX_PUBLIC_LEAF:
        return candidate

    # Deuxième passe : les mots purement structurels n'apportent rien dans un groupe slash.
    reduced = [part for part in compact if part not in {"command", "commands", "system"}]
    candidate = "-".join(reduced) or candidate
    if len(candidate) <= _MAX_PUBLIC_LEAF:
        return candidate

    # Dernier filet : longueur stable et lisible. Les collisions sont résolues avec -2/-3.
    return candidate[:_MAX_PUBLIC_LEAF].rstrip("-") or "command"


def _explicit_name(command) -> str | None:
    qualified = str(getattr(command, "qualified_name", "") or "").casefold().strip()
    name = str(getattr(command, "name", "") or "").casefold().strip()
    return COMPACT_COMMAND_NAMES.get(qualified) or COMPACT_COMMAND_NAMES.get(name)


def _preferred_name_from_existing_layer(command) -> str | None:
    """Réutilise les alias déjà choisis par SentriX sans rendre le bootstrap dépendant des Cogs."""
    try:
        from cogs import common_command_names

        preferred = str(common_command_names.preferred_name(command) or "").strip()
    except Exception:
        return None
    if not preferred:
        return None
    # Pour un sous-groupe, seule la dernière partie est le leaf slash.
    return preferred.split()[-1]


def _compact_group_for(command) -> tuple[str, str]:
    root_name, original_leaf = _ORIGINAL_GROUP_FOR(command)
    root_name = COMPACT_ROOT_NAMES.get(root_name, root_name)

    explicit = _explicit_name(command)
    preferred = _preferred_name_from_existing_layer(command)
    command_name = str(getattr(command, "name", "") or "").casefold().strip()

    if explicit:
        leaf = explicit
    elif preferred and preferred != command_name:
        leaf = preferred
    else:
        leaf = original_leaf

    return v95._safe_name(root_name), _normalise_public_leaf(leaf)


def _compact_should_expose(command) -> bool:
    if not _ORIGINAL_SHOULD_EXPOSE(command):
        return False

    # Les anciens écrans/configurations fusionnés restent utilisables avec leur ancien +
    # nom pour compatibilité, mais ne doivent plus créer un deuxième slash public.
    try:
        from cogs import command_catalog_cleanup as catalog

        qualified = str(getattr(command, "qualified_name", "") or "").casefold().strip()
        name = str(getattr(command, "name", "") or "").casefold().strip()
        merged = set(catalog.MERGED_COMMANDS) | set(catalog.PURE_DUPLICATE_COMMANDS)
        if qualified in merged or name in merged:
            return False
    except Exception:
        pass
    return True


def _compact_unique_leaf(base: str, used: set[str], original: str) -> str:
    del original  # le suffixe n'est volontairement plus un hash technique.
    candidate = _normalise_public_leaf(base)
    if candidate not in used:
        used.add(candidate)
        return candidate

    serial = 2
    while True:
        suffix = f"-{serial}"
        short = candidate[: _MAX_PUBLIC_LEAF - len(suffix)].rstrip("-") + suffix
        if short not in used:
            used.add(short)
            return short
        serial += 1


def _compact_prefix_name(command) -> str:
    explicit = _explicit_name(command)
    if explicit:
        return _normalise_public_leaf(explicit).replace("-", "") if "-" in explicit else explicit

    preferred = _preferred_name_from_existing_layer(command)
    if preferred:
        return preferred

    original = str(getattr(command, "name", "") or "").casefold().strip()
    if len(original) > _MAX_PUBLIC_LEAF:
        return _normalise_public_leaf(original).replace("-", "")
    return original


def _apply_prefix_surface(bot) -> tuple[int, int]:
    """Ajoute un seul nom canonique court à chaque commande racine sans casser les anciens +."""
    renamed = 0
    collisions = 0
    seen_objects: set[int] = set()

    for command in list(bot.walk_commands()):
        if getattr(command, "parent", None) is not None or id(command) in seen_objects:
            continue
        seen_objects.add(id(command))

        original = str(getattr(command, "name", "") or "").casefold().strip()
        compact = _compact_prefix_name(command).casefold().strip()
        if not compact or compact == original:
            continue

        existing = bot.all_commands.get(compact)
        if existing is not None and existing is not command:
            collisions += 1
            continue

        aliases = getattr(command, "aliases", None)
        if isinstance(aliases, list):
            # Déduplique les alias existants tout en conservant leur ordre.
            aliases[:] = list(dict.fromkeys(str(alias).casefold() for alias in aliases if alias))
            if compact not in aliases:
                aliases.append(compact)
        bot.all_commands[compact] = command

        extras = getattr(command, "extras", None)
        if isinstance(extras, dict):
            extras["sentrix_preferred_name"] = compact
        renamed += 1

    return renamed, collisions


def _wrap_prepare_bot() -> None:
    current = v95.prepare_bot
    if getattr(current, "_sentrix_compact_surface_v110", False):
        return

    async def prepare_bot_compact(bot):
        renamed, collisions = _apply_prefix_surface(bot)
        result = await current(bot)
        logger.info(
            "V110 surface compacte active : %s noms + canoniques, %s collision(s) ignorée(s), %s slash publiés.",
            renamed,
            collisions,
            len(result),
        )
        return result

    prepare_bot_compact._sentrix_compact_surface_v110 = True
    prepare_bot_compact._sentrix_original = current
    v95.prepare_bot = prepare_bot_compact


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    v95._group_for = _compact_group_for
    v95._should_expose = _compact_should_expose
    v95._unique_leaf = _compact_unique_leaf

    # Descriptions des racines renommées.
    if "moderation" in v95.GROUP_DESCRIPTIONS:
        v95.GROUP_DESCRIPTIONS["mod"] = v95.GROUP_DESCRIPTIONS["moderation"]
    if "notifications" in v95.GROUP_DESCRIPTIONS:
        v95.GROUP_DESCRIPTIONS["notify"] = v95.GROUP_DESCRIPTIONS["notifications"]

    _wrap_prepare_bot()
    _INSTALLED = True
    logger.info("V110 noms courts installé : + et / partagent une surface canonique compacte.")


__all__ = [
    "COMPACT_COMMAND_NAMES",
    "COMPACT_ROOT_NAMES",
    "install",
]
