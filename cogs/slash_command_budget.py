"""Budget et sélection canonique des commandes slash SentriX."""
from __future__ import annotations

import logging
from types import MethodType

import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger("bot.slash-budget")
GLOBAL_CHAT_INPUT_BUDGET = 100

# Discord limite les commandes chat-input globales à 100 racines. Les quatre entrées
# proof ci-dessous doivent rester disponibles même quand le catalogue historique remplit
# déjà le budget.
PROOF_SLASH_PREFERRED = frozenset({"proof", "proofsetup", "proofexample", "proofstatus"})


def _v110_public_root_names() -> set[str]:
    """Retourne les racines publiques explicitement choisies par la surface V110."""
    try:
        import sentrix_command_surface_v110 as surface
    except (ImportError, ModuleNotFoundError):
        return set()

    roots = {
        str(public_name).casefold().strip()
        for public_name in getattr(surface, "STANDARD_DIRECT_SLASH", {}).values()
        if str(public_name).strip()
    }
    roots.update(
        str(root_name).casefold().strip()
        for root_name, _leaf_name in getattr(surface, "STANDARD_GROUPED_SLASH", {}).values()
        if str(root_name).strip()
    )
    roots.update(
        str(root_name).casefold().strip()
        for root_name, _leaf_name in getattr(surface, "CANONICAL_GROUPED_NAMES", {}).values()
        if str(root_name).strip()
    )
    return roots


def _canonical_group_root_names() -> set[str]:
    """Racines V95 qui donnent accès aux fonctions avancées sans multiplier les slash.

    Elles ont priorité sur les anciennes commandes plates : perdre /security ou /ticket
    pour conserver un mini-jeu isolé rendrait une famille entière de fonctions
    introuvable. Les racines spéciales giveaway/invites/notifications sont construites
    hors CATEGORY_ROOTS par V95 et doivent donc être ajoutées explicitement.
    """
    try:
        import sentrix_v95_runtime as v95
    except (ImportError, ModuleNotFoundError):
        return {"help", "setup", "ping", "sentrix"}

    roots = {
        str(name).casefold().strip()
        for name in getattr(v95, "DIRECT_ROOTS", ())
        if str(name).strip()
    }
    roots.update(
        str(name).casefold().strip()
        for name in getattr(v95, "CATEGORY_ROOTS", {}).values()
        if str(name).strip()
    )
    roots.update({"giveaway", "invites", "notifications"})
    return roots


def _required_names() -> set[str]:
    """Tier 1 : racines qui ne doivent jamais être sacrifiées au budget."""
    return (
        _v110_public_root_names()
        | _canonical_group_root_names()
        | set(PROOF_SLASH_PREFERRED)
    )


def _preferred_names() -> set[str]:
    """Tier 2 : anciennes racines utiles, conservées seulement après le tier 1."""
    from .command_catalog_cleanup import NORMAL_DIRECT_COMMANDS

    return _required_names() | set(NORMAL_DIRECT_COMMANDS)


def _excluded_names() -> set[str]:
    from .command_catalog_cleanup import ADMIN_DIRECT_COMMANDS, MERGED_COMMANDS

    # MERGED_COMMANDS décrit la visibilité historique des commandes préfixées. V110 peut
    # réutiliser l'un de ces noms comme racine slash standard (ex. /queue, /resume,
    # /profile, /shop, /weekly). Ces racines sont intentionnelles et ne doivent donc pas
    # être bloquées par le filtre legacy du budget.
    legacy_excluded = set(ADMIN_DIRECT_COMMANDS) | set(MERGED_COMMANDS)
    return legacy_excluded - _v110_public_root_names()


def _global_roots(tree) -> list:
    try:
        return list(tree.get_commands(guild=None, type=discord.AppCommandType.chat_input))
    except Exception:
        return [
            item for item in tree.get_commands(guild=None)
            if isinstance(item, (app_commands.Command, app_commands.Group))
        ]


def _remove_root(tree, name: str) -> None:
    try:
        tree.remove_command(name, type=discord.AppCommandType.chat_input)
    except TypeError:
        tree.remove_command(name)


