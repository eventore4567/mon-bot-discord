"""V2 de +reset-logs-all : reprise ciblée, idempotence et protection contre les courses.

Cette couche remplace uniquement la commande propriétaire. Le Cog historique reste chargé
pour les notifications de nouveau serveur et le bouton d'assistance.
"""
from __future__ import annotations

import asyncio
import logging
import time

import discord
from discord.ext import commands

from utils import checks, embeds, log_service
from utils import sentrix_panels as panels
from . import owner_log_rebuild as v1

logger = logging.getLogger("bot.owner-log-rebuild-v2")

_LOCAL_LOCK_ATTR = "_sentrix_reset_logs_all_v2_lock"
_SETTLE_SECONDS = 0.8


def _route_channel_ids(channels_by_type: dict[str, discord.TextChannel]) -> dict[str, int]:
    return {key: int(channel.id) for key, channel in channels_by_type.items()}


async def _current_route_ids(bot, guild_id: int) -> dict[str, int | None]:
    result: dict[str, int | None] = {}
    for log_type, _column, _name, _topic in v1.LOG_ROUTES:
        try:
            setting = await log_service.get_log_setting(bot, guild_id, log_type)
            result[log_type] = int(setting.get("channel_id") or 0) or None
        except Exception:
            result[log_type] = None
    return result


async def _routes_owned(bot, guild_id: int, channels_by_type: dict[str, discord.TextChannel]) -> bool:
    expected = _route_channel_ids(channels_by_type)
    current = await _current_route_ids(bot, guild_id)
    return all(current.get(log_type) == channel_id for log_type, channel_id in expected.items())


async def _cleanup_created(
    channels: list[discord.TextChannel],
    categories: list[discord.CategoryChannel],
    *,
    reason: str,
) -> None:
    for channel in reversed(channels):
        try:
            await channel.delete(reason=reason)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass
    for category in reversed(categories):
        try:
            if not category.channels:
                await category.delete(reason=reason)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass


async def _is_healthy(bot, guild: discord.Guild) -> bool:
    """Validation sans message de test : permet de ne pas reconstruire les 11 serveurs sains."""
    for log_type, _column, _name, _topic in v1.LOG_ROUTES:
        try:
            setting = await log_service.get_log_setting(bot, guild.id, log_type)
        except Exception:
            return False
        if not setting.get("enabled") or not setting.get("channel_id"):
            return False
        valid, _reason = log_service.validate_channel(guild, setting.get("channel_id"))
        if not valid:
            return False
    return True


def _bot_overwrites(guild: discord.Guild, conf) -> dict:
    me = guild.me
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        me: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            embed_links=True,
            attach_files=True,
            read_message_history=True,
            manage_channels=True,
        ),
    }
    mod_role_id = v1._conf_value(conf, "mod_role")
    if mod_role_id:
        role = guild.get_role(int(mod_role_id))
        if role is not None:
            overwrites[role] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
            )
    return overwrites


async def _new_category(
    guild: discord.Guild,
    overwrites: dict,
    requester: discord.abc.User,
) -> discord.CategoryChannel:
    return await guild.create_category(
        v1.LOG_CATEGORY_NAME,
        overwrites=overwrites,
        reason=f"Reconstruction logs SentriX V2 par {requester} ({requester.id})",
    )


async def _create_channel_resilient(
    guild: discord.Guild,
    *,
    channel_name: str,
    topic: str,
    category: discord.CategoryChannel | None,
    overwrites: dict,
    requester: discord.abc.User,
) -> tuple[discord.TextChannel, discord.CategoryChannel | None, list[discord.CategoryChannel], bool]:
    """Crée un salon et survit à une catégorie supprimée entre deux appels Discord."""
    extra_categories: list[discord.CategoryChannel] = []
    fallback_root = False

    for attempt in range(3):
        try:
            channel = await guild.create_text_channel(
                channel_name,
                category=category,
                overwrites=overwrites,
                topic=f"SentriX logs • {topic}",
                reason="Architecture officielle des logs SentriX V2",
            )
            return channel, category, extra_categories, fallback_root
        except discord.HTTPException as exc:
            text = str(exc).casefold()
            category_gone = (
                getattr(exc, "code", None) == 50035
                and ("parent_id" in text or "category does not exist" in text)
            )
            if not category_gone:
                raise

            logger.warning(
                "Catégorie de logs disparue pendant création guild=%s salon=%s tentative=%s",
                guild.id,
                channel_name,
                attempt + 1,
            )
            if attempt == 0:
                category = await _new_category(guild, overwrites, requester)
                extra_categories.append(category)
                continue

            category = None
            fallback_root = True

    raise RuntimeError(f"création impossible du salon {channel_name}")


