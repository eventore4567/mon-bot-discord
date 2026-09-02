"""SentriX V71 — Sécurité avancée, honeypot configurable et score de vérification.

V71 rétablit les réglages détaillés retirés de l'interface V69/V70 sans affaiblir
les protections existantes :
- bouton global + choix individuel de chaque protection AutoMod ;
- intensité anti-raid configurable ;
- honeypot activable, suppression automatique du message et sanction configurable ;
- vérification humaine conservée, complétée par un score multi-signaux 0..2000 ;
- seuil strict par défaut : 1888/2000 ;
- aucune collecte d'IP, d'appareil ou d'information hors de l'API Discord.

Le score n'invente pas « 1000 facteurs ». Il agrège des preuves Discord réellement
observables et le challenge interactif déjà présent. Les preuves du challenge ont le
poids principal afin qu'un humain légitime puisse passer sans profilage opaque.
"""
from __future__ import annotations

import asyncio
import logging
import secrets
import time
import types
from collections import deque
from datetime import timedelta
from typing import Any

import discord
from discord.ext import commands

from utils import embeds
from utils import sentrix_panels as panels
from . import setup_control_center as setup_ui
from . import setup_polish_v70 as v70

logger = logging.getLogger("bot.security-verification-v71")

RUNTIME_MARKER = "Sécurité V71"
SCORE_MAX = 2000
DEFAULT_SCORE_THRESHOLD = 1888
MIN_SCORE_THRESHOLD = 1600
MAX_SCORE_THRESHOLD = 1999
DEFAULT_MIN_ACCOUNT_AGE_MINUTES = 30

SCHEMA = """
CREATE TABLE IF NOT EXISTS sentrix_security_v71 (
    guild_id INTEGER PRIMARY KEY,
    raid_intensity TEXT NOT NULL DEFAULT 'normal',
    honeypot_enabled INTEGER NOT NULL DEFAULT 1,
    honeypot_action TEXT NOT NULL DEFAULT 'softban',
    honeypot_delete_message INTEGER NOT NULL DEFAULT 1,
    honeypot_mute_minutes INTEGER NOT NULL DEFAULT 60,
    verification_enabled INTEGER NOT NULL DEFAULT 1,
    verification_threshold INTEGER NOT NULL DEFAULT 1888,
    verification_min_account_age_minutes INTEGER NOT NULL DEFAULT 30,
    updated_by INTEGER,
    updated_at INTEGER NOT NULL DEFAULT 0
)
"""

# Compatibilité : V71 peut démarrer même si le moteur de vérification historique n'a
# pas encore créé sa table pendant le boot.
HONEYPOT_SCHEMA = """
CREATE TABLE IF NOT EXISTS honeypot_verification (
    guild_id INTEGER PRIMARY KEY,
    enabled INTEGER NOT NULL DEFAULT 1,
    category_id INTEGER,
    trap_channel_id INTEGER,
    verify_channel_id INTEGER,
    unverified_role_id INTEGER,
    verified_role_id INTEGER,
    sanction TEXT NOT NULL DEFAULT 'softban',
    created_at INTEGER NOT NULL DEFAULT 0
)
"""

RAID_PROFILES: dict[str, tuple[int, int, int]] = {
    # intensité -> (arrivées, fenêtre secondes, durée du mode raid)
    "faible": (12, 20, 90),
    "normal": (8, 20, 120),
    "eleve": (5, 20, 180),
    "extreme": (3, 20, 240),
}
RAID_LABELS = {
    "faible": "Faible",
    "normal": "Normal",
    "eleve": "Élevé",
    "extreme": "Extrême",
}
ACTION_LABELS = {
    "softban": "Softban",
    "kick": "Kick",
    "ban": "Ban",
    "mute": "Mute / timeout",
}


def _get(row: Any, key: str, default: Any = None) -> Any:
    if row is None:
        return default
    try:
        value = row[key]
    except (KeyError, IndexError, TypeError):
        return default
    return default if value is None else value


