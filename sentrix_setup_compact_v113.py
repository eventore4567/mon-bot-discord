"""SentriX V113/V4 — Smart Setup compact, sûr et orienté produit.

Cette couche conserve la logique métier du cog Configuration et transforme /setup en
centre de configuration court : Configuration, Sécurité, Modules, Smart Setup, Terminer.
Elle ajoute analyse serveur, modèles, aperçu obligatoire avant application, snapshot,
rollback de configuration, diagnostic final, recherche de réglage et design cohérent.

Règles de sécurité : aucune suppression automatique de rôle/salon, aucun rôle staff créé
avec des permissions sensibles, aucun gros changement appliqué sans aperçu explicite.
"""
from __future__ import annotations

import logging
import time
import unicodedata
from typing import Any

import discord

from utils import embeds, helpers
from utils import sentrix_panels as panels

logger = logging.getLogger("bot.setup-v113")

_CONFIG_MODULE = None
_INSTALLED = False

PAGE_HOME = -1
PAGE_CONFIGURATION = 0
PAGE_ROLES = 1
PAGE_MANAGERS_PROXY = 2
PAGE_MODULES = 3
PAGE_LEVELS = 4
PAGE_LOGS = 5
PAGE_AUTO = 6
PAGE_SECURITY = 7
PAGE_SUMMARY = 8

_SIMPLE_SETTINGS = (
    ("mod_role", "role", "Rôle staff", "Rôle utilisé pour la modération"),
    ("log_channel", "channel", "Salon principal des logs", "Salon de repli des journaux"),
    ("welcome_channel", "channel", "Salon de bienvenue", "Arrivées des membres"),
    ("announce_channel", "channel", "Salon des annonces", "Annonces générales"),
    ("autorole", "role", "Rôle automatique", "Rôle donné à l'arrivée"),
    ("verify_role", "role", "Rôle de vérification", "Rôle donné après vérification"),
)

_EXPERT_SETTINGS = _SIMPLE_SETTINGS + (
    ("goodbye_channel", "channel", "Salon de départ", "Départs des membres"),
    ("suggest_channel", "channel", "Salon des suggestions", "Suggestions des membres"),
    ("giveaway_channel", "channel", "Salon des giveaways", "Tirages au sort"),
    ("level_channel", "channel", "Salon des niveaux", "Annonces de niveau"),
)

SETTING_ALIASES = {
    "staff": "mod_role", "modo": "mod_role", "moderation": "mod_role",
    "logs": "log_channel", "log": "log_channel",
    "welcome": "welcome_channel", "bienvenue": "welcome_channel", "accueil": "welcome_channel",
    "depart": "goodbye_channel", "goodbye": "goodbye_channel",
    "annonce": "announce_channel", "annonces": "announce_channel",
    "suggestion": "suggest_channel", "suggestions": "suggest_channel",
    "giveaway": "giveaway_channel", "giveaways": "giveaway_channel",
    "niveau": "level_channel", "niveaux": "level_channel", "level": "level_channel",
    "autorole": "autorole", "membre": "autorole", "member": "autorole",
    "verification": "verify_role", "verify": "verify_role",
}

SMART_TEMPLATES = {
    "balanced": {
        "label": "Équilibré",
        "description": "Base propre pour la majorité des serveurs",
        "security": "moyen",
        "channels": ("welcome_channel", "announce_channel", "suggest_channel"),
        "tickets": False,
    },
    "community": {
        "label": "Communauté",
        "description": "Bienvenue, annonces, suggestions et modération",
        "security": "moyen",
        "channels": ("welcome_channel", "announce_channel", "suggest_channel"),
        "tickets": True,
    },
    "gaming": {
        "label": "Gaming",
        "description": "Bienvenue, annonces, giveaways et protection",
        "security": "moyen",
        "channels": ("welcome_channel", "announce_channel", "giveaway_channel"),
        "tickets": True,
    },
    "creator": {
        "label": "Créateur",
        "description": "Annonces, communauté et suggestions",
        "security": "moyen",
        "channels": ("welcome_channel", "announce_channel", "suggest_channel"),
        "tickets": False,
    },
    "support": {
        "label": "Support",
        "description": "Logs, tickets et organisation du support",
        "security": "moyen",
        "channels": ("welcome_channel",),
        "tickets": True,
    },
    "marketplace": {
        "label": "Marketplace",
        "description": "Protection renforcée, annonces et tickets",
        "security": "eleve",
        "channels": ("welcome_channel", "announce_channel"),
        "tickets": True,
    },
    "private": {
        "label": "Privé",
        "description": "Configuration minimale sans créer de structure inutile",
        "security": "faible",
        "channels": (),
        "tickets": False,
    },
}

CHANNEL_TARGETS = {
    "welcome_channel": ("bienvenue", ("bienvenue", "welcome", "accueil")),
    "announce_channel": ("annonces", ("annonces", "announcements", "announcement", "news")),
    "suggest_channel": ("suggestions", ("suggestions", "suggestion", "idees", "ideas")),
    "giveaway_channel": ("giveaways", ("giveaways", "giveaway", "concours")),
}

AUTO_SCOPES = {
    "security": "Sécurité",
    "logs": "Logs",
    "roles": "Rôles",
    "channels": "Salons",
    "community": "Modules communauté",
}


def _row_value(row: Any, key: str, default=None):
    if row is None:
        return default
    try:
        if hasattr(row, "keys") and key not in row.keys():
            return default
        value = row[key]
        return default if value is None else value
    except (KeyError, TypeError, IndexError):
        return default


