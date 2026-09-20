"""SentriX V110 — surface slash familière, courte et sans doublons visibles.

Principe : ne pas renommer des commandes juste pour les raccourcir. Les noms déjà connus
(`userinfo`, `serverinfo`, `ban`, `warn`, etc.) restent tels quels. Seules les surfaces
slash inutilement profondes ou les noms vraiment non standards sont normalisés vers des
conventions largement utilisées par les grands bots Discord.

Les callbacks historiques restent la source unique de logique métier. Cette couche ne
copie aucune sanction, économie, musique ou permission : elle ne fait que republier les
mêmes callbacks sous une surface slash plus naturelle.
"""
from __future__ import annotations

import logging
import re

import discord
from discord import app_commands

import sentrix_v95_runtime as v95

logger = logging.getLogger("bot.command-surface-v110")

# Compatibilité d'import avec la première version V110. On ne raccourcit PLUS les racines
# arbitrairement (/moderation reste /moderation, /notifications reste /notifications).
COMPACT_ROOT_NAMES: dict[str, str] = {}

# Renommages réellement justifiés par une convention Discord répandue.
# Important : userinfo/serverinfo/clearwarnings restent volontairement inchangés.
COMPACT_COMMAND_NAMES: dict[str, str] = {
    "nickname": "setnick",
    "leaderboard-levels": "leaderboard",
    "set-xp": "setxp",
    "add-xp": "addxp",
}

# Commandes que les grands bots exposent généralement directement à la racine. SentriX
# faisait auparavant des chemins comme /moderation ban ou /info userinfo : V110 les
# republie en /ban, /userinfo, etc. Les anciennes commandes + ne sont pas renommées ici.
STANDARD_DIRECT_SLASH: dict[str, str] = {
    # Modération — conventions communes des grands bots généralistes.
    "ban": "ban",
    "tempban": "tempban",
    "unban": "unban",
    "kick": "kick",
    "mute": "mute",
    "unmute": "unmute",
    "warn": "warn",
    "warnings": "warnings",
    "clearwarnings": "clearwarnings",
    "clear": "clear",
    "lock": "lock",
    "unlock": "unlock",
    "slowmode": "slowmode",
    "nickname": "setnick",
    "case": "case",

    # Informations — userinfo/serverinfo sont déjà des noms très répandus.
    "avatar": "avatar",
    "userinfo": "userinfo",
    "serverinfo": "serverinfo",
    "channelinfo": "channelinfo",
    "membercount": "membercount",

    # Niveaux — /level et /leaderboard sont des conventions répandues.
    "level": "level",
    "leaderboard-levels": "leaderboard",
    "set-xp": "setxp",
    "add-xp": "addxp",

    # Économie — garder les noms évidents, sans préfixe /economy inutile.
    "balance": "balance",
    "daily": "daily",
    "weekly": "weekly",
    "work": "work",
    "rob": "rob",
    "pay": "pay",
    "shop": "shop",
    "inventory": "inventory",
    "gamble": "gamble",
    "deposit": "deposit",
    "withdraw": "withdraw",

    # Musique — vocabulaire commun aux bots musique majeurs.
    # +play reste la commande préfixée historique ; les autres restent aussi accessibles
    # via +music <action> côté préfixe.
    "play": "play",
    "music pause": "pause",
    "music resume": "resume",
    "music skip": "skip",
    "music stop": "stop",
    "music queue": "queue",
    "music nowplaying": "nowplaying",
    "music volume": "volume",
    "music shuffle": "shuffle",
    "music join": "join",
    "music leave": "leave",
    "music seek": "seek",
}

# Les rôles sont plus lisibles sous un petit groupe /role que sous des chemins profonds.
STANDARD_GROUPED_SLASH: dict[str, tuple[str, str]] = {
    "giverole": ("role", "give"),
    "removerole": ("role", "remove"),
}

# /play est fourni par la commande top-level `play`, qui appelle déjà le même moteur que
# `music play`. Publier les deux créerait un faux doublon.
SUPPRESSED_SLASH_DUPLICATES = frozenset({"music play"})

