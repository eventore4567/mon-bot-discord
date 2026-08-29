"""SentriX V69 — refonte complète du Setup, structure inspirée du Control Center Oxyde.

Ce module remplace uniquement l'expérience VISUELLE du Setup. Les données, les
permissions Discord, les protections V66/V68 et les callbacks historiques restent la
source de vérité.

Principes :
- un panneau large et sobre ;
- une seule navigation principale ;
- une page claire par module ;
- statut/configuration en haut, réglages utiles ensuite ;
- pas de miniature, pas de pavés de texte, pas de commandes techniques visibles ;
- Permissions et Sécurité = un seul bouton Activer/Désactiver ;
- aucune règle Setup ne peut créer une permission Discord.
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

logger = logging.getLogger("bot.setup-oxyde-v69")

RUNTIME_MARKER = "Setup V69"
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
    "security": "Protection automatique du serveur.",
    "logs": "Journaux et salons de suivi.",
    "tickets": "Panels, catégories et équipe support.",
    "welcome": "Messages d'arrivée, départ et autorôle.",
    "roles": "Rôles automatiques, membre et vérification.",
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
    panel.set_footer(text=f"SentriX • Control Center{label} • Enregistrement automatique")
    return panel


class OxydePageSelect(discord.ui.Select):
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
            placeholder="Choisir une page du Control Center",
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
    def __init__(self, owner):
        self.owner = owner
        super().__init__(label="Activer / Désactiver", style=discord.ButtonStyle.primary, row=1)

    async def callback(self, interaction: discord.Interaction):
        row = await self.owner.bot.db.fetchone(
            "SELECT * FROM automod_settings WHERE guild_id = ?",
            (self.owner.guild.id,),
        )
        enabled = any(bool(setup_ui._get(row, field, 0)) for field, _ in setup_ui.AUTOMOD) if row else False
        await self.owner.bot.db.execute(
            "INSERT INTO automod_settings (guild_id) VALUES (?) ON CONFLICT(guild_id) DO NOTHING",
            (self.owner.guild.id,),
        )
        columns = ", ".join(f"{field} = ?" for field, _ in setup_ui.AUTOMOD)
        target = 0 if enabled else 1
        values = tuple(target for _field, _label_value in setup_ui.AUTOMOD)
        await self.owner.bot.db.execute(
            f"UPDATE automod_settings SET {columns} WHERE guild_id = ?",
            (*values, self.owner.guild.id),
        )
        await self.owner.audit(interaction.user.id, "security_profile", "off" if enabled else "on")
        await self.owner.refresh(interaction)


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
        if isinstance(child, OxydePageSelect):
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
                pass


def _patch_setup_controls() -> None:
    cls = setup_ui.SetupView
    if getattr(cls.render, "_sentrix_oxyde_v69", False):
        return

    previous_render = cls.render

    def render_v69(self) -> None:
        previous_render(self)
        for child in list(self.children):
            if getattr(child, "row", None) == 0:
                self.remove_item(child)
        self.add_item(OxydePageSelect(self))

        if self.category in {"permissions", "security"}:
            for child in list(self.children):
                if isinstance(child, OxydePageSelect):
                    continue
                self.remove_item(child)
            if self.category == "permissions":
                self.add_item(PermissionToggleButton(self))
            else:
                self.add_item(SecurityToggleButton(self))
        else:
            for child in list(self.children):
                if isinstance(child, OxydePageSelect):
                    continue
                label = str(getattr(child, "label", "") or "").casefold()
                if label in {"accueil", "actualiser", "fermer"}:
                    self.remove_item(child)
            _compact_rows(self)

    render_v69._sentrix_permissions_v66 = True
    render_v69._sentrix_setup_simple_v68 = True
    render_v69._sentrix_oxyde_v69 = True
    render_v69._sentrix_previous = previous_render
    cls.render = render_v69


async def _build_home(self, original: discord.Embed) -> discord.Embed:
    del original
    conf = await self.bot.db.get_guild_config(self.guild.id)
    statuses = await setup_ui.module_statuses(self.bot, self.guild, conf)
    active = sum(state == setup_ui.ConfigState.ACTIVE for state, _, _ in statuses.values())
    panel = _panel(
        "SentriX • Control Center",
        "Gérez tout le serveur depuis un seul panneau. Choisissez une page dans le menu ci-dessous.",
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
        "Profil de protection automatique SentriX. Aucun réglage compliqué à faire.",
    )
    panel.add_field(name="État du module", value="● ACTIF" if active else "○ INACTIF", inline=True)
    panel.add_field(name="Profil", value="**AUTOMATIQUE**", inline=True)
    panel.add_field(
        name="Protections gérées",
        value="Anti-spam · Anti-raid · Anti-liens · Anti-invitations · Anti-ping · Anti-scam · Anti-nuke · comptes récents · bots",
        inline=False,
    )
    panel.add_field(
        name="Important",
        value="Activer applique le profil complet. Désactiver coupe l'automod mais ne change aucune permission Discord des membres ou du staff.",
        inline=False,
    )
    return _footer(panel, page="security")


async def _build_page(self, original: discord.Embed) -> discord.Embed:
    page_id = str(self.category)
    source = _clean_panel(original.copy())
    fields = _field_map(source)
    panel = _panel(_label(page_id), _description(page_id))

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
    if getattr(cls.build_embed, "_sentrix_oxyde_v69", False):
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
    build_embed_v69._sentrix_oxyde_v69 = True
    build_embed_v69._sentrix_previous = previous_build
    cls.build_embed = build_embed_v69


def install(bot: commands.Bot) -> None:
    """Dernière autorité visuelle du Setup. La sécurité V68 reste inchangée."""
    v68._install_permission_runtime()
    _patch_setup_controls()
    _patch_setup_embed()
    setup_ui.SetupView._sentrix_oxyde_v69 = True
    bot._sentrix_setup_oxyde_v69 = True
    logger.info("V69 actif : ancien design Setup remplacé par le Control Center large page-par-page.")


__all__ = ["RUNTIME_MARKER", "WIDE_RULE", "PAGE_ORDER", "install"]
