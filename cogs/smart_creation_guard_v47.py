from __future__ import annotations

import logging
import time
from collections import Counter, defaultdict
from types import MethodType

import discord
from discord.ext import commands

logger = logging.getLogger("bot.security.smart-creation-v47")

WINDOW_SECONDS = 30
RISKY_SCORE = 5
SEVERE_SCORE = 8


def _normalize_name(value: str) -> str:
    return " ".join(str(value or "").casefold().replace("_", " ").replace("-", " ").split())[:120]


def _role_risk(role: discord.Role) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []
    perms = role.permissions

    checks = (
        ("administrator", 10, "permission Administrateur"),
        ("manage_guild", 5, "Gérer le serveur"),
        ("manage_roles", 5, "Gérer les rôles"),
        ("manage_channels", 4, "Gérer les salons"),
        ("ban_members", 3, "Bannir des membres"),
        ("kick_members", 3, "Expulser des membres"),
        ("manage_webhooks", 3, "Gérer les webhooks"),
        ("mention_everyone", 2, "Mentionner @everyone"),
    )
    for attr, weight, label in checks:
        if bool(getattr(perms, attr, False)):
            score += weight
            reasons.append(label)

    # Un rôle normal, même créé dans une grosse configuration, ne doit pas compter comme nuke.
    return min(score, 20), reasons


def _channel_risk(channel: discord.abc.GuildChannel) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []

    try:
        overwrite = channel.overwrites_for(channel.guild.default_role)
    except Exception:
        overwrite = None

    if overwrite is not None:
        checks = (
            ("manage_channels", 6, "@everyone peut gérer les salons"),
            ("manage_roles", 6, "@everyone peut gérer les rôles"),
            ("manage_webhooks", 5, "@everyone peut gérer les webhooks"),
            ("mention_everyone", 3, "@everyone peut mentionner tout le monde"),
        )
        for attr, weight, label in checks:
            if getattr(overwrite, attr, None) is True:
                score += weight
                reasons.append(label)

    # Les noms seuls ne suffisent jamais à bannir : certains bots légitimes créent des
    # salons comme #raid-protection, #security, #admin, etc.
    return min(score, 20), reasons


async def _recent_destructive_events(bot: commands.Bot, guild_id: int, actor_id: int) -> int:
    """Contexte supplémentaire : vraies actions anti-nuke déjà observées récemment.

    Cette table est le compteur commun de l'anti-nuke existant. Les créations propres ne
    sont plus ajoutées dedans par ce correctif, donc un gros setup sain reste à zéro.
    """
    cutoff = int(time.time()) - WINDOW_SECONDS
    try:
        row = await bot.db.fetchone(
            "SELECT COUNT(*) AS n FROM antinuke_events "
            "WHERE guild_id = ? AND actor_id = ? AND created_at >= ?",
            (guild_id, actor_id, cutoff),
        )
        return int(row["n"] if row else 0)
    except Exception:
        return 0


def _resource_from_action(guild: discord.Guild, action: discord.AuditLogAction, target_id: int):
    if action == discord.AuditLogAction.role_create:
        return guild.get_role(target_id), "role"
    return guild.get_channel(target_id), "channel"