def _clean_name(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(ch for ch in text if not unicodedata.combining(ch)).casefold().strip()


def _score_colour(score: int) -> int:
    score = max(0, min(100, int(score)))
    if score >= 80:
        return 0x23A559
    if score >= 55:
        return 0xF0B232
    return 0xF23F43


def _template_targets(template_key: str) -> tuple[str, ...]:
    template = SMART_TEMPLATES.get(template_key) or SMART_TEMPLATES["balanced"]
    return tuple(template["channels"])


def _plan_signature(plan: list[dict[str, Any]]) -> tuple:
    return tuple(
        (
            item.get("kind"), item.get("scope"), item.get("key"), item.get("value"),
            item.get("name"), item.get("preset"), bool(item.get("automatic")),
        )
        for item in plan
    )


def _find_text_channel(guild: discord.Guild, names: tuple[str, ...]):
    wanted = {_clean_name(name) for name in names}
    for channel in guild.text_channels:
        if _clean_name(channel.name) in wanted:
            return channel
    for channel in guild.text_channels:
        cleaned = _clean_name(channel.name)
        if any(name in cleaned for name in wanted):
            return channel
    return None


def _find_staff_role(guild: discord.Guild):
    me = guild.me
    exact = {"staff", "moderateur", "moderator", "mod", "administrateur", "administrator", "admin"}
    roles = [
        role for role in guild.roles
        if role != guild.default_role and not role.managed and (me is None or role < me.top_role)
    ]
    for role in reversed(roles):
        if _clean_name(role.name) in exact:
            return role
    for role in reversed(roles):
        name = _clean_name(role.name)
        if any(token in name for token in ("staff", "moder", "admin")):
            return role
    return None


def _find_member_role(guild: discord.Guild):
    me = guild.me
    for role in reversed(guild.roles):
        if role == guild.default_role or role.managed:
            continue
        if me is not None and role >= me.top_role:
            continue
        if _clean_name(role.name) in {"membre", "member", "members"}:
            return role
    return None


def _logs_configured(conf) -> bool:
    if not conf:
        return False
    keys = (
        "log_channel", "log_server", "log_messages", "log_members", "log_voice",
        "log_roles", "log_moderation", "log_automod",
    )
    return any(bool(_row_value(conf, key)) for key in keys)


def _ensure_v4_state(view) -> None:
    if not hasattr(view, "_v4_mode"):
        view._v4_mode = "complete"
    if not hasattr(view, "_v4_template"):
        view._v4_template = "balanced"
    if not hasattr(view, "_v4_scopes"):
        view._v4_scopes = set(AUTO_SCOPES)
    if not hasattr(view, "_v4_preview_ready"):
        view._v4_preview_ready = False
    if not hasattr(view, "_v4_preview_signature"):
        view._v4_preview_signature = None
    if not hasattr(view, "_v4_last_snapshot"):
        view._v4_last_snapshot = None
    if not hasattr(view, "_v4_last_result"):
        view._v4_last_result = None
    if not hasattr(view, "_v4_expert"):
        view._v4_expert = False
    if not hasattr(view, "_v4_health_cache"):
        view._v4_health_cache = None


def _invalidate_health(view) -> None:
    view._v4_health_cache = None


def _mention(view, field: str, conf) -> str:
    if field == "prefix":
        value = view.choices.get("prefix", _row_value(conf, "prefix", "+")) or "+"
        return f"`{value}`"
    return view._mention_current(field, conf)


def _decorate_embed(view, embed: discord.Embed, *, section: str) -> discord.Embed:
    guild = view._guild()
    if guild and guild.icon:
        embed.set_thumbnail(url=guild.icon.url)
    embed.set_footer(text=f"SentriX • Setup V4 • {section}")
    return embed


async def _health_snapshot(view, *, force: bool = False) -> dict[str, Any]:
    _ensure_v4_state(view)
    now = time.monotonic()
    cached = view._v4_health_cache
    if not force and cached and now - cached[0] < 15:
        return cached[1]

    conf = await view.bot.db.get_guild_config(view.guild_id)
    ticket_row = await view.bot.db.fetchone(
        "SELECT COUNT(*) AS n FROM ticket_panels_v2 WHERE guild_id = ?", (view.guild_id,)
    )
    ticket_count = int(_row_value(ticket_row, "n", 0) or 0)
    active_security = sum(1 for value in view.security_choices.values() if value)
    total_security = max(1, len(_CONFIG_MODULE.AUTOMOD_TOGGLE_LABELS))
    security_score = round(active_security / total_security * 100)

    essentials = {
        "Rôle staff": bool(_row_value(conf, "mod_role")),
        "Logs": _logs_configured(conf),
        "Protection": active_security > 0,
        "Bienvenue": bool(_row_value(conf, "welcome_channel")),
        "Tickets": ticket_count > 0,
    }
    essential_done = sum(1 for ok in essentials.values() if ok)
    findings = []
    ops_score = None
    ops_label = None
    ops = getattr(view.bot, "sentrix_ops", None)
    if ops is not None:
        try:
            report = await ops.health_report(view._guild())
            ops_score = int(report.score)
            ops_label = str(report.label)
            findings = list(report.findings)
        except Exception:
            logger.exception("Setup V4 : health_report indisponible guild=%s", view.guild_id)

    fallback_score = round((essential_done / len(essentials)) * 70 + (security_score / 100) * 30)
    data = {
        "score": ops_score if ops_score is not None else fallback_score,
        "label": ops_label or ("Bon" if fallback_score >= 75 else "À renforcer" if fallback_score >= 50 else "Fragile"),
        "security_score": security_score,
        "active_security": active_security,
        "total_security": total_security,
        "essentials": essentials,
        "essential_done": essential_done,
        "ticket_count": ticket_count,
        "findings": findings,
    }
    view._v4_health_cache = (now, data)
    return data


async def _home_embed(self) -> discord.Embed:
    _ensure_v4_state(self)
    health = await _health_snapshot(self)
    guild = self._guild()
    findings = health["findings"]
    next_actions = []
    for item in findings[:3]:
        next_actions.append(f"• {item.title}")
    if not next_actions:
        for label, ok in health["essentials"].items():
            if not ok:
                next_actions.append(f"• Configurer {label.lower()}")
            if len(next_actions) >= 3:
                break
    if not next_actions:
        next_actions.append("• Aucun problème important détecté")

    e = embeds.neutral(
        "SentriX • Setup",
        f"**{guild.name if guild else 'Serveur'}**\nConfiguration intelligente, sans mur de réglages.",
        color=_score_colour(health["score"]),
    )
    e.add_field(name="Santé", value=f"**{health['score']}/100**\n{health['label']}", inline=True)
    e.add_field(name="Sécurité", value=f"**{health['security_score']}%**\n{health['active_security']}/{health['total_security']} protections", inline=True)
    e.add_field(name="Essentiel", value=f"**{health['essential_done']}/5**\néléments prêts", inline=True)
    e.add_field(name="À faire maintenant", value="\n".join(next_actions)[:1024], inline=False)
    if self.dirty:
        e.add_field(name="Modifications en attente", value="Des réglages ne sont pas encore enregistrés.", inline=False)
    if self._v4_last_snapshot:
        e.add_field(name="Point de restauration", value=f"Snapshot **#{self._v4_last_snapshot}** disponible.", inline=False)
    return _decorate_embed(self, e, section="Accueil")


async def _configuration_embed(self) -> discord.Embed:
    _ensure_v4_state(self)
    conf = await self.bot.db.get_guild_config(self.guild_id)
    lines = [
        f"**Préfixe** — {_mention(self, 'prefix', conf)}",
        f"**Rôle staff** — {_mention(self, 'mod_role', conf)}",
        f"**Logs** — {_mention(self, 'log_channel', conf)}",
        f"**Bienvenue** — {_mention(self, 'welcome_channel', conf)}",
        f"**Annonces** — {_mention(self, 'announce_channel', conf)}",
        f"**Rôle automatique** — {_mention(self, 'autorole', conf)}",
    ]
    if self._v4_expert:
        lines.extend([
            f"**Départ** — {_mention(self, 'goodbye_channel', conf)}",
            f"**Suggestions** — {_mention(self, 'suggest_channel', conf)}",
            f"**Giveaways** — {_mention(self, 'giveaway_channel', conf)}",
            f"**Niveaux** — {_mention(self, 'level_channel', conf)}",
        ])
    e = embeds.neutral(
        "SentriX • Configuration",
        "Choisis un réglage, puis le rôle ou le salon. Le mode simple garde uniquement l'essentiel.",
        color=_CONFIG_MODULE.SETUP_COLOR_MAIN,
    )
    e.add_field(name="Réglages actuels", value="\n".join(lines)[:1024], inline=False)
    e.add_field(name="Mode", value="Expert" if self._v4_expert else "Simple", inline=True)
    e.add_field(name="Sauvegarde", value="À enregistrer" if self.dirty else "À jour", inline=True)
    if self.picker_selected:
        settings = _EXPERT_SETTINGS if self._v4_expert else _SIMPLE_SETTINGS
        label = next((item[2] for item in settings if item[0] == self.picker_selected), self.picker_selected)
        e.add_field(name="En cours", value=label, inline=False)
    return _decorate_embed(self, e, section="Configuration")


async def _security_embed(self) -> discord.Embed:
    _ensure_v4_state(self)
    health = await _health_snapshot(self)
    labels = _CONFIG_MODULE.AUTOMOD_TOGGLE_LABELS
    active = [label for field, label in labels.items() if self.security_choices.get(field)]
    security_findings = [
        item for item in health["findings"]
        if str(item.code).startswith(("automod.", "botperm.", "hierarchy."))
    ]
    e = embeds.neutral(
        "SentriX • Sécurité",
        "Préréglage rapide ou contrôle précis. Les corrections automatiques restent limitées aux actions sûres.",
        color=_score_colour(health["security_score"]),
    )
    e.add_field(name="Protection", value=f"**{health['security_score']}/100**", inline=True)
    e.add_field(name="Filtres actifs", value=f"**{len(active)}/{len(labels)}**", inline=True)
    e.add_field(name="Points à vérifier", value=f"**{len(security_findings)}**", inline=True)
    if security_findings:
        e.add_field(
            name="Priorités",
            value="\n".join(f"• {item.title}" for item in security_findings[:5])[:1024],
            inline=False,
        )
    else:
        e.add_field(name="Priorités", value="Aucun problème de sécurité prioritaire détecté.", inline=False)
    return _decorate_embed(self, e, section="Sécurité")


async def _module_states(self) -> list[tuple[str, str]]:
    conf = await self.bot.db.get_guild_config(self.guild_id)
    ticket_row = await self.bot.db.fetchone(
        "SELECT COUNT(*) AS n FROM ticket_panels_v2 WHERE guild_id = ?", (self.guild_id,)
    )
    level_row = await self.bot.db.fetchone(
        "SELECT COUNT(*) AS n FROM level_roles WHERE guild_id = ?", (self.guild_id,)
    )
    ticket_count = int(_row_value(ticket_row, "n", 0) or 0)
    level_count = int(_row_value(level_row, "n", 0) or 0)
    return [
        ("Modération", "Disponible" if self.bot.get_cog("Moderation") or "cogs.moderation" in self.bot.extensions else "Indisponible"),
        ("Bienvenue", "Configuré" if _row_value(conf, "welcome_channel") else "À configurer"),
        ("Tickets", "Configuré" if ticket_count else "À configurer"),
        ("Niveaux", "Configuré" if level_count else "Disponible"),
        ("Logs", "Configuré" if _logs_configured(conf) else "À configurer"),
        ("Auto-rôle", "Configuré" if _row_value(conf, "autorole") else "À configurer"),
        ("Vérification", "Configuré" if _row_value(conf, "verify_role") else "Disponible"),
        ("IA", "Disponible" if "cogs.ai" in self.bot.extensions else "Indisponible"),
        ("Économie", "Disponible" if "cogs.economy" in self.bot.extensions else "Indisponible"),
        ("Notifications", "Disponible" if "cogs.notifications" in self.bot.extensions else "Indisponible"),
    ]


async def _modules_embed(self) -> discord.Embed:
    states = await _module_states(self)
    configured = sum(1 for _name, status in states if status == "Configuré")
    available = sum(1 for _name, status in states if status in {"Configuré", "Disponible"})
    lines = [f"**{name}** — {status}" for name, status in states]
    e = embeds.neutral(
        "SentriX • Modules",
        "Vue unique des fonctions importantes. Ouvre seulement le module que tu veux modifier.",
        color=_CONFIG_MODULE.SETUP_COLOR_MAIN,
    )
    e.add_field(name="Configurés", value=f"**{configured}**", inline=True)
    e.add_field(name="Disponibles", value=f"**{available}/{len(states)}**", inline=True)
    e.add_field(name="État", value="\n".join(lines)[:1024], inline=False)
    return _decorate_embed(self, e, section="Modules")


async def _build_smart_plan(self) -> list[dict[str, Any]]:
    _ensure_v4_state(self)
    guild = self._guild()
    conf = await self.bot.db.get_guild_config(self.guild_id)
    if guild is None:
        return []

    mode = self._v4_mode
    template = SMART_TEMPLATES.get(self._v4_template) or SMART_TEMPLATES["balanced"]
    scopes = set(self._v4_scopes) if mode == "custom" else set(AUTO_SCOPES)
    if mode == "essential":
        scopes = {"security", "logs", "roles"}

    plan: list[dict[str, Any]] = []
    me = guild.me
    perms = me.guild_permissions if me else None

    if me is None:
        plan.append({"kind": "manual", "scope": "security", "automatic": False, "label": "SentriX n'est pas résolu comme membre du serveur"})
    else:
        required = (
            ("manage_channels", "Gérer les salons"),
            ("manage_roles", "Gérer les rôles"),
            ("view_audit_log", "Voir le journal d'audit"),
            ("moderate_members", "Modérer les membres"),
        )
        missing = [label for attr, label in required if not (perms.administrator or getattr(perms, attr, False))]
        if missing:
            plan.append({"kind": "manual", "scope": "security", "automatic": False, "label": "Permissions SentriX à corriger : " + ", ".join(missing)})
        manageable = [r for r in guild.roles if r != guild.default_role and not r.managed]
        if manageable and me.top_role.position <= max(r.position for r in manageable):
            plan.append({"kind": "manual", "scope": "security", "automatic": False, "label": "Remonter le rôle SentriX dans la hiérarchie"})

    if "security" in scopes:
        active = sum(1 for value in self.security_choices.values() if value)
        total = max(1, len(_CONFIG_MODULE.AUTOMOD_TOGGLE_LABELS))
        preset = template["security"]
        target_ratio = {"faible": 0.25, "moyen": 0.5, "eleve": 0.75}.get(preset, 0.5)
        if active / total < target_ratio:
            plan.append({
                "kind": "security_preset", "scope": "security", "automatic": True,
                "preset": preset, "label": f"Appliquer la protection {preset}",
            })

    if "logs" in scopes and not _logs_configured(conf):
        if perms and (perms.administrator or perms.manage_channels):
            plan.append({"kind": "logs", "scope": "logs", "automatic": True, "label": "Créer et connecter le système de logs privés"})
        else:
            plan.append({"kind": "manual", "scope": "logs", "automatic": False, "label": "Logs à configurer après correction des permissions"})

    if "roles" in scopes and not _row_value(conf, "mod_role"):
        role = _find_staff_role(guild)
        if role:
            plan.append({"kind": "set_config", "scope": "roles", "automatic": True, "key": "mod_role", "value": role.id, "label": f"Utiliser {role.name} comme rôle staff"})
        else:
            plan.append({"kind": "manual", "scope": "roles", "automatic": False, "label": "Choisir le rôle staff (aucun rôle évident détecté)"})

    if "roles" in scopes and not _row_value(conf, "autorole"):
        role = _find_member_role(guild)
        if role:
            plan.append({"kind": "set_config", "scope": "roles", "automatic": True, "key": "autorole", "value": role.id, "label": f"Utiliser {role.name} comme rôle automatique"})
        elif mode != "essential" and perms and (perms.administrator or perms.manage_roles):
            plan.append({"kind": "create_role", "scope": "roles", "automatic": True, "key": "autorole", "name": "Membre", "label": "Créer le rôle Membre et l'utiliser comme rôle automatique"})

    if mode != "essential" and "channels" in scopes:
        for key in _template_targets(self._v4_template):
            if _row_value(conf, key):
                continue
            name, aliases = CHANNEL_TARGETS[key]
            channel = _find_text_channel(guild, aliases)
            if channel:
                plan.append({"kind": "set_config", "scope": "channels", "automatic": True, "key": key, "value": channel.id, "label": f"Réutiliser #{channel.name} pour {name}"})
            elif perms and (perms.administrator or perms.manage_channels):
                plan.append({"kind": "create_channel", "scope": "channels", "automatic": True, "key": key, "name": name, "label": f"Créer #{name} et le connecter à SentriX"})
            else:
                plan.append({"kind": "manual", "scope": "channels", "automatic": False, "label": f"Créer/configurer #{name} après correction des permissions"})

    ticket_row = await self.bot.db.fetchone(
        "SELECT COUNT(*) AS n FROM ticket_panels_v2 WHERE guild_id = ?", (self.guild_id,)
    )
    if mode != "essential" and "community" in scopes and template.get("tickets") and not int(_row_value(ticket_row, "n", 0) or 0):
        plan.append({"kind": "manual", "scope": "community", "automatic": False, "label": "Configurer le panel de tickets (choix humain requis)"})

    if mode != "essential" and "community" in scopes and self._v4_template in {"community", "marketplace"} and not _row_value(conf, "verify_role"):
        plan.append({"kind": "manual", "scope": "community", "automatic": False, "label": "Choisir le rôle de vérification"})

    return plan


async def _auto_embed(self) -> discord.Embed:
    _ensure_v4_state(self)
    plan = await _build_smart_plan(self)
    automatic = [item for item in plan if item.get("automatic")]
    manual = [item for item in plan if not item.get("automatic")]
    template = SMART_TEMPLATES.get(self._v4_template) or SMART_TEMPLATES["balanced"]
    mode_labels = {"essential": "Essentiel", "complete": "Complet", "custom": "Personnalisé"}

    e = embeds.neutral(
        "SentriX • Smart Setup",
        "Analyse le serveur, prépare un plan précis, puis demande un aperçu avant toute application.",
        color=_CONFIG_MODULE.SETUP_COLOR_SECONDARY,
    )
    e.add_field(name="Mode", value=f"**{mode_labels.get(self._v4_mode, 'Complet')}**", inline=True)
    e.add_field(name="Modèle", value=f"**{template['label']}**", inline=True)
    e.add_field(name="Plan", value=f"**{len(automatic)} auto** · **{len(manual)} manuel**", inline=True)

    if self._v4_preview_ready:
        auto_lines = [f"• {item['label']}" for item in automatic]
        manual_lines = [f"• {item['label']}" for item in manual]
        e.add_field(name="Aperçu — changements automatiques", value="\n".join(auto_lines)[:1024] if auto_lines else "Aucun changement automatique.", inline=False)
        if manual_lines:
            e.add_field(name="À faire manuellement", value="\n".join(manual_lines)[:1024], inline=False)
        e.add_field(name="Sécurité de l'opération", value="**0 suppression automatique** · snapshot avant application · rôles/salons existants conservés.", inline=False)
    else:
        recommendations = [f"• {item['label']}" for item in plan[:7]]
        e.add_field(name="Analyse", value="\n".join(recommendations)[:1024] if recommendations else "Le serveur ne nécessite aucun changement automatique important.", inline=False)
        e.add_field(name="Avant d'appliquer", value="Clique sur **Prévisualiser** pour verrouiller le plan exact.", inline=False)

    if self._v4_last_result:
        e.add_field(name="Dernière application", value=self._v4_last_result[:1024], inline=False)
    if self._v4_last_snapshot:
        e.add_field(name="Rollback", value=f"Snapshot **#{self._v4_last_snapshot}** disponible. Le rollback restaure la configuration SentriX sans supprimer les rôles/salons créés.", inline=False)
    return _decorate_embed(self, e, section="Smart Setup")


async def _diagnostic(self) -> dict[str, Any]:
    guild = self._guild()
    conf = await self.bot.db.get_guild_config(self.guild_id)
    tests: list[tuple[str, bool, bool]] = []
    if guild is None:
        return {"score": 0, "passed": 0, "total": 1, "warnings": 1, "lines": ["À corriger — serveur introuvable"]}

    me = guild.me
    perms = me.guild_permissions if me else None
    tests.append(("SentriX peut gérer les salons", bool(perms and (perms.administrator or perms.manage_channels)), False))
    tests.append(("SentriX peut gérer les rôles", bool(perms and (perms.administrator or perms.manage_roles)), False))
    tests.append(("Journal d'audit accessible", bool(perms and (perms.administrator or perms.view_audit_log)), False))
    tests.append(("Modération des membres disponible", bool(perms and (perms.administrator or perms.moderate_members)), False))

    mod_role_id = int(_row_value(conf, "mod_role", 0) or 0)
    mod_role = guild.get_role(mod_role_id) if mod_role_id else None
    tests.append(("Rôle staff valide", mod_role is not None, False))
    tests.append(("Système de logs configuré", _logs_configured(conf), False))

    active = sum(1 for value in self.security_choices.values() if value)
    tests.append(("Protection AutoMod active", active > 0, False))

    welcome_id = int(_row_value(conf, "welcome_channel", 0) or 0)
    welcome = guild.get_channel(welcome_id) if welcome_id else None
    welcome_ok = False
    if isinstance(welcome, discord.TextChannel) and me is not None:
        channel_perms = welcome.permissions_for(me)
        welcome_ok = channel_perms.view_channel and channel_perms.send_messages
    tests.append(("Bienvenue prête", welcome_ok, True))

    autorole_id = int(_row_value(conf, "autorole", 0) or 0)
    autorole = guild.get_role(autorole_id) if autorole_id else None
    autorole_ok = autorole is not None and me is not None and (perms.administrator or (perms.manage_roles and me.top_role > autorole))
    tests.append(("Rôle automatique attribuable", autorole_ok, True))

    ticket_row = await self.bot.db.fetchone(
        "SELECT COUNT(*) AS n FROM ticket_panels_v2 WHERE guild_id = ?", (self.guild_id,)
    )
    tests.append(("Panel de tickets configuré", int(_row_value(ticket_row, "n", 0) or 0) > 0, True))

    required = [item for item in tests if not item[2]]
    optional = [item for item in tests if item[2]]
    passed_required = sum(1 for _label, ok, _optional in required if ok)
    passed_optional = sum(1 for _label, ok, _optional in optional if ok)
    score = round((passed_required / max(1, len(required))) * 85 + (passed_optional / max(1, len(optional))) * 15)
    lines = []
    for label, ok, optional_flag in tests:
        if ok:
            prefix = "OK"
        elif optional_flag:
            prefix = "Optionnel"
        else:
            prefix = "À corriger"
        lines.append(f"**{prefix}** — {label}")
    return {
        "score": score,
        "passed": sum(1 for _label, ok, _optional in tests if ok),
        "total": len(tests),
        "warnings": sum(1 for _label, ok, _optional in tests if not ok),
        "lines": lines,
    }


async def _summary_embed(self) -> discord.Embed:
    diagnostic = await _diagnostic(self)
    e = embeds.neutral(
        "SentriX • Terminer",
        "Diagnostic sans effet réel : SentriX vérifie la configuration avant de fermer l'assistant.",
        color=_score_colour(diagnostic["score"]),
    )
    e.add_field(name="Score", value=f"**{diagnostic['score']}/100**", inline=True)
    e.add_field(name="Tests réussis", value=f"**{diagnostic['passed']}/{diagnostic['total']}**", inline=True)
    e.add_field(name="À vérifier", value=f"**{diagnostic['warnings']}**", inline=True)
    e.add_field(name="Diagnostic", value="\n".join(diagnostic["lines"])[:1024], inline=False)
    if self.dirty:
        e.add_field(name="Avant de terminer", value="Des modifications sont encore en attente. Clique sur **Enregistrer**.", inline=False)
    if self._v4_last_snapshot:
        e.add_field(name="Sécurité", value=f"Dernier snapshot automatique : **#{self._v4_last_snapshot}**.", inline=False)
    return _decorate_embed(self, e, section="Diagnostic final")


def _add_nav(view, *, save: bool = False, summary: bool = True, cancel: bool = True, row: int = 4):
    button = _CONFIG_MODULE.SetupNavButton
    view.add_item(button("home", view.message_id, label="Accueil", style=discord.ButtonStyle.secondary, row=row))
    if save:
        view.add_item(button("save", view.message_id, label="Enregistrer", style=discord.ButtonStyle.success, row=row))
    if summary:
        view.add_item(button("summary", view.message_id, label="Terminer", style=discord.ButtonStyle.primary, row=row))
    if cancel:
        view.add_item(button("cancel", view.message_id, label="Fermer", style=discord.ButtonStyle.danger, row=row))


def _render_home(self):
    self.clear_items()
    button = _CONFIG_MODULE.SetupNavButton
    self.add_item(button("prev", self.message_id, label="Configuration", style=discord.ButtonStyle.primary, row=0))
    self.add_item(button("next", self.message_id, label="Sécurité", style=discord.ButtonStyle.primary, row=0))
    self.add_item(button("preview", self.message_id, label="Modules", style=discord.ButtonStyle.secondary, row=0))
    self.add_item(button("restart", self.message_id, label="Smart Setup", style=discord.ButtonStyle.success, row=1))
    self.add_item(button("summary", self.message_id, label="Terminer", style=discord.ButtonStyle.secondary, row=1))
    tools = discord.ui.Select(
        placeholder="Outils du setup",
        options=[
            discord.SelectOption(label="Diagnostic", value="diagnostic", description="Vérifier permissions et configuration"),
            discord.SelectOption(label="Historique", value="history", description="Voir les modifications récentes"),
            discord.SelectOption(label="Actualiser", value="refresh", description="Relancer l'analyse du serveur"),
            discord.SelectOption(label="Créer un snapshot", value="snapshot", description="Sauvegarder la configuration actuelle"),
        ],
        row=2,
    )
    tools.callback = _home_tools_callback(self, tools)
    self.add_item(tools)


def _home_tools_callback(view, select: discord.ui.Select):
    async def callback(interaction: discord.Interaction):
        if not select.values:
            return await interaction.response.defer()
        action = select.values[0]
        if action == "diagnostic":
            view.page = PAGE_SUMMARY
            view.render_page()
            await view.persist_session()
            return await view._refresh_message(interaction)
        if action == "history":
            return await _show_history(view, interaction)
        if action == "snapshot":
            ops = getattr(view.bot, "sentrix_ops", None)
            if ops is None:
                return await interaction.response.send_message("Le système de snapshots n'est pas disponible.", ephemeral=True)
            try:
                sid = await ops.capture_snapshot(view.guild_id, interaction.user.id, label="Snapshot manuel /setup", source="setup-v4-manual")
            except Exception:
                logger.exception("Setup V4 : snapshot manuel impossible guild=%s", view.guild_id)
                return await interaction.response.send_message("Impossible de créer le snapshot pour le moment.", ephemeral=True)
            view._v4_last_snapshot = sid
            return await interaction.response.send_message(f"Snapshot **#{sid}** créé.", ephemeral=True)
        _invalidate_health(view)
        return await view._refresh_message(interaction)
    return callback


class SetupSearchModal(discord.ui.Modal, title="Rechercher un réglage"):
    query = discord.ui.TextInput(label="Réglage recherché", placeholder="Ex: logs, bienvenue, staff, giveaway...", max_length=60)

    def __init__(self, view):
        super().__init__()
        self.view_ref = view

    async def on_submit(self, interaction: discord.Interaction):
        text = _clean_name(self.query.value)
        field = SETTING_ALIASES.get(text)
        settings = _EXPERT_SETTINGS if self.view_ref._v4_expert else _SIMPLE_SETTINGS
        if field is None:
            candidates = []
            for key, _kind, label, description in settings:
                searchable = _clean_name(f"{key} {label} {description}")
                if text and text in searchable:
                    candidates.append(key)
            field = candidates[0] if candidates else None
        valid = {item[0] for item in settings}
        if field not in valid:
            return await interaction.response.send_message("Aucun réglage correspondant dans ce mode. Essaie le mode expert.", ephemeral=True)
        self.view_ref.picker_selected = field
        self.view_ref.render_page()
        await self.view_ref.persist_session()
        await self.view_ref._refresh_message(interaction)


def _configuration_picker_callback(view, select: discord.ui.Select):
    async def callback(interaction: discord.Interaction):
        if select.values:
            view.picker_selected = select.values[0]
        view.render_page()
        await view.persist_session()
        await view._refresh_message(interaction)
    return callback


def _toggle_expert_callback(view):
    async def callback(interaction: discord.Interaction):
        view._v4_expert = not view._v4_expert
        valid = {item[0] for item in (_EXPERT_SETTINGS if view._v4_expert else _SIMPLE_SETTINGS)}
        if view.picker_selected not in valid:
            view.picker_selected = None
        view.render_page()
        await view._refresh_message(interaction)
    return callback


async def _show_history(view, interaction: discord.Interaction):
    rows = await view.bot.db.list_setup_history(view.guild_id, limit=10)
    if not rows:
        return await interaction.response.send_message("Aucune modification enregistrée pour l'instant.", ephemeral=True)
    lines = []
    for row in rows:
        module = str(_row_value(row, "module", "Configuration"))
        action = str(_row_value(row, "action", "modification"))
        user_id = int(_row_value(row, "user_id", 0) or 0)
        created_at = int(_row_value(row, "created_at", 0) or 0)
        when = f"<t:{created_at}:R>" if created_at else "récemment"
        actor = f"<@{user_id}>" if user_id else "SentriX"
        lines.append(f"{when} · **{module}** · {action} · {actor}")
    e = embeds.neutral("SentriX • Historique", "\n".join(lines)[:3900], color=_CONFIG_MODULE.SETUP_COLOR_MAIN)
    e.set_footer(text="SentriX • Setup V4 • 10 dernières actions")
    await interaction.response.send_message(embed=e, ephemeral=True)


async def _module_hint(view, interaction: discord.Interaction, title: str, command: str, detail: str):
    e = embeds.neutral(f"SentriX • {title}", f"{detail}\n\nAccès actuel : **`{command}`**", color=_CONFIG_MODULE.SETUP_COLOR_MAIN)
    e.set_footer(text="SentriX • Setup V4 • Module dédié")
    await interaction.response.send_message(embed=e, ephemeral=True)


def _modules_picker_callback(view, select: discord.ui.Select):
    async def callback(interaction: discord.Interaction):
        if not select.values:
            return await interaction.response.defer()
        target = select.values[0]
        mapping = {
            "configuration": PAGE_CONFIGURATION,
            "security": PAGE_SECURITY,
            "roles": PAGE_ROLES,
            "managers": PAGE_MANAGERS_PROXY,
            "levels": PAGE_LEVELS,
            "logs": PAGE_LOGS,
        }
        if target in mapping:
            view.page = mapping[target]
            view.picker_selected = None
            view.render_page()
            await view.persist_session()
            return await view._refresh_message(interaction)
        if target == "tickets":
            return await _module_hint(view, interaction, "Tickets", "+ticketsetup", "Le système tickets conserve son assistant complet : panels, types, formulaires et contrôles staff.")
        if target == "ai":
            return await _module_hint(view, interaction, "Intelligence artificielle", "+aisetup", "Configuration des fonctions IA et de leurs accès.")
        if target == "notifications":
            return await _module_hint(view, interaction, "Notifications", "+notifs-list", "Gestion des notifications YouTube, TikTok, Twitch et autres sources configurées.")
        if target == "verification":
            view.page = PAGE_CONFIGURATION
            view._v4_expert = True
            view.picker_selected = "verify_role"
            view.render_page()
            await view.persist_session()
            return await view._refresh_message(interaction)
        return await interaction.response.defer()
    return callback


def _set_auto_mode(view, mode: str):
    async def callback(interaction: discord.Interaction):
        view._v4_mode = mode
        view._v4_preview_ready = False
        view._v4_preview_signature = None
        view.render_page()
        await view._refresh_message(interaction)
    return callback


def _template_callback(view, select: discord.ui.Select):
    async def callback(interaction: discord.Interaction):
        if select.values:
            view._v4_template = select.values[0]
            view._v4_preview_ready = False
            view._v4_preview_signature = None
        view.render_page()
        await view._refresh_message(interaction)
    return callback


def _scope_callback(view, select: discord.ui.Select):
    async def callback(interaction: discord.Interaction):
        view._v4_scopes = set(select.values)
        view._v4_preview_ready = False
        view._v4_preview_signature = None
        view.render_page()
        await view._refresh_message(interaction)
    return callback


async def _preview_auto(view, interaction: discord.Interaction):
    plan = await _build_smart_plan(view)
    view._v4_preview_signature = _plan_signature(plan)
    view._v4_preview_ready = True
    view.render_page()
    await view._refresh_message(interaction)


async def _reload_security(view) -> None:
    conf = await view.bot.db.get_automod(view.guild_id)
    for field in _CONFIG_MODULE.AUTOMOD_TOGGLE_LABELS:
        view.security_choices[field] = int(_row_value(conf, field, 0) or 0)


async def _apply_auto(view, interaction: discord.Interaction):
    plan = await _build_smart_plan(view)
    if not view._v4_preview_ready or view._v4_preview_signature != _plan_signature(plan):
        view._v4_preview_ready = False
        view._v4_preview_signature = None
        view.render_page()
        await view._refresh_message(interaction)
        return await interaction.followup.send("Le plan a changé. Prévisualise-le de nouveau avant application.", ephemeral=True) if interaction.response.is_done() else await interaction.response.send_message("Le plan a changé. Prévisualise-le de nouveau avant application.", ephemeral=True)

    automatic = [item for item in plan if item.get("automatic")]
    if not automatic:
        return await interaction.response.send_message("Aucun changement automatique nécessaire.", ephemeral=True)

    await interaction.response.defer()
    guild = interaction.guild
    ops = getattr(view.bot, "sentrix_ops", None)
    snapshot_id = None
    if ops is not None:
        try:
            snapshot_id = await ops.capture_snapshot(
                view.guild_id, interaction.user.id,
                label=f"Avant Smart Setup {SMART_TEMPLATES.get(view._v4_template, SMART_TEMPLATES['balanced'])['label']}",
                source="setup-v4-auto",
            )
        except Exception:
            logger.exception("Setup V4 : snapshot auto impossible guild=%s", view.guild_id)

    applied: list[str] = []
    skipped: list[str] = []
    config_cog = view.bot.get_cog("Configuration")

    for item in automatic:
        try:
            kind = item["kind"]
            if kind == "security_preset":
                for field, value in _CONFIG_MODULE.SECURITY_PRESETS.get(item["preset"], {}).items():
                    await view.bot.db.set_automod(view.guild_id, field, value)
                    view.security_choices[field] = value
                await view.bot.db.set_guild_config(view.guild_id, "security_level", item["preset"])
                automod = view.bot.get_cog("Automod")
                if automod:
                    automod.automod_cache.pop(view.guild_id, None)
                view.security_touched = True
            elif kind == "logs":
                if config_cog is None:
                    raise RuntimeError("Configuration cog absent")
                created = await config_cog.create_log_channels(guild, interaction.user)
                view.logs_created.extend(created)
            elif kind == "set_config":
                await view.bot.db.set_guild_config(view.guild_id, item["key"], item["value"])
            elif kind == "create_channel":
                existing = _find_text_channel(guild, (item["name"],))
                channel = existing or await guild.create_text_channel(
                    item["name"], reason=f"SentriX Smart Setup par {interaction.user}"
                )
                await view.bot.db.set_guild_config(view.guild_id, item["key"], channel.id)
            elif kind == "create_role":
                existing = discord.utils.get(guild.roles, name=item["name"])
                role = existing or await guild.create_role(
                    name=item["name"], reason=f"SentriX Smart Setup par {interaction.user}"
                )
                await view.bot.db.set_guild_config(view.guild_id, item["key"], role.id)
            else:
                continue
            applied.append(item["label"])
            await view.bot.db.log_setup_history(
                view.guild_id, interaction.user.id, "Smart Setup", "réglage automatique", new_value=item["label"]
            )
        except (discord.Forbidden, discord.HTTPException) as exc:
            skipped.append(f"{item['label']} ({type(exc).__name__})")
        except Exception as exc:
            logger.exception("Setup V4 : échec action=%s guild=%s", item.get("kind"), view.guild_id)
            skipped.append(f"{item['label']} ({type(exc).__name__})")

    if ops is not None:
        try:
            await ops.log_admin_action(
                view.guild_id, interaction.user.id, "setup.smart-apply",
                target_type="setup", target_id=view._v4_template,
                before={"snapshot": snapshot_id},
                after={"applied": applied, "skipped": skipped, "mode": view._v4_mode},
                reversible=bool(snapshot_id),
            )
        except Exception:
            logger.exception("Setup V4 : journal admin impossible guild=%s", view.guild_id)

    if snapshot_id:
        view._v4_last_snapshot = snapshot_id
    view._v4_last_result = f"{len(applied)} changement(s) appliqué(s)" + (f" · {len(skipped)} à vérifier" if skipped else "")
    view._v4_preview_ready = False
    view._v4_preview_signature = None
    _invalidate_health(view)
    await _reload_security(view)
    await view.persist_session()
    view.render_page()
    await view._refresh_message(interaction)

    text = f"Smart Setup terminé : **{len(applied)}** changement(s) appliqué(s)."
    if snapshot_id:
        text += f" Snapshot de sécurité : **#{snapshot_id}**."
    if skipped:
        text += "\nÀ vérifier : " + " ; ".join(skipped)[:1200]
    await interaction.followup.send(text, ephemeral=True)


async def _rollback_auto(view, interaction: discord.Interaction):
    _ensure_v4_state(view)
    if not view._v4_last_snapshot:
        return await interaction.response.send_message("Aucun snapshot Smart Setup disponible dans cette session.", ephemeral=True)
    ops = getattr(view.bot, "sentrix_ops", None)
    if ops is None:
        return await interaction.response.send_message("Le système de rollback n'est pas disponible.", ephemeral=True)

    confirm = helpers.ConfirmView(interaction.user.id, timeout=30)
    await interaction.response.send_message(
        f"Restaurer la configuration SentriX depuis le snapshot **#{view._v4_last_snapshot}** ?\n"
        "Les rôles et salons créés par Smart Setup ne seront pas supprimés automatiquement.",
        view=confirm,
        ephemeral=True,
    )
    await confirm.wait()
    if not confirm.value:
        return
    try:
        result = await ops.restore_snapshot(view.guild_id, interaction.user.id, view._v4_last_snapshot)
    except Exception as exc:
        logger.exception("Setup V4 : rollback impossible guild=%s", view.guild_id)
        return await interaction.followup.send(f"Rollback impossible : {type(exc).__name__}.", ephemeral=True)
    view._v4_last_snapshot = result.get("safety_snapshot")
    view._v4_last_result = f"Configuration restaurée depuis le snapshot #{result.get('restored')}"
    _invalidate_health(view)
    await _reload_security(view)
    view.render_page()
    await view._refresh_message(interaction)
    await interaction.followup.send("Configuration SentriX restaurée. Les ressources Discord existantes ont été conservées.", ephemeral=True)


async def _apply_safe_security_fixes(view, interaction: discord.Interaction):
    health = await _health_snapshot(view, force=True)
    fixable = [item for item in health["findings"] if getattr(item, "auto_fixable", False)]
    if not fixable:
        return await interaction.response.send_message("Aucune correction automatique sûre n'est nécessaire.", ephemeral=True)
    ops = getattr(view.bot, "sentrix_ops", None)
    if ops is None:
        return await interaction.response.send_message("Le moteur de corrections sûres n'est pas disponible.", ephemeral=True)

    confirm = helpers.ConfirmView(interaction.user.id, timeout=30)
    await interaction.response.send_message(
        f"Appliquer **{len(fixable)}** correction(s) de sécurité sûres ? Un snapshot sera créé avant.",
        view=confirm,
        ephemeral=True,
    )
    await confirm.wait()
    if not confirm.value:
        return

    try:
        sid = await ops.capture_snapshot(view.guild_id, interaction.user.id, label="Avant corrections sécurité /setup", source="setup-v4-security")
    except Exception:
        sid = None
    done, failed = [], []
    for finding in fixable:
        try:
            await ops.apply_safe_fix(interaction.guild, interaction.user.id, finding.code)
            done.append(finding.code)
        except Exception:
            failed.append(finding.code)
    if sid:
        view._v4_last_snapshot = sid
    await _reload_security(view)
    _invalidate_health(view)
    view.render_page()
    await view._refresh_message(interaction)
    text = f"Corrections appliquées : **{len(done)}**."
    if failed:
        text += f" Échecs : **{len(failed)}**."
    await interaction.followup.send(text, ephemeral=True)


def _render_page(self):
    _ensure_v4_state(self)
    if self.page == PAGE_HOME:
        _render_home(self)
        return

    if self.page == PAGE_CONFIGURATION:
        self.clear_items()
        settings = _EXPERT_SETTINGS if self._v4_expert else _SIMPLE_SETTINGS
        picker = discord.ui.Select(
            placeholder="Choisir un réglage à modifier",
            options=[discord.SelectOption(label=label, value=field, description=description[:100]) for field, _kind, label, description in settings],
            row=0,
        )
        picker.callback = _configuration_picker_callback(self, picker)
        self.add_item(picker)
        if self.picker_selected:
            meta = next((item for item in settings if item[0] == self.picker_selected), None)
            if meta:
                field, kind, label, _description = meta
                if kind == "role":
                    value_select = discord.ui.RoleSelect(placeholder=f"Choisir : {label}"[:100], row=1)
                    value_select.callback = self._make_picker_role_value_callback(field, value_select)
                else:
                    value_select = discord.ui.ChannelSelect(placeholder=f"Choisir : {label}"[:100], channel_types=[discord.ChannelType.text], row=1)
                    value_select.callback = self._make_picker_channel_value_callback(field, value_select)
                self.add_item(value_select)
        text_button = discord.ui.Button(label="Préfixe & messages", style=discord.ButtonStyle.secondary, row=2)
        text_button.callback = self._open_text_modal
        self.add_item(text_button)
        search_button = discord.ui.Button(label="Rechercher", style=discord.ButtonStyle.secondary, row=2)
        async def search_callback(interaction: discord.Interaction):
            await interaction.response.send_modal(SetupSearchModal(self))
        search_button.callback = search_callback
        self.add_item(search_button)
        expert_button = discord.ui.Button(label="Mode simple" if self._v4_expert else "Mode expert", style=discord.ButtonStyle.secondary, row=2)
        expert_button.callback = _toggle_expert_callback(self)
        self.add_item(expert_button)
        _add_nav(self, save=True)
        return

    if self.page == PAGE_SECURITY:
        self.clear_items()
        for label, level, style in (
            ("Faible", "faible", discord.ButtonStyle.secondary),
            ("Moyen", "moyen", discord.ButtonStyle.primary),
            ("Élevé", "eleve", discord.ButtonStyle.danger),
        ):
            button = discord.ui.Button(label=label, style=style, row=0)
            button.callback = self._make_security_preset_callback(level)
            self.add_item(button)
        options = [
            discord.SelectOption(label=label, value=field, default=bool(self.security_choices.get(field)))
            for field, label in list(_CONFIG_MODULE.AUTOMOD_TOGGLE_LABELS.items())[:25]
        ]
        precise = discord.ui.Select(
            placeholder="Choisir précisément les protections",
            min_values=0,
            max_values=len(options),
            options=options,
            row=1,
        )
        precise.callback = self._make_security_select_callback(precise)
        self.add_item(precise)
        fix_button = discord.ui.Button(label="Corriger les problèmes sûrs", style=discord.ButtonStyle.success, row=2)
        async def fix_callback(interaction: discord.Interaction):
            await _apply_safe_security_fixes(self, interaction)
        fix_button.callback = fix_callback
        self.add_item(fix_button)
        _add_nav(self, save=False)
        return

    if self.page == PAGE_MODULES:
        self.clear_items()
        select = discord.ui.Select(
            placeholder="Ouvrir un module",
            options=[
                discord.SelectOption(label="Configuration / salons", value="configuration"),
                discord.SelectOption(label="Sécurité", value="security"),
                discord.SelectOption(label="Rôles", value="roles"),
                discord.SelectOption(label="Tickets", value="tickets"),
                discord.SelectOption(label="Vérification", value="verification"),
                discord.SelectOption(label="Niveaux", value="levels"),
                discord.SelectOption(label="Logs", value="logs"),
                discord.SelectOption(label="Gestionnaires", value="managers"),
                discord.SelectOption(label="IA", value="ai"),
                discord.SelectOption(label="Notifications", value="notifications"),
            ],
            row=0,
        )
        select.callback = _modules_picker_callback(self, select)
        self.add_item(select)
        _add_nav(self, save=False)
        return

    if self.page == PAGE_AUTO:
        self.clear_items()
        for label, mode, style in (
            ("Essentiel", "essential", discord.ButtonStyle.secondary),
            ("Complet", "complete", discord.ButtonStyle.primary),
            ("Personnalisé", "custom", discord.ButtonStyle.secondary),
        ):
            button = discord.ui.Button(label=label, style=style, row=0, disabled=self._v4_mode == mode)
            button.callback = _set_auto_mode(self, mode)
            self.add_item(button)
        template_select = discord.ui.Select(
            placeholder="Choisir un modèle de serveur",
            options=[
                discord.SelectOption(label=meta["label"], value=key, description=meta["description"][:100], default=self._v4_template == key)
                for key, meta in SMART_TEMPLATES.items()
            ],
            row=1,
        )
        template_select.callback = _template_callback(self, template_select)
        self.add_item(template_select)
        if self._v4_mode == "custom":
            scope_select = discord.ui.Select(
                placeholder="Choisir ce que Smart Setup peut modifier",
                min_values=1,
                max_values=len(AUTO_SCOPES),
                options=[discord.SelectOption(label=label, value=key, default=key in self._v4_scopes) for key, label in AUTO_SCOPES.items()],
                row=2,
            )
            scope_select.callback = _scope_callback(self, scope_select)
            self.add_item(scope_select)
        action_row = 3
        preview = discord.ui.Button(label="Prévisualiser", style=discord.ButtonStyle.secondary, row=action_row)
        async def preview_callback(interaction: discord.Interaction):
            await _preview_auto(self, interaction)
        preview.callback = preview_callback
        self.add_item(preview)
        apply_button = discord.ui.Button(label="Appliquer", style=discord.ButtonStyle.success, row=action_row, disabled=not self._v4_preview_ready)
        async def apply_callback(interaction: discord.Interaction):
            await _apply_auto(self, interaction)
        apply_button.callback = apply_callback
        self.add_item(apply_button)
        if self._v4_last_snapshot:
            rollback = discord.ui.Button(label="Rollback config", style=discord.ButtonStyle.danger, row=action_row)
            async def rollback_callback(interaction: discord.Interaction):
                await _rollback_auto(self, interaction)
            rollback.callback = rollback_callback
            self.add_item(rollback)
        _add_nav(self, save=False, row=4)
        return

    if self.page == PAGE_SUMMARY:
        self.clear_items()
        button = _CONFIG_MODULE.SetupNavButton
        self.add_item(button("home", self.message_id, label="Accueil", style=discord.ButtonStyle.secondary, row=0))
        self.add_item(button("save", self.message_id, label="Enregistrer", style=discord.ButtonStyle.primary, row=0))
        refresh = discord.ui.Button(label="Relancer diagnostic", style=discord.ButtonStyle.secondary, row=0)
        async def refresh_callback(interaction: discord.Interaction):
            _invalidate_health(self)
            await self._refresh_message(interaction)
        refresh.callback = refresh_callback
        self.add_item(refresh)
        self.add_item(button("finish", self.message_id, label="Terminer le setup", style=discord.ButtonStyle.success, row=0))
        return

    if self.page == PAGE_MANAGERS_PROXY:
        current = self.page
        self.page = 6
        try:
            self._sentrix_v113_original_render_page()
        finally:
            self.page = current
        return

    self._sentrix_v113_original_render_page()


async def _build_embed(self) -> discord.Embed:
    _ensure_v4_state(self)
    if self.page == PAGE_HOME:
        return await _home_embed(self)
    if self.page == PAGE_CONFIGURATION:
        return await _configuration_embed(self)
    if self.page == PAGE_SECURITY:
        return await _security_embed(self)
    if self.page == PAGE_MODULES:
        return await _modules_embed(self)
    if self.page == PAGE_AUTO:
        return await _auto_embed(self)
    if self.page == PAGE_SUMMARY:
        return await _summary_embed(self)
    if self.page == PAGE_MANAGERS_PROXY:
        current = self.page
        self.page = 6
        try:
            return await self._sentrix_v113_original_build_embed()
        finally:
            self.page = current
    return await self._sentrix_v113_original_build_embed()


async def _handle_nav_action(self, interaction: discord.Interaction, action: str):
    _ensure_v4_state(self)
    if self.page == PAGE_HOME:
        target = {
            "prev": PAGE_CONFIGURATION,
            "next": PAGE_SECURITY,
            "preview": PAGE_MODULES,
            "restart": PAGE_AUTO,
            "summary": PAGE_SUMMARY,
        }.get(action)
        if target is not None:
            self.page = target
            self.picker_selected = None
            self.render_page()
            await self.persist_session()
            return await self._refresh_message(interaction)

    if action == "home" and self.page != PAGE_HOME:
        self.page = PAGE_HOME
        self.picker_selected = None
        self.render_page()
        await self.persist_session()
        return await self._refresh_message(interaction)

    if action == "summary" and self.page != PAGE_SUMMARY:
        self.page = PAGE_SUMMARY
        self.picker_selected = None
        self.render_page()
        await self.persist_session()
        return await self._refresh_message(interaction)

    result = await self._sentrix_v113_original_handle_nav_action(interaction, action)
    if action in {"save", "finish"}:
        _invalidate_health(self)
    return result


def install_for_bot(bot) -> None:
    """Patche SetupView après le chargement du cog, sans remplacer ses données."""
    global _CONFIG_MODULE, _INSTALLED
    if _INSTALLED:
        return
    configuration = bot.get_cog("Configuration")
    if configuration is None:
        logger.warning("V113/V4 non installé : cog Configuration absent.")
        return

    from cogs import configuration as config_module

    _CONFIG_MODULE = config_module
    view_cls = config_module.SetupView
    if getattr(view_cls, "_sentrix_v113", False):
        _INSTALLED = True
        return

    view_cls._sentrix_v113_original_render_page = view_cls.render_page
    view_cls._sentrix_v113_original_build_embed = view_cls.build_embed
    view_cls._sentrix_v113_original_handle_nav_action = view_cls.handle_nav_action
    view_cls.render_page = _render_page
    view_cls.build_embed = _build_embed
    view_cls.handle_nav_action = _handle_nav_action
    view_cls._sentrix_v113 = True

    for active_view in list(getattr(configuration, "active_setups", {}).values()):
        try:
            _ensure_v4_state(active_view)
            if active_view.page not in {
                PAGE_HOME, PAGE_CONFIGURATION, PAGE_ROLES, PAGE_MANAGERS_PROXY,
                PAGE_MODULES, PAGE_LEVELS, PAGE_LOGS, PAGE_AUTO, PAGE_SECURITY, PAGE_SUMMARY,
            }:
                active_view.page = PAGE_HOME
            active_view.render_page()
        except Exception:
            logger.exception("V113/V4 : impossible de migrer une session /setup ouverte.")

    _INSTALLED = True
    logger.info("SentriX Setup V4 actif : Smart Setup, modèles, preview, snapshot, rollback et diagnostic.")


__all__ = [
    "AUTO_SCOPES",
    "CHANNEL_TARGETS",
    "SETTING_ALIASES",
    "SMART_TEMPLATES",
    "_clean_name",
    "_plan_signature",
    "_score_colour",
    "_template_targets",
    "install_for_bot",
]
