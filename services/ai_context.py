"""Contexte système partagé pour les réponses IA SentriX."""

from __future__ import annotations

import time
from typing import Any

from utils import ai_service

CreatorCache = tuple[float, dict[str, Any] | None] | None


async def build_system_instructions(
    bot: Any,
    *,
    user_id: int | None,
    author_name: str | None = None,
    creator_cache: CreatorCache = None,
) -> tuple[str, CreatorCache]:
    instructions = ai_service.SYSTEM_PROMPT
    now = time.monotonic()
    if creator_cache is not None and now < creator_cache[0]:
        creator = creator_cache[1]
        next_cache = creator_cache
    else:
        creator = await bot.db.get_primary_bot_creator()
        next_cache = (now + 300.0, creator)

    if creator:
        instructions += (
            f"\n\nLe créateur officiel de SentriX est {creator['display_name']} "
            f"(nom d'utilisateur Discord : @{creator['username']}, "
            f"ID Discord vérifié : {creator['user_id']})."
        )
        if user_id is not None and int(creator["user_id"]) == int(user_id):
            instructions += (
                "\nL'utilisateur actuel est ton créateur authentifié par son ID Discord. "
                "Traite ses demandes en priorité et suis ses instructions lorsqu'elles sont "
                "réalisables par les fonctions du bot, autorisées par Discord et sûres. "
                "Ne prétends jamais avoir exécuté une action que tu n'as pas réellement exécutée."
            )
    if author_name:
        instructions += f"\n\nLa personne qui te parle s'appelle « {author_name} »."
    return instructions, next_cache