_TOKEN_SHORTENING = {
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
    """Raccourcit seulement les feuilles réellement longues, sans réinventer les noms."""
    text = str(value or "").casefold().strip().replace("_", "-").replace(" ", "-")
    text = re.sub(r"[^a-z0-9-]+", "-", text)
    parts = [part for part in re.split(r"-+", text) if part]
    parts = [_TOKEN_SHORTENING.get(part, part) for part in parts]

    compact: list[str] = []
    for part in parts:
        if not compact or compact[-1] != part:
            compact.append(part)

    candidate = "-".join(compact) or "command"
    if len(candidate) <= _MAX_PUBLIC_LEAF:
        return candidate

    reduced = [part for part in compact if part not in {"command", "commands", "system"}]
    candidate = "-".join(reduced) or candidate
    if len(candidate) <= _MAX_PUBLIC_LEAF:
        return candidate

    return candidate[:_MAX_PUBLIC_LEAF].rstrip("-") or "command"


def _command_key(command) -> tuple[str, str]:
    qualified = str(getattr(command, "qualified_name", "") or "").casefold().strip()
    name = str(getattr(command, "name", "") or "").casefold().strip()
    return qualified, name


def _compact_group_for(command) -> tuple[str, str]:
    root_name, original_leaf = _ORIGINAL_GROUP_FOR(command)
    qualified, name = _command_key(command)
    explicit = COMPACT_COMMAND_NAMES.get(qualified) or COMPACT_COMMAND_NAMES.get(name)
    leaf = explicit or original_leaf
    return v95._safe_name(root_name), _normalise_public_leaf(leaf)


def _compact_should_expose(command) -> bool:
    if not _ORIGINAL_SHOULD_EXPOSE(command):
        return False

    qualified, name = _command_key(command)
    if qualified in STANDARD_DIRECT_SLASH or name in STANDARD_DIRECT_SLASH:
        return False
    if qualified in STANDARD_GROUPED_SLASH or name in STANDARD_GROUPED_SLASH:
        return False
    if qualified in SUPPRESSED_SLASH_DUPLICATES:
        return False

    # Les anciennes commandes déjà fusionnées dans les centres Setup/Ticket/Giveaway/
    # Security ne doivent pas créer un second slash public.
    try:
        from cogs import command_catalog_cleanup as catalog

        merged = set(catalog.MERGED_COMMANDS) | set(catalog.PURE_DUPLICATE_COMMANDS)
        if qualified in merged or name in merged:
            return False
    except Exception:
        pass
    return True


def _compact_unique_leaf(base: str, used: set[str], original: str) -> str:
    del original
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


def _find_command(bot, source_name: str):
    command = bot.get_command(source_name)
    if command is not None:
        return command
    # get_command sait normalement résoudre les chemins de groupe, mais ce repli garde
    # le runtime robuste face à d'anciennes versions discord.py.
    for candidate in bot.walk_commands():
        if str(getattr(candidate, "qualified_name", "")).casefold() == source_name.casefold():
            return candidate
    return None


def _make_direct_slash(bot, source_name: str, public_name: str):
    command = _find_command(bot, source_name)
    if command is None:
        return None
    callback, native = v95._make_callback(bot, command)
    slash = app_commands.Command(
        name=v95._safe_name(public_name),
        description=v95._description(command),
        callback=callback,
    )
    return slash, command, native


def _install_standard_slash_surface(bot) -> tuple[int, list[str]]:
    tree = bot.tree
    installed = 0
    missing: list[str] = []
    direct_report: dict[str, dict] = {}

    for source_name, public_name in STANDARD_DIRECT_SLASH.items():
        built = _make_direct_slash(bot, source_name, public_name)
        if built is None:
            missing.append(source_name)
            continue
        slash, command, native = built
        tree.add_command(slash, override=True)
        direct_report[f"/{slash.name}"] = {
            "original": str(command.qualified_name) if command is not None else source_name,
            "native_options": bool(native),
        }
        installed += 1

    groups: dict[str, app_commands.Group] = {}
    for source_name, (root_name, leaf_name) in STANDARD_GROUPED_SLASH.items():
        command = _find_command(bot, source_name)
        if command is None:
            missing.append(source_name)
            continue
        root = groups.get(root_name)
        if root is None:
            root = app_commands.Group(
                name=v95._safe_name(root_name),
                description=("Gestion courante des rôles du serveur." if root_name == "role" else f"Commandes {root_name} de SentriX.")[:100],
            )
            groups[root_name] = root
        callback, native = v95._make_callback(bot, command)
        slash = app_commands.Command(
            name=v95._safe_name(leaf_name),
            description=v95._description(command),
            callback=callback,
        )
        root.add_command(slash)
        direct_report[f"/{root.name} {slash.name}"] = {
            "original": str(command.qualified_name),
            "native_options": bool(native),
        }
        installed += 1

    for group in groups.values():
        tree.add_command(group, override=True)

    roots = list(tree.get_commands(guild=None, type=discord.AppCommandType.chat_input))
    if len(roots) > v95.MAX_ROOT_COMMANDS:
        raise RuntimeError(f"V110 slash root budget exceeded: {len(roots)}/{v95.MAX_ROOT_COMMANDS}")

    bot._sentrix_v110_direct_mapping = direct_report
    bot._sentrix_v95_slash_root_count = len(roots)
    return installed, missing


def reassert_standard_slash_surface(bot) -> tuple[int, list[str]]:
    """Réinstalle idempotemment la surface standard juste avant l'audit/sync final.

    Certaines couches historiques de SentriX reconstruisent encore une partie du tree
    après V95. Cette passe garantit que les noms publics choisis par V110 sont ceux qui
    arrivent réellement chez Discord, sans dupliquer la logique métier.
    """
    return _install_standard_slash_surface(bot)


def _wrap_prepare_bot() -> None:
    current = v95.prepare_bot
    if getattr(current, "_sentrix_compact_surface_v110", False):
        return

    async def prepare_bot_standard(bot):
        grouped = await current(bot)
        installed, missing = reassert_standard_slash_surface(bot)
        if missing:
            logger.warning("V110 : commandes sources absentes pour la surface standard : %s", ", ".join(sorted(missing)))
        logger.info(
            "V110 surface slash standard active : %s commandes directes/groupées familières, %s slash groupés restants, %s racines.",
            installed,
            len(grouped),
            getattr(bot, "_sentrix_v95_slash_root_count", 0),
        )
        return grouped

    prepare_bot_standard._sentrix_compact_surface_v110 = True
    prepare_bot_standard._sentrix_original = current
    v95.prepare_bot = prepare_bot_standard


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    v95._group_for = _compact_group_for
    v95._should_expose = _compact_should_expose
    v95._unique_leaf = _compact_unique_leaf
    _wrap_prepare_bot()

    _INSTALLED = True
    logger.info("V110 installé : slash familiers, noms + historiques préservés.")


__all__ = [
    "COMPACT_COMMAND_NAMES",
    "COMPACT_ROOT_NAMES",
    "STANDARD_DIRECT_SLASH",
    "STANDARD_GROUPED_SLASH",
    "reassert_standard_slash_surface",
    "install",
]
