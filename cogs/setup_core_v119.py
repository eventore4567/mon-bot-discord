"""SentriX Setup Core — couche de compatibilité visuelle du Setup.

Cette couche conserve les données, permissions Discord et callbacks historiques,
mais impose les règles actuelles de SentriX :
- interface compacte et lisible ;
- une page claire par module ;
- aucun salon, rôle, permission ou protection choisi automatiquement ;
- chaque changement vient d'une action explicite de l'utilisateur ;
- aucune recréation d'une ressource supprimée.
"""
from __future__ import annotations

import logging
from typing import Iterable

import discord
from discord.ext import commands

from utils import embeds
from . import setup_control_center as setup_ui
from . import setup_v2_core as core
from . import setup_simple_v68 as v68

logger = logging.getLogger("bot.setup-core-v119")

RUNTIME_MARKER = "SentriX Setup Core V119"
WIDE_RULE = "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
SHOW_THUMBNAILS = False

PAGE_LABELS = {
    "moderation": "Modération",
    "security": "Sécurité",
    "logs": "Logs",
    "tickets": "Tickets",
    "welcome": "Bienvenue",
    "roles": "Rôles",
    "levels": "Niveaux & économie",
    "notifications": "Notifications",
    "ai": "Intelligence artificielle",
    "permissions": "Permissions",
}

PAGE_DESCRIPTIONS = {
    "moderation": "Rôles staff et outils de modération.",
    "security": "Protections du serveur choisies manuellement.",
    "logs": "Journaux et salons de suivi.",
    "tickets": "Panels, catégories et équipe support.",
    "welcome": "Messages d'arrivée, départ et autorôle.",
    "roles": "Rôles, membres et vérification.",
    "levels": "Progression, économie et récompenses.",
    "notifications": "YouTube, Twitch, TikTok et rôles de notification.",
    "ai": "Assistant, limites et génération d'images.",
    "permissions": "Active ou désactive les restrictions supplémentaires SentriX.",
}


def _page_order() -> tuple[str, ...]:
    return tuple(setup_ui.CATEGORIES.keys())


PAGE_ORDER = _page_order()


def _label(page_id: str) -> str:
    if page_id in PAGE_LABELS:
        return PAGE_LABELS[page_id]
    raw = setup_ui.CATEGORIES.get(page_id, (page_id.replace("_", " ").title(), ""))[0]
    return str(raw)


def _description(page_id: str) -> str:
    if page_id in PAGE_DESCRIPTIONS:
        return PAGE_DESCRIPTIONS[page_id]
    return str(setup_ui.CATEGORIES.get(page_id, ("", "Configuration SentriX."))[1])


def _state_text(value: object) -> str:
    raw = str(getattr(value, "value", value) or "NON CONFIGURÉ").upper()
    if raw == "ACTIF":
        return "● ACTIF"
    if raw == "INACTIF":
        return "○ INACTIF"
    if "ERREUR" in raw:
        return "! À CORRIGER"
    return "— NON CONFIGURÉ"


def _strip_old_rule(text: str) -> str:
    lines = str(text or "").splitlines()
    while lines and lines[0].strip() and set(lines[0].strip()) <= {"━", "—", "-", "_"}:
        lines.pop(0)
    return "\n".join(lines).strip()


def _clean_panel(panel: discord.Embed) -> discord.Embed:
    panel.set_thumbnail(url=None)
    panel.description = _strip_old_rule(str(panel.description or ""))
    return panel


def _field_map(panel: discord.Embed) -> dict[str, str]:
    return {str(field.name): str(field.value) for field in list(panel.fields)}


def _pick(fields: dict[str, str], *names: str, default: str = "—") -> str:
    lowered = {key.casefold(): value for key, value in fields.items()}
    for name in names:
        if name.casefold() in lowered:
            return lowered[name.casefold()]
    return default


def _copy_matching_fields(
    source: discord.Embed,
    target: discord.Embed,
    *,
    excluded: Iterable[str] = (),
    limit: int = 5,
) -> None:
    blocked = {name.casefold() for name in excluded}
    count = 0
    for field in list(source.fields):
        if str(field.name).casefold() in blocked:
            continue
        value = str(field.value or "—").strip()
        if not value:
            continue
        target.add_field(name=str(field.name), value=value[:1024], inline=False)
        count += 1
        if count >= limit:
            break


def _panel(title: str, subtitle: str) -> discord.Embed:
    result = embeds.brand(title, f"{WIDE_RULE}\n{subtitle}")
    result.set_thumbnail(url=None)
    return result


def _footer(panel: discord.Embed, *, page: str | None = None) -> discord.Embed:
    label = f" • {_label(page)}" if page else ""
    panel.set_footer(text=f"SentriX Core · Setup{label} · Sauvegarde après chaque choix")
    return panel


