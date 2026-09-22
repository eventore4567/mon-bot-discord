"""Messages de refus : chaque erreur dit sa VRAIE cause, sur les deux transports.

- un BotPermissionError garde son message d'origine (jamais « pas la permission ») ;
- MissingPermissions / BotMissingPermissions nomment la permission exacte ;
- un module coupé n'a plus l'en-tête « Vous n'avez pas accès à cette commande » ;
- un check muet ne conclut jamais « permission » : la matrice est interrogée.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import discord
from discord.ext import commands

from utils import error_texts
from utils.access_matrix import AccessDecision
from utils.checks import BotPermissionError

ECO_OFF = "Le **système d'argent est désactivé** sur ce serveur. Les soldes, récompenses et boutiques sont actuellement bloqués."


def test_bot_permission_error_keeps_its_original_message_everywhere():
    error = BotPermissionError(ECO_OFF)
    assert error_texts.user_error_text(error) == ECO_OFF

    import sentrix_grouped_slash_fix as grouped
    assert grouped._short_error(error) == ECO_OFF
    assert grouped._short_error(commands.CommandInvokeError(error)) == ECO_OFF

    from cogs import final_error_embed_v5 as v5
    ctx = SimpleNamespace(clean_prefix="+", command=None, invoked_with="balance", bot=None, current_parameter=None)
    assert v5._texte_erreur_prefix(ctx, error) == ECO_OFF
    assert "pas la permission" not in v5._texte_erreur_prefix(ctx, error)


def test_missing_permissions_names_the_exact_permission():
    import sentrix_grouped_slash_fix as grouped
    from cogs import final_error_embed_v5 as v5

    error = commands.MissingPermissions(["manage_messages"])
    expected = "Il te faut la permission **Gérer les messages** pour utiliser cette commande."
    assert error_texts.user_error_text(error) == expected
    assert grouped._short_error(error) == expected
    ctx = SimpleNamespace(clean_prefix="+", command=None, invoked_with="clear", bot=None, current_parameter=None)
    assert v5._texte_erreur_prefix(ctx, error) == expected

    app_error = discord.app_commands.MissingPermissions(["ban_members"])
    assert v5._texte_erreur_slash(app_error) == "Il te faut la permission **Bannir des membres** pour utiliser cette commande."


def test_bot_missing_permissions_names_the_exact_permission():
    import sentrix_grouped_slash_fix as grouped
    from cogs import final_error_embed_v5 as v5

    error = commands.BotMissingPermissions(["manage_roles"])
    expected = "Il manque à SentriX la permission **Gérer les rôles** pour effectuer cette action."
    assert error_texts.user_error_text(error) == expected
    assert grouped._short_error(error) == expected
    ctx = SimpleNamespace(clean_prefix="+", command=None, invoked_with="giverole", bot=None, current_parameter=None)
    assert v5._texte_erreur_prefix(ctx, error) == expected
    assert v5._texte_erreur_slash(discord.app_commands.BotMissingPermissions(["manage_roles"])) == expected


def test_generic_permission_phrase_is_gone_for_silent_check_failures():
    import sentrix_grouped_slash_fix as grouped

    silent = commands.CheckFailure("The check functions for command balance failed.")
    text = grouped._short_error(silent)
    assert "pas la permission" not in text.casefold()
    assert text == error_texts.CHECK_FALLBACK
    assert error_texts.user_error_text(silent) is None  # l'appelant interroge la matrice


def test_module_off_decision_has_no_permission_header():
    module_off = AccessDecision(False, "Le module **Économie** est désactivé sur ce serveur.", "module:economy:off")
    assert module_off.message == "Le module **Économie** est désactivé sur ce serveur."
    dm = AccessDecision(False, "Cette commande doit être utilisée dans un serveur.", "guild-required")
    assert "accès" not in dm.message
    permission = AccessDecision(False, "**Permission Discord requise :** Bannir des membres.", "discord:ban_members")
    assert permission.message.startswith("Vous n'avez pas accès à cette commande.")
    owner = AccessDecision(False, "Cette commande est réservée au **propriétaire global de SentriX**.", "owner-global")
    assert "propriétaire global" in owner.message


def test_explain_check_failure_prefers_matrix_reason_then_economy_gate():
    decision = AccessDecision(False, "Le module **Économie** est désactivé sur ce serveur.", "module:economy:off")

    async def evaluate(bot, *, command_name, author, guild):
        return decision

    import utils.access_matrix as matrix
    original = matrix.evaluate
    matrix.evaluate = evaluate
    try:
        command = SimpleNamespace(qualified_name="balance", name="balance", root_parent=None, cog_name="Economy")
        text = asyncio.run(error_texts.explain_check_failure(SimpleNamespace(db=None), command=command, author=None, guild=SimpleNamespace(id=1)))
    finally:
        matrix.evaluate = original
    assert text == "Le module **Économie** est désactivé sur ce serveur."

    # Hors serveur : la cause est le message privé, pas une permission.
    text = asyncio.run(error_texts.explain_check_failure(SimpleNamespace(db=None), command=command, author=None, guild=None))
    assert text == error_texts.GUILD_ONLY_TEXT


def test_argument_errors_name_the_argument():
    param = SimpleNamespace(name="nombre", displayed_name="nombre")
    assert "« nombre »" in error_texts.user_error_text(commands.MissingRequiredArgument(param), usage="+clear <nombre>")
    assert "entre 1 et 100" in error_texts.user_error_text(commands.RangeError(150, minimum=1, maximum=100), usage=None, param_name="nombre")
    assert error_texts.user_error_text(commands.MemberNotFound("bob")).startswith("Membre introuvable : « bob »")
    assert error_texts.user_error_text(commands.CommandOnCooldown(None, 12.4, commands.BucketType.user)) == "Commande en attente : réessayez dans 12 s."
    assert error_texts.user_error_text(commands.NoPrivateMessage()) == error_texts.GUILD_ONLY_TEXT


def test_subcommand_tiers_are_honoured_by_every_evaluator():
    """« giveaway create » est déclaré catégorie configuration : V65/V68 le renvoyaient
    en fail-closed (Administrateur) au lieu de Gérer le serveur."""
    from cogs import setup_simple_v68 as v68
    from cogs import permission_setup_hardening_v65 as v65

    assert v68._category_for("giveaway create") == "configuration"
    assert v65._category_for("sentrixpro lockdown") == "securite"
    assert v68._category_for("ban") is None


def test_economy_off_uses_the_money_system_wording_in_every_evaluator():
    from utils import access_matrix

    eco = access_matrix.module_disabled_message("economy")
    assert eco.startswith("Le **système d'argent est désactivé** sur ce serveur.")
    assert access_matrix.module_disabled_message("levels").startswith("Le **système de niveaux est désactivé**")
    assert access_matrix.module_disabled_message("roles").startswith("Le module **Rôles** est désactivé")
    decision = access_matrix.AccessDecision(False, eco, "module:economy:off")
    assert decision.message == eco  # pas d'en-tête « pas accès »
