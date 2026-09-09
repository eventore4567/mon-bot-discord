"""ModerationService — Core V2, Phase 2 (docs/core-v2-plan.md).

Premier exemple concret de la règle « une fonctionnalité = un handler métier » :
+ban et /ban étaient déjà UN SEUL hybrid_command (donc déjà un seul callback),
mais ce callback mélangeait hiérarchie, notification, action Discord et
persistance directement dans le code d'adaptation Discord de cogs/moderation.py.
Cette fonction extrait ce pipeline pour qu'il soit testable sans jamais
instancier Discord, et corrige au passage un vrai trou trouvé en l'extrayant :
``bot.db.record_sanction()`` n'était protégé par aucun try/except — une
exception y remontait jusqu'au pipeline d'erreur alors que le bannissement
Discord avait déjà réellement réussi, contredisant directement la règle de la
demande initiale (section 17) : « Si Discord exécute le ban mais que le log
échoue, la sanction doit rester réussie. »

+kick suit le même pipeline (hiérarchie -> notification -> exécution Discord ->
persistance), seule l'action Discord change : les deux partagent maintenant
_run_sanction_pipeline() plutôt que de dupliquer la même séquence deux fois.

tempban, mute, unmute, warn, unban restent sur leur code existant dans
cogs/moderation.py, inchangé — migrés un par un dans des étapes suivantes,
chacun testé indépendamment.
"""
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import discord

from utils import checks

logger = logging.getLogger("services.moderation")


@dataclass
class SanctionOutcome:
    executed: bool
    hierarchy_error: str | None = None
    dm_sent: bool = False
    case_number: int | None = None
    persistence_error: str | None = None


async def persist_sanction(
    bot: Any,
    *,
    guild_id: int,
    target_id: int,
    actor_id: int,
    action: str,
    reason: str,
    duration_seconds: int | None = None,
) -> tuple[int | None, str | None]:
    """Enregistre le dossier de sanction sans jamais faire échouer l'appelant.

    La sanction Discord est, au moment où cette fonction est appelée,
    TOUJOURS déjà appliquée — une erreur de persistance ne doit donc jamais
    se propager comme une erreur de commande. Retourne (numéro_de_dossier,
    None) en cas de succès, ou (None, message_erreur) en cas d'échec.
    """
    try:
        case_number = await bot.db.record_sanction(
            guild_id, target_id, actor_id, action, reason, duration_seconds
        )
        return case_number, None
    except Exception as exc:
        logger.exception(
            "Persistance de la sanction '%s' impossible (guild=%s cible=%s) — "
            "la sanction Discord reste appliquée.",
            action, guild_id, target_id,
        )
        return None, str(exc)


async def _run_sanction_pipeline(
    bot: Any,
    *,
    guild: discord.Guild,
    actor: discord.Member,
    target: discord.Member,
    reason: str,
    dm_text: str | None,
    action: str,
    execute: Callable[[], Awaitable[None]],
) -> SanctionOutcome:
    """Pipeline partagé par les sanctions "un membre, une raison" : hiérarchie
    -> notification -> exécution Discord (fournie par l'appelant via
    ``execute``) -> persistance. ``ban()`` et ``kick()`` ne diffèrent que par
    cette étape d'exécution et par le nom de l'action persistée.

    Le MP part AVANT l'exécution Discord — délivrabilité : un membre banni ou
    expulsé n'est en général plus joignable par MP une fois l'action
    appliquée. C'est le choix déjà fait par le code existant, conservé ici à
    l'identique, pas un écart par rapport à « validate -> permission ->
    hierarchy -> execute -> persist -> log -> DM » de la demande initiale.

    L'autorisation d'accès à la commande (utils/access_matrix.py) et la
    permission Discord du bot (@checks.action_validation) sont déjà vérifiées
    avant l'appel : cette fonction ne refait que ce qu'il reste à valider —
    la hiérarchie entre l'auteur/le bot et la cible.
    """
    hierarchy_error = checks.check_hierarchy(actor, target) or checks.check_bot_hierarchy(guild, target)
    if hierarchy_error:
        return SanctionOutcome(executed=False, hierarchy_error=hierarchy_error)

    dm_sent = False
    if dm_text:
        try:
            await target.send(dm_text, allowed_mentions=discord.AllowedMentions.none())
            dm_sent = True
        except discord.HTTPException:
            dm_sent = False

    await execute()

    case_number, persistence_error = await persist_sanction(
        bot,
        guild_id=guild.id,
        target_id=target.id,
        actor_id=actor.id,
        action=action,
        reason=reason,
    )

    return SanctionOutcome(
        executed=True,
        dm_sent=dm_sent,
        case_number=case_number,
        persistence_error=persistence_error,
    )


async def ban(
    bot: Any,
    *,
    guild: discord.Guild,
    actor: discord.Member,
    target: discord.Member,
    reason: str,
    dm_text: str | None = None,
) -> SanctionOutcome:
    """Pipeline complet du bannissement — voir _run_sanction_pipeline()."""
    return await _run_sanction_pipeline(
        bot,
        guild=guild,
        actor=actor,
        target=target,
        reason=reason,
        dm_text=dm_text,
        action="ban",
        execute=lambda: guild.ban(target, reason=f"{actor} : {reason}", delete_message_seconds=0),
    )


async def kick(
    bot: Any,
    *,
    guild: discord.Guild,
    actor: discord.Member,
    target: discord.Member,
    reason: str,
    dm_text: str | None = None,
) -> SanctionOutcome:
    """Pipeline complet de l'expulsion — voir _run_sanction_pipeline().

    Contrairement à ban(), aucun paramètre de suppression de messages : Discord
    n'en propose pas pour un kick, ce n'est pas un oubli.
    """
    return await _run_sanction_pipeline(
        bot,
        guild=guild,
        actor=actor,
        target=target,
        reason=reason,
        dm_text=dm_text,
        action="kick",
        execute=lambda: guild.kick(target, reason=f"{actor} : {reason}"),
    )
