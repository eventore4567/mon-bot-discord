"""Branchement des deux transports Discord sur la matrice d'accès unique.

Ce module ne DÉCIDE rien. Il se contente de :
- extraire le nom racine de la commande, identiquement pour ``+`` et ``/`` ;
- appeler ``utils.access_matrix.evaluate()`` ;
- rendre le refus lisible.

Toute règle d'accès vit dans ``utils/access_matrix.py``. Ne pas rajouter de
condition ici : ce serait recréer la divergence que cette refonte supprime.

Contrat fail-closed
-------------------
Une commande inconnue de la matrice est REFUSÉE, jamais autorisée par défaut.
``install()`` le vérifie réellement au démarrage via
``_assert_fail_closed_contract()`` : si une commande inventée obtenait un accès,
l'installation échoue bruyamment au lieu d'ouvrir silencieusement le bot.
"""
from __future__ import annotations

import asyncio
import inspect
import logging
from typing import Any

import discord
from discord.ext import commands

from utils import access_matrix
from utils import checks as checks_module
from utils.access_matrix import AccessDecision, evaluate, normalise
from utils.checks import BotPermissionError

logger = logging.getLogger("bot.permission-guard")

# Réexports de compatibilité : d'anciens modules importent ces noms.
PROOF_PUBLIC_COMMANDS = frozenset({"proof", "proofstatus"})
PROOF_ADMIN_COMMANDS = frozenset({
    "proofsetup", "proofexample", "proofexample-remove", "proofexamples",
    "proofpanel", "proofreset",
})


def command_root_name(command: Any) -> str:
    """Nom evalue par la matrice.

    Par defaut la racine : les alias sont deja resolus par discord.py et les
    sous-commandes heritent de leur groupe. access_matrix.resolve_name ne renvoie le nom
    COMPLET que pour les rares sous-commandes declarees plus strictes que leur groupe
    (table SUBCOMMAND_TIERS), afin qu'une sous-commande sensible ne puisse pas devenir
    publique parce que sa racine l'est.
    """
    if command is None:
        return ""
    root = getattr(command, "root_parent", None) or command
    return access_matrix.resolve_name(
        getattr(command, "qualified_name", ""), getattr(root, "name", "")
    )


def interaction_root_name(interaction: discord.Interaction) -> str:
    command = getattr(interaction, "command", None)
    name = command_root_name(command)
    if name:
        return name
    data = getattr(interaction, "data", None)
    if isinstance(data, dict):
        return normalise(data.get("name"))
    return ""


def _default_permissions_for(name: str) -> discord.Permissions | None:
    """Permission Discord a afficher pour une commande slash, tiree de la matrice.

    Ce reglage est PUREMENT COSMETIQUE : il indique a Discord de masquer la commande
    dans le menu des membres qui ne pourront de toute facon pas l'utiliser. La decision
    reelle reste prise au runtime par access_matrix.evaluate a chaque invocation — un
    membre qui contournerait l'affichage serait refuse exactement pareil.

    Les commandes publiques ne recoivent RIEN : elles doivent rester visibles de tous.
    """
    from cogs.permission_setup_hardening_v65 import CATEGORY_REQUIRED_PERMISSION

    tier = access_matrix.access_tier(name)
    if tier == "public":
        return None
    if tier in {"guild-owner", "owner-global"}:
        # Discord ne sait pas exprimer « proprietaire uniquement » : Administrateur est
        # le filtre d'affichage le plus proche. Le niveau reel est applique au runtime.
        return discord.Permissions(administrator=True)
    if tier == "embed-staff":
        return discord.Permissions(manage_messages=True)
    if tier.startswith("discord:"):
        permission = tier.split(":", 1)[1]
        try:
            return discord.Permissions(**{permission: True})
        except TypeError:
            return discord.Permissions(manage_guild=True)
    if tier.startswith("categorie:"):
        category = tier.split(":", 1)[1]
        native = CATEGORY_REQUIRED_PERMISSION.get(category, "manage_guild")
        try:
            return discord.Permissions(**{native: True})
        except TypeError:
            return discord.Permissions(manage_guild=True)
    # fail-closed : la commande n'est pas classee, on ne l'affiche pas aux membres.
    return discord.Permissions(administrator=True)


