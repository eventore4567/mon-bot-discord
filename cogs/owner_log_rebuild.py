"""Outils propriétaire pour reconstruire les logs SentriX et assistance d'installation.

- +reset-logs-all : recrée les routes de logs officielles sur tous les serveurs, puis
  supprime les anciens salons uniquement après validation et tests.
- À l'arrivée sur un serveur : le créateur reçoit les informations du serveur.
- Un administrateur peut demander de l'aide via un bouton. L'invitation temporaire
  n'est créée qu'après cette action explicite.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import discord
from discord.ext import commands

import config
from database.db import PRIMARY_CREATOR_ID
from utils import checks, embeds, log_service
from utils import sentrix_panels as panels

logger = logging.getLogger("bot.owner-log-rebuild")

HELP_INVITE_MAX_AGE = 24 * 60 * 60
HELP_INVITE_MAX_USES = 1
HELP_REQUEST_COOLDOWN = 10 * 60

LOG_CATEGORY_NAME = "SentriX — Logs"

# log_type, colonne historique, nom du nouveau salon, description
LOG_ROUTES = (
    ("messages", "log_messages", "logs-messages", "Messages modifiés ou supprimés."),
    ("members", "log_members", "logs-membres", "Arrivées, départs et changements de membres."),
    ("roles", "log_roles", "logs-roles", "Création, suppression et attribution des rôles."),
    ("server", "log_server", "logs-salons", "Création, suppression et modification des salons."),
    ("voice", "log_voice", "logs-vocal", "Connexions, déconnexions et déplacements vocaux."),
    ("moderation", "log_moderation", "logs-moderation", "Warns, mutes, kicks, bans et autres sanctions."),
    ("automod", "log_automod", "logs-securite", "AutoMod, anti-spam, anti-raid et protections."),
    ("tickets", "ticket_log_channel", "logs-tickets", "Ouverture, claim et fermeture des tickets."),
)

KNOWN_OLD_LOG_NAMES = {
    "logs-serveur",
    "logs-server",
    "logs-salons",
    "logs-message",
    "logs-messages",
    "logs-membre",
    "logs-membres",
    "logs-role",
    "logs-roles",
    "logs-vocal",
    "logs-moderation",
    "logs-modération",
    "logs-automod",
    "logs-securite",
    "logs-sécurité",
    "automod-logs",
    "automod",
    "raidprotect-logs",
    "anti-raid-logs",
    "logs-ticket",
    "logs-tickets",
}

LEGACY_COLUMNS = tuple(route[1] for route in LOG_ROUTES) + ("log_channel",)


@dataclass
class RebuildResult:
    guild_id: int
    guild_name: str
    ok: bool
    created: int = 0
    deleted: int = 0
    tests: int = 0
    detail: str = ""


def _conf_value(conf, key: str):
    if conf is None:
        return None
    try:
        return conf[key]
    except (KeyError, IndexError, TypeError):
        return None


def _creator_ids(bot: commands.Bot) -> set[int]:
    ids: set[int] = set()
    try:
        primary = int(PRIMARY_CREATOR_ID or 0)
        if primary > 0:
            ids.add(primary)
    except (TypeError, ValueError):
        pass

    for raw in getattr(config, "OWNER_IDS", ()) or ():
        try:
            value = int(raw)
        except (TypeError, ValueError):
            continue
        if value > 0:
            ids.add(value)

    owner_id = getattr(bot, "owner_id", None)
    if owner_id:
        ids.add(int(owner_id))
    return ids


async def _send_creator_dm(bot: commands.Bot, *, embed: discord.Embed) -> int:
    delivered = 0
    for user_id in _creator_ids(bot):
        user = bot.get_user(user_id)
        if user is None:
            try:
                user = await bot.fetch_user(user_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                continue
        try:
            await panels.envoyer(user, panels.depuis_embed(embed))
            delivered += 1
        except (discord.Forbidden, discord.HTTPException):
            logger.warning("MP créateur impossible pour user=%s", user_id)
    return delivered


def _guild_info_embed(guild: discord.Guild) -> discord.Embed:
    owner_text = str(guild.owner) if guild.owner else "Non présent dans le cache"
    embed = embeds.brand(
        "SentriX ajouté à un nouveau serveur",
        "Le bot vient d'être ajouté. Aucune invitation n'a été créée automatiquement.",
    )
    embed.add_field(name="Serveur", value=f"{guild.name}\n`{guild.id}`", inline=False)
    embed.add_field(name="Propriétaire", value=f"{owner_text}\n`{guild.owner_id}`", inline=True)
    embed.add_field(name="Membres", value=str(guild.member_count or 0), inline=True)
    embed.add_field(
        name="Assistance",
        value=(
            "Un administrateur peut utiliser le bouton **Demander de l'aide** sur le serveur. "
            "À ce moment-là seulement, SentriX crée une invitation valable 24 h et utilisable une fois."
        ),
        inline=False,
    )
    return embed


def _help_request_embed(guild: discord.Guild, requester: discord.abc.User, invite: discord.Invite) -> discord.Embed:
    embed = embeds.brand(
        "Demande d'aide SentriX",
        "Un administrateur du serveur demande de l'aide pour configurer SentriX.",
    )
    embed.add_field(name="Serveur", value=f"{guild.name}\n`{guild.id}`", inline=False)
    embed.add_field(name="Demandé par", value=f"{requester}\n`{requester.id}`", inline=True)
    embed.add_field(name="Invitation temporaire", value=invite.url, inline=False)
    embed.set_footer(text="Invitation valable 24 h • 1 utilisation maximum")
    return embed


def _target_help_channel(guild: discord.Guild) -> discord.TextChannel | None:
    me = guild.me
    if me is None:
        return None
    ordered = [guild.system_channel, guild.public_updates_channel, guild.rules_channel, *guild.text_channels]
    seen: set[int] = set()
    for channel in ordered:
        if channel is None or channel.id in seen:
            continue
        seen.add(channel.id)
        perms = channel.permissions_for(me)
        if perms.view_channel and perms.send_messages and perms.embed_links:
            return channel
    return None


def _invite_channel(
    guild: discord.Guild,
    preferred: discord.abc.GuildChannel | None = None,
) -> discord.TextChannel | None:
    me = guild.me
    if me is None:
        return None
    ordered = []
    if isinstance(preferred, discord.TextChannel):
        ordered.append(preferred)
    ordered.extend(guild.text_channels)
    seen: set[int] = set()
    for channel in ordered:
        if channel.id in seen:
            continue
        seen.add(channel.id)
        perms = channel.permissions_for(me)
        if perms.view_channel and perms.create_instant_invite:
            return channel
    return None


async def _create_and_deliver_help_invite(
    bot: commands.Bot,
    guild: discord.Guild,
    requester: discord.Member,
    *,
    preferred_channel: discord.abc.GuildChannel | None = None,
) -> tuple[bool, str]:
    cooldowns = getattr(bot, "_sentrix_setup_help_cooldowns", None)
    if cooldowns is None:
        cooldowns = {}
        setattr(bot, "_sentrix_setup_help_cooldowns", cooldowns)

    now = time.monotonic()
    last = float(cooldowns.get(guild.id, 0.0))
    remaining = HELP_REQUEST_COOLDOWN - (now - last)
    if remaining > 0:
        return False, f"Une demande d'aide a déjà été envoyée récemment. Réessaie dans {max(1, round(remaining / 60))} min."

    channel = _invite_channel(guild, preferred_channel)
    if channel is None:
        return False, "Je n'ai la permission **Créer une invitation** dans aucun salon de ce serveur."

    try:
        invite = await channel.create_invite(
            max_age=HELP_INVITE_MAX_AGE,
            max_uses=HELP_INVITE_MAX_USES,
            unique=True,
            reason=f"Assistance SentriX demandée par {requester} ({requester.id})",
        )
    except (discord.Forbidden, discord.HTTPException) as exc:
        logger.warning("Création invitation assistance impossible guild=%s: %s", guild.id, exc)
        return False, "Je n'ai pas réussi à créer l'invitation. Vérifie ma permission **Créer une invitation**."

    delivered = await _send_creator_dm(
        bot,
        embed=_help_request_embed(guild, requester, invite),
    )
    if delivered <= 0:
        try:
            await invite.delete(reason="Aucun créateur SentriX joignable pour la demande d'aide")
        except (discord.Forbidden, discord.HTTPException):
            pass
        return False, "L'invitation a été créée, mais je n'ai pas pu contacter le créateur de SentriX."

    cooldowns[guild.id] = now
    return True, "La demande a été envoyée au créateur de SentriX avec une invitation temporaire."


class SetupHelpView(discord.ui.View):
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(
        label="Demander de l'aide",
        style=discord.ButtonStyle.secondary,
        custom_id="sentrix:setup-help:request:v1",
    )
    async def request_help(self, interaction: discord.Interaction, _button: discord.ui.Button):
        guild = interaction.guild
        member = interaction.user
        if guild is None or not isinstance(member, discord.Member):
            return await interaction.response.send_message(
                "Cette action doit être utilisée depuis le serveur concerné.",
                ephemeral=True,
            )

        perms = member.guild_permissions
        allowed = member.id == guild.owner_id or perms.administrator or perms.manage_guild
        if not allowed:
            return await interaction.response.send_message(
                "Seul le propriétaire ou un administrateur du serveur peut demander cette aide.",
                ephemeral=True,
            )

        await interaction.response.defer(ephemeral=True)
        _ok, message = await _create_and_deliver_help_invite(
            self.bot,
            guild,
            member,
            preferred_channel=interaction.channel,
        )
        await interaction.followup.send(message, ephemeral=True)


class OwnerLogRebuild(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self) -> None:
        # Vue persistante : le bouton continue de fonctionner après un redémarrage.
        self.bot.add_view(SetupHelpView(self.bot))

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild):
        # Le créateur reçoit l'identité du serveur immédiatement, mais aucun lien secret.
        try:
            await _send_creator_dm(self.bot, embed=_guild_info_embed(guild))
        except Exception:
            logger.exception("Notification créateur impossible pour nouveau guild=%s", guild.id)

        channel = _target_help_channel(guild)
        if channel is None:
            return

        embed = embeds.brand(
            "Besoin d'aide pour configurer SentriX ?",
            (
                "Le propriétaire ou un administrateur peut demander l'aide du créateur de SentriX. "
                "Le bot créera alors une invitation temporaire de 24 h, utilisable une seule fois."
            ),
        )
        try:
            await panels.envoyer(channel, panels.avec_composants(panels.depuis_embed(embed), SetupHelpView(self.bot)), allowed_mentions=discord.AllowedMentions.none())
        except (discord.Forbidden, discord.HTTPException):
            logger.warning("Carte d'assistance impossible à envoyer guild=%s", guild.id)

    def _old_log_candidates(
        self,
        guild: discord.Guild,
        conf,
        settings: dict[str, dict],
    ) -> tuple[list[discord.TextChannel], list[discord.CategoryChannel]]:
        configured_ids: set[int] = set()

        for column in LEGACY_COLUMNS:
            value = _conf_value(conf, column)
            if value:
                configured_ids.add(int(value))

        for setting in settings.values():
            channel_id = setting.get("channel_id")
            if channel_id:
                configured_ids.add(int(channel_id))

        old_categories: list[discord.CategoryChannel] = []
        old_category_ids: set[int] = set()
        for category in guild.categories:
            normalized = category.name.casefold()
            if "sentrix" in normalized and "log" in normalized:
                old_categories.append(category)
                old_category_ids.add(category.id)

        candidates: list[discord.TextChannel] = []
        seen: set[int] = set()
        for channel in guild.text_channels:
            is_configured = channel.id in configured_ids
            in_sentrix_log_category = channel.category_id in old_category_ids
            known_name = channel.name.casefold() in KNOWN_OLD_LOG_NAMES
            topic = (channel.topic or "").casefold()
            sentrix_topic = "sentrix" in topic and "log" in topic

            if is_configured or (known_name and in_sentrix_log_category) or (known_name and sentrix_topic):
                if channel.id not in seen:
                    candidates.append(channel)
                    seen.add(channel.id)

        return candidates, old_categories

    async def _rollback_routes(
        self,
        guild: discord.Guild,
        legacy_snapshot: dict[str, int | None],
        settings_snapshot: dict[str, dict],
        new_channels: list[discord.TextChannel],
        new_category: discord.CategoryChannel | None,
    ) -> None:
        for _log_type, column, _name, _topic in LOG_ROUTES:
            try:
                await self.bot.db.set_guild_config(guild.id, column, legacy_snapshot.get(column))
            except Exception:
                logger.exception("Rollback colonne %s impossible guild=%s", column, guild.id)

        try:
            await self.bot.db.set_guild_config(guild.id, "log_channel", legacy_snapshot.get("log_channel"))
        except Exception:
            logger.exception("Rollback log_channel impossible guild=%s", guild.id)

        for log_type, _column, _name, _topic in LOG_ROUTES:
            previous = settings_snapshot.get(log_type) or {}
            previous_channel = previous.get("channel_id")
            previous_enabled = bool(previous.get("enabled"))
            try:
                await log_service.set_log_channel(self.bot, guild.id, log_type, previous_channel)
                if previous_enabled and previous_channel:
                    await log_service.set_log_enabled(self.bot, guild.id, log_type, True)
                else:
                    await log_service.set_log_enabled(self.bot, guild.id, log_type, False)
            except Exception:
                logger.exception("Rollback log_settings type=%s impossible guild=%s", log_type, guild.id)

        for channel in new_channels:
            try:
                await channel.delete(reason="Rollback reconstruction logs SentriX")
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass
        if new_category is not None:
            try:
                await new_category.delete(reason="Rollback reconstruction logs SentriX")
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass

    async def _rebuild_one_guild(self, guild: discord.Guild, requester: discord.abc.User) -> RebuildResult:
        result = RebuildResult(guild.id, guild.name, False)

        me = guild.me
        if me is None:
            result.detail = "membre bot absent du cache"
            return result

        if not me.guild_permissions.manage_channels:
            result.detail = "permission Gérer les salons manquante"
            return result

        try:
            conf = await self.bot.db.get_guild_config(guild.id)
            settings_snapshot = {
                log_type: dict(await log_service.get_log_setting(self.bot, guild.id, log_type))
                for log_type, _column, _name, _topic in LOG_ROUTES
            }
        except Exception as exc:
            result.detail = f"lecture configuration impossible: {type(exc).__name__}"
            logger.exception("Snapshot logs impossible guild=%s", guild.id)
            return result

        legacy_snapshot = {column: _conf_value(conf, column) for column in LEGACY_COLUMNS}
        old_channels, old_categories = self._old_log_candidates(guild, conf, settings_snapshot)

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
        mod_role_id = _conf_value(conf, "mod_role")
        if mod_role_id:
            role = guild.get_role(int(mod_role_id))
            if role is not None:
                overwrites[role] = discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                )

        new_category: discord.CategoryChannel | None = None
        new_channels: list[discord.TextChannel] = []
        channels_by_type: dict[str, discord.TextChannel] = {}

        try:
            new_category = await guild.create_category(
                LOG_CATEGORY_NAME,
                overwrites=overwrites,
                reason=f"Reconstruction globale des logs SentriX par {requester} ({requester.id})",
            )

            for log_type, _column, channel_name, topic in LOG_ROUTES:
                channel = await guild.create_text_channel(
                    channel_name,
                    category=new_category,
                    overwrites=overwrites,
                    topic=f"SentriX logs • {topic}",
                    reason="Nouvelle architecture officielle des logs SentriX",
                )
                new_channels.append(channel)
                channels_by_type[log_type] = channel

            result.created = len(new_channels)

            # On bascule les deux systèmes de configuration (legacy + log_settings) vers
            # les nouveaux salons. Ainsi les anciens listeners comme les nouveaux utilisent
            # exactement les mêmes routes.
            for log_type, column, _channel_name, _topic in LOG_ROUTES:
                channel = channels_by_type[log_type]
                await self.bot.db.set_guild_config(guild.id, column, channel.id)
                await log_service.set_log_channel(self.bot, guild.id, log_type, channel.id)
                await log_service.set_log_enabled(self.bot, guild.id, log_type, True)

            # Repli historique utilisé par quelques commandes de modération.
            await self.bot.db.set_guild_config(
                guild.id,
                "log_channel",
                channels_by_type["moderation"].id,
            )

            # Vérification stricte avant de toucher aux anciens salons.
            for log_type, _column, _channel_name, _topic in LOG_ROUTES:
                channel = channels_by_type[log_type]
                setting = await log_service.get_log_setting(self.bot, guild.id, log_type)
                if not setting["enabled"] or int(setting["channel_id"] or 0) != channel.id:
                    raise RuntimeError(f"route {log_type} non persistée")
                valid, reason = log_service.validate_channel(guild, channel.id)
                if not valid:
                    raise RuntimeError(f"route {log_type} invalide: {reason}")

            # Test de chaque route via le système officiel. Les anciens salons ne sont
            # supprimés que si les huit tests passent.
            for log_type, _column, _channel_name, _topic in LOG_ROUTES:
                ok, detail = await log_service.send_test_log(self.bot, guild, log_type, me)
                if not ok:
                    raise RuntimeError(f"test {log_type} échoué: {detail}")
                result.tests += 1

        except Exception as exc:
            logger.exception("Reconstruction logs échouée guild=%s", guild.id)
            result.detail = f"{type(exc).__name__}: {exc}"[:300]
            await self._rollback_routes(
                guild,
                legacy_snapshot,
                settings_snapshot,
                new_channels,
                new_category,
            )
            return result

        # Les nouveaux salons sont configurés et testés. On peut maintenant retirer les
        # anciens sans risquer de laisser le serveur sans route de logs fonctionnelle.
        new_ids = {channel.id for channel in new_channels}
        delete_errors = 0
        for channel in old_channels:
            if channel.id in new_ids:
                continue
            try:
                await channel.delete(reason="Ancien salon de logs remplacé par SentriX")
                result.deleted += 1
            except discord.NotFound:
                pass
            except (discord.Forbidden, discord.HTTPException):
                delete_errors += 1

        for category in old_categories:
            if new_category is not None and category.id == new_category.id:
                continue
            try:
                # On ne supprime jamais une catégorie qui contient encore un salon :
                # cela protège les salons non liés aux logs que des admins auraient placés dedans.
                if not category.channels:
                    await category.delete(reason="Ancienne catégorie de logs SentriX vide")
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                delete_errors += 1

        result.ok = True
        result.detail = "nouveaux logs actifs"
        if delete_errors:
            result.detail += f" • {delete_errors} ancien(s) élément(s) non supprimé(s)"
        return result

    @commands.command(name="reset-logs-all", aliases=("resetlogsall",), hidden=True)
    @checks.is_bot_owner()
    async def reset_logs_all(self, ctx: commands.Context):
        """Reconstruit les logs de tous les serveurs où SentriX est présent."""
        guilds = list(self.bot.guilds)
        if not guilds:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.warning("SentriX n'est actuellement présent sur aucun serveur.")))

        started = time.monotonic()
        await panels.envoyer(ctx, panels.depuis_embed(embeds.warning(f"Reconstruction des logs lancée sur **{len(guilds)} serveur(s)**.\nLes anciens salons ne seront supprimés qu'après création, configuration et test réussi des nouveaux.")))

        results: list[RebuildResult] = []
        for guild in guilds:
            try:
                results.append(await self._rebuild_one_guild(guild, ctx.author))
            except Exception as exc:
                logger.exception("Erreur globale reset logs guild=%s", guild.id)
                results.append(
                    RebuildResult(
                        guild.id,
                        guild.name,
                        False,
                        detail=f"{type(exc).__name__}: {exc}"[:300],
                    )
                )

        ok_results = [item for item in results if item.ok]
        failed = [item for item in results if not item.ok]
        created = sum(item.created for item in ok_results)
        deleted = sum(item.deleted for item in ok_results)
        tests = sum(item.tests for item in ok_results)
        elapsed = time.monotonic() - started

        if failed:
            final = embeds.warning(
                (
                    f"Reconstruction terminée : **{len(ok_results)}/{len(results)} serveur(s)** réparé(s).\n"
                    f"Nouveaux salons : **{created}** • anciens supprimés : **{deleted}** • tests réussis : **{tests}**."
                )
            )
            lines = [
                f"• **{item.guild_name}** (`{item.guild_id}`) — {item.detail}"
                for item in failed[:12]
            ]
            if len(failed) > 12:
                lines.append(f"• … et {len(failed) - 12} autre(s).")
            final.add_field(name="Serveurs non réparés", value="\n".join(lines), inline=False)
        else:
            final = embeds.success(
                (
                    f"Tous les serveurs ont été reconstruits : **{len(ok_results)}/{len(results)}**.\n"
                    f"Nouveaux salons : **{created}** • anciens supprimés : **{deleted}** • tests réussis : **{tests}**."
                )
            )

        final.set_footer(text=f"SentriX • reset-logs-all • {elapsed:.1f} s")
        await panels.envoyer(ctx, panels.depuis_embed(final))


async def setup(bot: commands.Bot):
    await bot.add_cog(OwnerLogRebuild(bot))
