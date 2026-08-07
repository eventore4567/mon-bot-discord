"""Évite les réponses Discord liées à un message qui peut ensuite être supprimé.

Les commandes qui utilisent ctx.reply restent visuellement identiques, mais SentriX envoie
un message normal dans le salon. Ainsi Discord n'affiche plus « Le message original a été
supprimé » si le message de commande est effacé ensuite.
"""
from __future__ import annotations

from discord.ext import commands

_INSTALLED = False


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    # À ce stade Context.send est déjà enveloppé par le moteur premium SentriX. On le
    # réutilise volontairement pour conserver exactement le même style, mais sans créer
    # de MessageReference vers le message de commande.
    send = commands.Context.send

    async def reply_without_reference(self: commands.Context, *args, **kwargs):
        kwargs.pop("mention_author", None)
        kwargs.pop("fail_if_not_exists", None)
        kwargs.pop("reference", None)
        return await send(self, *args, **kwargs)

    commands.Context.reply = reply_without_reference