async def _force_channel_access(guild: discord.Guild, channel: discord.TextChannel) -> bool:
    me = guild.me
    if me is None:
        return False
    overwrite = channel.overwrites_for(me)
    overwrite.view_channel = True
    overwrite.send_messages = True
    overwrite.embed_links = True
    overwrite.attach_files = True
    overwrite.read_message_history = True
    overwrite.manage_channels = True
    try:
        await channel.set_permissions(
            me,
            overwrite=overwrite,
            reason="Réparation accès logs SentriX V2",
        )
        await asyncio.sleep(0.25)
        return True
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        return False


async def _test_route_with_repair(
    bot,
    guild: discord.Guild,
    requester: discord.abc.User,
    log_type: str,
    channel: discord.TextChannel,
    *,
    column: str,
    channel_name: str,
    topic: str,
    overwrites: dict,
    created_channels: list[discord.TextChannel],
) -> tuple[discord.TextChannel, bool]:
    """Teste une route, répare un 403 et remplace uniquement le salon si nécessaire."""
    ok, detail = await log_service.send_test_log(bot, guild, log_type, requester)
    if ok:
        return channel, False

    lowered = str(detail).casefold()
    access_problem = "403" in lowered or "missing access" in lowered or "permission" in lowered
    if access_problem and await _force_channel_access(guild, channel):
        ok, detail = await log_service.send_test_log(bot, guild, log_type, requester)
        if ok:
            return channel, True

    if access_problem:
        replacement = await guild.create_text_channel(
            channel_name,
            category=None,
            overwrites=overwrites,
            topic=f"SentriX logs • {topic}",
            reason=f"Remplacement route {log_type} après Missing Access",
        )
        created_channels.append(replacement)
        await bot.db.set_guild_config(guild.id, column, replacement.id)
        await log_service.set_log_channel(bot, guild.id, log_type, replacement.id)
        await log_service.set_log_enabled(bot, guild.id, log_type, True)
        ok, detail = await log_service.send_test_log(bot, guild, log_type, requester)
        if ok:
            try:
                await channel.delete(reason="Route de logs remplacée après échec d'accès")
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass
            return replacement, True

    raise RuntimeError(f"test {log_type} échoué: {detail}")


