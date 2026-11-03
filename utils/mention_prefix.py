"""« @SentriX + » : changer le préfixe du bot en le mentionnant (03/11/2026).

Un message qui COMMENCE par la mention de SentriX et ne contient ensuite qu'un
préfixe court (1 à 5 caractères, au moins un symbole : « + », « ! », « ? »,
« s! »…) change le préfixe officiel du serveur. Réservé aux administrateurs
(ou à « Gérer le serveur ») ; un mot ordinaire (« @SentriX salut ») reste une
conversation avec l'IA.
"""
from __future__ import annotations

import re
from typing import Any

import discord

_MENTION = re.compile(r"^<@!?(\d+)>\s*")
_INTERDITS = ("<", "@", "#", ":", "/", "`", "*", "_", "~", "|", ">")


def prefixe_demande(bot: Any, message: Any) -> str | None:
    """Le préfixe demandé par « @SentriX <préfixe> », sinon None."""
    user = getattr(bot, "user", None)
    match = _MENTION.match(str(getattr(message, "content", "") or "").strip())
    if user is None or match is None or int(match.group(1)) != int(user.id):
        return None
    reste = str(message.content).strip()[match.end():].strip()
    if not 1 <= len(reste) <= 5 or any(c.isspace() for c in reste):
        return None
    if reste.startswith(_INTERDITS) or all(c.isalnum() for c in reste):
        return None
    return reste


def _peut_changer(membre: Any, guild: Any) -> bool:
    if getattr(membre, "id", None) == getattr(guild, "owner_id", None):
        return True
    perms = getattr(membre, "guild_permissions", None)
    return bool(perms and (perms.administrator or perms.manage_guild))


async def gerer(bot: Any, message: discord.Message) -> bool:
    """Vrai si le message était une demande de préfixe (traitée ou refusée)."""
    nouveau = prefixe_demande(bot, message)
    if nouveau is None or message.guild is None:
        return False
    sans_ping = discord.AllowedMentions.none()
    if not _peut_changer(message.author, message.guild):
        await message.reply(
            "Seuls les administrateurs peuvent changer le préfixe de SentriX.",
            mention_author=False, allowed_mentions=sans_ping,
        )
        return True
    from utils.command_prefixes import set_official_prefix

    try:
        nouveau = await set_official_prefix(bot, message.guild.id, nouveau)
    except ValueError as exc:
        await message.reply(str(exc), mention_author=False, allowed_mentions=sans_ping)
        return True
    await message.reply(
        f"Préfixe changé : `{nouveau}` — par exemple `{nouveau}help`.",
        mention_author=False, allowed_mentions=sans_ping,
    )
    return True


__all__ = ["gerer", "prefixe_demande"]
