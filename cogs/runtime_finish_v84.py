"""Finalisation ciblée V84 : tickets, logs Setup et preset privé ``+create manox``.

Cette couche ne remplace aucun moteur métier. Elle sécurise les étapes non critiques qui
s'exécutent après une action réussie et ajoute un preset de serveur idempotent réservé au
propriétaire global de SentriX.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Iterable

import discord
from discord.ext import commands

from utils import checks, embeds, log_service

logger = logging.getLogger("bot.runtime-finish-v84")

_MANOX_LOCKS: dict[int, asyncio.Lock] = {}

# Canaux racine visibles sur les captures de référence.
ROOT_CHANNELS: tuple[tuple[str, str], ...] = (
    ("text", "🚫・sanctions"),
    ("text", "📜・preuves-sanction"),
    ("text", "📊・sondage-staff"),
    ("text", "⚔️・général-modérateur"),
    ("voice", "🎮・Gaming"),
    ("voice", "✚・Créer votre Salon"),
    ("voice", "💤・AFK"),
)

# (nom catégorie, privée, ((type, nom, limite utilisateur), ...))
MANOX_STRUCTURE: tuple[tuple[str, bool, tuple[tuple[str, str, int | None], ...]], ...] = (
    (
        "🔥 Haut-Staff",
        True,
        (
            ("text", "📣・annonces-haut-staff", None),
            ("text", "🔥・général-haut-staff", None),
            ("text", "📅・absence", None),
        ),
    ),
    (
        "💾 Logs",
        True,
        (
            ("text", "💾・logs-tickets", None),
            ("text", "💾・logs-dossiers", None),
            ("text", "💾・logs-serveur", None),
            ("text", "💾・logs-membre", None),
            ("text", "💾・logs-messages", None),
            ("text", "💾・logs-vocal", None),
            ("text", "💾・logs-rôles", None),
            ("text", "💾・logs-modération", None),
            ("text", "💾・logs-protect-spam-logs", None),
            ("text", "💾・automod", None),
            ("text", "💾・moderator-only", None),
            ("text", "💾・raidprotect-logs", None),
            ("text", "💾・logs-salons", None),
        ),
    ),
    (
        "Entretien",
        True,
        (
            ("text", "📣・annonce-entretien", None),
            ("text", "📄・résultats-entretien", None),
            ("text", "💥・chat-entretien", None),
            ("voice", "🚀・Vocal entretien 1", None),
            ("voice", "👱‍♀️・Vocal entretien 2", 3),
        ),
    ),
    (
        "🚪 Informations Staff",
        True,
        (
            ("text", "📣・annonce-staff", None),
            ("text", "📏・règlement-staff", None),
            ("text", "📕・règlement-ticket-staff", None),
            ("text", "🤖・guide-sanction", None),
            ("text", "✅・contrôle-activité", None),
            ("text", "👑・hiérarchie-staff", None),
            ("text", "☁️・convocation", None),
            ("text", "💻・rdv-staff", None),
        ),
    ),
    (
        "🎤 Staff",
        True,
        (
            ("text", "⛏️・général-staff", None),
            ("text", "⚙️・commandes-staff", None),
            ("text", "🛑・absence-staff", None),
        ),
    ),
    (
        "🎉 Animation",
        False,
        (
            ("text", "📣・annonces-animations", None),
            ("text", "🎪・général-animation", None),
            ("stage", "🎡・Animation", None),
        ),
    ),
    (
        "💎 V.I.P",
        False,
        (
            ("text", "💎・général-vip", None),
            ("text", "🌟・giveaways-vip", None),
        ),
    ),
    (
        "📍 Bureaux",
        False,
        (
            ("voice", "👑・Bureau Odboug", None),
            ("voice", "🌹・Bureau Freeze", None),
            ("voice", "💫・Bureau Kabutox", None),
            ("voice", "🎤・Staff", None),
            ("voice", "⚪・Salle d'attente", 99),
        ),
    ),
    (
        "🎙️ Salons Vocaux",
        False,
        (
            ("voice", "🍃・Public 1", None),
            ("voice", "🍃・Public 2", None),
            ("voice", "🍃・Public 3", None),
            ("voice", "🎮・Gaming", None),
        ),
    ),
    (
        "🌍 Communauté",
        False,
        (
            ("text", "💬・chat", None),
            ("text", "📷・médias", None),
            ("text", "🔧・commandes", None),
        ),
    ),
    (
        "🔥 Ultra ODB",
        False,
        (
            ("text", "📎・infos-ultra", None),
            ("text", "📷・preuve-ultra", None),
            ("text", "💬・chat-ultra-et-staff", None),
        ),
    ),
    (
        "🐺 Steal a Brainrot",
        False,
        (
            ("text", "⚡・infos-sab", None),
            ("text", "🍓・recherche-brainrot", None),
            ("text", "⚔️・pvp", None),
            ("text", "🔄・trade", None),
            ("text", "⚖️・w-or-l", None),
            ("text", "✔️・vouchs", None),
            ("text", "🤡・steals-and-fails", None),
            ("text", "⚠️・scam", None),
        ),
    ),
    (
        "🛒 Service SAB",
        False,
        (
            ("text", "👑・odboug-shop", None),
            ("text", "🚦・middle-man", None),
        ),
    ),
    (
        "🏝️ Giveaways",
        False,
        (
            ("text", "🎁・giveaways-1", None),
            ("text", "🎁・giveaways-2", None),
            ("text", "🎁・giveaways-3", None),
            ("text", "🎉・invites-rewards", None),
            ("text", "✅・preuves-giveaways", None),
        ),
    ),
    (
        "👑 Odboug",
        False,
        (
            ("text", "▶️・vidéos", None),
            ("text", "📣・tournages", None),
            ("voice", "🎥・Tournage", None),
        ),
    ),
    (
        "🏠 Accueil",
        False,
        (
            ("text", "📜・règlement", None),
            ("text", "🛬・arrivées", None),
            ("text", "💌・invitations", None),
            ("text", "🎵・tiktok", None),
        ),
    ),
    (
        "❗ Informations",
        False,
        (
            ("text", "📣・annonces", None),
            ("text", "💼・recrutements-staff", None),
            ("text", "📊・sondages", None),
            ("text", "🔮・boosts-serveur", None),
            ("text", "👑・hiérarchie", None),
            ("text", "📊・niveaux", None),
            ("text", "📝・présentation-staff", None),
        ),
    ),
    (
        "📞 Support",
        False,
        (
            ("text", "🧰・support", None),
            ("text", "🎟️・ticket-natox__", None),
            ("voice", "❓・Besoin d'aide", 2),
        ),
    ),
)

LOG_ROUTE_NAMES = {
    "moderation": "💾・logs-modération",
    "messages": "💾・logs-messages",
    "members": "💾・logs-membre",
    "channels": "💾・logs-salons",
    "roles": "💾・logs-rôles",
    "voice": "💾・logs-vocal",
    "server": "💾・logs-serveur",
    "tickets": "💾・logs-tickets",
    "protection": "💾・automod",
}


def _lock(guild_id: int) -> asyncio.Lock:
    key = int(guild_id)
    lock = _MANOX_LOCKS.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _MANOX_LOCKS[key] = lock
    return lock


def _walk_components(items: Iterable[Any]):
    for item in items:
        yield item
        children = getattr(item, "children", None)
        if children:
            yield from _walk_components(children)


def _private_overwrites(guild: discord.Guild, author: discord.Member):
    me = guild.me
    overwrites: dict[Any, discord.PermissionOverwrite] = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        author: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            connect=True,
            speak=True,
        ),
    }
    if me is not None:
        overwrites[me] = discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            manage_channels=True,
            connect=True,
            speak=True,
        )
    return overwrites


async def _ensure_category(
    guild: discord.Guild,
    name: str,
    *,
    private: bool,
    author: discord.Member,
) -> tuple[discord.CategoryChannel, bool]:
    category = discord.utils.get(guild.categories, name=name)
    if category is not None:
        if private:
            # Ne supprime jamais les rôles déjà autorisés : on garantit seulement que
            # @everyone reste privé et que l'auteur/bot ne puisse pas se verrouiller dehors.
            await category.set_permissions(
                guild.default_role,
                overwrite=discord.PermissionOverwrite(view_channel=False),
                reason="Preset privé +create manox",
            )
            for target, overwrite in _private_overwrites(guild, author).items():
                if target == guild.default_role:
                    continue
                current = category.overwrites_for(target)
                current.update(**{key: value for key, value in overwrite if value is not None})
                await category.set_permissions(target, overwrite=current, reason="Accès +create manox")
        return category, False

    category = await guild.create_category(
        name,
        overwrites=_private_overwrites(guild, author) if private else None,
        reason="Preset serveur +create manox",
    )
    return category, True


def _find_channel(guild: discord.Guild, name: str, kind: str, category: discord.CategoryChannel | None):
    if kind == "text":
        candidates = guild.text_channels
    elif kind == "stage":
        candidates = list(getattr(guild, "stage_channels", [])) + list(guild.voice_channels)
    else:
        candidates = guild.voice_channels

    exact = [channel for channel in candidates if channel.name == name]
    if category is not None:
        in_category = next((channel for channel in exact if channel.category_id == category.id), None)
        if in_category is not None:
            return in_category
    return exact[0] if exact else None


async def _ensure_channel(
    guild: discord.Guild,
    *,
    kind: str,
    name: str,
    category: discord.CategoryChannel | None,
    user_limit: int | None = None,
):
    existing = _find_channel(guild, name, kind, category)
    if existing is not None:
        changes: dict[str, Any] = {}
        if category is not None and existing.category_id != category.id:
            changes["category"] = category
            changes["sync_permissions"] = True
        if isinstance(existing, discord.VoiceChannel) and user_limit is not None and existing.user_limit != user_limit:
            changes["user_limit"] = user_limit
        if changes:
            try:
                await existing.edit(reason="Réparation +create manox", **changes)
            except (discord.Forbidden, discord.HTTPException):
                logger.warning("Impossible de déplacer/ajuster %s pendant +create manox", name, exc_info=True)
        return existing, False

    if kind == "text":
        channel = await guild.create_text_channel(name, category=category, reason="Preset serveur +create manox")
    elif kind == "stage":
        try:
            channel = await guild.create_stage_channel(name, category=category, reason="Preset serveur +create manox")
        except (discord.Forbidden, discord.HTTPException):
            channel = await guild.create_voice_channel(name, category=category, reason="Fallback vocal +create manox")
    else:
        channel = await guild.create_voice_channel(
            name,
            category=category,
            user_limit=user_limit or 0,
            reason="Preset serveur +create manox",
        )
    return channel, True


async def _persist_log_route(bot: commands.Bot, guild_id: int, log_type: str, channel_id: int) -> None:
    category, _emoji, _kind = log_service.resolve(log_type)
    row = await log_service._ensure_category_row(bot, guild_id, category)
    enabled = bool(row.get("enabled", 1))
    await bot.db.execute(
        "UPDATE log_config SET channel_id=?, enabled=1 WHERE guild_id=? AND category=?",
        (int(channel_id), int(guild_id), category),
    )
    try:
        await log_service._mirror_legacy_setting(
            bot,
            int(guild_id),
            category,
            channel_id=int(channel_id),
            enabled=True if not enabled else enabled,
        )
    except Exception:
        logger.debug("Miroir legacy du log %s ignoré", category, exc_info=True)


async def _safe_set_config(bot: commands.Bot, guild_id: int, field: str, value: int) -> bool:
    try:
        await bot.db.set_guild_config(guild_id, field, value)
        return True
    except Exception:
        logger.warning("Champ guild_config %s non appliqué pour %s", field, guild_id, exc_info=True)
        return False


async def build_manox_server(
    bot: commands.Bot,
    guild: discord.Guild,
    author: discord.Member,
) -> dict[str, Any]:
    created_categories = 0
    created_channels = 0
    channels_by_name: dict[str, Any] = {}
    categories_by_name: dict[str, discord.CategoryChannel] = {}
    warnings: list[str] = []

    for kind, name in ROOT_CHANNELS:
        channel, made = await _ensure_channel(guild, kind=kind, name=name, category=None)
        channels_by_name[name] = channel
        created_channels += int(made)

    for category_name, private, specs in MANOX_STRUCTURE:
        category, made = await _ensure_category(guild, category_name, private=private, author=author)
        categories_by_name[category_name] = category
        created_categories += int(made)
        for kind, name, user_limit in specs:
            channel, channel_made = await _ensure_channel(
                guild,
                kind=kind,
                name=name,
                category=category,
                user_limit=user_limit,
            )
            channels_by_name[name] = channel
            created_channels += int(channel_made)

    logs_ready = 0
    for log_type, channel_name in LOG_ROUTE_NAMES.items():
        channel = channels_by_name.get(channel_name)
        if isinstance(channel, discord.TextChannel):
            try:
                await _persist_log_route(bot, guild.id, log_type, channel.id)
                logs_ready += 1
            except Exception:
                warnings.append(f"log {log_type}")
                logger.exception("Configuration route log %s impossible sur %s", log_type, guild.id)

    # Réglages généraux directement reliés aux salons du preset.
    general_log = channels_by_name.get("💾・logs-serveur")
    ticket_log = channels_by_name.get("💾・logs-tickets")
    arrivals = channels_by_name.get("🛬・arrivées")
    levels = channels_by_name.get("📊・niveaux")
    support_category = categories_by_name.get("📞 Support")

    config_pairs = (
        ("log_channel", getattr(general_log, "id", None)),
        ("ticket_log_channel", getattr(ticket_log, "id", None)),
        ("ticket_category", getattr(support_category, "id", None)),
        ("welcome_channel", getattr(arrivals, "id", None)),
        ("level_channel", getattr(levels, "id", None)),
    )
    for field, value in config_pairs:
        if value is not None:
            await _safe_set_config(bot, guild.id, field, int(value))

    ticket_ready = False
    try:
        from . import setup_ticket_autoconfig_v72 as ticket_v72

        await ticket_v72.ensure_ticket_configuration(bot, guild, actor_id=author.id)
        ticket_ready = True
    except Exception:
        warnings.append("tickets")
        logger.exception("Auto-configuration Tickets du preset manox impossible sur %s", guild.id)

    try:
        from . import setup_v2_core as core

        for module in ("logs", "welcome", "levels"):
            await core.set_module_enabled(bot, guild.id, module, True, actor_id=author.id)
    except Exception:
        warnings.append("modules setup")
        logger.exception("Activation des modules de base manox impossible sur %s", guild.id)

    return {
        "categories_created": created_categories,
        "categories_total": len(MANOX_STRUCTURE),
        "channels_created": created_channels,
        "channels_total": len(ROOT_CHANNELS) + sum(len(specs) for _name, _private, specs in MANOX_STRUCTURE),
        "logs_ready": logs_ready,
        "ticket_ready": ticket_ready,
        "warnings": warnings,
    }


def _install_ticket_log_resilience() -> None:
    from . import tickets as ticket_runtime

    current = ticket_runtime.Tickets.log_action
    if getattr(current, "_sentrix_v84_best_effort", False):
        return

    async def safe_log_action(self, guild, embed, log_channel_id=None):
        try:
            return await current(self, guild, embed, log_channel_id)
        except Exception:
            # Un ticket déjà créé/fermé ne doit jamais devenir une « Action impossible »
            # uniquement parce que son journal est temporairement indisponible.
            logger.exception(
                "Journal ticket indisponible après action réussie (guild=%s, channel=%s)",
                getattr(guild, "id", None),
                log_channel_id,
            )
            return None

    safe_log_action._sentrix_v84_best_effort = True
    safe_log_action._sentrix_previous = current
    ticket_runtime.Tickets.log_action = safe_log_action


def _install_setup_log_channel_resilience() -> None:
    from . import setup_experience_v74 as v74

    cls = v74.SentriXSetupV74
    current = cls._build_page
    if getattr(current, "_sentrix_v84_log_channel_save", False):
        return

    async def build_page_v84(self, page: str):
        result = await current(self, page)
        if page != "logs":
            return result

        selected_type = getattr(self.backend, "selected_log", None)
        if not selected_type:
            return result

        for item in _walk_components(getattr(self, "children", ())):
            if not isinstance(item, discord.ui.ChannelSelect):
                continue
            placeholder = str(getattr(item, "placeholder", "") or "")
            if not placeholder.startswith("2. Choisir le salon pour"):
                continue

            select = item

            async def choose_channel_v84(interaction: discord.Interaction, *, _select=select):
                log_type = getattr(self.backend, "selected_log", None) or selected_type
                if not interaction.response.is_done():
                    await interaction.response.defer()
                channel = _select.values[0] if _select.values else None
                channel_id = int(channel.id) if channel is not None else None

                # La sauvegarde ne dépend pas d'un audit/refresh et ne rejette pas un salon
                # valide à cause d'un cache Discord incomplet. L'état des permissions reste
                # affiché ensuite par validate_channel() sur la page Logs.
                try:
                    if channel_id is None:
                        await log_service.set_log_channel(self.bot, self.guild.id, log_type, None)
                    else:
                        await _persist_log_route(self.bot, self.guild.id, log_type, channel_id)
                except Exception as exc:
                    logger.exception(
                        "Échec réel de sauvegarde salon logs guild=%s type=%s channel=%s",
                        self.guild.id,
                        log_type,
                        channel_id,
                    )
                    detail = str(exc).strip() or type(exc).__name__
                    try:
                        await interaction.followup.send(
                            embed=embeds.error(
                                f"Le salon n'a pas pu être enregistré en base. Détail : `{detail[:180]}`"
                            ),
                            ephemeral=True,
                        )
                    except discord.HTTPException:
                        pass
                    return

                try:
                    await self.backend.audit(interaction.user.id, f"log:{log_type}", channel_id)
                except Exception:
                    logger.debug("Audit log channel V84 indisponible", exc_info=True)

                try:
                    await self.refresh(interaction)
                except Exception:
                    # Important : la DB est déjà sauvegardée. On ne ment plus avec
                    # « Salon non enregistré » lorsque seul le rendu du panneau échoue.
                    logger.exception(
                        "Salon log sauvegardé mais refresh Setup impossible guild=%s type=%s",
                        self.guild.id,
                        log_type,
                    )
                    try:
                        if channel is None:
                            text = "Le salon de cette catégorie de logs a bien été désactivé."
                        else:
                            text = f"Salon enregistré : {channel.mention}. Le panneau sera actualisé au prochain rafraîchissement."
                        await interaction.followup.send(embed=embeds.success(text), ephemeral=True)
                    except discord.HTTPException:
                        pass

            select.callback = choose_channel_v84
            break
        return result

    build_page_v84._sentrix_v84_log_channel_save = True
    build_page_v84._sentrix_previous = current
    cls._build_page = build_page_v84


def _install_manox_command(bot: commands.Bot) -> None:
    root = bot.get_command("create")
    if not isinstance(root, commands.Group):
        logger.warning("+create absent : preset manox non installé.")
        return
    if root.get_command("manox") is not None:
        return

    async def manox_callback(ctx: commands.Context):
        if not await checks.is_verified_bot_owner(ctx):
            raise checks.BotPermissionError(
                "Cette commande est réservée au **propriétaire global de SentriX**."
            )
        guild = ctx.guild
        if guild is None or not isinstance(ctx.author, discord.Member):
            return await ctx.send(embed=embeds.error("Utilise `+create manox` dans un serveur Discord."))

        me = guild.me
        if me is None or not me.guild_permissions.manage_channels:
            return await ctx.send(
                embed=embeds.error(
                    "SentriX a besoin au minimum de **Gérer les salons** pour construire ce serveur."
                )
            )

        lock = _lock(guild.id)
        if lock.locked():
            return await ctx.send(embed=embeds.info("La création/réparation **manox** est déjà en cours."))

        progress = await ctx.send(
            embed=embeds.info(
                "Je crée ou répare les catégories, salons, vocaux, logs et tickets du preset **manox**. "
                "Les éléments déjà présents sont réutilisés."
            )
        )
        async with lock:
            try:
                result = await build_manox_server(bot, guild, ctx.author)
            except discord.Forbidden:
                logger.exception("+create manox refusé par Discord guild=%s", guild.id)
                panel = embeds.error(
                    "Discord a refusé une création. Vérifie les permissions de SentriX et la position de son rôle."
                )
            except discord.HTTPException as exc:
                logger.exception("+create manox erreur HTTP guild=%s", guild.id)
                panel = embeds.error(f"Discord a interrompu l'installation : `{str(exc)[:200]}`")
            except Exception as exc:
                logger.exception("+create manox erreur interne guild=%s", guild.id)
                panel = embeds.error(f"Erreur pendant l'installation : `{type(exc).__name__}: {str(exc)[:180]}`")
            else:
                warnings = result["warnings"]
                extra = f"\nÀ vérifier : **{', '.join(warnings)}**" if warnings else ""
                panel = embeds.success(
                    "Preset **manox** créé/réparé.\n\n"
                    f"**Catégories :** {result['categories_created']} nouvelle(s) / {result['categories_total']} prévues\n"
                    f"**Salons :** {result['channels_created']} nouveau(x) / {result['channels_total']} prévus\n"
                    f"**Routes de logs :** {result['logs_ready']}/{len(LOG_ROUTE_NAMES)} configurées\n"
                    f"**Tickets :** {'configurés' if result['ticket_ready'] else 'à vérifier'}"
                    f"{extra}"
                )

        try:
            await progress.edit(content=None, embed=panel, view=None)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException, TypeError):
            await ctx.send(embed=panel)

    command = commands.Command(manox_callback, name="manox", help="Preset privé complet du serveur manox.")
    command.extras["sentrix_permission"] = "Propriétaire global SentriX"
    root.add_command(command)
    logger.info("Commande privée +create manox installée.")


def install(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_runtime_finish_v84", False):
        return
    _install_ticket_log_resilience()
    _install_setup_log_channel_resilience()
    _install_manox_command(bot)
    bot._sentrix_runtime_finish_v84 = True
    logger.info("Runtime Finish V84 actif : tickets, logs Setup et +create manox.")


__all__ = ["build_manox_server", "install"]