async def install(bot: commands.Bot) -> None:
    """Remplace uniquement la logique anti-nuke appliquée aux créations de ressources."""
    if getattr(bot, "_sentrix_smart_creation_guard_v47", False):
        return

    hardening = bot.get_cog("SecurityHardening")
    automod = bot.get_cog("Automod")
    if hardening is None or automod is None:
        return

    history: dict[tuple[int, int], list[dict]] = defaultdict(list)
    last_safe_log: dict[tuple[int, int], float] = {}
    last_trigger: dict[tuple[int, int], float] = {}

    async def smart_record_created_resource(
        self,
        guild: discord.Guild,
        action: discord.AuditLogAction,
        target_id: int,
        reason: str,
    ):
        automod_local, actor = await self._antinuke_actor(guild, action, target_id)
        if automod_local is None or actor is None:
            return

        resource, kind = _resource_from_action(guild, action, target_id)
        if resource is None:
            return

        if kind == "role":
            score, risk_reasons = _role_risk(resource)
        else:
            score, risk_reasons = _channel_risk(resource)

        now_ts = time.time()
        key = (guild.id, actor.id)
        events = history[key]
        events.append(
            {
                "at": now_ts,
                "id": int(target_id),
                "kind": kind,
                "name": _normalize_name(getattr(resource, "name", "")),
                "score": int(score),
                "reasons": list(risk_reasons),
            }
        )
        events[:] = [event for event in events if now_ts - event["at"] <= WINDOW_SECONDS]

        burst = len(events)
        risky = [event for event in events if event["score"] >= RISKY_SCORE]
        severe = [event for event in events if event["score"] >= SEVERE_SCORE]
        duplicate_counts = Counter(event["name"] for event in events if event["name"])
        max_duplicate = max(duplicate_counts.values(), default=0)
        destructive = await _recent_destructive_events(self.bot, guild.id, actor.id)

        # Important : le volume seul n'est PLUS une preuve de nuke.
        # Raid Protect, Ticket Tool, un bot de setup ou SentriX lui-même peuvent créer
        # beaucoup de salons/rôles sans aucune sanction si les ressources sont normales.
        trigger = False
        trigger_reasons: list[str] = []

        if destructive >= 1 and risky:
            trigger = True
            trigger_reasons.append("création dangereuse combinée à une action destructrice récente")
        if len(severe) >= 2:
            trigger = True
            trigger_reasons.append(f"{len(severe)} créations à risque critique")
        elif len(risky) >= 3:
            trigger = True
            trigger_reasons.append(f"{len(risky)} créations à permissions dangereuses")
        if burst >= 10 and max_duplicate >= 8:
            trigger = True
            trigger_reasons.append(f"spam de {max_duplicate} ressources portant le même nom")

        # Un seul rôle Administrateur créé n'entraîne donc pas de ban automatique.
        # Il est surveillé et ne devient bloquant qu'avec d'autres preuves.
        if not trigger:
            if burst >= 8 and now_ts - last_safe_log.get(key, 0) >= WINDOW_SECONDS:
                last_safe_log[key] = now_ts
                try:
                    await self._security_event(
                        guild.id,
                        "antinuke_creation_burst_safe",
                        actor_id=actor.id,
                        detail=(
                            f"{burst} créations analysées/{WINDOW_SECONDS}s; "
                            f"dangereuses={len(risky)}; critiques={len(severe)}; "
                            "aucune sanction: le volume seul n'est pas considéré comme un nuke"
                        ),
                    )
                except Exception:
                    pass
            return

        # Anti-doublon : une même rafale ne doit pas lancer plusieurs sanctions simultanées.
        if now_ts - last_trigger.get(key, 0) < WINDOW_SECONDS:
            return
        last_trigger[key] = now_ts

        detail_bits = []
        for event in risky[-4:]:
            why = ", ".join(event["reasons"]) or "comportement anormal"
            detail_bits.append(f"{event['kind']} {event['name']!r}: {why}")
        detail = "; ".join(detail_bits)
        final_reason = (
            "Anti-nuke intelligent : "
            + ", ".join(trigger_reasons)
            + (f" — {detail}" if detail else "")
        )

        try:
            await self._security_event(
                guild.id,
                "antinuke_smart_creation_trigger",
                actor_id=actor.id,
                detail=(
                    f"burst={burst}; risky={len(risky)}; severe={len(severe)}; "
                    f"destructive={destructive}; duplicate={max_duplicate}; {final_reason}"
                ),
            )
        except Exception:
            pass

        await automod_local.punish_nuker(guild, actor.id, final_reason)
        history[key] = []

    hardening._record_created_resource = MethodType(smart_record_created_resource, hardening)
    hardening._sentrix_smart_creation_guard_v47 = True

    # Le système Vérification + Honeypot V48 est une protection complémentaire :
    # il est installé dans la même pile sécurité mais reste opt-in par serveur via
    # +honeypot-setup. Aucune permission de salon n'est modifiée tant que cette commande
    # n'est pas exécutée par un propriétaire/admin.
    try:
        from .honeypot_verification_v48 import install as install_honeypot_verification_v48
        await install_honeypot_verification_v48(bot)
    except Exception:
        logger.exception("Impossible d'installer Vérification + Honeypot V48.")

    bot._sentrix_smart_creation_guard_v47 = True
    logger.info(
        "Anti-nuke V47 activé : créations de salons/rôles analysées par risque, volume seul autorisé."
    )