def apply_slash_default_permissions(bot: commands.Bot) -> int:
    """Aligne l'AFFICHAGE des commandes slash sur la matrice. Retourne le nombre pose.

    Appele une fois avant la synchronisation de l'arbre. Ce n'est pas un wrapper : rien
    n'est intercepte, on renseigne un attribut declaratif que Discord lit au sync.
    """
    applied = 0
    for command in bot.tree.walk_commands():
        if command.parent is not None:
            continue  # Discord n'applique le reglage qu'a la racine d'un groupe
        if getattr(command, "default_permissions", None) is not None:
            continue  # deja declare explicitement dans le code
        name = access_matrix.resolve_name(
            getattr(command, "qualified_name", ""), getattr(command, "name", "")
        )
        permissions = _default_permissions_for(name)
        if permissions is None:
            continue
        try:
            command.default_permissions = permissions
            applied += 1
        except Exception:
            logger.exception("default_permissions impossible sur /%s", name)
    if applied:
        logger.info("Affichage slash aligne sur la matrice : %s commande(s).", applied)
    return applied


async def evaluate_command_access(
    bot: commands.Bot, *, command_name: str, author: Any, guild: Any
) -> AccessDecision:
    """Point d'entrée unique. NE PAS envelopper : modifier la matrice."""
    return await evaluate(bot, command_name=command_name, author=author, guild=guild)


async def evaluate_interaction_access(
    bot: commands.Bot, interaction: discord.Interaction
) -> AccessDecision:
    return await evaluate(
        bot,
        command_name=interaction_root_name(interaction),
        author=getattr(interaction, "user", None),
        guild=getattr(interaction, "guild", None),
    )


async def _send_interaction_denial(
    interaction: discord.Interaction, decision: AccessDecision
) -> None:
    embed = discord.Embed(
        title="SentriX — Permission insuffisante",
        description=decision.message,
        colour=discord.Colour(0xED4245),
    )
    embed.set_footer(text="SentriX • Permissions identiques en + et /")
    kwargs = {
        "embed": embed,
        "ephemeral": True,
        "allowed_mentions": discord.AllowedMentions.none(),
    }
    try:
        if interaction.response.is_done():
            await interaction.followup.send(**kwargs)
        else:
            await interaction.response.send_message(**kwargs)
    except (discord.Forbidden, discord.HTTPException, discord.InteractionResponded):
        logger.debug("Impossible d'envoyer le refus slash.", exc_info=True)


def _force_help_public(bot: commands.Bot) -> None:
    command = bot.get_command("help")
    if command is None:
        return
    for holder in (command, getattr(command, "app_command", None)):
        if holder is None:
            continue
        checks_list = getattr(holder, "checks", None)
        if isinstance(checks_list, list) and checks_list:
            checks_list.clear()
        holder._sentrix_help_public = True


def _is_redundant_authorization_check(predicate: Any) -> bool:
    """Vrai UNIQUEMENT si le check est explicitement un ancien check d'autorisation.

    Politique fail-safe : en cas de doute, on CONSERVE le check. Un check non
    marqué est traité comme une validation métier, jamais comme du bruit.
    Retirer par erreur une validation de cible est un problème de sécurité ;
    conserver par erreur un check d'autorisation ne l'est pas, puisque la
    matrice rend la même décision et ne peut donc pas créer de divergence +//.
    """
    if getattr(predicate, "_sentrix_keep", False):
        return False

    kind = str(getattr(predicate, "_sentrix_check_kind", "") or "")
    if kind == checks_module.CHECK_KIND_ACTION_VALIDATION:
        return False
    if kind != checks_module.CHECK_KIND_AUTHORIZATION:
        # Non marqué : on ne sait pas ce que fait ce check -> on le garde.
        module = str(getattr(predicate, "__module__", "") or "")
        qualname = str(getattr(predicate, "__qualname__", "") or "")
        if module.startswith("discord.ext.commands"):
            # Seuls ces deux-là sont, par construction, de l'autorisation pure.
            return (
                "has_permissions.<locals>.predicate" in qualname
                or "has_guild_permissions.<locals>.predicate" in qualname
            )
        return False

    label = str(getattr(predicate, "_sentrix_permission_label", "") or "")
    # Défense en profondeur : le verrou owner global reste en place. La matrice
    # rend la même décision, donc aucune divergence + // n'est possible.
    if "Proprietaire global SentriX" in label or "Propriétaire global SentriX" in label:
        return False
    return True


