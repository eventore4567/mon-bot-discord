"""Correctifs de stabilité transversaux installés sans dupliquer les cogs principaux.

Cette couche cible uniquement des courses/échecs silencieux observables à l'exécution :
- notifications sociales : ne jamais marquer une publication comme traitée si l'envoi
  Discord a échoué, afin qu'elle soit retentée au passage suivant ;
- invitations : sérialiser la comparaison du cache par serveur pour éviter que deux
  arrivées quasi simultanées lisent le même ancien compteur ;
- mini-jeux : sérialiser l'attribution des récompenses par utilisateur afin que deux jeux
  différents gagnés au même instant ne puissent pas dépasser la limite journalière ;
- Enterprise Suite : installation idempotente dans la même chaîne de runtime, sans ajouter
  de commandes publiques ni modifier l'ordre du verrou final sans emoji ;
- Excellence Runtime : vitesse, anti-crash, AutoMod progressif, économie atomique,
  mini-jeux, tickets, notifications, diagnostics et anti-abus, sans dashboard.

Les patches sont idempotents et ne modifient ni les anciennes commandes publiques ni leur
comportement fonctionnel attendu.
"""
from __future__ import annotations

import asyncio
import logging

import discord

logger = logging.getLogger("bot.stability-runtime")

_NOTIFICATION_PATCHED = False
_INVITE_PATCHED = False
_GAME_REWARD_PATCHED = False


def _install_notifications_retry(bot) -> None:
    global _NOTIFICATION_PATCHED
    if _NOTIFICATION_PATCHED:
        return

    cog = bot.get_cog("Notifications")
    if cog is None:
        return

    cls = type(cog)
    current = cls._check_subscription
    if getattr(current, "_sentrix_retry_safe", False):
        _NOTIFICATION_PATCHED = True
        return

    from . import notifications as notifications_mod

    async def check_subscription_retry_safe(self, row):
        guild = self.bot.get_guild(row["guild_id"])
        if guild is None:
            return

        channel = guild.get_channel(row["discord_channel_id"])
        role = guild.get_role(row["role_id"])
        if channel is None or role is None:
            await self.bot.db.execute(
                "UPDATE social_notifications SET enabled = 0 WHERE id = ?",
                (row["id"],),
            )
            return

        try:
            item = await notifications_mod._extract_latest(row["source_url"])
        except Exception:
            logger.warning(
                "Lecture impossible de l'abonnement social %s",
                row["id"],
                exc_info=True,
            )
            return
        if not item:
            return

        item_id = str(item.get("id") or "")
        if not item_id:
            return

        if not row["last_item_id"]:
            await self._update_last_item(row["id"], item_id, row["source_url"])
            return
        if item_id == str(row["last_item_id"]):
            return

        platform = row["platform"]
        link = notifications_mod._item_url(platform, row["source_url"], item)
        title = (item.get("title") or f"Nouvelle publication sur {platform}")[:256]
        description = row["custom_text"] or "Une nouvelle publication vient d'être mise en ligne."
        notification = discord.Embed(
            title=title,
            description=description,
            color=notifications_mod._platform_details(row["source_url"])[1],
        )
        notification.add_field(
            name="Voir la publication",
            value=f"[Ouvrir sur {platform}]({link})",
            inline=False,
        )
        notification.set_footer(text=f"Notification automatique SentriX • {platform}")
        image_url = row["image_url"] or item.get("thumbnail")
        if image_url and notifications_mod._valid_https_url(image_url):
            notification.set_image(url=image_url)

        try:
            await channel.send(
                content=role.mention,
                embed=notification,
                allowed_mentions=discord.AllowedMentions(
                    everyone=False,
                    users=False,
                    roles=[role],
                    replied_user=False,
                ),
            )
        except discord.HTTPException:
            logger.warning(
                "Envoi impossible pour l'abonnement social %s — la publication sera retentée.",
                row["id"],
                exc_info=True,
            )
            return

        await self._update_last_item(row["id"], item_id, link)

    check_subscription_retry_safe._sentrix_retry_safe = True
    cls._check_subscription = check_subscription_retry_safe
    _NOTIFICATION_PATCHED = True
    logger.info("Notifications sociales : reprise automatique après échec d'envoi activée.")


