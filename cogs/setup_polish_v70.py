"""SentriX V70 — finition visuelle du Control Center.

V70 ne modifie aucun moteur métier. Elle s'installe après V69 et ne fait que :
- uniformiser les pages ;
- rendre l'accueil lisible en quelques secondes ;
- réduire les textes inutiles ;
- mieux utiliser la largeur des embeds Discord ;
- rendre les états ACTIF / INACTIF / À CORRIGER immédiatement visibles ;
- simplifier la navigation et les libellés des contrôles.

Les callbacks, les écritures DB, les permissions Discord et la politique Owner restent
ceux des couches V68/V69.
"""
from __future__ import annotations

import logging
import re

import discord
from discord.ext import commands

from utils import embeds
from . import setup_control_center as setup_ui
from . import setup_v2_core as core
from . import setup_oxyde_v69 as v69

logger = logging.getLogger("bot.setup-polish-v70")

RUNTIME_MARKER = "Control Center V70"
WIDE_RULE = "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

HOME_GROUPS = (
    ("ESSENTIEL", ("moderation", "security", "logs")),
    ("COMMUNAUTÉ", ("tickets", "welcome", "roles")),
    ("SERVICES", ("levels", "notifications", "ai", "permissions")),
)

SHORT_DESCRIPTIONS = {
    "moderation": "Staff, sanctions et rôles de modération.",
    "security": "Protection automatique du serveur.",
    "logs": "Journaux et salons de suivi.",
    "tickets": "Panels et équipe support.",
    "welcome": "Arrivées, départs et autorôle.",
    "roles": "Rôles automatiques et récompenses.",
    "levels": "Progression, XP et économie.",
    "notifications": "YouTube, Twitch et TikTok.",
    "ai": "Assistant et génération d'images.",
    "permissions": "Restrictions supplémentaires SentriX.",
}


def _label(page_id: str) -> str:
    return v69._label(page_id)


def _description(page_id: str) -> str:
    return SHORT_DESCRIPTIONS.get(page_id, v69._description(page_id))


def _plain(value: object) -> str:
    text = str(value or "").replace("**", "").replace("`", "")
    return re.sub(r"\s+", " ", text).strip()


def _state(value: object) -> str:
    raw = _plain(value).upper()
    if "ERREUR" in raw or "CORRIGER" in raw or "MANQUANT" in raw:
        return "! À CORRIGER"
    if "NON CONFIG" in raw:
        return "— NON CONFIGURÉ"
    if "INACTIF" in raw or raw in {"OFF", "0"}:
        return "○ INACTIF"
    if "ACTIF" in raw or raw in {"ON", "1"}:
        return "● ACTIF"
    return _plain(value) or "—"


def _panel(title: str, subtitle: str, *, context: str | None = None) -> discord.Embed:
    context_line = f"**{context}**\n" if context else ""
    panel = embeds.brand(title, f"{context_line}{WIDE_RULE}\n{subtitle}")
    panel.set_thumbnail(url=None)
    return panel


def _footer(panel: discord.Embed, *, page: str | None = None) -> discord.Embed:
    suffix = f" • {_label(page)}" if page else ""
    panel.set_footer(text=f"SentriX • Control Center V70{suffix} • Sauvegarde automatique")
    return panel


def _field_map(panel: discord.Embed) -> dict[str, str]:
    return {str(field.name).casefold(): str(field.value or "") for field in panel.fields}


def _pick(fields: dict[str, str], *names: str, default: str = "—") -> str:
    for name in names:
        value = fields.get(name.casefold())
        if value is not None:
            return value
    return default


def _is_generic_field(name: str) -> bool:
    key = name.casefold()
    return key in {
        "état", "etat", "état du module", "etat du module",
        "configuration", "configuration actuelle",
        "permissions sentrix", "permissions du bot",
    }


def _detail_name(name: str) -> str:
    cleaned = _plain(name)
    if cleaned.casefold() in {"problèmes détectés", "problemes detectes"}:
        return "À CORRIGER"
    return cleaned.upper()