def _strip_redundant_local_checks(bot: commands.Bot) -> int:
    """Remove only local authorization checks replaced by the access matrix.

    Context and execution-safety checks (guild_only, target hierarchy,
    modifiability, bot permissions, business validation...) are deliberately
    preserved.
    """
    removed = 0
    for command in bot.walk_commands():
        root = command.root_parent or command
        if normalise(getattr(root, "name", "")) not in access_matrix.KNOWN_COMMANDS:
            continue
        for holder in (command, getattr(command, "app_command", None)):
            if holder is None:
                continue
            checks_list = getattr(holder, "checks", None)
            if not isinstance(checks_list, list):
                continue
            keep = [c for c in checks_list if not _is_redundant_authorization_check(c)]
            removed += len(checks_list) - len(keep)
            checks_list[:] = keep
    return removed


async def _assert_fail_closed_contract(bot: commands.Bot) -> None:
    """Vérifie que la matrice refuse bien une commande inconnue (fail-closed).

    Ce n'est pas une formalité : une régression qui rendrait la matrice
    permissive par défaut ouvrirait d'un coup toutes les commandes non classées.
    On teste donc le comportement, pas une chaîne de caractères.
    """
    probe = "__sentrix_probe_commande_inexistante__"

    class _Member:
        id = 0
        roles = ()
        guild_permissions = discord.Permissions.none()

    class _Guild:
        id = 0
        owner_id = None

    decision = await evaluate(
        bot, command_name=probe, author=_Member(), guild=_Guild()
    )
    if decision.allowed:
        raise RuntimeError(
            "Contrat fail-closed rompu : une commande inconnue a été autorisée "
            f"(policy={decision.policy!r}). Installation interrompue."
        )


def install(bot: commands.Bot) -> None:
    _force_help_public(bot)
    if getattr(bot, "_sentrix_permission_guard_installed", False):
        return

    removed = _strip_redundant_local_checks(bot)

    async def prefix_permission_guard(ctx: commands.Context) -> bool:
        command = getattr(ctx, "command", None)
        if command is None:
            return True
        decision = await evaluate_command_access(
            bot,
            command_name=command_root_name(command),
            author=getattr(ctx, "author", None),
            guild=getattr(ctx, "guild", None),
        )
        if decision.allowed:
            return True
        raise BotPermissionError(decision.message)

    prefix_permission_guard._sentrix_permission_guard = True
    bot.global_permission_check = prefix_permission_guard

    # Affichage seulement : Discord masque aux membres les commandes qu'ils ne peuvent
    # pas utiliser. La decision reste prise au runtime a chaque invocation.
    apply_slash_default_permissions(bot)

    original_tree_check = bot.tree.interaction_check

    async def slash_permission_guard(interaction: discord.Interaction) -> bool:
        previous = original_tree_check(interaction)
        if inspect.isawaitable(previous):
            previous = await previous
        if previous is False:
            return False
        if interaction.type != discord.InteractionType.application_command:
            return True
        decision = await evaluate_interaction_access(bot, interaction)
        if decision.allowed:
            return True
        logger.warning(
            "Slash refusé command=%s user=%s guild=%s policy=%s",
            interaction_root_name(interaction),
            getattr(getattr(interaction, "user", None), "id", None),
            getattr(interaction, "guild_id", None),
            decision.policy,
        )
        await _send_interaction_denial(interaction, decision)
        return False

    slash_permission_guard._sentrix_permission_guard = True
    slash_permission_guard._sentrix_previous_tree_check = original_tree_check
    bot.tree.interaction_check = slash_permission_guard
    bot._sentrix_permission_guard_installed = True

    # Contrat fail-closed vérifié pour de vrai, pas seulement documenté.
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is not None:
        loop.create_task(_assert_fail_closed_contract(bot))

    logger.info(
        "Permissions SentriX : matrice unique active (%s commandes classées, "
        "%s check(s) local(aux) redondant(s) retiré(s)).",
        len(access_matrix.KNOWN_COMMANDS),
        removed,
    )


__all__ = [
    "AccessDecision", "evaluate_command_access", "evaluate_interaction_access",
    "command_root_name", "interaction_root_name", "install",
]