def _install_invite_serialization(bot) -> None:
    global _INVITE_PATCHED
    if _INVITE_PATCHED:
        return

    cog = bot.get_cog("Invites")
    if cog is None:
        return

    cls = type(cog)
    original = cls.find_used_invite
    if getattr(original, "_sentrix_serialized", False):
        _INVITE_PATCHED = True
        return

    async def find_used_invite_serialized(self, guild: discord.Guild):
        locks = getattr(self, "_sentrix_invite_locks", None)
        if locks is None:
            locks = {}
            self._sentrix_invite_locks = locks
        lock = locks.get(guild.id)
        if lock is None:
            lock = asyncio.Lock()
            locks[guild.id] = lock
        async with lock:
            return await original(self, guild)

    find_used_invite_serialized._sentrix_serialized = True
    cls.find_used_invite = find_used_invite_serialized
    _INVITE_PATCHED = True
    logger.info("Invitations : comparaison du cache sérialisée par serveur.")


def _install_atomic_game_daily_limit(bot) -> None:
    global _GAME_REWARD_PATCHED
    if _GAME_REWARD_PATCHED:
        return

    from utils import game_rewards

    original = game_rewards.reward_game_winner
    if getattr(original, "_sentrix_daily_limit_atomic", False):
        _GAME_REWARD_PATCHED = True
        return

    reward_locks: dict[tuple[int, int], asyncio.Lock] = {}

    async def reward_game_winner_atomic(
        runtime_bot,
        guild_id: int,
        user_id: int,
        game_name: str,
        base_amount: int,
        session_id: str,
        result: str = "win",
        metadata: dict | None = None,
    ):
        key = (int(guild_id), int(user_id))
        lock = reward_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            reward_locks[key] = lock

        async with lock:
            if result == "win":
                settings = await game_rewards.get_settings(runtime_bot, guild_id)
                try:
                    daily_limit = int(settings.get("daily_limit", 0) or 0)
                except (TypeError, ValueError):
                    daily_limit = 0
                if daily_limit > 0:
                    played = await runtime_bot.db.count_game_rewards_today(guild_id, user_id)
                    if played >= daily_limit:
                        return game_rewards.GameReward(
                            success=False,
                            game_name=game_name,
                            session_id=session_id,
                            guild_id=guild_id,
                            user_id=user_id,
                            amount=0,
                            result=result,
                            reason="daily_limit",
                            metadata=metadata or {},
                        )

            return await original(
                runtime_bot,
                guild_id,
                user_id,
                game_name,
                base_amount,
                session_id,
                result=result,
                metadata=metadata,
            )

    reward_game_winner_atomic._sentrix_daily_limit_atomic = True
    game_rewards.reward_game_winner = reward_game_winner_atomic
    _GAME_REWARD_PATCHED = True
    logger.info("Mini-jeux : limite quotidienne sérialisée par joueur.")


async def install(bot, extension_name: str) -> None:
    """Appelé après chaque extension chargée ; les briques sont toutes idempotentes."""
    name = str(extension_name or "")
    if name == "cogs.notifications" or name.endswith(".notifications"):
        _install_notifications_retry(bot)
    elif name == "cogs.invites" or name.endswith(".invites"):
        _install_invite_serialization(bot)
    elif name in {"cogs.minigames", "cogs.economy"} or name.endswith((".minigames", ".economy")):
        _install_atomic_game_daily_limit(bot)

    # Cette installation est volontairement appelée après chaque extension : le wrapper
    # enterprise_runtime retourne immédiatement dès que le Cog existe. Cela garantit que
    # les audits et le démarrage Railway obtiennent la suite Enterprise sans modifier la
    # liste historique EXTENSIONS ni créer de nouvelles commandes publiques.
    from .enterprise_runtime import install as install_enterprise_runtime
    await install_enterprise_runtime(bot)

    # Même principe pour le runtime d'excellence : aucune commande publique nouvelle,
    # aucune route web. Les patches deviennent actifs seulement lorsque leur cog cible
    # vient d'être chargé, ce qui évite les dépendances d'ordre fragiles.
    from .bot_excellence_runtime import install as install_bot_excellence_runtime
    await install_bot_excellence_runtime(bot, name)