def _add_details(source: discord.Embed, target: discord.Embed) -> None:
    added = 0
    for field in source.fields:
        name = str(field.name or "")
        if _is_generic_field(name):
            continue
        value = str(field.value or "—").strip()
        if not value:
            continue
        compact = value.replace("\n\n", "\n")
        inline = len(compact) <= 240 and compact.count("\n") <= 2
        target.add_field(name=_detail_name(name), value=compact[:1024], inline=inline)
        added += 1
        if added >= 6:
            break


def _add_bot_permissions(source: discord.Embed, target: discord.Embed) -> None:
    fields = _field_map(source)
    raw = _pick(fields, "Permissions du bot", "Permissions SentriX", default="")
    if not raw:
        return
    if "MANQUANT" in raw.upper():
        missing = []
        for part in re.split(r"[\n·]", raw):
            if "MANQUANT" in part.upper():
                missing.append(_plain(part).replace(": MANQUANT", ""))
        target.add_field(
            name="PERMISSIONS DU BOT",
            value="! À CORRIGER" + (f" — {', '.join(missing)}" if missing else ""),
            inline=False,
        )
    else:
        target.add_field(name="PERMISSIONS DU BOT", value="● TOUT EST PRÊT", inline=True)


class V70PageSelect(discord.ui.Select):
    # V70 retire ET remplace TOUT enfant en ligne 0 à chaque render() (voir render_v70
    # plus bas) : c'est donc la dernière autorité réelle du menu de navigation, et les
    # options de sous-page posées par les couches antérieures (V3CategorySelect,
    # _V4CategorySelectCompat) ne survivaient jamais jusqu'à l'utilisateur. Sans ces
    # entrées ici, "Rôles — Règles & CAPTCHA" (et "Rôles — Panel de choix",
    # "Sécurité — Vérification") étaient injoignables par le menu en production.
    _SUBPAGES = {
        "security_verification": ("security", "verification"),
        "roles_panel": ("roles", "panel"),
        "roles_rules": ("roles", "rules"),
    }

    def __init__(self, owner):
        self.owner = owner
        subpage = getattr(owner, "_v3_subpage", None)
        current = next(
            (value for value, (cat, sub) in self._SUBPAGES.items() if owner.category == cat and subpage == sub),
            owner.category or "__home__",
        )
        options = [
            discord.SelectOption(
                label="Accueil",
                value="__home__",
                description="Vue générale du serveur.",
                default=current == "__home__",
            )
        ]
        for key in tuple(setup_ui.CATEGORIES.keys()):
            options.append(
                discord.SelectOption(
                    label=_label(key)[:100],
                    value=key,
                    description=_description(key)[:100],
                    default=current == key,
                )
            )
        if "security" in setup_ui.CATEGORIES:
            options.append(discord.SelectOption(
                label="Sécurité — Vérification",
                value="security_verification",
                description="Vérification renforcée et honeypot anti-bot",
                default=current == "security_verification",
            ))
        if "roles" in setup_ui.CATEGORIES:
            options.append(discord.SelectOption(
                label="Rôles — Panel de choix",
                value="roles_panel",
                description="Salon et rôles proposés aux membres",
                default=current == "roles_panel",
            ))
            options.append(discord.SelectOption(
                label="Rôles — Règles & CAPTCHA",
                value="roles_rules",
                description="Salon des règles, rôle donné et CAPTCHA de vérification",
                default=current == "roles_rules",
            ))
        placeholder = "Accueil" if owner.category is None else f"Page : {_label(str(owner.category))}"
        super().__init__(placeholder=placeholder[:150], options=options[:25], row=0)

    async def callback(self, interaction: discord.Interaction):
        value = self.values[0]
        self.owner._v3_subpage = None
        if value in self._SUBPAGES:
            self.owner.category, self.owner._v3_subpage = self._SUBPAGES[value]
        else:
            self.owner.category = None if value == "__home__" else value
        self.owner.selected_log = None
        self.owner.selected_ticket = None
        self.owner.selected_notification = None
        await self.owner.refresh(interaction)


