"""ProfileService — Core V2, Phase 4 (docs/core-v2-plan.md).

+profile (cogs/profile_oxyde_runtime.py::build_page — le corps réellement
exécuté ; cogs/levels.py::profile ne s'exécute jamais, voir
docs/core-v2-audit-technical-debt.md #15) assemblait ses données et calculait
ses badges en appelant directement un module cog voisin
(cogs/community_v31.py::_profile_snapshot) — de la logique métier sans aucun
type Discord au-delà de bot/guild/member (déjà "service-shaped"), mais vivant
dans un cog plutôt que dans services/, sans jamais avoir été testée
directement.

Cette extraction ne change AUCUN comportement : build_snapshot() délègue tel
quel à community_v31._profile_snapshot() (l'agrégation elle-même n'est pas
dupliquée ici, seulement exposée comme point d'entrée stable et testable) ;
compute_badges() est cogs/profile_oxyde_runtime.py::_badges déplacé à
l'identique, maintenant testable sans jamais construire un cog ni Discord.
"""
from __future__ import annotations

from typing import Any

import discord

from cogs import community_v31


async def build_snapshot(bot: Any, guild: discord.Guild, member: discord.Member) -> dict[str, Any]:
    """Agrège statistiques, progression, classements et bio pour /profile.

    Délègue à community_v31._profile_snapshot() : ce module reste le seul
    endroit qui sait assembler stats_service + community_v3 + la bio + les
    classements ; cette fonction n'en est qu'un point d'entrée stable côté
    services/, pour que cogs/profile_oxyde_runtime.py n'ait plus besoin de
    connaître ce détail d'implémentation.
    """
    return await community_v31._profile_snapshot(bot, guild, member)


def compute_badges(member: discord.Member, stats: dict, progression: dict) -> list[str]:
    """Badges calculés uniquement à partir des vraies données du membre.

    Logique identique à l'ancienne cogs/profile_oxyde_runtime.py::_badges."""
    badges: list[str] = []
    if int(stats.get("message_count", 0)) >= 1000:
        badges.append("Actif")
    if int(stats.get("wallet", 0)) + int(stats.get("bank", 0)) >= 10_000:
        badges.append("Économiste")
    if int(progression.get("season_xp", 0)) > 0:
        badges.append("Saisonnier")
    if member.guild_permissions.manage_messages or member.guild_permissions.moderate_members:
        badges.append("Staff")
    account_days = max(0, (discord.utils.utcnow() - member.created_at).days)
    if account_days >= 365:
        badges.append("Vétéran")
    return badges[:5]
