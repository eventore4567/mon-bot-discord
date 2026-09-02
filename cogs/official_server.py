"""Serveur officiel SentriX : installation complète en une commande.

Ce module ne crée aucune nouvelle commande Discord. Il ajoute l'alias texte
``+sentrix-server`` à la commande existante ``+create-server`` afin de ne pas augmenter
le registre de commandes/slash déjà chargé. L'alias est strictement limité au serveur
correspondant à l'invitation officielle configurée.

L'installation est idempotente et non destructive : rôles, catégories et salons portant
les noms attendus sont réutilisés et mis à jour, mais aucun salon ou rôle étranger n'est
supprimé automatiquement.
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

from utils import embeds, helpers
from utils import sentrix_panels as panels
from . import server_builder


logger = logging.getLogger("bot.official-server")

OFFICIAL_INVITE = "https://discord.gg/5P5Bqjqu5t"
OFFICIAL_GUILD_SETTING = "sentrix_official_guild_id"
RELEASE_GUILD_SETTING = "sentrix_release_announce_guild_id"
RELEASE_CHANNEL_SETTING = "sentrix_release_announce_channel_id"
OFFICIAL_ALIASES = {"sentrix-server", "setup-sentrix"}
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

RESP_STAFF_PERMISSIONS = discord.Permissions(
    view_audit_log=True,
    manage_roles=True,
    manage_channels=True,
    kick_members=True,
    ban_members=True,
    moderate_members=True,
    manage_messages=True,
    manage_threads=True,
    manage_nicknames=True,
    move_members=True,
    mute_members=True,
    deafen_members=True,
)

DEVELOPER_PERMISSIONS = discord.Permissions(
    view_audit_log=True,
    manage_guild=True,
    manage_roles=True,
    manage_channels=True,
    manage_messages=True,
    manage_threads=True,
    manage_webhooks=True,
)

OFFICIAL_ROLES = [
    server_builder._role(ROLE_NAMES["founder"], discord.Color.from_rgb(255, 59, 107), server_builder.FOUNDER_PERMISSIONS, hoist=True),
    server_builder._role(ROLE_NAMES["cofounder"], discord.Color.from_rgb(217, 70, 239), server_builder.FOUNDER_PERMISSIONS, hoist=True),
    server_builder._role(ROLE_NAMES["developer"], discord.Color.from_rgb(139, 92, 246), DEVELOPER_PERMISSIONS, hoist=True),
    server_builder._role(ROLE_NAMES["staff_manager"], discord.Color.from_rgb(255, 138, 61), RESP_STAFF_PERMISSIONS, hoist=True),
    server_builder._role(ROLE_NAMES["admin"], discord.Color.from_rgb(239, 68, 68), server_builder.ADMIN_PERMISSIONS, hoist=True),
    server_builder._role(ROLE_NAMES["moderator"], discord.Color.from_rgb(59, 130, 246), server_builder.MODERATOR_PERMISSIONS, hoist=True),
    server_builder._role(ROLE_NAMES["trial_moderator"], discord.Color.from_rgb(96, 165, 250), server_builder.TRIAL_MODERATOR_PERMISSIONS, hoist=True),
    server_builder._role(ROLE_NAMES["support"], discord.Color.from_rgb(34, 211, 238), server_builder.SUPPORT_PERMISSIONS, hoist=True),
    server_builder._role(ROLE_NAMES["animator"], discord.Color.from_rgb(250, 204, 21), server_builder.EVENT_MANAGER_PERMISSIONS, hoist=True),
    server_builder._role(ROLE_NAMES["vip"], discord.Color.from_rgb(168, 85, 247), hoist=True),
    server_builder._role(ROLE_NAMES["booster"], discord.Color.from_rgb(244, 114, 182), hoist=True),
    server_builder._role(ROLE_NAMES["partner"], discord.Color.from_rgb(20, 184, 166), hoist=True),
    server_builder._role(ROLE_NAMES["active"], discord.Color.from_rgb(34, 197, 94), hoist=True),
    server_builder._role(ROLE_NAMES["member"], discord.Color.from_rgb(110, 231, 183)),
    server_builder._role(ROLE_NAMES["updates"], discord.Color.from_rgb(139, 92, 246)),
    server_builder._role(ROLE_NAMES["giveaways"], discord.Color.from_rgb(245, 158, 11)),
    server_builder._role(ROLE_NAMES["events"], discord.Color.from_rgb(59, 130, 246)),
    server_builder._role(ROLE_NAMES["bots"], discord.Color.from_rgb(75, 85, 99)),
    server_builder._role(ROLE_NAMES["muted"], discord.Color.from_rgb(55, 65, 81)),
]

OFFICIAL_CATEGORIES = [
    {
        "name": "INFORMATIONS",
        "privacy": "public",
        "channels": [
            ("règlement", "readonly"),
            ("annonces-sentrix", "readonly"),
            ("présentation-sentrix", "readonly"),
            ("guide-sentrix", "readonly"),
            ("faq", "readonly"),
            ("rôles", "readonly"),
        ],
    },
    {
        "name": "SENTRIX",
        "privacy": "public",
        "channels": [
            ("commandes-sentrix", "text"),
            ("statut-sentrix", "readonly"),
            ("serveurs-sentrix", "readonly"),
            ("bugs-sentrix", "text"),
            ("suggestions-sentrix", "text"),
        ],
    },
    {
        "name": "COMMUNAUTÉ",
        "privacy": "public",
        "channels": [
            ("général", "text"),
            ("présentations", "text"),
            ("boosters", "readonly"),
            ("giveaways", "readonly"),
        ],
    },
    {
        "name": "SUPPORT",
        "privacy": "public",
        "channels": [
            ("ouvrir-un-ticket", "readonly"),
            ("aide-sentrix", "text"),
            ("problème-important", "text"),
        ],
    },
    {
        "name": "VOCAUX",
        "privacy": "public",
        "channels": [
            ("Général", "voice"),
            ("Support", "voice"),
            ("AFK", "voice"),
        ],
    },
    {
        "name": "STAFF",
        "privacy": "staff",
        "channels": [
            ("annonces-staff", "readonly"),
            ("discussion-staff", "text"),
            ("bugs-dev", "text"),
            ("logs-tickets", "readonly"),
        ],
    },
    {
        "name": "TICKETS OUVERTS",
        "privacy": "staff",
        "channels": [],
    },
]

OFFICIAL_TEMPLATE = {
    "label": "Serveur officiel SentriX",
    "description": "Serveur officiel, support, communauté, statut live, annonces et rôles automatiques.",
    "roles": OFFICIAL_ROLES,
    "staff_role_name": ROLE_NAMES["support"],
    "member_role_name": ROLE_NAMES["member"],
    "categories": OFFICIAL_CATEGORIES,
    "accent": ACCENT,
}

TICKET_TYPES = [
    {
        "name": "Support SentriX",
        "description": "Question ou aide pour utiliser et configurer SentriX.",
        "button_style": "bleu",
        "name_format": "support-{pseudo}",
        "open_message": "Expliquez votre demande et indiquez la commande ou la fonction concernée.",
    },
    {
        "name": "Bug technique",
        "description": "Une commande ne fonctionne pas ou produit une erreur.",
        "button_style": "rouge",
        "name_format": "bug-{pseudo}",
        "open_message": "Décrivez le bug, la commande utilisée et joignez une capture si possible.",
    },
    {
        "name": "Sécurité / problème important",
        "description": "Signaler un problème sérieux nécessitant une prise en charge privée.",
        "button_style": "gris",
        "name_format": "securite-{pseudo}",
        "open_message": "Expliquez les faits sans publier d'informations sensibles dans un salon public.",
    },
    {
        "name": "Autre demande",
        "description": "Toute demande qui ne correspond pas aux autres catégories.",
        "button_style": "vert",
        "name_format": "demande-{pseudo}",
        "open_message": "Décrivez précisément votre demande afin que le support puisse vous orienter.",
    },
]

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
                "Le rôle n'existe plus. Relancez `+sentrix-server` pour le recréer.",
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

    async def _configure_guild_settings(
        self,
        guild: discord.Guild,
        role_map: dict[str, discord.Role],
        category_map: dict[str, discord.CategoryChannel],
        channel_map: dict[str, discord.abc.GuildChannel],
    ) -> int:
        settings: dict[str, Any] = {
            "mod_role": role_map.get(ROLE_NAMES["moderator"]),
            "admin_role": role_map.get(ROLE_NAMES["admin"]),
            "autorole": role_map.get(ROLE_NAMES["member"]),
            "member_role": role_map.get(ROLE_NAMES["member"]),
            "booster_role": role_map.get(ROLE_NAMES["booster"]),
            "mute_role": role_map.get(ROLE_NAMES["muted"]),
            "rules_channel": channel_map.get("règlement"),
            "announce_channel": channel_map.get("annonces-sentrix"),
            "suggest_channel": channel_map.get("suggestions-sentrix"),
            "giveaway_channel": channel_map.get("giveaways"),
            "bot_commands_channel": channel_map.get("commandes-sentrix"),
            "report_channel": channel_map.get("problème-important"),
            "stats_channel": channel_map.get("statut-sentrix"),
            "error_channel": channel_map.get("logs-tickets"),
            "log_channel": channel_map.get("logs-tickets"),
            "ticket_log_channel": channel_map.get("logs-tickets"),
            "ticket_category": category_map.get("TICKETS OUVERTS"),
            "log_server": channel_map.get("logs-tickets"),
            "log_messages": channel_map.get("logs-tickets"),
            "log_members": channel_map.get("logs-tickets"),
            "log_voice": channel_map.get("logs-tickets"),
            "log_roles": channel_map.get("logs-tickets"),
            "log_moderation": channel_map.get("logs-tickets"),
            "log_automod": channel_map.get("logs-tickets"),
        }
        configured = 0
        for setting, target in settings.items():
            if target is None:
                continue
            await self.bot.db.set_guild_config(guild.id, setting, target.id)
            configured += 1
        announce = channel_map.get("annonces-sentrix")
        if isinstance(announce, discord.TextChannel):
            await self._set_setting(OFFICIAL_GUILD_SETTING, guild.id)
            await self._set_setting(RELEASE_GUILD_SETTING, guild.id)
            await self._set_setting(RELEASE_CHANNEL_SETTING, announce.id)
            self._official_guild_id = guild.id
        return configured

    async def _configure_tickets(
        self,
        guild: discord.Guild,
        role_map: dict[str, discord.Role],
        category_map: dict[str, discord.CategoryChannel],
        channel_map: dict[str, discord.abc.GuildChannel],
    ) -> str:
        ticket_cog = self.bot.get_cog("Tickets")
        panel_channel = channel_map.get("ouvrir-un-ticket")
        ticket_category = category_map.get("TICKETS OUVERTS")
        log_channel = channel_map.get("logs-tickets")
        support_role = role_map.get(ROLE_NAMES["support"])
        if ticket_cog is None:
            return "module Tickets indisponible"
        if not isinstance(panel_channel, discord.TextChannel) or ticket_category is None or support_role is None:
            return "salon, catégorie ou rôle support introuvable"

        panel_name = "Support SentriX officiel"
        panel = await ticket_cog.get_panel_by_name(guild.id, panel_name)
        if panel is None:
            panel_id = await ticket_cog.create_panel(guild.id, panel_name)
            previous_channel_id = None
            previous_message_id = None
        else:
            panel_id = panel["id"]
            previous_channel_id = panel["channel_id"]
            previous_message_id = panel["message_id"]

        await self.bot.db.execute(
            "UPDATE ticket_panels_v2 SET title = ?, description = ?, color = ?, "
            "footer_text = ?, style = ?, enabled = 1, channel_id = ? WHERE id = ?",
            (
                "✦ Support SentriX",
                "Choisissez le type de demande. Les informations sensibles doivent rester dans le ticket privé.",
                ACCENT.value,
                "SentriX • Support officiel",
                "button",
                panel_channel.id,
                panel_id,
            ),
        )

        existing_types = await ticket_cog.get_panel_types(panel_id)
        log_channel_id = log_channel.id if isinstance(log_channel, discord.TextChannel) else None
        for position, type_data in enumerate(TICKET_TYPES):
            if position < len(existing_types):
                type_id = existing_types[position]["id"]
            else:
                type_id = await ticket_cog.add_type(guild.id, panel_id, type_data["name"])
            await self.bot.db.execute(
                "UPDATE ticket_types SET name = ?, description = ?, emoji = NULL, button_label = ?, "
                "button_style = ?, staff_role_id = ?, category_id = ?, name_format = ?, "
                "open_message = ?, max_per_member = 1, autoclose_hours = 72, "
                "log_channel_id = ?, mention_staff = 1, use_form = 0, position = ? WHERE id = ?",
                (
                    type_data["name"],
                    type_data["description"],
                    type_data["name"],
                    type_data["button_style"],
                    support_role.id,
                    ticket_category.id,
                    type_data["name_format"],
                    type_data["open_message"],
                    log_channel_id,
                    position,
                    type_id,
                ),
            )

        from cogs.tickets import TicketPanelView

        panel = await ticket_cog.get_panel(panel_id)
        ticket_types = await ticket_cog.get_panel_types(panel_id)
        view = TicketPanelView(panel, ticket_types)
        old_message = None
        old_channel = guild.get_channel(previous_channel_id) if previous_channel_id else None
        if previous_message_id and isinstance(old_channel, discord.TextChannel):
            try:
                old_message = await old_channel.fetch_message(previous_message_id)
            except discord.HTTPException:
                old_message = None
        if old_message and old_channel.id == panel_channel.id:
            await old_message.edit(embed=ticket_cog.build_panel_embed(panel), view=view)
            message = old_message
        else:
            if old_message:
                try:
                    await old_message.delete()
                except discord.HTTPException:
                    pass
            message = await panels.envoyer(panel_channel, panels.avec_composants(panels.depuis_embed(ticket_cog.build_panel_embed(panel)), view))
        await self.bot.db.execute(
            "UPDATE ticket_panels_v2 SET message_id = ?, channel_id = ? WHERE id = ?",
            (message.id, panel_channel.id, panel_id),
        )
        return f"{len(TICKET_TYPES)} types de tickets configurés"

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

    async def _publish_static_content(
        self,
        guild: discord.Guild,
        channel_map: dict[str, discord.abc.GuildChannel],
    ) -> int:
        prefix = await self._prefix(guild)
        published = 0

        rules = self._base_embed(
            "✦ Règlement",
            "**1. Respect** — Aucun harcèlement, insulte, haine ou menace.\n"
            "**2. Sécurité** — Aucun scam, phishing, fichier suspect ou tentative de contournement.\n"
            "**3. Vie privée** — Ne publiez jamais de données personnelles ou confidentielles.\n"
            "**4. Publicité** — Pas de spam, flood ou publicité non autorisée.\n"
            "**5. Salons** — Utilisez le salon adapté et ouvrez un ticket pour les demandes privées.\n"
            "**6. Staff** — Respectez les décisions du staff ; un recours se fait calmement par ticket.\n"
            "**7. Discord** — Les Conditions d'utilisation et règles de Discord restent applicables.",
        )
        if await self._upsert_message(channel_map.get("règlement"), "rules", rules, preserve_manual=True):
            published += 1

        presentation = self._base_embed(
            "✦ Bienvenue sur SentriX",
            "**SentriX** est un bot Discord tout-en-un conçu pour gérer, protéger et animer un serveur depuis une seule interface.\n\n"
            "🛡️ **Modération & sécurité** — sanctions, anti-spam, anti-liens, anti-raid, anti-nuke et audits.\n"
            "🎫 **Tickets** — support privé avec catégories, claim, fermeture et logs.\n"
            "🎮 **Communauté** — niveaux, économie, jeux, événements, giveaways et profils.\n"
            "🤖 **IA & utilitaires** — assistance, images, recherches et outils quotidiens.\n"
            "⚙️ **Configuration** — la majorité des fonctions se règlent avec des panneaux simples.\n\n"
            f"Commencez avec **`{prefix}help`** ou utilisez les commandes slash `/`.",
        )
        if self.bot.user:
            presentation.set_thumbnail(url=self.bot.user.display_avatar.url)
        presentation.add_field(name="Serveurs connectés", value=str(len(self.bot.guilds)), inline=True)
        presentation.add_field(name="Commandes texte", value=str(len(self.bot.commands)), inline=True)
        presentation.add_field(name="Préfixe ici", value=f"`{prefix}`", inline=True)
        if await self._upsert_message(channel_map.get("présentation-sentrix"), "presentation", presentation):
            published += 1

        commands_channel = channel_map.get("commandes-sentrix")
        ticket_channel = channel_map.get("ouvrir-un-ticket")
        bug_channel = channel_map.get("bugs-sentrix")
        suggestion_channel = channel_map.get("suggestions-sentrix")
        guide = self._base_embed(
            "✦ Guide rapide SentriX",
            f"**1. Découvrir les commandes**\nTapez `{prefix}help` et choisissez la catégorie voulue.\n\n"
            f"**2. Tester le bot**\nUtilisez {commands_channel.mention if isinstance(commands_channel, discord.TextChannel) else 'le salon commandes'}.\n\n"
            f"**3. Besoin d'aide privée**\nOuvrez un ticket dans {ticket_channel.mention if isinstance(ticket_channel, discord.TextChannel) else 'le support'}.\n\n"
            f"**4. Trouvé un bug ?**\nExpliquez-le dans {bug_channel.mention if isinstance(bug_channel, discord.TextChannel) else 'le salon bugs'} avec la commande et une capture.\n\n"
            f"**5. Une idée ?**\nProposez-la dans {suggestion_channel.mention if isinstance(suggestion_channel, discord.TextChannel) else 'le salon suggestions'}.",
        )
        if await self._upsert_message(channel_map.get("guide-sentrix"), "guide", guide):
            published += 1

        faq = self._base_embed(
            "✦ Questions fréquentes",
            f"**Comment voir les commandes ?**\n`{prefix}help` ou `/help`.\n\n"
            "**Une commande ne répond pas ?**\nVérifiez les permissions du bot puis signalez le bug avec une capture.\n\n"
            "**Comment configurer SentriX ?**\nUtilisez le panneau de configuration prévu par le bot.\n\n"
            "**Comment demander de l'aide sans montrer mes informations ?**\nUtilisez un ticket privé.\n\n"
            "**Les mises à jour sont annoncées où ?**\nDans `#📢・annonces-sentrix`, automatiquement après les nouveaux déploiements.",
        )
        if await self._upsert_message(channel_map.get("faq"), "faq", faq):
            published += 1

        roles = self._base_embed(
            "✦ Vos rôles de notifications",
            "Choisissez uniquement les notifications que vous souhaitez recevoir. Cliquez à nouveau sur un bouton pour retirer le rôle.\n\n"
            "📢 **Mises à jour** — nouvelles versions et changements importants.\n"
            "🎁 **Giveaways** — concours et récompenses.\n"
            "🎮 **Événements** — animations et événements communautaires.\n\n"
            "Les rôles VIP, Booster, Partenaire et staff ne peuvent pas être obtenus avec ces boutons.",
        )
        if await self._upsert_message(channel_map.get("rôles"), "roles", roles, view=NotificationRoleView()):
            published += 1

        announcements = self._base_embed(
            "✦ Annonces officielles SentriX",
            "Ce salon reçoit les informations importantes et les nouvelles versions de SentriX. "
            "Les mises à jour techniques sont publiées automatiquement avec leur résumé et leur statut de déploiement.",
        )
        if await self._upsert_message(channel_map.get("annonces-sentrix"), "announcements_intro", announcements):
            published += 1

        bugs = self._base_embed(
            "✦ Signaler un bug",
            "Pour qu'un bug puisse être corrigé rapidement, indiquez **la commande**, **ce que vous vouliez faire**, "
            "**ce qui s'est passé** et ajoutez une capture si possible. Ne publiez jamais de token ou donnée privée.",
        )
        if await self._upsert_message(channel_map.get("bugs-sentrix"), "bugs_guide", bugs):
            published += 1

        suggestions = self._base_embed(
            "✦ Proposer une amélioration",
            "Décrivez votre idée simplement : **fonction souhaitée**, **problème résolu** et, si utile, un exemple. "
            "Une suggestion claire est beaucoup plus facile à étudier et à développer.",
        )
        if await self._upsert_message(channel_map.get("suggestions-sentrix"), "suggestions_guide", suggestions):
            published += 1

        help_embed = self._base_embed(
            "✦ Aide SentriX",
            f"Posez ici les questions simples sur les commandes et la configuration. Pour une demande privée, "
            f"utilisez {ticket_channel.mention if isinstance(ticket_channel, discord.TextChannel) else 'le panneau de tickets'}.\n\n"
            f"Avant de demander de l'aide, essayez aussi `{prefix}help`.",
        )
        if await self._upsert_message(channel_map.get("aide-sentrix"), "help_guide", help_embed):
            published += 1

        important = self._base_embed(
            "✦ Problème important",
            "Ce salon sert à signaler rapidement un dysfonctionnement important. **Ne publiez aucune information privée ici.** "
            "Pour un problème de sécurité, une sanction, un compte ou toute donnée sensible, ouvrez directement un ticket.",
            colour=discord.Color.from_rgb(239, 68, 68),
        )
        if await self._upsert_message(channel_map.get("problème-important"), "important_guide", important):
            published += 1

        boosters = self._base_embed(
            "✦ Merci aux Boosters",
            "Chaque boost aide le serveur officiel SentriX à améliorer sa qualité. Lorsqu'un membre booste le serveur, "
            f"SentriX lui attribue automatiquement le rôle **{ROLE_NAMES['booster']}** et publie un remerciement ici.",
            colour=discord.Color.from_rgb(244, 114, 182),
        )
        if await self._upsert_message(channel_map.get("boosters"), "boosters_intro", boosters):
            published += 1

        giveaways = self._base_embed(
            "✦ Giveaways SentriX",
            "Les concours officiels seront publiés ici. Activez le rôle **🎁・Giveaways** dans le salon des rôles si vous souhaitez être notifié.",
            colour=discord.Color.from_rgb(245, 158, 11),
        )
        if await self._upsert_message(channel_map.get("giveaways"), "giveaways_intro", giveaways):
            published += 1

        staff = self._base_embed(
            "✦ Espace Staff SentriX",
            "Cette catégorie est privée. Utilisez `#discussion-staff` pour la coordination, `#bugs-dev` pour les problèmes techniques "
            "et `#logs-tickets` pour le suivi automatique. Les décisions sensibles ne doivent pas être recopiées dans les salons publics.",
        )
        if await self._upsert_message(channel_map.get("annonces-staff"), "staff_intro", staff):
            published += 1

        return published

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

    async def build_official_server(
        self,
        guild: discord.Guild,
        author: discord.Member,
        builder: server_builder.ServerBuilder,
    ) -> discord.Embed:
        if not await self.is_official_guild(guild):
            return embeds.error(
                "`+sentrix-server` est verrouillée sur le **serveur officiel SentriX**. "
                "Elle ne peut pas installer cette structure sur un autre serveur."
            )
        me = guild.me
        if me is None or not me.guild_permissions.administrator:
            return embeds.error(
                "SentriX doit avoir **Administrateur** pendant l'installation et son rôle doit être placé au-dessus "
                "des rôles qu'il doit créer/gérer. Aucun élément ne sera supprimé automatiquement."
            )

        capacity_error = builder._capacity_error(guild, OFFICIAL_TEMPLATE)
        if capacity_error:
            return embeds.error(capacity_error)
        reason = f"Installation du serveur officiel SentriX demandée par {author}"

        builder._build_step = "création des rôles officiels SentriX"
        role_map, roles_created, roles_updated = await builder._ensure_roles(guild, OFFICIAL_TEMPLATE, reason)
        # Le moteur historique cherche la clé « Muet » dans le dictionnaire ; on lui donne
        # un alias vers le rôle stylé sans créer un deuxième rôle visible.
        if ROLE_NAMES["muted"] in role_map:
            role_map["Muet"] = role_map[ROLE_NAMES["muted"]]

        builder._build_step = "création des catégories et salons officiels"
        (
            category_map,
            channel_map,
            categories_created,
            categories_updated,
            channels_created,
            channels_updated,
        ) = await builder._ensure_structure(guild, OFFICIAL_TEMPLATE, role_map, reason)

        builder._build_step = "liaison des fonctions SentriX"
        settings_count = await self._configure_guild_settings(guild, role_map, category_map, channel_map)

        builder._build_step = "installation du panneau de tickets"
        try:
            ticket_status = await self._configure_tickets(guild, role_map, category_map, channel_map)
        except Exception:
            logger.exception("Échec de la configuration du panneau de tickets officiel.")
            ticket_status = "à vérifier : erreur pendant la configuration des tickets"

        builder._build_step = "publication des panneaux officiels"
        messages_count = await self._publish_static_content(guild, channel_map)

        builder._build_step = "synchronisation des Boosters et Bots"
        await self._sync_special_roles(guild)
        await self.refresh_live_panels()

        total_channels = sum(len(category["channels"]) for category in OFFICIAL_CATEGORIES)
        result = embeds.success(
            f"**{guild.name}** est maintenant configuré comme serveur officiel SentriX.\n\n"
            f"**Rôles :** {len(OFFICIAL_ROLES)} prévus — {roles_created} créé(s), {roles_updated} mis à jour.\n"
            f"**Structure :** {len(OFFICIAL_CATEGORIES)} catégories, {total_channels} salons — "
            f"{categories_created} catégorie(s) créée(s), {categories_updated} mise(s) à jour, "
            f"{channels_created} salon(s) créé(s), {channels_updated} mis à jour.\n"
            f"**Réglages SentriX :** {settings_count} liaisons automatiques.\n"
            f"**Panneaux/Guides :** {messages_count} message(s) créé(s) ou restauré(s).\n"
            f"**Tickets :** {ticket_status}.\n\n"
            "Le statut, le compteur de serveurs et les Boosters continueront ensuite à se mettre à jour automatiquement. "
            "Vous pouvez relancer la commande plus tard : elle met à jour l'installation sans supprimer vos salons personnels.",
            title="Serveur SentriX prêt",
        )
        result.add_field(
            name="Automatisations actives",
            value=(
                "• mises à jour automatiques dans `#📢・annonces-sentrix`\n"
                "• statut SentriX actualisé automatiquement\n"
                "• compteur global des serveurs\n"
                "• rôle + message Booster automatiques\n"
                "• boutons de rôles notifications\n"
                "• panneau de tickets + logs"
            ),
            inline=False,
        )
        return result

    async def run_official_command(self, ctx: commands.Context) -> None:
        if ctx.guild is None or not isinstance(ctx.author, discord.Member):
            await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Cette commande doit être lancée dans le serveur officiel SentriX.')))
            return
        if not await self.is_official_guild(ctx.guild):
            await panels.envoyer(ctx, panels.depuis_embed(embeds.error("Cette commande est réservée au serveur officiel SentriX lié à l'invitation configurée.")))
            return
        builder = self.bot.get_cog("ServerBuilder")
        if builder is None:
            await panels.envoyer(ctx, panels.depuis_embed(embeds.error("Le module de création de serveur n'est pas encore chargé.")))
            return
        progress = await panels.envoyer(ctx, panels.depuis_embed(embeds.neutral('Installation SentriX en cours', "Je configure les rôles, permissions, salons, tickets, guides, statut, compteur de serveurs et automatisations. Ne supprimez aucun salon pendant l'installation.")))
        try:
            summary = await self.build_official_server(ctx.guild, ctx.author, builder)
        except discord.Forbidden:
            logger.exception("Permission refusée pendant +sentrix-server")
            summary = embeds.error(
                f"Discord a refusé l'étape **{builder._build_step}**. Placez le rôle SentriX au-dessus des rôles à gérer "
                "et vérifiez la permission Administrateur, puis relancez la commande."
            )
        except discord.HTTPException as exc:
            logger.exception("Erreur Discord pendant +sentrix-server")
            summary = embeds.error(
                f"Discord a interrompu l'étape **{builder._build_step}** : `{str(exc)[:250]}`. "
                "Les éléments déjà créés restent en place ; relancez la commande pour reprendre sans doublons."
            )
        except Exception as exc:
            logger.exception("Erreur inattendue pendant +sentrix-server")
            summary = embeds.error(
                f"L'installation s'est arrêtée pendant **{builder._build_step}** (`{exc.__class__.__name__}`). "
                "Aucun nettoyage destructif n'est lancé ; vous pouvez corriger le problème puis relancer la commande."
            )
        try:
            await panels.editer(progress, panels.depuis_embed(summary))
        except discord.HTTPException:
            await panels.envoyer(ctx, panels.depuis_embed(summary))

    def patch_create_server_alias(self) -> None:
        command = self.bot.get_command("create-server")
        if command is None:
            return
        for alias in OFFICIAL_ALIASES:
            if alias not in command.aliases:
                command.aliases.append(alias)
            self.bot.all_commands[alias] = command

        callback = command.callback
        if getattr(callback, "_sentrix_official_wrapper", False):
            return
        original_callback = callback
        runtime = self

        async def wrapped(builder_cog, ctx: commands.Context, *args, **kwargs):
            invoked = str(getattr(ctx, "invoked_with", "") or "").casefold()
            if invoked in OFFICIAL_ALIASES:
                return await runtime.run_official_command(ctx)
            return await original_callback(builder_cog, ctx, *args, **kwargs)

        wrapped._sentrix_official_wrapper = True
        wrapped._sentrix_official_original = original_callback
        command.callback = wrapped
        logger.info("Alias +sentrix-server installé sur la commande create-server existante.")

    async def on_ready(self) -> None:
        self.patch_create_server_alias()
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
    """Installe le runtime une seule fois, puis réessaie l'alias après chaque extension."""
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
    runtime.patch_create_server_alias()
