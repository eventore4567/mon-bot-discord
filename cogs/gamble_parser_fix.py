"""Correctif ciblé du parseur de +gamble, sans nouvelle commande.

Le callback de +gamble est remplacé à chaud par la couche d'intégrité afin de rendre la
transaction atomique. Certaines anciennes couches ont pu laisser un Parameter discord.py
incorrect sur la commande préfixée : même `+gamble 10` déclenchait alors BadArgument.

Ce module ne touche PAS à l'Application Command `/gamble` ni à la callback métier. Il
reconstruit uniquement les paramètres du parseur texte de +gamble à partir d'une signature
propre connue : un seul argument utilisateur `montant: int`.
"""
from __future__ import annotations

import logging

from discord.ext import commands

logger = logging.getLogger("bot.gamble-parser-fix")


async def _gamble_signature_probe(ctx: commands.Context, montant: int):
    """Signature de référence utilisée uniquement pour reconstruire Command.params."""
    return None


def _apply(bot: commands.Bot) -> bool:
    command = bot.get_command("gamble")
    if command is None:
        return False

    # Laisser discord.py construire lui-même le bon Parameter évite de bricoler ses
    # attributs internes/converters à la main. Comme la fonction est top-level, discord.py
    # retire automatiquement `ctx` et conserve uniquement `montant` avec le convertisseur int.
    probe = commands.Command(_gamble_signature_probe, name="_sentrix_gamble_signature_probe")
    command.params = probe.params.copy()
    command.usage = "<montant>"
    command._sentrix_gamble_parser_fixed = True

    params = tuple(command.params)
    if params != ("montant",):
        logger.error("Correctif +gamble incomplet : paramètres obtenus=%r", params)
        return False

    logger.info("Parseur +gamble réparé : paramètres=%r, convertisseur montant=int.", params)
    return True


def install(bot: commands.Bot) -> None:
    """Installe le correctif maintenant et le réapplique une dernière fois à on_ready."""
    _apply(bot)
    if getattr(bot, "_sentrix_gamble_parser_fix_listener", False):
        return

    async def reapply_on_ready():
        _apply(bot)

    bot.add_listener(reapply_on_ready, "on_ready")
    bot._sentrix_gamble_parser_fix_listener = True