class SentriXPageSelect(discord.ui.Select):
    def __init__(self, owner):
        self.owner = owner
        options = [
            discord.SelectOption(
                label="Accueil",
                value="__home__",
                description="Vue générale de la configuration.",
            )
        ]
        for key in _page_order():
            options.append(
                discord.SelectOption(
                    label=_label(key)[:100],
                    value=key,
                    description=_description(key)[:100],
                )
            )
        super().__init__(
            placeholder="Choisir une page de SentriX Setup",
            options=options[:25],
            row=0,
        )

    async def callback(self, interaction: discord.Interaction):
        value = self.values[0]
        self.owner.category = None if value == "__home__" else value
        self.owner.selected_log = None
        self.owner.selected_ticket = None
        self.owner.selected_notification = None
        await self.owner.refresh(interaction)


class SecurityToggleButton(discord.ui.Button):
    """Compatibilité V69 : ne configure jamais toutes les protections d'un coup."""

    def __init__(self, owner):
        self.owner = owner
        super().__init__(label="Configurer les protections", style=discord.ButtonStyle.secondary, row=1)

    async def callback(self, interaction: discord.Interaction):
        # La sécurité se règle protection par protection dans les couches Setup
        # suivantes. Ce bouton historique ne modifie volontairement aucune valeur.
        await interaction.response.send_message(
            "Choisis les protections individuellement dans la page Sécurité.",
            ephemeral=True,
        )


class PermissionToggleButton(discord.ui.Button):
    def __init__(self, owner):
        self.owner = owner
        super().__init__(label="Activer / Désactiver", style=discord.ButtonStyle.primary, row=1)

    async def callback(self, interaction: discord.Interaction):
        enabled = await core.module_enabled(self.owner.bot, self.owner.guild.id, "permissions")
        await core.set_module_enabled(
            self.owner.bot,
            self.owner.guild.id,
            "permissions",
            not enabled,
            actor_id=interaction.user.id,
        )
        await self.owner.audit(
            interaction.user.id,
            "module:permissions",
            "off" if enabled else "on",
        )
        await self.owner.refresh(interaction)


def _compact_rows(view) -> None:
    next_row = 1
    row_map: dict[int, int] = {}
    for child in list(view.children):
        if isinstance(child, SentriXPageSelect):
            continue
        old_row = getattr(child, "row", None)
        if old_row is None:
            old_row = next_row
        if old_row not in row_map:
            row_map[old_row] = next_row
            next_row = min(4, next_row + 1)
        try:
            child.row = row_map[old_row]
        except Exception:
            try:
                child._row = row_map[old_row]
            except Exception:
                logger.warning("Étape non critique ignorée dans _compact_rows", exc_info=True)


def _patch_setup_controls() -> None:
    cls = setup_ui.SetupView
    if getattr(cls.render, "_sentrix_setup_core_v119", False):
        return

    previous_render = cls.render

    def render_v69(self) -> None:
        previous_render(self)
        for child in list(self.children):
            if getattr(child, "row", None) == 0:
                self.remove_item(child)
        self.add_item(SentriXPageSelect(self))

        if self.category == "permissions":
            for child in list(self.children):
                if isinstance(child, SentriXPageSelect):
                    continue
                self.remove_item(child)
            self.add_item(PermissionToggleButton(self))
        else:
            for child in list(self.children):
                if isinstance(child, SentriXPageSelect):
                    continue
                label = str(getattr(child, "label", "") or "").casefold()
                if label in {"accueil", "actualiser", "fermer"}:
                    self.remove_item(child)
            _compact_rows(self)

    render_v69._sentrix_permissions_v66 = True
    render_v69._sentrix_setup_simple_v68 = True
    render_v69._sentrix_setup_core_v119 = True
    render_v69._sentrix_previous = previous_render
    cls.render = render_v69


async def _build_home(self, original: discord.Embed) -> discord.Embed:
    del original
    conf = await self.bot.db.get_guild_config(self.guild.id)
    statuses = await setup_ui.module_statuses(self.bot, self.guild, conf)
    active = sum(state == setup_ui.ConfigState.ACTIVE for state, _, _ in statuses.values())
    panel = _panel(
        "SentriX Setup",
        "Configure le serveur depuis un seul panneau. Chaque changement vient de ton choix.",
    )
    panel.add_field(name="Serveur", value=f"**{self.guild.name}**", inline=True)
    panel.add_field(name="Modules actifs", value=f"**{active} / {len(statuses)}**", inline=True)
    panel.add_field(name="Configuration", value=f"**{setup_ui._completion(statuses)} %**", inline=True)

    lines = []
    for key in setup_ui.CATEGORY_ORDER:
        if key not in statuses:
            continue
        state, summary, _problems = statuses[key]
        lines.append(f"**{_label(key)}**  ·  {_state_text(state)}\n{summary}")
    panel.add_field(name="Aperçu", value="\n\n".join(lines)[:1024] or "Aucun module disponible.", inline=False)

    problems = []
    for key, data in statuses.items():
        if data[0] == setup_ui.ConfigState.ERROR and data[2]:
            problems.append(f"**{_label(key)}** — {data[2][0]}")
    if problems:
        panel.add_field(name="À corriger", value="\n".join(problems)[:1024], inline=False)
    return _footer(panel)


