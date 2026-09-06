"""SentriX V77 — fiabilise l'attribution des invitations consommées.

Discord peut supprimer une invitation à usage limité exactement au moment où elle est
consommée. Dans ce cas ``guild.invites()`` ne contient déjà plus le code quand
``on_member_join`` s'exécute et l'ancien tracker affichait « invitant inconnu ».

V77 garde brièvement les invitations supprimées, retente la lecture Discord pour absorber
les délais de propagation et n'attribue un tombstone que lorsqu'il existe un candidat
unique et plausible. En cas d'ambiguïté, SentriX préfère rester inconnu plutôt que
d'inventer un invitant.
"""
from __future__ import annotations

import asyncio
import logging
import time
from types import MethodType

import discord
from discord.ext import commands

logger = logging.getLogger("bot.invites-v77")

_TOMBSTONE_TTL = 20.0
_RETRY_DELAYS = (0.0, 0.35, 0.70)


def _uses(invite: discord.Invite) -> int:
    try:
        return max(0, int(invite.uses or 0))
    except (TypeError, ValueError):
        return 0


def _max_uses(invite: discord.Invite) -> int:
    try:
        return max(0, int(invite.max_uses or 0))
    except (TypeError, ValueError):
        return 0


def _plausibly_consumed(invite: discord.Invite) -> bool:
    maximum = _max_uses(invite)
    if maximum <= 0:
        return False
    # Une invitation à usage unique est le cas qui disparaît le plus souvent avant
    # on_member_join. Selon l'ordre des événements Discord, ``uses`` peut encore valoir 0.
    if maximum == 1:
        return True
    return _uses(invite) >= maximum


def install(bot: commands.Bot) -> bool:
    if getattr(bot, "_sentrix_invite_detection_v77", False):
        return True

    cog = bot.get_cog("Invites")
    if cog is None or not hasattr(cog, "find_used_invite"):
        logger.warning("V77 invitations non installé : cog Invites absent.")
        return False

    tombstones: dict[int, list[tuple[float, discord.Invite]]] = {}

    def prune(guild_id: int) -> list[tuple[float, discord.Invite]]:
        now = time.monotonic()
        fresh = [item for item in tombstones.get(guild_id, []) if now - item[0] <= _TOMBSTONE_TTL]
        if fresh:
            tombstones[guild_id] = fresh
        else:
            tombstones.pop(guild_id, None)
        return fresh

    async def remember_deleted(invite: discord.Invite) -> None:
        guild = getattr(invite, "guild", None)
        if guild is None or not getattr(invite, "code", None):
            return
        if getattr(invite, "inviter", None) is None:
            return
        bucket = prune(int(guild.id))
        bucket.append((time.monotonic(), invite))
        tombstones[int(guild.id)] = bucket[-12:]

    async def find_used_invite_v77(self, guild: discord.Guild) -> discord.Invite | None:
        guild_id = int(guild.id)
        cached = dict(self.invite_cache.get(guild_id, {}) or {})
        current: list[discord.Invite] = []

        # Deux petites relectures supplémentaires absorbent le cas où l'événement membre
        # arrive avant que le compteur d'utilisation soit visible dans l'API Discord.
        for delay in _RETRY_DELAYS:
            if delay:
                await asyncio.sleep(delay)
            try:
                current = list(await guild.invites())
            except discord.Forbidden:
                return None
            except discord.HTTPException:
                if delay == _RETRY_DELAYS[-1]:
                    return None
                continue

            used = None
            for invite in current:
                previous = cached.get(invite.code, _uses(invite))
                if _uses(invite) > int(previous or 0):
                    used = invite
                    break
            if used is not None:
                self.invite_cache[guild_id] = {invite.code: _uses(invite) for invite in current}
                tombstones[guild_id] = [
                    item for item in prune(guild_id) if item[1].code != used.code
                ]
                return used

        self.invite_cache[guild_id] = {invite.code: _uses(invite) for invite in current}

        # Invitation supprimée au moment de sa consommation. On ne choisit jamais entre
        # plusieurs suppressions proches : un candidat unique est obligatoire.
        candidates = [
            invite
            for _stamp, invite in prune(guild_id)
            if getattr(invite, "inviter", None) is not None and _plausibly_consumed(invite)
        ]
        unique_by_code = {invite.code: invite for invite in candidates if getattr(invite, "code", None)}
        if len(unique_by_code) == 1:
            used = next(iter(unique_by_code.values()))
            tombstones[guild_id] = [
                item for item in prune(guild_id) if item[1].code != used.code
            ]
            logger.info(
                "V77 : invitation consommée récupérée après suppression guild=%s code=%s inviter=%s.",
                guild_id,
                used.code,
                getattr(getattr(used, "inviter", None), "id", None),
            )
            return used

        # Vanity : comportement canonique conservé, sans inventer d'invitant.
        try:
            return await self._invitation_vanity(guild)
        except Exception:
            logger.debug("V77 : détection vanity impossible guild=%s", guild_id, exc_info=True)
            return None

    find_used_invite_v77._sentrix_invite_detection_v77 = True
    find_used_invite_v77._sentrix_original = getattr(cog.find_used_invite, "__func__", cog.find_used_invite)
    cog.find_used_invite = MethodType(find_used_invite_v77, cog)
    bot.add_listener(remember_deleted, "on_invite_delete")
    bot._sentrix_invite_detection_v77 = True
    bot._sentrix_invite_tombstones_v77 = tombstones
    logger.info("V77 invitations actif : retry Discord + récupération sûre des invitations consommées.")
    return True


__all__ = ["install", "_plausibly_consumed"]