def _normalise_control_labels(view) -> None:
    for child in list(view.children):
        if isinstance(child, discord.ui.Button):
            label = str(child.label or "")
            folded = label.casefold()
            if "activer / désactiver" in folded or "activer / desactiver" in folded:
                child.label = "Activer / Désactiver"
            elif folded == "modifier les limites":
                child.label = "Limites IA"


def _compact_rows(view) -> None:
    row_map: dict[int, int] = {}
    next_row = 1
    for child in list(view.children):
        if isinstance(child, V70PageSelect):
            continue
        row = getattr(child, "row", None)
        old = int(row) if row is not None else next_row
        if old not in row_map:
            row_map[old] = next_row
            next_row = min(4, next_row + 1)
        try:
            child.row = row_map[old]
        except Exception:
            try:
                child._row = row_map[old]
            except Exception:
                pass


def _patch_render() -> None:
    cls = setup_ui.SetupView
    if getattr(cls.render, "_sentrix_polish_v70", False):
        return
    previous_render = cls.render

    def render_v70(self) -> None:
        previous_render(self)
        for child in list(self.children):
            if isinstance(child, (v69.OxydePageSelect, V70PageSelect)) or getattr(child, "row", None) == 0:
                self.remove_item(child)
        self.add_item(V70PageSelect(self))
        _normalise_control_labels(self)
        _compact_rows(self)

    render_v70._sentrix_permissions_v66 = True
    render_v70._sentrix_setup_simple_v68 = True
    render_v70._sentrix_oxyde_v69 = True
    render_v70._sentrix_polish_v70 = True
    render_v70._sentrix_previous = previous_render
    cls.render = render_v70


def _patch_prepare() -> None:
    cls = setup_ui.SetupView
    if getattr(cls.prepare, "_sentrix_polish_v70", False):
        return
    previous_prepare = cls.prepare

    async def prepare_v70(self) -> None:
        await previous_prepare(self)
        _normalise_control_labels(self)
        _compact_rows(self)

    prepare_v70._sentrix_polish_v70 = True
    prepare_v70._sentrix_previous = previous_prepare
    cls.prepare = prepare_v70


async def _home(self) -> discord.Embed:
    conf = await self.bot.db.get_guild_config(self.guild.id)
    statuses = await setup_ui.module_statuses(self.bot, self.guild, conf)
    permissions_enabled = await core.module_enabled(self.bot, self.guild.id, "permissions")

    active = sum(state == setup_ui.ConfigState.ACTIVE for state, _, _ in statuses.values())
    errors = sum(state == setup_ui.ConfigState.ERROR for state, _, _ in statuses.values())
    completion = setup_ui._completion(statuses)

    panel = _panel(
        "SentriX — Control Center",
        f"**{completion}% configuré**  ·  **{active}/{len(statuses)} modules actifs**  ·  **{errors} à corriger**",
        context=self.guild.name,
    )

    all_states: dict[str, str] = {
        key: _state(data[0]) for key, data in statuses.items()
    }
    all_states["permissions"] = "● ACTIF" if permissions_enabled else "○ INACTIF"

    for heading, keys in HOME_GROUPS:
        lines = []
        for key in keys:
            if key in all_states:
                lines.append(f"**{_label(key)}**  {all_states[key]}")
        if lines:
            panel.add_field(name=heading, value="\n".join(lines), inline=True)

    problems = []
    for key, data in statuses.items():
        if data[0] != setup_ui.ConfigState.ERROR:
            continue
        detail = data[2][0] if data[2] else "Configuration à vérifier."
        problems.append(f"**{_label(key)}** — {detail}")
    if problems:
        panel.add_field(name="À CORRIGER", value="\n".join(problems)[:1024], inline=False)

    panel.add_field(
        name="NAVIGATION",
        value="Choisissez une page dans le menu ci-dessous. Chaque modification est enregistrée automatiquement.",
        inline=False,
    )
    return _footer(panel)