async def _build_permissions(self) -> discord.Embed:
    enabled = await core.module_enabled(self.bot, self.guild.id, "permissions")
    panel = _panel(
        "Permissions",
        "Un seul réglage. SentriX applique ou ignore ses restrictions supplémentaires.",
    )
    panel.add_field(name="État du module", value="● ACTIF" if enabled else "○ INACTIF", inline=True)
    panel.add_field(name="Permissions Discord", value="**TOUJOURS OBLIGATOIRES**", inline=True)
    panel.add_field(
        name="À savoir",
        value=(
            "Désactiver ce module ne donne aucun droit de modération aux membres. "
            "Ban, Kick, Mute, Clear, gestion des rôles/salons et commandes administrateur "
            "restent protégés par les permissions Discord réelles."
        ),
        inline=False,
    )
    panel.add_field(
        name="Commandes membres",
        value="Jeux, argent, banque, classements, invitations, niveaux et utilitaires restent disponibles normalement.",
        inline=False,
    )
    return _footer(panel, page="permissions")


async def _build_security(self) -> discord.Embed:
    row = await self.bot.db.fetchone("SELECT * FROM automod_settings WHERE guild_id = ?", (self.guild.id,))
    enabled_count = sum(bool(setup_ui._get(row, field, 0)) for field, _ in setup_ui.AUTOMOD) if row else 0
    active = enabled_count > 0
    panel = _panel(
        "Sécurité",
        "Choisis uniquement les protections dont ton serveur a besoin.",
    )
    panel.add_field(name="État du module", value="● ACTIF" if active else "○ INACTIF", inline=True)
    panel.add_field(name="Mode", value="**MANUEL**", inline=True)
    panel.add_field(
        name="Protections gérées",
        value="Anti-spam · Anti-raid · Anti-liens · Anti-invitations · Anti-ping · Anti-scam · Anti-nuke · comptes récents · bots",
        inline=False,
    )
    panel.add_field(
        name="Important",
        value="SentriX n'active aucune protection à ta place. Chaque protection est choisie séparément.",
        inline=False,
    )
    return _footer(panel, page="security")


_TITLE_PREFIX = "SentriX — "


def _page_title(page_id: str, original: discord.Embed) -> str:
    """Respecte un titre de sous-page (ex: "Rôles — Règles & CAPTCHA") au lieu de
    toujours retomber sur le libellé nu de la catégorie : cette page reconstruit
    l'embed depuis zéro et ignorait jusqu'ici le titre déjà choisi en amont."""
    original_title = str(getattr(original, "title", "") or "")
    if original_title.startswith(_TITLE_PREFIX):
        return original_title[len(_TITLE_PREFIX):]
    return _label(page_id)


async def _build_page(self, original: discord.Embed) -> discord.Embed:
    page_id = str(self.category)
    source = _clean_panel(original.copy())
    fields = _field_map(source)
    panel = _panel(_page_title(page_id, original), _description(page_id))

    state = _pick(fields, "État", "État du module", default="—")
    config = _pick(fields, "Configuration", "Configuration actuelle", default="—")
    panel.add_field(name="État du module", value=state, inline=True)
    panel.add_field(name="Configuration actuelle", value=config, inline=True)

    _copy_matching_fields(
        source,
        panel,
        excluded={
            "État", "État du module", "Configuration", "Configuration actuelle",
            "Permissions SentriX", "Permissions du bot",
        },
        limit=4,
    )

    bot_perms = _pick(fields, "Permissions SentriX", "Permissions du bot", default="")
    if bot_perms and bot_perms != "—":
        compact = bot_perms.replace("\n", "  ·  ")
        panel.add_field(name="Permissions du bot", value=compact[:1024], inline=False)
    return _footer(panel, page=page_id)


def _patch_setup_embed() -> None:
    cls = setup_ui.SetupView
    if getattr(cls.build_embed, "_sentrix_setup_core_v119", False):
        return
    previous_build = cls.build_embed

    async def build_embed_v69(self) -> discord.Embed:
        original = await previous_build(self)
        if self.category is None:
            return await _build_home(self, original)
        if self.category == "permissions":
            return await _build_permissions(self)
        if self.category == "security":
            return await _build_security(self)
        return await _build_page(self, original)

    build_embed_v69._sentrix_permissions_v66 = True
    build_embed_v69._sentrix_setup_simple_v68 = True
    build_embed_v69._sentrix_setup_core_v119 = True
    build_embed_v69._sentrix_previous = previous_build
    cls.build_embed = build_embed_v69


def install(bot: commands.Bot) -> None:
    """Couche de compatibilité du Setup ; aucune configuration automatique."""
    v68._install_permission_runtime()
    _patch_setup_controls()
    _patch_setup_embed()
    setup_ui.SetupView._sentrix_setup_core_v119 = True
    bot._sentrix_setup_core_v119 = True
    logger.info("SentriX Setup Core actif : navigation manuelle page-par-page.")


__all__ = [
    "RUNTIME_MARKER", "WIDE_RULE", "PAGE_ORDER", "SentriXPageSelect",
    "_label", "_description", "_state_text", "_clean_panel", "_field_map",
    "_copy_matching_fields", "_panel", "_footer", "install",
]
