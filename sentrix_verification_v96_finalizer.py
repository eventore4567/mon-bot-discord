"""Autorité finale V96 pour la vérification SentriX.

Plusieurs runtimes historiques réécrivent ``verify-setup`` très tard pendant le boot.
Cette couche s'exécute juste avant la préparation slash V95, donc après le chargement de
toutes les extensions Railway. Elle garantit que la configuration guidée règlement +
CAPTCHA reste l'unique commande de vérification publique, en ``+`` comme en ``/``.
"""
from __future__ import annotations

import logging

from discord.ext import commands

import sentrix_v95_runtime as v95
import sentrix_verification_v96 as v96
from sentrix_v103_setup_fix import install as install_setup_v103
from sentrix_v105_slash_schema_guard import install as install_slash_guard_v105

logger = logging.getLogger("bot.verification-v96-final")

_NAMES = (
    "verification",
    "verify-panel",
    "verify-setup",
    "verify-config",
    "verification-config",
)


def _install_verification_transport_bypass() -> None:
    """Laisse V96 contrôler son propre rendu sans le formatter global.

    ``final_interaction_policy`` reformate normalement toutes les réponses de commandes.
    C'est utile pour les anciennes commandes texte, mais V96 possède déjà son embed et ses
    composants. Le reformatage transformait donc le panneau de configuration en fausse
    carte « Erreur » et les follow-ups des boutons en panneau « Information » avec une
    bannière jointe. Les interactions de composants n'ont pas de ``interaction.command`` :
    on les rattache à V96 grâce au message qui porte le panneau.
    """
    try:
        from cogs import final_interaction_policy as policy
    except Exception:
        logger.exception("Impossible d'installer le transport direct de la vérification V96.")
        return

    current_plain = policy._plain_root
    if not getattr(current_plain, "_sentrix_verification_v96", False):
        def plain_root_with_verification(root: str) -> bool:
            return str(root or "").casefold() == "verification" or current_plain(root)

        plain_root_with_verification._sentrix_verification_v96 = True
        plain_root_with_verification._sentrix_original = current_plain
        policy._plain_root = plain_root_with_verification

    current_root = policy._root_from_interaction
    if not getattr(current_root, "_sentrix_verification_v96", False):
        def root_from_interaction_with_verification(interaction):
            root = current_root(interaction)
            if root:
                return root

            message = getattr(interaction, "message", None)
            for embed in list(getattr(message, "embeds", ()) or ()):
                title = str(getattr(embed, "title", "") or "").casefold()
                footer = str(getattr(getattr(embed, "footer", None), "text", "") or "").casefold()
                if (
                    "configuration de la vérification" in title
                    or "configuration de la verification" in title
                    or "vérification • captcha" in footer
                    or "verification • captcha" in footer
                ):
                    return "verification"
            return root

        root_from_interaction_with_verification._sentrix_verification_v96 = True
        root_from_interaction_with_verification._sentrix_original = current_root
        policy._root_from_interaction = root_from_interaction_with_verification

    logger.info(
        "V96 transport direct actif : panneau, composants et follow-ups exclus du formatter global."
    )


def _repair_permission_policy() -> None:
    try:
        import main

        main.CATEGORY_COMMANDS["configuration"] = (
            main.CATEGORY_COMMANDS.get("configuration", frozenset())
            | frozenset({"verification"})
        )
        main.KNOWN_PERMISSION_COMMANDS = (
            main.KNOWN_PERMISSION_COMMANDS | frozenset({"verification"})
        )
        main.PRUNED_COMMANDS = frozenset(
            name
            for name in main.PRUNED_COMMANDS
            if name not in {"verification", "verify-panel", "verify-setup"}
        )
    except Exception:
        logger.exception("Politique permissions V96 impossible à réaffirmer.")


async def reassert(bot: commands.Bot) -> commands.Command:
    """Réinstalle V96 après les runtimes V76/V78 qui remplacent les anciennes commandes."""
    old_cog = bot.get_cog("VerificationConfigV96")
    if old_cog is not None:
        await bot.remove_cog("VerificationConfigV96")

    # Retirer les commandes réintroduites tardivement. On retire leur vrai nom canonique,
    # pas seulement la clé d'alias, pour éviter qu'un alias reste accroché au vieux callback.
    canonical_names: set[str] = set()
    for lookup in _NAMES:
        command = bot.get_command(lookup)
        if command is not None:
            canonical_names.add(str(command.name))
    for name in canonical_names:
        bot.remove_command(name)

    await bot.add_cog(v96.VerificationConfigV96(bot))
    _repair_permission_policy()

    command = bot.get_command("verification")
    if command is None:
        raise RuntimeError("V96: commande +verification absente après réinstallation finale")
    for alias in _NAMES[1:]:
        if bot.get_command(alias) is not command:
            raise RuntimeError(f"V96: alias +{alias} absent ou lié au mauvais callback")
    return command


def install() -> None:
    """Entoure V95 puis arme les gardes finaux V103 et V105 de la surface slash."""
    _install_verification_transport_bypass()
    v96._install_v95_route()
    current = v95.prepare_bot

    if not getattr(current, "_sentrix_verification_v96_final", False):
        async def prepare_with_verification(bot: commands.Bot):
            command = await reassert(bot)
            result = await current(bot)

            verification_paths = [
                path
                for path, info in result.items()
                if str(info.get("original")) == str(command.qualified_name)
            ]
            if len(verification_paths) != 1:
                raise RuntimeError(
                    "V96: la commande de vérification doit avoir exactement un chemin slash, "
                    f"obtenu={verification_paths!r}"
                )
            if not verification_paths[0].startswith("/roles "):
                raise RuntimeError(
                    f"V96: chemin slash inattendu pour la vérification: {verification_paths[0]}"
                )

            bot._sentrix_verification_v96_path = verification_paths[0]
            logger.warning(
                "V96 final : +verification/+verify-panel/+verify-setup actifs ; slash=%s.",
                verification_paths[0],
            )
            return result

        prepare_with_verification._sentrix_verification_v96_final = True
        prepare_with_verification._sentrix_original = current
        v95.prepare_bot = prepare_with_verification
        logger.info("V96 finalizer branché juste avant la préparation slash V95.")

    # Le bootstrap HA charge ce finalizer après les anciennes couches. V103 réinstalle
    # /setup, puis V105 devient l'ultime garde avant chaque CommandTree.sync : il normalise
    # aussi /help, /ping et /sentrix, puis refuse toute fuite ctx/args/kwargs restante.
    install_setup_v103()
    install_slash_guard_v105()


__all__ = ["install", "reassert"]
