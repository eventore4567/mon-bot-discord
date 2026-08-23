"""SentriX V20 — sécurité des arguments d'envoi Discord.

Certaines couches visuelles transforment un texte positionnel ``ctx.send("texte")`` en
embed et ajoutent ensuite ``content=None``. Si le premier argument positionnel ``None``
reste présent, Python appelle finalement ``Context.send(None, content=None, ...)`` et
lève ``TypeError: got multiple values for argument 'content'``.

Ce garde-fou canonicalise le résultat du renderer final. Il ne modifie ni le contenu ni
la logique métier : il garantit seulement qu'une valeur ``content`` n'est jamais fournie
à la fois en positionnel et en mot-clé. Il couvre Context.send, Messageable.send,
InteractionResponse et Webhook car tous passent par ``plain_response_policy._force_rich_args``.
"""
from __future__ import annotations

import logging
from typing import Any

from discord.ext import commands

logger = logging.getLogger("bot.send-argument-safety-v20")


def _canonicalize(args: tuple[Any, ...], kwargs: dict[str, Any]):
    positional = list(args)
    named = dict(kwargs)

    if positional and "content" in named:
        # Cas créé par le renderer SentriX : le texte positionnel a déjà été converti en
        # embed et remplacé par None. On retire complètement ce faux argument positionnel.
        if positional[0] is None:
            positional.pop(0)
        else:
            # Si un vrai texte positionnel subsiste, il est la source historique de la
            # commande. On ne transmet donc pas un second ``content=`` contradictoire.
            named.pop("content", None)

    return tuple(positional), named


def install(bot: commands.Bot | None = None, extension_name: str = "") -> None:
    del bot, extension_name
    from . import plain_response_policy

    current = plain_response_policy._force_rich_args
    if getattr(current, "_sentrix_content_argument_safe", False):
        return

    def force_rich_args_safe(*args, **kwargs):
        rendered_args, rendered_kwargs = current(*args, **kwargs)
        return _canonicalize(rendered_args, rendered_kwargs)

    force_rich_args_safe._sentrix_content_argument_safe = True
    force_rich_args_safe._sentrix_original = current
    plain_response_policy._force_rich_args = force_rich_args_safe
    logger.info("V20 : transport Discord protégé contre le double argument content.")


__all__ = ["install", "_canonicalize"]