class OwnerLogRebuildV2(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _rebuild_one_guild(self, guild: discord.Guild, requester: discord.abc.User) -> v1.RebuildResult:
        result = v1.RebuildResult(guild.id, guild.name, False)

        if await _is_healthy(self.bot, guild):
            result.ok = True
            result.detail = "déjà sain — aucune reconstruction"
            return result

        me = guild.me
        if me is None:
            result.detail = "membre bot absent du cache"
            return result
        if not (me.guild_permissions.manage_channels or me.guild_permissions.administrator):
            result.detail = "permission Gérer les salons manquante"
            return result

        try:
            conf = await self.bot.db.get_guild_config(guild.id)
            settings_snapshot = {
                log_type: dict(await log_service.get_log_setting(self.bot, guild.id, log_type))
                for log_type, _column, _name, _topic in v1.LOG_ROUTES
            }
        except Exception as exc:
            result.detail = f"lecture configuration impossible: {type(exc).__name__}"
            return result

        legacy_snapshot = {column: v1._conf_value(conf, column) for column in v1.LEGACY_COLUMNS}
        old_helper = self.bot.get_cog("OwnerLogRebuild")
        if old_helper is not None:
            old_channels, old_categories = old_helper._old_log_candidates(guild, conf, settings_snapshot)
        else:
            old_channels, old_categories = [], []
        overwrites = _bot_overwrites(guild, conf)

        created_channels: list[discord.TextChannel] = []
        created_categories: list[discord.CategoryChannel] = []
        channels_by_type: dict[str, discord.TextChannel] = {}
        fallback_root = False

        try:
            category = await _new_category(guild, overwrites, requester)
            created_categories.append(category)

            for log_type, column, channel_name, topic in v1.LOG_ROUTES:
                channel, category, extra_categories, used_root = await _create_channel_resilient(
                    guild,
                    channel_name=channel_name,
                    topic=topic,
                    category=category,
                    overwrites=overwrites,
                    requester=requester,
                )
                for extra in extra_categories:
                    if extra not in created_categories:
                        created_categories.append(extra)
                fallback_root = fallback_root or used_root
                created_channels.append(channel)
                channels_by_type[log_type] = channel
                result.created += 1

                await self.bot.db.set_guild_config(guild.id, column, channel.id)
                await log_service.set_log_channel(self.bot, guild.id, log_type, channel.id)
                await log_service.set_log_enabled(self.bot, guild.id, log_type, True)

            await self.bot.db.set_guild_config(
                guild.id,
                "log_channel",
                channels_by_type["moderation"].id,
            )

            await asyncio.sleep(_SETTLE_SECONDS)
            if not await _routes_owned(self.bot, guild.id, channels_by_type):
                result.detail = "une autre instance a repris les routes — tentative abandonnée proprement"
                await _cleanup_created(created_channels, created_categories, reason="Concurrence reset logs SentriX")
                return result
            await asyncio.sleep(_SETTLE_SECONDS)
            if not await _routes_owned(self.bot, guild.id, channels_by_type):
                result.detail = "routes modifiées pendant la reconstruction — tentative abandonnée"
                await _cleanup_created(created_channels, created_categories, reason="Concurrence reset logs SentriX")
                return result

            for log_type, column, channel_name, topic in v1.LOG_ROUTES:
                channel = channels_by_type[log_type]
                valid, reason = log_service.validate_channel(guild, channel.id)
                if not valid and not await _force_channel_access(guild, channel):
                    raise RuntimeError(f"route {log_type} invalide: {reason}")

                channel, repaired = await _test_route_with_repair(
                    self.bot,
                    guild,
                    requester,
                    log_type,
                    channel,
                    column=column,
                    channel_name=channel_name,
                    topic=topic,
                    overwrites=overwrites,
                    created_channels=created_channels,
                )
                channels_by_type[log_type] = channel
                result.tests += 1
                if repaired:
                    fallback_root = True

            if not await _routes_owned(self.bot, guild.id, channels_by_type):
                result.detail = "routes reprises par une autre instance après les tests"
                await _cleanup_created(created_channels, created_categories, reason="Concurrence post-test SentriX")
                return result

        except Exception as exc:
            logger.exception("Reconstruction V2 échouée guild=%s", guild.id)
            result.detail = f"{type(exc).__name__}: {exc}"[:300]
            owns = bool(channels_by_type) and await _routes_owned(self.bot, guild.id, channels_by_type)
            if owns and old_helper is not None:
                await old_helper._rollback_routes(
                    guild,
                    legacy_snapshot,
                    settings_snapshot,
                    created_channels,
                    created_categories[-1] if created_categories else None,
                )
            else:
                await _cleanup_created(created_channels, created_categories, reason="Nettoyage V2 sans rollback partagé")
            return result

        new_ids = {channel.id for channel in created_channels}
        for channel in old_channels:
            if channel.id in new_ids:
                continue
            try:
                await channel.delete(reason="Ancien salon de logs remplacé par SentriX V2")
                result.deleted += 1
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass

        created_category_ids = {category.id for category in created_categories}
        for category in old_categories:
            if category.id in created_category_ids:
                continue
            try:
                if not category.channels:
                    await category.delete(reason="Ancienne catégorie SentriX vide")
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass

        result.ok = True
        result.detail = "nouveaux logs actifs"
        if fallback_root:
            result.detail += " • fallback permissions/catégorie appliqué"
        return result

    @commands.command(name="reset-logs-all", aliases=("resetlogsall",), hidden=True)
    @checks.is_bot_owner()
    async def reset_logs_all(self, ctx: commands.Context):
        lock = getattr(self.bot, _LOCAL_LOCK_ATTR, None)
        if lock is None:
            lock = asyncio.Lock()
            setattr(self.bot, _LOCAL_LOCK_ATTR, lock)
        if lock.locked():
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.warning('Une reconstruction des logs est déjà en cours sur cette instance.')))

        async with lock:
            guilds = list(self.bot.guilds)
            if not guilds:
                return await panels.envoyer(ctx, panels.depuis_embed(embeds.warning("SentriX n'est présent sur aucun serveur.")))

            started = time.monotonic()
            await panels.envoyer(ctx, panels.depuis_embed(embeds.warning(f'Vérification/réparation des logs lancée sur **{len(guilds)} serveur(s)**. Les serveurs déjà sains sont conservés sans recréation.')))

            results: list[v1.RebuildResult] = []
            for guild in guilds:
                try:
                    results.append(await self._rebuild_one_guild(guild, ctx.author))
                except Exception as exc:
                    logger.exception("Erreur globale reset V2 guild=%s", guild.id)
                    results.append(v1.RebuildResult(guild.id, guild.name, False, detail=f"{type(exc).__name__}: {exc}"[:300]))

            ok_results = [item for item in results if item.ok]
            failed = [item for item in results if not item.ok]
            already_healthy = sum(1 for item in ok_results if item.detail.startswith("déjà sain"))
            repaired = len(ok_results) - already_healthy
            created = sum(item.created for item in ok_results)
            deleted = sum(item.deleted for item in ok_results)
            tests = sum(item.tests for item in ok_results)
            elapsed = time.monotonic() - started

            if failed:
                final = embeds.warning(
                    f"Vérification terminée : **{len(ok_results)}/{len(results)} serveur(s)** sains.\n"
                    f"Déjà sains : **{already_healthy}** • réparés : **{repaired}** • nouveaux salons : **{created}** • "
                    f"anciens supprimés : **{deleted}** • tests réussis : **{tests}**."
                )
                lines = [f"• **{item.guild_name}** (`{item.guild_id}`) — {item.detail}" for item in failed[:12]]
                final.add_field(name="Serveurs restant à réparer", value="\n".join(lines), inline=False)
            else:
                final = embeds.success(
                    f"Tous les serveurs sont sains : **{len(ok_results)}/{len(results)}**.\n"
                    f"Déjà sains : **{already_healthy}** • réparés maintenant : **{repaired}** • "
                    f"tests réussis : **{tests}**."
                )

            final.set_footer(text=f"SentriX • reset-logs-all V2 • {elapsed:.1f} s")
            await panels.envoyer(ctx, panels.depuis_embed(final))