def _clamp_threshold(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = DEFAULT_SCORE_THRESHOLD
    return max(MIN_SCORE_THRESHOLD, min(MAX_SCORE_THRESHOLD, parsed))


def _clamp_age(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = DEFAULT_MIN_ACCOUNT_AGE_MINUTES
    return max(30, min(525600, parsed))


async def ensure_schema(bot: commands.Bot) -> None:
    await bot.db.execute(SCHEMA)
    await bot.db.execute(HONEYPOT_SCHEMA)


async def settings(bot: commands.Bot, guild_id: int) -> dict[str, Any]:
    await ensure_schema(bot)
    await bot.db.execute(
        "INSERT INTO sentrix_security_v71(guild_id) VALUES(?) ON CONFLICT(guild_id) DO NOTHING",
        (int(guild_id),),
    )
    row = await bot.db.fetchone(
        "SELECT * FROM sentrix_security_v71 WHERE guild_id = ?", (int(guild_id),)
    )
    intensity = str(_get(row, "raid_intensity", "normal"))
    if intensity not in RAID_PROFILES:
        intensity = "normal"
    action = str(_get(row, "honeypot_action", "softban"))
    if action not in ACTION_LABELS:
        action = "softban"
    return {
        "raid_intensity": intensity,
        "honeypot_enabled": bool(_get(row, "honeypot_enabled", 1)),
        "honeypot_action": action,
        "honeypot_delete_message": bool(_get(row, "honeypot_delete_message", 1)),
        "honeypot_mute_minutes": max(1, min(40320, int(_get(row, "honeypot_mute_minutes", 60)))),
        "verification_enabled": bool(_get(row, "verification_enabled", 1)),
        "verification_threshold": _clamp_threshold(_get(row, "verification_threshold", DEFAULT_SCORE_THRESHOLD)),
        "verification_min_account_age_minutes": _clamp_age(
            _get(row, "verification_min_account_age_minutes", DEFAULT_MIN_ACCOUNT_AGE_MINUTES)
        ),
    }


async def update_setting(bot: commands.Bot, guild_id: int, field: str, value: Any, actor_id: int | None) -> None:
    allowed = {
        "raid_intensity",
        "honeypot_enabled",
        "honeypot_action",
        "honeypot_delete_message",
        "honeypot_mute_minutes",
        "verification_enabled",
        "verification_threshold",
        "verification_min_account_age_minutes",
    }
    if field not in allowed:
        raise ValueError(f"Réglage V71 inconnu : {field}")
    await ensure_schema(bot)
    await bot.db.execute(
        "INSERT INTO sentrix_security_v71(guild_id) VALUES(?) ON CONFLICT(guild_id) DO NOTHING",
        (int(guild_id),),
    )
    await bot.db.execute(
        f"UPDATE sentrix_security_v71 SET {field} = ?, updated_by = ?, updated_at = ? WHERE guild_id = ?",
        (value, actor_id, int(time.time()), int(guild_id)),
    )


def _invalidate_automod(bot: commands.Bot, guild_id: int) -> None:
    cog = bot.get_cog("Automod")
    cache = getattr(cog, "automod_cache", None)
    if isinstance(cache, dict):
        cache.pop(int(guild_id), None)


async def _automod_row(bot: commands.Bot, guild_id: int):
    return await bot.db.fetchone("SELECT * FROM automod_settings WHERE guild_id = ?", (int(guild_id),))


class AdvancedAutomodSelect(discord.ui.Select):
    """Restaure la sélection individuelle de V2, avec invalidation du cache AutoMod."""

    def __init__(self, owner):
        self.owner = owner
        super().__init__(
            placeholder="Protections actives — choisir celles à garder",
            min_values=0,
            max_values=len(setup_ui.AUTOMOD),
            options=[discord.SelectOption(label=label, value=field) for field, label in setup_ui.AUTOMOD],
            row=2,
        )

    async def callback(self, interaction: discord.Interaction):
        chosen = set(self.values)
        await self.owner.bot.db.execute(
            "INSERT INTO automod_settings(guild_id) VALUES(?) ON CONFLICT(guild_id) DO NOTHING",
            (self.owner.guild.id,),
        )
        columns = ", ".join(f"{field} = ?" for field, _label in setup_ui.AUTOMOD)
        values = tuple(1 if field in chosen else 0 for field, _label in setup_ui.AUTOMOD)
        await self.owner.bot.db.execute(
            f"UPDATE automod_settings SET {columns} WHERE guild_id = ?",
            (*values, self.owner.guild.id),
        )
        _invalidate_automod(self.owner.bot, self.owner.guild.id)
        await self.owner.audit(interaction.user.id, "security_protections", ",".join(sorted(chosen)))
        await self.owner.refresh(interaction)


class RaidIntensitySelect(discord.ui.Select):
    def __init__(self, owner):
        self.owner = owner
        super().__init__(
            placeholder="Intensité de l’anti-raid",
            options=[
                discord.SelectOption(
                    label=RAID_LABELS[key],
                    value=key,
                    description=f"Mode raid dès {profile[0]} arrivées en {profile[1]} s",
                )
                for key, profile in RAID_PROFILES.items()
            ],
            row=3,
        )

    async def callback(self, interaction: discord.Interaction):
        value = self.values[0]
        await update_setting(self.owner.bot, self.owner.guild.id, "raid_intensity", value, interaction.user.id)
        await self.owner.audit(interaction.user.id, "raid_intensity", value)
        await self.owner.refresh(interaction)


class HoneypotActionSelect(discord.ui.Select):
    def __init__(self, owner):
        self.owner = owner
        super().__init__(
            placeholder="Sanction du salon stay-muted",
            options=[
                discord.SelectOption(label="Softban", value="softban", description="Ban puis unban immédiat"),
                discord.SelectOption(label="Kick", value="kick", description="Expulse le compte du serveur"),
                discord.SelectOption(label="Ban", value="ban", description="Bannissement permanent"),
                discord.SelectOption(label="Mute / timeout", value="mute", description="Timeout selon la durée choisie"),
            ],
            row=2,
        )

    async def callback(self, interaction: discord.Interaction):
        value = self.values[0]
        await update_setting(self.owner.bot, self.owner.guild.id, "honeypot_action", value, interaction.user.id)
        # La colonne historique reste synchronisée pour les écrans/outils existants.
        await self.owner.bot.db.execute(
            "UPDATE honeypot_verification SET sanction = ? WHERE guild_id = ?",
            (value, self.owner.guild.id),
        )
        runtime = getattr(self.owner.bot, "_sentrix_security_v71_runtime", None)
        if runtime is not None:
            await runtime.refresh_gateway_panels(self.owner.guild)
        await self.owner.audit(interaction.user.id, "honeypot_action", value)
        await self.owner.refresh(interaction)


class HoneypotMuteSelect(discord.ui.Select):
    def __init__(self, owner):
        self.owner = owner
        super().__init__(
            placeholder="Durée du mute si l’action Mute est choisie",
            options=[
                discord.SelectOption(label="10 minutes", value="10"),
                discord.SelectOption(label="30 minutes", value="30"),
                discord.SelectOption(label="1 heure", value="60"),
                discord.SelectOption(label="6 heures", value="360"),
                discord.SelectOption(label="24 heures", value="1440"),
                discord.SelectOption(label="7 jours", value="10080"),
            ],
            row=3,
        )

    async def callback(self, interaction: discord.Interaction):
        value = int(self.values[0])
        await update_setting(self.owner.bot, self.owner.guild.id, "honeypot_mute_minutes", value, interaction.user.id)
        await self.owner.audit(interaction.user.id, "honeypot_mute_minutes", value)
        await self.owner.refresh(interaction)


class VerificationThresholdSelect(discord.ui.Select):
    def __init__(self, owner):
        self.owner = owner
        super().__init__(
            placeholder="Seuil du score de confiance",
            options=[
                discord.SelectOption(label="Équilibré — 1700 / 2000", value="1700"),
                discord.SelectOption(label="Renforcé — 1800 / 2000", value="1800"),
                discord.SelectOption(label="Strict — 1888 / 2000", value="1888"),
                discord.SelectOption(label="Maximum — 1950 / 2000", value="1950"),
            ],
            row=2,
        )

    async def callback(self, interaction: discord.Interaction):
        value = _clamp_threshold(self.values[0])
        await update_setting(self.owner.bot, self.owner.guild.id, "verification_threshold", value, interaction.user.id)
        runtime = getattr(self.owner.bot, "_sentrix_security_v71_runtime", None)
        if runtime is not None:
            await runtime.refresh_gateway_panels(self.owner.guild)
        await self.owner.audit(interaction.user.id, "verification_threshold", value)
        await self.owner.refresh(interaction)


class VerificationAgeSelect(discord.ui.Select):
    def __init__(self, owner):
        self.owner = owner
        super().__init__(
            placeholder="Ancienneté minimale du compte",
            options=[
                discord.SelectOption(label="30 minutes", value="30"),
                discord.SelectOption(label="1 heure", value="60"),
                discord.SelectOption(label="6 heures", value="360"),
                discord.SelectOption(label="24 heures", value="1440"),
                discord.SelectOption(label="7 jours", value="10080"),
                discord.SelectOption(label="30 jours", value="43200"),
            ],
            row=3,
        )

    async def callback(self, interaction: discord.Interaction):
        value = _clamp_age(self.values[0])
        await update_setting(
            self.owner.bot,
            self.owner.guild.id,
            "verification_min_account_age_minutes",
            value,
            interaction.user.id,
        )
        runtime = getattr(self.owner.bot, "_sentrix_security_v71_runtime", None)
        if runtime is not None:
            await runtime.refresh_gateway_panels(self.owner.guild)
        await self.owner.audit(interaction.user.id, "verification_min_account_age_minutes", value)
        await self.owner.refresh(interaction)


class SecurityNavButton(discord.ui.Button):
    def __init__(self, owner, label: str, target: str | None):
        self.owner = owner
        self.target = target
        super().__init__(label=label, style=discord.ButtonStyle.secondary, row=1)

    async def callback(self, interaction: discord.Interaction):
        self.owner.security_subpage = self.target
        await self.owner.refresh(interaction)


class SecurityToggleButton(discord.ui.Button):
    def __init__(self, owner):
        self.owner = owner
        super().__init__(label="Activer / Désactiver", style=discord.ButtonStyle.primary, row=1)

    async def callback(self, interaction: discord.Interaction):
        row = await _automod_row(self.owner.bot, self.owner.guild.id)
        active = any(bool(_get(row, field, 0)) for field, _label in setup_ui.AUTOMOD) if row else False
        await self.owner.bot.db.execute(
            "INSERT INTO automod_settings(guild_id) VALUES(?) ON CONFLICT(guild_id) DO NOTHING",
            (self.owner.guild.id,),
        )
        target = 0 if active else 1
        columns = ", ".join(f"{field} = ?" for field, _label in setup_ui.AUTOMOD)
        await self.owner.bot.db.execute(
            f"UPDATE automod_settings SET {columns} WHERE guild_id = ?",
            (*tuple(target for _ in setup_ui.AUTOMOD), self.owner.guild.id),
        )
        _invalidate_automod(self.owner.bot, self.owner.guild.id)
        await self.owner.audit(interaction.user.id, "security_all", "off" if active else "on")
        await self.owner.refresh(interaction)


class V71SettingToggle(discord.ui.Button):
    def __init__(self, owner, *, field: str, label: str):
        self.owner = owner
        self.field = field
        super().__init__(label=label, style=discord.ButtonStyle.primary, row=1)

    async def callback(self, interaction: discord.Interaction):
        current = await settings(self.owner.bot, self.owner.guild.id)
        value = not bool(current[self.field])
        await update_setting(self.owner.bot, self.owner.guild.id, self.field, int(value), interaction.user.id)
        runtime = getattr(self.owner.bot, "_sentrix_security_v71_runtime", None)
        if runtime is not None:
            await runtime.refresh_gateway_panels(self.owner.guild)
        await self.owner.audit(interaction.user.id, self.field, "on" if value else "off")
        await self.owner.refresh(interaction)


def _security_main_controls(view) -> None:
    view.add_item(SecurityToggleButton(view))
    view.add_item(SecurityNavButton(view, "Honeypot", "honeypot"))
    view.add_item(SecurityNavButton(view, "Vérification", "verification"))
    view.add_item(AdvancedAutomodSelect(view))
    view.add_item(RaidIntensitySelect(view))


def _honeypot_controls(view) -> None:
    view.add_item(SecurityNavButton(view, "Retour Sécurité", None))
    view.add_item(V71SettingToggle(view, field="honeypot_enabled", label="Honeypot On / Off"))
    view.add_item(V71SettingToggle(view, field="honeypot_delete_message", label="Suppression message On / Off"))
    view.add_item(HoneypotActionSelect(view))
    view.add_item(HoneypotMuteSelect(view))


def _verification_controls(view) -> None:
    view.add_item(SecurityNavButton(view, "Retour Sécurité", None))
    view.add_item(V71SettingToggle(view, field="verification_enabled", label="Vérification On / Off"))
    view.add_item(VerificationThresholdSelect(view))
    view.add_item(VerificationAgeSelect(view))


def _patch_setup_render() -> None:
    cls = setup_ui.SetupView
    if getattr(cls.render, "_sentrix_security_v71", False):
        return
    previous = cls.render

    def render_v71(self) -> None:
        previous(self)
        if self.category != "security":
            self.security_subpage = None
            return
        # V70 garde sa navigation principale (row 0), V71 remplace uniquement les
        # contrôles de la page Sécurité.
        for child in list(self.children):
            if getattr(child, "row", None) != 0:
                self.remove_item(child)
        subpage = getattr(self, "security_subpage", None)
        if subpage == "honeypot":
            _honeypot_controls(self)
        elif subpage == "verification":
            _verification_controls(self)
        else:
            _security_main_controls(self)

    render_v71._sentrix_permissions_v66 = True
    render_v71._sentrix_setup_simple_v68 = True
    render_v71._sentrix_oxyde_v69 = True
    render_v71._sentrix_polish_v70 = True
    render_v71._sentrix_security_v71 = True
    render_v71._sentrix_previous = previous
    cls.render = render_v71


def _protection_lines(row: Any) -> str:
    lines = []
    for field, label in setup_ui.AUTOMOD:
        lines.append(f"{'●' if bool(_get(row, field, 0)) else '○'} **{label}**")
    return "\n".join(lines)


async def _security_main_embed(view) -> discord.Embed:
    row = await _automod_row(view.bot, view.guild.id)
    cfg = await settings(view.bot, view.guild.id)
    enabled = sum(bool(_get(row, field, 0)) for field, _label in setup_ui.AUTOMOD) if row else 0
    panel = embeds.brand(
        "SentriX — Sécurité",
        f"**{view.guild.name}**\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Choisissez exactement les protections que vous voulez utiliser.",
    )
    panel.set_thumbnail(url=None)
    panel.add_field(name="ÉTAT", value="● ACTIF" if enabled else "○ INACTIF", inline=True)
    panel.add_field(name="PROTECTIONS", value=f"**{enabled}/{len(setup_ui.AUTOMOD)} actives**", inline=True)
    panel.add_field(name="ANTI-RAID", value=f"**{RAID_LABELS[cfg['raid_intensity']]}**", inline=True)
    panel.add_field(name="PROTECTIONS INDIVIDUELLES", value=_protection_lines(row), inline=False)
    panel.add_field(
        name="MODULES AVANCÉS",
        value=(
            f"**Honeypot :** {'● ACTIF' if cfg['honeypot_enabled'] else '○ INACTIF'} · {ACTION_LABELS[cfg['honeypot_action']]}\n"
            f"**Vérification :** {'● ACTIF' if cfg['verification_enabled'] else '○ INACTIF'} · seuil {cfg['verification_threshold']}/{SCORE_MAX}"
        ),
        inline=False,
    )
    panel.set_footer(text="SentriX • Sécurité V71 • Sauvegarde automatique")
    return panel


async def _honeypot_embed(view) -> discord.Embed:
    cfg = await settings(view.bot, view.guild.id)
    old = await view.bot.db.fetchone("SELECT * FROM honeypot_verification WHERE guild_id = ?", (view.guild.id,))
    trap = view.guild.get_channel(int(_get(old, "trap_channel_id", 0))) if _get(old, "trap_channel_id") else None
    panel = embeds.brand(
        "SentriX — Honeypot",
        f"**{view.guild.name}**\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Configuration du salon piège anti-bot.",
    )
    panel.set_thumbnail(url=None)
    panel.add_field(name="ÉTAT", value="● ACTIF" if cfg["honeypot_enabled"] else "○ INACTIF", inline=True)
    panel.add_field(name="SALON", value=trap.mention if isinstance(trap, discord.TextChannel) else "— Non configuré", inline=True)
    panel.add_field(name="ACTION", value=ACTION_LABELS[cfg["honeypot_action"]], inline=True)
    panel.add_field(
        name="MESSAGE DU MEMBRE",
        value="● Supprimé automatiquement" if cfg["honeypot_delete_message"] else "○ Conservé",
        inline=True,
    )
    if cfg["honeypot_action"] == "mute":
        panel.add_field(name="DURÉE DU MUTE", value=f"{cfg['honeypot_mute_minutes']} minute(s)", inline=True)
    panel.add_field(
        name="SÉCURITÉ",
        value="Le propriétaire, les administrateurs, le staff hors rôle `Non vérifié` et les membres déjà vérifiés ne sont jamais sanctionnés par le piège.",
        inline=False,
    )
    panel.set_footer(text="SentriX • Honeypot V71")
    return panel


async def _verification_embed(view) -> discord.Embed:
    cfg = await settings(view.bot, view.guild.id)
    panel = embeds.brand(
        "SentriX — Vérification",
        f"**{view.guild.name}**\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Passerelle humaine renforcée et score de confiance.",
    )
    panel.set_thumbnail(url=None)
    panel.add_field(name="ÉTAT", value="● ACTIF" if cfg["verification_enabled"] else "○ INACTIF", inline=True)
    panel.add_field(name="SEUIL", value=f"**{cfg['verification_threshold']} / {SCORE_MAX}**", inline=True)
    panel.add_field(name="ÂGE MINIMUM", value=f"**{cfg['verification_min_account_age_minutes']} min**", inline=True)
    panel.add_field(
        name="PREUVES ANALYSÉES",
        value=(
            "Séquence interactive · code unique · calcul unique · Membership Screening · compte humain · "
            "cohérence du compte Discord · ancienneté · temps depuis l'arrivée · timeout · rôles de vérification · "
            "tentatives récentes · avatar · cohérence Snowflake."
        ),
        inline=False,
    )
    panel.add_field(
        name="IMPORTANT",
        value=(
            "Le score utilise uniquement des informations réellement disponibles via Discord. "
            "Aucune IP, empreinte d'appareil ou donnée cachée n'est collectée. Les trois preuves du challenge "
            "restent obligatoires avant toute attribution du rôle Vérifié."
        ),
        inline=False,
    )
    panel.set_footer(text="SentriX • Security Gateway V71")
    return panel


def _patch_setup_embed() -> None:
    cls = setup_ui.SetupView
    if getattr(cls.build_embed, "_sentrix_security_v71", False):
        return
    previous = cls.build_embed

    async def build_embed_v71(self) -> discord.Embed:
        if self.category == "security":
            subpage = getattr(self, "security_subpage", None)
            if subpage == "honeypot":
                return await _honeypot_embed(self)
            if subpage == "verification":
                return await _verification_embed(self)
            return await _security_main_embed(self)
        return await previous(self)

    build_embed_v71._sentrix_permissions_v66 = True
    build_embed_v71._sentrix_setup_simple_v68 = True
    build_embed_v71._sentrix_oxyde_v69 = True
    build_embed_v71._sentrix_polish_v70 = True
    build_embed_v71._sentrix_security_v71 = True
    build_embed_v71._sentrix_previous = previous
    cls.build_embed = build_embed_v71


class SecurityVerificationRuntimeV71:
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._recent_traps: dict[tuple[int, int], float] = {}
        self._join_windows: dict[int, deque[float]] = {}
        self._raid_until: dict[int, float] = {}
        self._patched_engine_id: int | None = None

    async def _legacy_config(self, guild_id: int):
        await ensure_schema(self.bot)
        return await self.bot.db.fetchone(
            "SELECT * FROM honeypot_verification WHERE guild_id = ?", (int(guild_id),)
        )

    def _staff_bypass(self, member: discord.Member, conf: Any) -> bool:
        if member.bot or member.id == member.guild.owner_id:
            return True
        if member.guild_permissions.administrator or member.guild_permissions.manage_guild:
            return True
        verified_id = _get(conf, "verified_role_id")
        if verified_id and any(role.id == int(verified_id) for role in member.roles):
            return True
        unverified_id = _get(conf, "unverified_role_id")
        # Le piège ne vise que les comptes explicitement placés en attente.
        if unverified_id and not any(role.id == int(unverified_id) for role in member.roles):
            return True
        return False

    async def on_message(self, message: discord.Message) -> None:
        if message.guild is None or not isinstance(message.author, discord.Member):
            return
        if self.bot.user is not None and message.author.id == self.bot.user.id:
            return
        conf = await self._legacy_config(message.guild.id)
        if not conf or not _get(conf, "trap_channel_id"):
            return
        if message.channel.id != int(_get(conf, "trap_channel_id")):
            return
        cfg = await settings(self.bot, message.guild.id)
        if not cfg["honeypot_enabled"] or self._staff_bypass(message.author, conf):
            return

        key = (message.guild.id, message.author.id)
        now = time.monotonic()
        if self._recent_traps.get(key, 0.0) > now:
            if cfg["honeypot_delete_message"]:
                try:
                    await message.delete()
                except (discord.Forbidden, discord.HTTPException):
                    pass
            return
        self._recent_traps[key] = now + 8.0

        if cfg["honeypot_delete_message"]:
            try:
                await message.delete()
            except (discord.Forbidden, discord.HTTPException):
                logger.warning("V71: impossible de supprimer un message honeypot guild=%s", message.guild.id)

        me = message.guild.me
        if me is None or message.author.top_role >= me.top_role:
            return

        action = cfg["honeypot_action"]
        reason = "SentriX V71 : message envoyé dans le honeypot stay-muted"
        applied = action
        try:
            if action == "softban":
                await message.guild.ban(message.author, reason=reason, delete_message_seconds=0)
                await message.guild.unban(message.author, reason="SentriX V71 : fin du softban honeypot")
            elif action == "kick":
                await message.author.kick(reason=reason)
            elif action == "ban":
                await message.author.ban(reason=reason, delete_message_seconds=0)
            elif action == "mute":
                until = discord.utils.utcnow() + timedelta(minutes=cfg["honeypot_mute_minutes"])
                await message.author.timeout(until, reason=reason)
            else:
                applied = "none"
        except (discord.Forbidden, discord.HTTPException):
            logger.exception("V71: sanction honeypot impossible guild=%s user=%s", message.guild.id, message.author.id)
            applied = "failed"

        engine = self.bot.get_cog("HoneypotVerification")
        log_fn = getattr(engine, "_log", None)
        if callable(log_fn):
            try:
                await log_fn(
                    message.guild,
                    "Honeypot déclenché",
                    f"{message.author.mention} (`{message.author.id}`) · action : **{ACTION_LABELS.get(action, action)}** · résultat : `{applied}`.",
                    danger=True,
                )
            except Exception:
                logger.exception("V71: log honeypot impossible")

    async def on_member_join(self, member: discord.Member) -> None:
        row = await _automod_row(self.bot, member.guild.id)
        if not row or not bool(_get(row, "antiraid", 0)):
            return
        cfg = await settings(self.bot, member.guild.id)
        limit, window, duration = RAID_PROFILES[cfg["raid_intensity"]]
        now = time.monotonic()
        hits = self._join_windows.setdefault(member.guild.id, deque())
        hits.append(now)
        while hits and now - hits[0] > window:
            hits.popleft()
        if len(hits) >= limit:
            self._raid_until[member.guild.id] = max(self._raid_until.get(member.guild.id, 0.0), now + duration)

        if self._raid_until.get(member.guild.id, 0.0) <= now:
            return
        conf = await self._legacy_config(member.guild.id)
        if not conf or not cfg["verification_enabled"]:
            return
        role_id = _get(conf, "unverified_role_id")
        role = member.guild.get_role(int(role_id)) if role_id else None
        if role is None or member.id == member.guild.owner_id or member.bot:
            return
        if member.guild_permissions.administrator or member.guild_permissions.manage_guild:
            return
        if role not in member.roles:
            try:
                await member.add_roles(role, reason=f"SentriX V71 : mode anti-raid {RAID_LABELS[cfg['raid_intensity']]}")
            except (discord.Forbidden, discord.HTTPException):
                pass

    def _score(self, engine: Any, member: discord.Member, state: Any, code: str, math_answer: str, cfg: dict[str, Any]) -> tuple[int, dict[str, bool]]:
        now = discord.utils.utcnow()
        age_seconds = max(0, int((now - member.created_at).total_seconds()))
        joined_seconds = max(0, int((now - member.joined_at).total_seconds())) if member.joined_at else 0
        timeout_until = getattr(member, "timed_out_until", None)
        timed_out = bool(timeout_until and timeout_until > now)

        try:
            snowflake_ok = abs((discord.utils.snowflake_time(member.id) - member.created_at).total_seconds()) <= 300
        except Exception:
            snowflake_ok = False

        failures = getattr(engine, "_failures", {}).get((member.guild.id, member.id), [])
        recent_failures = [stamp for stamp in failures if time.time() - float(stamp) <= 600]

        conf = None
        # config is already cached in the challenge flow; role checks can use names safely
        unverified_present = any(role.name == "Non vérifié" for role in member.roles)
        verified_preassigned = any(role.name == "Vérifié" for role in member.roles)
        role_state_ok = unverified_present and not verified_preassigned

        checks = {
            "sequence": bool(getattr(state, "sequence_done", False)),
            "code": secrets.compare_digest(str(code).strip(), str(getattr(state, "code", "")).strip()),
            "math": secrets.compare_digest(str(math_answer).strip(), str(getattr(state, "math_answer", "")).strip()),
            "human": not member.bot,
            "not_system": not bool(getattr(member, "system", False)),
            "screening": not bool(getattr(member, "pending", False)),
            "min_age": age_seconds >= cfg["verification_min_account_age_minutes"] * 60,
            "join_delay": member.joined_at is not None and joined_seconds >= 8,
            "not_timeout": not timed_out,
            "role_state": role_state_ok,
            "clean_attempts": len(recent_failures) == 0,
            "snowflake": snowflake_ok,
            "age_7d": age_seconds >= 7 * 86400,
            "avatar": getattr(member, "avatar", None) is not None,
        }
        weights = {
            "sequence": 350,
            "code": 300,
            "math": 250,
            "human": 150,
            "not_system": 75,
            "screening": 200,
            "min_age": 200,
            "join_delay": 75,
            "not_timeout": 75,
            "role_state": 100,
            "clean_attempts": 75,
            "snowflake": 50,
            "age_7d": 50,
            "avatar": 50,
        }
        score = sum(weight for name, weight in weights.items() if checks[name])
        return int(score), checks

    async def patch_engine(self) -> None:
        engine = self.bot.get_cog("HoneypotVerification")
        if engine is None:
            return
        if self._patched_engine_id == id(engine):
            return

        # Retire l'ancien listener du salon piège pour éviter deux sanctions sur le même
        # message. Les listeners join/challenge historiques restent inchangés.
        old_message = getattr(engine, "on_message", None)
        if callable(old_message):
            try:
                self.bot.remove_listener(old_message, "on_message")
                engine._sentrix_v71_old_message_listener_removed = True
            except Exception:
                logger.exception("V71: impossible de retirer l'ancien listener honeypot")

        original_start = getattr(engine, "start_human_verification", None)
        if callable(original_start) and not getattr(engine, "_sentrix_v71_start", False):
            runtime = self

            async def start_v71(_self, interaction: discord.Interaction):
                if interaction.guild is not None:
                    cfg = await settings(runtime.bot, interaction.guild.id)
                    if not cfg["verification_enabled"]:
                        return await panels.envoyer(interaction.response, panels.depuis_embed(embeds.warning('La vérification SentriX est désactivée sur ce serveur.')), ephemere=True)
                    if isinstance(interaction.user, discord.Member):
                        age = max(0, int((discord.utils.utcnow() - interaction.user.created_at).total_seconds()))
                        required = cfg["verification_min_account_age_minutes"] * 60
                        if age < required:
                            minutes = max(1, (required - age + 59) // 60)
                            return await panels.envoyer(interaction.response, panels.depuis_embed(embeds.warning(f'Compte trop récent. Réessayez dans environ **{minutes} min**.')), ephemere=True)
                return await original_start(interaction)

            engine.start_human_verification = types.MethodType(start_v71, engine)
            engine._sentrix_v71_start = True

        original_complete = getattr(engine, "complete_human_challenge", None)
        if callable(original_complete) and not getattr(engine, "_sentrix_v71_complete", False):
            runtime = self

            async def complete_v71(_self, interaction: discord.Interaction, token: str, code: str, math_answer: str):
                if interaction.guild is None or not isinstance(interaction.user, discord.Member):
                    return await original_complete(interaction, token, code, math_answer)
                key = (interaction.guild.id, interaction.user.id)
                state = getattr(_self, "_challenges", {}).get(key)
                if state is None or getattr(state, "token", None) != token:
                    return await original_complete(interaction, token, code, math_answer)

                # Les trois preuves de challenge restent obligatoires et l'ancien moteur
                # conserve ses propres messages d'erreur pour les réponses incorrectes.
                core_ok = (
                    bool(getattr(state, "sequence_done", False))
                    and secrets.compare_digest(str(code).strip(), str(getattr(state, "code", "")).strip())
                    and secrets.compare_digest(str(math_answer).strip(), str(getattr(state, "math_answer", "")).strip())
                )
                if not core_ok:
                    return await original_complete(interaction, token, code, math_answer)

                cfg = await settings(runtime.bot, interaction.guild.id)
                if not cfg["verification_enabled"]:
                    getattr(_self, "_challenges", {}).pop(key, None)
                    return await panels.envoyer(interaction.response, panels.depuis_embed(embeds.warning('La vérification a été désactivée pendant cette session.')), ephemere=True)

                score, checks = runtime._score(_self, interaction.user, state, code, math_answer, cfg)
                if score < cfg["verification_threshold"]:
                    record_failure = getattr(_self, "_record_failure", None)
                    if callable(record_failure):
                        await record_failure(interaction.guild.id, interaction.user.id)
                    getattr(_self, "_challenges", {}).pop(key, None)
                    failed = [name for name, passed in checks.items() if not passed and name not in {"age_7d", "avatar"}]
                    await panels.envoyer(interaction.response, panels.depuis_embed(embeds.warning(f"Vérification incomplète : **{score}/{SCORE_MAX}** (seuil **{cfg['verification_threshold']}**).\nVotre accès reste verrouillé. Relancez une nouvelle session après avoir rempli les conditions Discord." + (f"\nContrôles à revoir : `{', '.join(failed[:5])}`" if failed else ''))), ephemere=True)
                    return

                # Le moteur historique effectue encore ses validations finales et attribue
                # le rôle. V71 ne contourne donc aucune vérification existante.
                return await original_complete(interaction, token, code, math_answer)

            engine.complete_human_challenge = types.MethodType(complete_v71, engine)
            engine._sentrix_v71_complete = True

        self._patched_engine_id = id(engine)

    async def _panel_message(self, channel: discord.TextChannel):
        try:
            async for message in channel.history(limit=25):
                if self.bot.user is not None and message.author.id == self.bot.user.id:
                    return message
        except (discord.Forbidden, discord.HTTPException):
            return None
        return None

    async def refresh_gateway_panels(self, guild: discord.Guild) -> None:
        conf = await self._legacy_config(guild.id)
        if not conf:
            return
        cfg = await settings(self.bot, guild.id)
        verify = guild.get_channel(int(_get(conf, "verify_channel_id", 0))) if _get(conf, "verify_channel_id") else None
        trap = guild.get_channel(int(_get(conf, "trap_channel_id", 0))) if _get(conf, "trap_channel_id") else None

        if isinstance(verify, discord.TextChannel):
            panel = discord.Embed(
                title="Passerelle de vérification",
                description=(
                    "### Accès temporairement verrouillé\n"
                    "SentriX valide plusieurs preuves Discord et le challenge humain avant d'ouvrir le serveur.\n\n"
                    f"**Score requis : {cfg['verification_threshold']}/{SCORE_MAX}** · compte minimum : "
                    f"**{cfg['verification_min_account_age_minutes']} min**."
                ),
                colour=0x5865F2,
            )
            panel.set_author(name="SentriX • Security Gateway")
            panel.add_field(
                name="Contrôles",
                value=(
                    "Membership Screening · séquence anti-automatisation · code unique · calcul unique · "
                    "ancienneté · cohérence Discord · état des rôles · tentatives récentes · timeout · score de confiance"
                ),
                inline=False,
            )
            panel.add_field(
                name="Accès",
                value="Le rôle `Vérifié` n'est attribué qu'après réussite complète. Aucune IP ni donnée d'appareil n'est utilisée.",
                inline=False,
            )
            panel.set_footer(text="SentriX • Security Gateway V71")
            message = await self._panel_message(verify)
            try:
                from . import verification_polish_v51 as polish
                view = polish.VerificationPanelView()
            except Exception:
                view = None
            try:
                if message:
                    await message.edit(embed=panel, view=view)
                else:
                    await verify.send(embed=panel, view=view)
            except (discord.Forbidden, discord.HTTPException):
                pass

        if isinstance(trap, discord.TextChannel):
            action = ACTION_LABELS[cfg["honeypot_action"]]
            panel = discord.Embed(
                title="Salon piège — ne pas écrire ici",
                description=(
                    "Ce salon est un **honeypot anti-bot** destiné aux comptes encore `Non vérifié`.\n\n"
                    f"**Action configurée : {action}.**\n"
                    f"Suppression automatique du message : **{'OUI' if cfg['honeypot_delete_message'] else 'NON'}**.\n\n"
                    + (f"Tout message déclenche un timeout de **{cfg['honeypot_mute_minutes']} min**." if cfg["honeypot_action"] == "mute" else "Tout message peut déclencher immédiatement l'action configurée.")
                ),
                colour=0xED4245,
            )
            panel.set_author(name="SentriX • Anti-Bot Honeypot")
            panel.set_footer(text="SentriX • Honeypot V71")
            message = await self._panel_message(trap)
            try:
                if message:
                    await message.edit(embed=panel, view=None)
                else:
                    await trap.send(embed=panel)
            except (discord.Forbidden, discord.HTTPException):
                pass

    async def on_ready(self) -> None:
        await self.patch_engine()


async def install(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_security_v71", False):
        return
    await ensure_schema(bot)
    _patch_setup_render()
    _patch_setup_embed()

    runtime = SecurityVerificationRuntimeV71(bot)
    bot._sentrix_security_v71_runtime = runtime
    bot.add_listener(runtime.on_message, "on_message")
    bot.add_listener(runtime.on_member_join, "on_member_join")
    bot.add_listener(runtime.on_ready, "on_ready")
    await runtime.patch_engine()

    # Rafraîchit les panneaux existants sans recréer de salons ni de rôles.
    try:
        rows = await bot.db.fetchall("SELECT guild_id FROM honeypot_verification")
        for row in rows[:200]:
            guild = bot.get_guild(int(_get(row, "guild_id", 0)))
            if guild is not None:
                await runtime.refresh_gateway_panels(guild)
                await asyncio.sleep(0.05)
    except Exception:
        logger.exception("V71: impossible de rafraîchir certains panneaux de vérification")

    bot._sentrix_security_v71 = True
    logger.info("Sécurité V71 active : AutoMod détaillé, anti-raid configurable, honeypot et score 1888/2000.")


__all__ = [
    "SCORE_MAX",
    "DEFAULT_SCORE_THRESHOLD",
    "RAID_PROFILES",
    "SecurityVerificationRuntimeV71",
    "install",
]