def finalize(bot: commands.Bot) -> None:
    """Écarte les racines legacy puis applique le budget par niveaux de priorité."""
    tree = bot.tree
    required = _required_names()
    preferred = _preferred_names()
    excluded = _excluded_names()

    if len(required) > GLOBAL_CHAT_INPUT_BUDGET:
        raise RuntimeError(
            f"Budget slash incohérent : {len(required)} racines obligatoires pour "
            f"{GLOBAL_CHAT_INPUT_BUDGET} places."
        )

    for item in list(_global_roots(tree)):
        name = str(getattr(item, "name", "") or "").casefold()
        if name in excluded:
            _remove_root(tree, name)

    roots = _global_roots(tree)
    if len(roots) <= GLOBAL_CHAT_INPUT_BUDGET:
        return

    # Ordre déterministe par priorité, tout en conservant l'ordre de construction du tree
    # à l'intérieur de chaque tier pour ne pas provoquer de churn entre deux boots.
    keep: set[str] = set()
    for tier in (required, preferred):
        for item in roots:
            name = str(getattr(item, "name", "") or "").casefold()
            if name in tier and len(keep) < GLOBAL_CHAT_INPUT_BUDGET:
                keep.add(name)
    for item in roots:
        name = str(getattr(item, "name", "") or "").casefold()
        if name not in keep and len(keep) < GLOBAL_CHAT_INPUT_BUDGET:
            keep.add(name)

    for item in list(roots):
        name = str(getattr(item, "name", "") or "").casefold()
        if name not in keep:
            _remove_root(tree, name)


def install(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_slash_budget_installed", False):
        finalize(bot)
        return
    bot._sentrix_slash_budget_installed = True

    tree = bot.tree
    original_add = tree.add_command
    skipped: list[str] = []
    bot._sentrix_skipped_global_slash = skipped

    def _call_original(command, *, guild=None, guilds=None, override: bool = False):
        kwargs = {"override": override}
        if guild is not None:
            kwargs["guild"] = guild
        if guilds is not None:
            kwargs["guilds"] = guilds
        try:
            return original_add(command, **kwargs)
        except app_commands.CommandLimitReached:
            name = str(getattr(command, "name", "") or "").casefold()
            skipped.append(name)
            logger.warning(
                "Budget slash : « %s » écartée après échec réel de discord.py "
                "(limite 100 déjà atteinte malgré le comptage local).",
                name,
            )
            return None

    def budgeted_add(
        _tree,
        command,
        *,
        guild=None,
        guilds=None,
        override: bool = False,
    ):
        if guild is not None or guilds is not None:
            return _call_original(command, guild=guild, guilds=guilds, override=override)

        if isinstance(command, (app_commands.Command, app_commands.Group)):
            name = str(getattr(command, "name", "") or "").casefold()
            if name in _excluded_names():
                skipped.append(name)
                return None

            roots = _global_roots(tree)
            existing = next(
                (item for item in roots if str(getattr(item, "name", "")).casefold() == name),
                None,
            )
            if existing is None and len(roots) >= GLOBAL_CHAT_INPUT_BUDGET:
                required = _required_names()
                preferred = _preferred_names()

                # Une racine V110/canonique/proof peut toujours remplacer une racine de
                # niveau inférieur. C'était le bug qui faisait disparaître /queue,
                # /unmute, /role, etc. : NORMAL_DIRECT_COMMANDS marquait auparavant presque
                # tout comme "protégé", donc aucune victime ne pouvait être choisie.
                if name in required:
                    victim = next(
                        (
                            item for item in roots
                            if str(getattr(item, "name", "")).casefold() not in required
                        ),
                        None,
                    )
                elif name in preferred:
                    victim = next(
                        (
                            item for item in roots
                            if str(getattr(item, "name", "")).casefold() not in preferred
                        ),
                        None,
                    )
                else:
                    victim = None

                if victim is not None:
                    victim_name = str(getattr(victim, "name", "")).casefold()
                    _remove_root(tree, victim_name)
                else:
                    skipped.append(name)
                    return None

        return _call_original(command, override=override)

    tree.add_command = MethodType(budgeted_add, tree)
    finalize(bot)
    logger.info(
        "Budget slash SentriX actif : maximum %s racines, tier1=%s, proof=%s, V110=%s.",
        GLOBAL_CHAT_INPUT_BUDGET,
        len(_required_names()),
        ",".join(sorted(PROOF_SLASH_PREFERRED)),
        len(_v110_public_root_names()),
    )
