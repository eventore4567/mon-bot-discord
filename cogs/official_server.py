"""Serveur officiel SentriX : panneaux live, rôles de notification et journal des serveurs.

Ce module ne crée aucune commande Discord. L'ancien alias ``+sentrix-server`` qui
construisait le serveur officiel via ``+create-server`` a été retiré avec toutes les
commandes de création de serveur ; il reste ici le runtime passif (statut live, rôles
spéciaux, compteur de serveurs) utilisé par les listeners et le dashboard.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

import discord
from discord.ext import commands

from utils import helpers
from utils import sentrix_panels as panels
from . import server_builder


logger = logging.getLogger("bot.official-server")

OFFICIAL_INVITE = "https://discord.gg/5P5Bqjqu5t"
OFFICIAL_GUILD_SETTING = "sentrix_official_guild_id"
RELEASE_GUILD_SETTING = "sentrix_release_announce_guild_id"
RELEASE_CHANNEL_SETTING = "sentrix_release_announce_channel_id"
ACCENT = discord.Color.from_rgb(139, 92, 246)

ROLE_NAMES = {
    "founder": "👑・Fondateur",
    "cofounder": "💠・Co-Fondateur",
    "developer": "🧬・Développeur",
    "staff_manager": "✦・Responsable Staff",
    "admin": "🛡️・Administrateur",
    "moderator": "🔨・Modérateur",
    "trial_moderator": "🧪・Modérateur Test",
    "support": "🎫・Support",
    "animator": "🎉・Animateur",
    "vip": "💎・VIP",
    "booster": "🔥・Booster",
    "partner": "🤝・Partenaire",
    "active": "🏆・Membre Actif",
    "member": "✓・Membre",
    "updates": "📢・Mises à jour",
    "giveaways": "🎁・Giveaways",
    "events": "🎮・Événements",
    "bots": "🤖・Bots",
    "muted": "🔇・Muet",
}

STAFF_ROLE_NAMES = {
    ROLE_NAMES["founder"],
    ROLE_NAMES["cofounder"],
    ROLE_NAMES["developer"],
    ROLE_NAMES["staff_manager"],
    ROLE_NAMES["admin"],
    ROLE_NAMES["moderator"],
    ROLE_NAMES["trial_moderator"],
    ROLE_NAMES["support"],
    ROLE_NAMES["animator"],
}

ROLE_BUTTONS = {
    "updates": (ROLE_NAMES["updates"], "Mises à jour", "📢"),
    "giveaways": (ROLE_NAMES["giveaways"], "Giveaways", "🎁"),
    "events": (ROLE_NAMES["events"], "Événements", "🎮"),
}


def _register_visual_names() -> None:
    """Enrichit le moteur historique sans changer les autres modèles de serveur."""
    server_builder.CATEGORY_EMOJIS.update({
        "INFORMATIONS": "✦",
        "SENTRIX": "⚡",
    })
    server_builder.CHANNEL_EMOJIS.update({
        "annonces-sentrix": "📢",
        "présentation-sentrix": "💜",
        "guide-sentrix": "📚",
        "faq": "❔",
        "rôles": "🎭",
        "commandes-sentrix": "🤖",
        "statut-sentrix": "🟢",
        "serveurs-sentrix": "🌐",
        "bugs-sentrix": "🐞",
        "suggestions-sentrix": "💡",
        "boosters": "💎",
        "giveaways": "🎉",
        "aide-sentrix": "❓",
        "problème-important": "🚨",
        "annonces-staff": "📢",
        "discussion-staff": "💬",
        "bugs-dev": "🐞",
        "logs-tickets": "📋",
    })
    server_builder.CHANNEL_TOPICS.update({
        "annonces-sentrix": "Toutes les annonces et nouvelles versions officielles de SentriX.",
        "présentation-sentrix": "Présentation officielle de SentriX et de ses principales fonctions.",
        "guide-sentrix": "Guide rapide pour installer, configurer et utiliser SentriX.",
        "faq": "Réponses aux questions les plus fréquentes concernant SentriX.",
        "rôles": "Choisissez vos rôles de notifications avec les boutons SentriX.",
        "commandes-sentrix": "Salon prévu pour tester les commandes de SentriX sans encombrer le général.",
        "statut-sentrix": "Dernier état connu de SentriX, actualisé automatiquement.",
        "serveurs-sentrix": "Compteur global des serveurs utilisant actuellement SentriX.",
        "bugs-sentrix": "Signalez un bug reproductible de SentriX avec les informations utiles.",
        "suggestions-sentrix": "Proposez des améliorations et nouvelles fonctions pour SentriX.",
        "boosters": "Remerciements automatiques aux membres qui boostent le serveur.",
        "giveaways": "Giveaways et récompenses officiels de la communauté SentriX.",
        "aide-sentrix": "Aide publique pour les questions simples ne nécessitant aucune donnée privée.",
        "problème-important": "Problèmes urgents ; utilisez un ticket si la demande contient des informations privées.",
        "annonces-staff": "Consignes et informations réservées au staff SentriX.",
        "discussion-staff": "Coordination privée de l'équipe SentriX.",
        "bugs-dev": "Suivi interne des bugs et correctifs en cours.",
        "logs-tickets": "Logs automatiques SentriX : tickets, modération, sécurité et serveur.",
    })
    server_builder.SLOWMODE_DELAYS.update({
        "bugs-sentrix": 15,
        "suggestions-sentrix": 15,
        "aide-sentrix": 5,
        "problème-important": 10,
        "présentations": 10,
    })
    server_builder.STAFF_ROLE_NAMES.update(STAFF_ROLE_NAMES)


class NotificationRoleButton(discord.ui.Button):
    def __init__(self, key: str):
        role_name, label, emoji = ROLE_BUTTONS[key]
        self.role_key = key
        self.role_name = role_name
        super().__init__(
            label=label,
            emoji=emoji,
            style=discord.ButtonStyle.secondary,
            custom_id=f"sentrix:official:role:{key}",
        )

    async def callback(self, interaction: discord.Interaction):
        runtime = getattr(interaction.client, "_sentrix_official_server_runtime", None)
        if runtime is None or interaction.guild is None:
            return await interaction.response.send_message(
                "Le système de rôles SentriX est momentanément indisponible.",
                ephemeral=True,
            )
        if not await runtime.is_official_guild(interaction.guild):
            return await interaction.response.send_message(
                "Ce panneau est réservé au serveur officiel SentriX.",
                ephemeral=True,
            )
        member = interaction.user
        if not isinstance(member, discord.Member):
            return await interaction.response.send_message("Membre introuvable.", ephemeral=True)
        role = discord.utils.get(interaction.guild.roles, name=self.role_name)
        if role is None:
            return await interaction.response.send_message(
                "Le rôle n'existe plus. Recréez-le depuis les paramètres du serveur.",
                ephemeral=True,
            )
        try:
            if role in member.roles:
                await member.remove_roles(role, reason="Rôle notification SentriX retiré par le membre")
                text = f"{role.mention} retiré de votre profil."
            else:
                await member.add_roles(role, reason="Rôle notification SentriX choisi par le membre")
                text = f"{role.mention} ajouté à votre profil."
        except discord.Forbidden:
            text = "Je ne peux pas gérer ce rôle. Placez le rôle SentriX au-dessus des rôles de notifications."
        except discord.HTTPException:
            text = "Discord n'a pas pu modifier votre rôle. Réessayez dans quelques secondes."
        await interaction.response.send_message(text, ephemeral=True)


class NotificationRoleView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        for key in ROLE_BUTTONS:
            self.add_item(NotificationRoleButton(key))


class OfficialServerRuntime:
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.started_at = time.time()
        self._heartbeat_task: asyncio.Task | None = None
        self._official_guild_id: int | None = None
        self._last_guild_count: int | None = None

    async def _get_setting(self, key: str) -> str | None:
        try:
            row = await self.bot.db.fetchone("SELECT value FROM bot_settings WHERE key = ?", (key,))
            if not row:
                return None
            try:
                return str(row["value"])
            except Exception:
                return str(row[0]) if row else None
        except Exception:
            return None

    async def _set_setting(self, key: str, value: Any) -> None:
        await self.bot.db.execute(
            "INSERT OR REPLACE INTO bot_settings (key, value) VALUES (?, ?)",
            (key, str(value)),
        )

    async def official_guild_id(self) -> int | None:
        if self._official_guild_id:
            return self._official_guild_id
        for key in (OFFICIAL_GUILD_SETTING, RELEASE_GUILD_SETTING):
            raw = await self._get_setting(key)
            if raw:
                try:
                    self._official_guild_id = int(raw)
                    return self._official_guild_id
                except ValueError:
                    pass
        try:
            invite = await self.bot.fetch_invite(OFFICIAL_INVITE, with_counts=False)
            guild_id = getattr(getattr(invite, "guild", None), "id", None)
            if guild_id:
                self._official_guild_id = int(guild_id)
                await self._set_setting(OFFICIAL_GUILD_SETTING, guild_id)
                return self._official_guild_id
        except Exception:
            logger.exception("Impossible de résoudre le serveur officiel SentriX depuis l'invitation.")
        return None

    async def is_official_guild(self, guild: discord.Guild) -> bool:
        guild_id = await self.official_guild_id()
        return bool(guild_id and guild.id == guild_id)

    def _find_text(self, guild: discord.Guild, base_name: str) -> discord.TextChannel | None:
        wanted = base_name.casefold()
        for channel in guild.text_channels:
            if server_builder._plain_discord_name(channel.name) == wanted:
                return channel
        return None

    def _find_category(self, guild: discord.Guild, base_name: str) -> discord.CategoryChannel | None:
        return server_builder._find_category(guild, base_name)

    async def _message_pointer(self, key: str) -> tuple[int, int] | None:
        raw = await self._get_setting(f"sentrix_official_msg_{key}")
        if not raw or ":" not in raw:
            return None
        channel_raw, message_raw = raw.split(":", 1)
        try:
            return int(channel_raw), int(message_raw)
        except ValueError:
            return None

    async def _save_message_pointer(self, key: str, channel_id: int, message_id: int) -> None:
        await self._set_setting(f"sentrix_official_msg_{key}", f"{channel_id}:{message_id}")

    async def _upsert_message(
        self,
        channel: discord.TextChannel | None,
        key: str,
        embed: discord.Embed,
        *,
        view: discord.ui.View | None = None,
        preserve_manual: bool = False,
    ) -> discord.Message | None:
        if channel is None:
            return None
        pointer = await self._message_pointer(key)
        if pointer and pointer[0] == channel.id:
            try:
                message = await channel.fetch_message(pointer[1])
                await panels.editer(message, panels.avec_composants(panels.depuis_embed(embed), view))
                return message
            except discord.HTTPException:
                pass
        if preserve_manual:
            try:
                async for existing in channel.history(limit=10):
                    if self.bot.user and existing.author.id != self.bot.user.id:
                        return None
            except discord.HTTPException:
                pass
        message = await panels.envoyer(channel, panels.avec_composants(panels.depuis_embed(embed), view))
        try:
            await self._save_message_pointer(key, channel.id, message.id)
        except Exception:
            logger.exception("Impossible d'enregistrer le message officiel %s.", key)
        return message

    async def _prefix(self, guild: discord.Guild) -> str:
        try:
            conf = await self.bot.db.get_guild_config(guild.id)
            value = conf["prefix"] if conf and conf["prefix"] else "+"
            return str(value)
        except Exception:
            return "+"

    def _base_embed(self, title: str, description: str, *, colour: discord.Color | None = None) -> discord.Embed:
        embed = discord.Embed(
            title=title,
            description=description,
            colour=colour or ACCENT,
            timestamp=datetime.now(timezone.utc),
        )
        if self.bot.user:
            embed.set_author(name="SentriX", icon_url=self.bot.user.display_avatar.url)
        embed.set_footer(text="SentriX • Serveur officiel")
        return embed

    def _status_embed(self) -> discord.Embed:
        latency = helpers.latence_ms(self.bot)
        if latency < 250:
            label = "🟢 Opérationnel"
            colour = discord.Color.from_rgb(34, 197, 94)
        elif latency < 600:
            label = "🟠 Latence élevée"
            colour = discord.Color.from_rgb(245, 158, 11)
        else:
            label = "🔴 Dégradé"
            colour = discord.Color.from_rgb(239, 68, 68)
        now_ts = int(time.time())
        uptime = max(0, now_ts - int(self.started_at))
        hours, remainder = divmod(uptime, 3600)
        minutes = remainder // 60
        sha = str(os.getenv("RAILWAY_GIT_COMMIT_SHA") or "local").strip()
        embed = self._base_embed(
            "✦ Statut de SentriX",
            "État automatiquement actualisé. Si SentriX devient totalement hors ligne, le dernier horodatage permet de voir quand le dernier contrôle a réussi.",
            colour=colour,
        )
        embed.add_field(name="État", value=label, inline=True)
        embed.add_field(name="Latence", value=f"{latency} ms", inline=True)
        embed.add_field(name="Version", value=f"`{sha[:8]}`", inline=True)
        embed.add_field(name="Uptime", value=f"{hours} h {minutes:02d} min", inline=True)
        embed.add_field(name="Dernier contrôle", value=f"<t:{now_ts}:R>", inline=True)
        embed.add_field(name="Gateway", value="Connectée" if self.bot.is_ready() else "Connexion…", inline=True)
        return embed

    def _servers_embed(self) -> discord.Embed:
        guild_count = len(self.bot.guilds)
        members = sum(int(guild.member_count or 0) for guild in self.bot.guilds)
        delta = None if self._last_guild_count is None else guild_count - self._last_guild_count
        self._last_guild_count = guild_count
        embed = self._base_embed(
            "✦ SentriX sur Discord",
            "Ce compteur indique combien de serveurs utilisent actuellement SentriX. Il se met à jour automatiquement lorsqu'un serveur ajoute ou retire le bot.",
        )
        embed.add_field(name="Serveurs", value=f"**{guild_count}**", inline=True)
        embed.add_field(name="Membres desservis", value=f"**{members:,}**".replace(",", " "), inline=True)
        if delta is not None and delta != 0:
            embed.add_field(name="Dernière variation", value=f"{delta:+d} serveur", inline=True)
        else:
            embed.add_field(name="Synchronisation", value="À jour", inline=True)
        embed.add_field(
            name="Confidentialité",
            value="Le compteur publie uniquement des totaux : il n'affiche pas publiquement la liste ni les informations privées des autres serveurs.",
            inline=False,
        )
        return embed

    async def refresh_live_panels(self) -> None:
        guild_id = await self.official_guild_id()
        if not guild_id:
            return
        guild = self.bot.get_guild(guild_id)
        if guild is None:
            return
        status_channel = self._find_text(guild, "statut-sentrix")
        servers_channel = self._find_text(guild, "serveurs-sentrix")
        if status_channel:
            await self._upsert_message(status_channel, "live_status", self._status_embed())
        if servers_channel:
            await self._upsert_message(servers_channel, "server_counter", self._servers_embed())

    async def _sync_special_roles(self, guild: discord.Guild) -> None:
        booster_role = discord.utils.get(guild.roles, name=ROLE_NAMES["booster"])
        bots_role = discord.utils.get(guild.roles, name=ROLE_NAMES["bots"])
        me = guild.me
        if me is None:
            return
        for member in guild.members:
            try:
                if member.bot and bots_role and bots_role not in member.roles and bots_role < me.top_role:
                    await member.add_roles(bots_role, reason="Rôle Bots SentriX automatique")
                if member.premium_since and booster_role and booster_role not in member.roles and booster_role < me.top_role:
                    await member.add_roles(booster_role, reason="Rôle Booster SentriX automatique")
            except discord.HTTPException:
                continue

    async def on_ready(self) -> None:
        if self._heartbeat_task is None or self._heartbeat_task.done():
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        try:
            await self.refresh_live_panels()
            guild_id = await self.official_guild_id()
            guild = self.bot.get_guild(guild_id) if guild_id else None
            if guild:
                await self._sync_special_roles(guild)
        except Exception:
            logger.exception("Impossible d'actualiser le serveur officiel au READY.")

    async def _heartbeat_loop(self) -> None:
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            try:
                await self.refresh_live_panels()
            except Exception:
                logger.exception("Échec de l'actualisation automatique du statut SentriX.")
            await asyncio.sleep(180)

    async def on_guild_join(self, guild: discord.Guild) -> None:
        try:
            await self.refresh_live_panels()
        except Exception:
            logger.exception("Impossible d'actualiser le compteur après ajout sur un serveur.")

    async def on_guild_remove(self, guild: discord.Guild) -> None:
        try:
            await self.refresh_live_panels()
        except Exception:
            logger.exception("Impossible d'actualiser le compteur après retrait d'un serveur.")

    async def on_member_join(self, member: discord.Member) -> None:
        if not await self.is_official_guild(member.guild):
            return
        if not member.bot:
            return
        role = discord.utils.get(member.guild.roles, name=ROLE_NAMES["bots"])
        if role and member.guild.me and role < member.guild.me.top_role:
            try:
                await member.add_roles(role, reason="Rôle Bots SentriX automatique")
            except discord.HTTPException:
                pass

    async def on_member_update(self, before: discord.Member, after: discord.Member) -> None:
        if not await self.is_official_guild(after.guild):
            return
        booster_role = discord.utils.get(after.guild.roles, name=ROLE_NAMES["booster"])
        if booster_role is None or after.guild.me is None or booster_role >= after.guild.me.top_role:
            return
        started = before.premium_since is None and after.premium_since is not None
        stopped = before.premium_since is not None and after.premium_since is None
        if not started and not stopped:
            return
        try:
            if started and booster_role not in after.roles:
                await after.add_roles(booster_role, reason="Boost du serveur officiel SentriX")
            elif stopped and booster_role in after.roles:
                await after.remove_roles(booster_role, reason="Fin du boost du serveur officiel SentriX")
        except discord.HTTPException:
            logger.exception("Impossible de synchroniser le rôle Booster de %s", after.id)
            return
        if started:
            channel = self._find_text(after.guild, "boosters")
            if channel:
                embed = self._base_embed(
                    "✦ Nouveau Booster",
                    f"Merci {after.mention} d'avoir boosté **{after.guild.name}** ! 💜\n"
                    f"Le rôle **{ROLE_NAMES['booster']}** vient de vous être attribué automatiquement.",
                    colour=discord.Color.from_rgb(244, 114, 182),
                )
                try:
                    await panels.envoyer(channel, panels.depuis_embed(embed), allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False))
                except discord.HTTPException:
                    logger.exception("Impossible de publier le remerciement Booster.")


def install(bot: commands.Bot) -> None:
    """Installe le runtime une seule fois (panneaux live, rôles spéciaux, journal des serveurs)."""
    _register_visual_names()
    runtime = getattr(bot, "_sentrix_official_server_runtime", None)
    if runtime is None:
        runtime = OfficialServerRuntime(bot)
        bot._sentrix_official_server_runtime = runtime
        try:
            bot.add_view(NotificationRoleView())
        except Exception:
            logger.exception("Impossible d'enregistrer la vue persistante des rôles SentriX.")
        bot.add_listener(runtime.on_ready, "on_ready")
        bot.add_listener(runtime.on_guild_join, "on_guild_join")
        bot.add_listener(runtime.on_guild_remove, "on_guild_remove")
        bot.add_listener(runtime.on_member_join, "on_member_join")
        bot.add_listener(runtime.on_member_update, "on_member_update")
        logger.info("Runtime du serveur officiel SentriX installé.")