async def _permissions(self) -> discord.Embed:
    enabled = await core.module_enabled(self.bot, self.guild.id, "permissions")
    panel = _panel(
        "SentriX — Permissions",
        "Restrictions supplémentaires de SentriX.",
        context=self.guild.name,
    )
    panel.add_field(name="ÉTAT", value="● ACTIF" if enabled else "○ INACTIF", inline=True)
    panel.add_field(name="SÉCURITÉ DISCORD", value="● TOUJOURS ACTIVE", inline=True)
    panel.add_field(
        name="FONCTIONNEMENT",
        value="Ce bouton contrôle uniquement les restrictions SentriX. Les permissions Discord réelles et les commandes Owner restent toujours protégées.",
        inline=False,
    )
    return _footer(panel, page="permissions")


async def _security(self) -> discord.Embed:
    row = await self.bot.db.fetchone("SELECT * FROM automod_settings WHERE guild_id = ?", (self.guild.id,))
    enabled_count = sum(bool(setup_ui._get(row, field, 0)) for field, _ in setup_ui.AUTOMOD) if row else 0
    total = len(setup_ui.AUTOMOD)
    active = enabled_count > 0
    panel = _panel(
        "SentriX — Sécurité",
        "Protection automatique du serveur, sans configuration compliquée.",
        context=self.guild.name,
    )
    panel.add_field(name="ÉTAT", value="● ACTIF" if active else "○ INACTIF", inline=True)
    panel.add_field(name="PROFIL", value="AUTOMATIQUE", inline=True)
    panel.add_field(name="PROTECTIONS", value=f"**{enabled_count}/{total} actives**", inline=True)
    panel.add_field(
        name="COUVERTURE",
        value="Anti-spam · Anti-raid · Anti-liens · Anti-invitations · Anti-ping · Anti-scam · Anti-nuke · comptes récents · bots",
        inline=False,
    )
    panel.add_field(
        name="FONCTIONNEMENT",
        value="Activer applique le profil complet. Désactiver coupe l'automod sans modifier les droits Discord du staff ou des membres.",
        inline=False,
    )
    return _footer(panel, page="security")


async def _generic_page(self, source: discord.Embed) -> discord.Embed:
    page_id = str(self.category)
    fields = _field_map(source)
    state = _state(_pick(fields, "État du module", "État", default="—"))
    configuration = _plain(_pick(fields, "Configuration actuelle", "Configuration", default="—")) or "—"

    # V69 transmet déjà un titre de sous-page nu (ex: "Rôles — Règles & CAPTCHA") sans
    # préfixe de marque quand la page en a un : le respecter au lieu de toujours
    # retomber sur le libellé nu de la catégorie perdait les sous-pages en route.
    source_title = str(getattr(source, "title", "") or "")
    panel = _panel(
        f"SentriX — {source_title or _label(page_id)}",
        _description(page_id),
        context=self.guild.name,
    )
    panel.add_field(name="ÉTAT", value=state, inline=True)
    panel.add_field(name="CONFIGURATION", value=configuration[:1024], inline=True)

    _add_details(source, panel)
    _add_bot_permissions(source, panel)
    return _footer(panel, page=page_id)


def _patch_embed() -> None:
    cls = setup_ui.SetupView
    if getattr(cls.build_embed, "_sentrix_polish_v70", False):
        return
    previous_build = cls.build_embed

    async def build_embed_v70(self) -> discord.Embed:
        source = await previous_build(self)
        if self.category is None:
            return await _home(self)
        if self.category == "permissions":
            return await _permissions(self)
        if self.category == "security":
            return await _security(self)
        return await _generic_page(self, source)

    build_embed_v70._sentrix_permissions_v66 = True
    build_embed_v70._sentrix_setup_simple_v68 = True
    build_embed_v70._sentrix_oxyde_v69 = True
    build_embed_v70._sentrix_polish_v70 = True
    build_embed_v70._sentrix_previous = previous_build
    cls.build_embed = build_embed_v70


def install(bot: commands.Bot) -> None:
    """Installe uniquement la finition visuelle, après V69."""
    _patch_render()
    _patch_prepare()
    _patch_embed()
    setup_ui.SetupView._sentrix_polish_v70 = True
    bot._sentrix_setup_polish_v70 = True
    logger.info("V70 actif : Control Center uniformisé, accueil compact et navigation finalisée.")


__all__ = ["RUNTIME_MARKER", "WIDE_RULE", "install"]
