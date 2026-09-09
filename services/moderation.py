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

+mute a une forme différente (durée à valider, MP envoyé APRÈS l'exécution —
un membre muet reste sur le serveur, contrairement à ban/kick, donc l'ordre
DM-avant-exécution n'est pas requis pour la délivrabilité, et le code existant
ne le fait pas) : reste une fonction séparée plutôt que de forcer
_run_sanction_pipeline à couvrir une forme qu'elle ne représente pas.

+tempban a une deuxième forme bespoke : en plus du dossier de sanction
habituel, il doit programmer sa propre levée automatique (table
tempactions, lue par cogs/moderation.py::check_tempactions) — une DEUXIÈME
écriture, indépendante de persist_sanction() et du bannissement Discord déjà
appliqué, protégée séparément par persist_tempaction() pour la même raison
(section 17 : un échec d'écriture ne doit jamais annuler une sanction Discord
déjà exécutée).

warn, unban restent sur leur code existant dans cogs/moderation.py, inchangé
— migrés dans des étapes suivantes, chacun testé indépendamment.
"""
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import discord

from database.db import now
from utils import checks, helpers

logger = logging.getLogger("services.moderation")

MAX_MUTE_SECONDS = 2419200  # 28 jours — limite native du timeout Discord


@dataclass
class SanctionOutcome:
    executed: bool
    hierarchy_error: str | None = None
    validation_error: str | None = None
    dm_sent: bool = False
    case_number: int | None = None
    persistence_error: str | None = None
    tempaction_error: str | None = None
    duration_seconds: int | None = None

    @property
    def rejection_reason(self) -> str | None:
        """Motif de refus, quelle que soit sa nature — hiérarchie ou validation
        métier (ex: durée invalide). None si la sanction a été exécutée."""
        return self.hierarchy_error or self.validation_error


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


async def persist_tempaction(
    bot: Any,
    *,
    guild_id: int,
    user_id: int,
    action: str,
    expires_at: int,
) -> str | None:
    """Programme la levée automatique d'une sanction temporaire sans jamais
    faire échouer l'appelant — même rationale que persist_sanction() : au
    moment de l'appel, le bannissement Discord est déjà appliqué. Un échec ici
    prive seulement la sanction de sa levée automatique (elle reste levable à
    la main) ; il ne doit jamais remettre en cause une sanction déjà
    exécutée. Retourne None en cas de succès, ou le message d'erreur sinon.
    """
    try:
        await bot.db.execute(
            "INSERT INTO tempactions (guild_id, user_id, action, expires_at) VALUES (?, ?, ?, ?)",
            (guild_id, user_id, action, expires_at),
        )
        return None
    except Exception as exc:
        logger.exception(
            "Programmation de la levée automatique impossible (guild=%s cible=%s action=%s) — "
            "la sanction Discord reste appliquée ; la levée automatique est indisponible.",
            guild_id, user_id, action,
        )
        return str(exc)


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
    dm_after: bool = False,
) -> SanctionOutcome:
    """Pipeline partagé par les sanctions "un membre, une raison" : hiérarchie
    -> notification -> exécution Discord (fournie par l'appelant via
    ``execute``) -> persistance. ``ban()``, ``kick()`` et ``unmute()`` ne
    diffèrent que par cette étape d'exécution, le nom de l'action persistée,
    et l'ordre notification/exécution.

    Par défaut, le MP part AVANT l'exécution Discord — délivrabilité : un
    membre banni ou expulsé n'est en général plus joignable par MP une fois
    l'action appliquée (ban/kick). ``dm_after=True`` inverse l'ordre pour les
    sanctions qui laissent le membre sur le serveur (unmute) : c'est le choix
    déjà fait par le code existant pour ce cas précis, conservé ici à
    l'identique. Ni l'un ni l'autre n'est un écart par rapport à « validate ->
    permission -> hierarchy -> execute -> persist -> log -> DM » de la demande
    initiale — cette dernière ne précisait pas l'ordre relatif exécution/MP
    pour un cas où la délivrabilité n'est pas en jeu.

    L'autorisation d'accès à la commande (utils/access_matrix.py) et la
    permission Discord du bot (@checks.action_validation) sont déjà vérifiées
    avant l'appel : cette fonction ne refait que ce qu'il reste à valider —
    la hiérarchie entre l'auteur/le bot et la cible.
    """
    hierarchy_error = checks.check_hierarchy(actor, target) or checks.check_bot_hierarchy(guild, target)
    if hierarchy_error:
        return SanctionOutcome(executed=False, hierarchy_error=hierarchy_error)

    async def _send_dm() -> bool:
        if not dm_text:
            return False
        try:
            await target.send(dm_text, allowed_mentions=discord.AllowedMentions.none())
            return True
        except discord.HTTPException:
            return False

    dm_sent = False
    if not dm_after:
        dm_sent = await _send_dm()

    await execute()

    if dm_after:
        dm_sent = await _send_dm()

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


async def unmute(
    bot: Any,
    *,
    guild: discord.Guild,
    actor: discord.Member,
    target: discord.Member,
    reason: str,
    dm_text: str | None = None,
) -> SanctionOutcome:
    """Pipeline complet du retrait de mute — voir _run_sanction_pipeline().

    ``dm_after=True`` : contrairement à ban()/kick(), le MP part APRÈS
    l'exécution — un membre qu'on démute reste sur le serveur, la
    délivrabilité n'est pas en jeu, et c'est l'ordre du code existant.
    """
    return await _run_sanction_pipeline(
        bot,
        guild=guild,
        actor=actor,
        target=target,
        reason=reason,
        dm_text=dm_text,
        action="unmute",
        execute=lambda: target.timeout(None, reason=f"{actor} : {reason}"),
        dm_after=True,
    )


async def mute(
    bot: Any,
    *,
    guild: discord.Guild,
    actor: discord.Member,
    target: discord.Member,
    reason: str,
    duree: str,
    render_dm_text: Callable[[int], str | None] | None = None,
) -> SanctionOutcome:
    """Pipeline complet du mute (timeout Discord natif) : hiérarchie -> durée ->
    exécution Discord -> notification -> persistance.

    Forme volontairement différente de ban()/kick() : le MP part APRÈS le
    timeout (un membre muet reste sur le serveur, joignable dans tous les cas
    — pas la même contrainte de délivrabilité que ban/kick), et il y a une
    étape de validation supplémentaire (durée) avant toute exécution. C'est le
    comportement du code existant, conservé à l'identique.

    ``render_dm_text`` reçoit la durée VALIDÉE en secondes et retourne le texte
    du MP déjà substitué, ou None si aucun gabarit n'est configuré — le texte
    ne peut être construit qu'une fois la durée connue (contrairement à
    ban()/kick(), où il l'est déjà avant l'appel), donc cette étape de rendu
    est confiée à l'appelant plutôt que dupliquée ici.
    """
    hierarchy_error = checks.check_hierarchy(actor, target) or checks.check_bot_hierarchy(guild, target)
    if hierarchy_error:
        return SanctionOutcome(executed=False, hierarchy_error=hierarchy_error)

    seconds = helpers.parse_duration(duree)
    if seconds is None or seconds > MAX_MUTE_SECONDS:
        return SanctionOutcome(
            executed=False,
            validation_error="Durée invalide (maximum 28 jours). Exemple : `10m`, `1h`, `1j`.",
        )

    until = discord.utils.utcnow() + timedelta(seconds=seconds)
    await target.timeout(until, reason=f"{actor} : {reason}")

    dm_sent = False
    dm_text = render_dm_text(seconds) if render_dm_text else None
    if dm_text:
        try:
            await target.send(dm_text, allowed_mentions=discord.AllowedMentions.none())
            dm_sent = True
        except discord.HTTPException:
            dm_sent = False

    case_number, persistence_error = await persist_sanction(
        bot,
        guild_id=guild.id,
        target_id=target.id,
        actor_id=actor.id,
        action="mute",
        reason=reason,
        duration_seconds=seconds,
    )

    return SanctionOutcome(
        executed=True,
        dm_sent=dm_sent,
        case_number=case_number,
        persistence_error=persistence_error,
        duration_seconds=seconds,
    )


async def tempban(
    bot: Any,
    *,
    guild: discord.Guild,
    actor: discord.Member,
    target: discord.Member,
    reason: str,
    duree: str,
    render_dm_text: Callable[[int], str | None] | None = None,
) -> SanctionOutcome:
    """Pipeline complet du bannissement temporaire : hiérarchie -> durée ->
    notification -> exécution Discord -> DEUX persistances indépendantes.

    Forme bespoke (comme mute()) plutôt que _run_sanction_pipeline() : en plus
    du dossier de sanction habituel, +tempban doit aussi programmer sa levée
    automatique (table tempactions). Le MP part AVANT l'exécution, comme
    ban()/kick() — un membre banni, même temporairement, n'est en général plus
    joignable par MP une fois le bannissement appliqué — c'est l'ordre du code
    existant, conservé à l'identique. Aucune limite haute sur la durée
    (contrairement à mute()) : ce n'est pas un timeout natif Discord borné à
    28 jours, juste un bannissement classique dont la levée est reprogrammée
    par check_tempactions ; le code existant n'en imposait pas non plus.
    """
    hierarchy_error = checks.check_hierarchy(actor, target) or checks.check_bot_hierarchy(guild, target)
    if hierarchy_error:
        return SanctionOutcome(executed=False, hierarchy_error=hierarchy_error)

    seconds = helpers.parse_duration(duree)
    if seconds is None:
        return SanctionOutcome(
            executed=False,
            validation_error="Durée invalide. Exemples valides : `30m`, `2h`, `1j`.",
        )

    dm_sent = False
    dm_text = render_dm_text(seconds) if render_dm_text else None
    if dm_text:
        try:
            await target.send(dm_text, allowed_mentions=discord.AllowedMentions.none())
            dm_sent = True
        except discord.HTTPException:
            dm_sent = False

    await guild.ban(target, reason=f"{actor} (temporaire {duree}) : {reason}", delete_message_seconds=0)

    tempaction_error = await persist_tempaction(
        bot, guild_id=guild.id, user_id=target.id, action="ban", expires_at=now() + seconds,
    )
    case_number, persistence_error = await persist_sanction(
        bot,
        guild_id=guild.id,
        target_id=target.id,
        actor_id=actor.id,
        action="tempban",
        reason=reason,
        duration_seconds=seconds,
    )

    return SanctionOutcome(
        executed=True,
        dm_sent=dm_sent,
        case_number=case_number,
        persistence_error=persistence_error,
        tempaction_error=tempaction_error,
        duration_seconds=seconds,
    )