async def install(bot: commands.Bot) -> None:
    existing_v2 = bot.get_cog("OwnerLogRebuildV2")
    if existing_v2 is not None:
        await bot.remove_cog("OwnerLogRebuildV2")

    old = bot.get_command("reset-logs-all")
    if old is not None:
        bot.remove_command(old.name)
        # remove_command la retire du registre, mais le cog V1 continue de la
        # DETENIR : walk_commands la voyait encore, et l'audit d'integrite
        # signalait un nom duplique en CRITIQUE a chaque demarrage. On la
        # detache donc de son cog — sans retirer le cog lui-meme, qui porte le
        # listener on_guild_join prevenant le createur d'un nouveau serveur.
        ancien_cog = getattr(old, "cog", None)
        commandes = getattr(ancien_cog, "__cog_commands__", None)
        if commandes:
            ancien_cog.__cog_commands__ = tuple(c for c in commandes if c is not old)

        # remove_command ne retire que les alias DECLARES. La couche de langue
        # en ajoute d'autres au demarrage (« reinitialiser-logs-all ») : selon
        # l'ordre de chargement, cet alias pouvait rester braque sur l'ANCIENNE
        # implementation. Deux noms de la meme commande executaient alors deux
        # codes differents. On purge donc toute entree pointant encore vers
        # l'objet remplace, quel que soit l'ordre.
        orphelins = [cle for cle, cmd in bot.all_commands.items() if cmd is old]
        for cle in orphelins:
            bot.all_commands.pop(cle, None)
        if orphelins:
            logger.info(
                "OwnerLogRebuild V1 : %s alias orphelin(s) retire(s) — %s.",
                len(orphelins),
                ", ".join(sorted(orphelins)),
            )

    await bot.add_cog(OwnerLogRebuildV2(bot))
    bot._sentrix_owner_log_rebuild_v2 = True
    logger.info("OwnerLogRebuild V2 installé : idempotence + reprise catégorie/403 + garde concurrence.")
