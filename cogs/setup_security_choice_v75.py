"""SentriX V75 — protections de sécurité choisies, permissions Discord automatiques.

Cette couche corrige la page Sécurité de V74 :
- l'administrateur choisit exactement les protections anti-* à activer ;
- les permissions Kick/Ban/Timeout/Gérer les messages/etc. ne sont jamais demandées ici ;
- SentriX s'appuie sur les permissions Discord réelles et la hiérarchie au moment de l'action ;
- les permissions propres au bot sont seulement auditées, car Discord interdit à un bot de
  modifier lui-même son rôle d'intégration géré.
"""
from __future__ import annotations

import logging
from typing import Any

import discord
from discord.ext import commands

from . import security_verification_v71 as security_v71
from . import setup_control_center as setup_ui
from . import setup_experience_v74 as v74
from . import setup_v2_core as core

logger = logging.getLogger("bot.setup-security-choice-v75")

RUNTIME_MARKER = "Setup Security Choice V75"

EXTRA_PROTECTIONS: tuple[tuple[str, str, str], ...] = (
    (
        "honeypot",
        "Honeypot anti-raid",
        "Piège les comptes suspects qui interagissent avec le salon de sécurité.",
    ),
    (
        "verification",
        "Vérification anti-alt",
        "Ajoute la vérification humaine et le score de confiance SentriX.",
    ),
)

AUTOMOD_DESCRIPTIONS = {
    "antispam": "Bloque les messages envoyés trop rapidement.",
    "antiraid": "Détecte les arrivées massives et active le mode raid.",
    "antilink": "Bloque les liens selon la configuration du serveur.",
    "antiinvite": "Bloque les invitations Discord non autorisées.",
    "antimention": "Bloque les abus de mentions et de pings.",
    "anticaps": "Limite les messages abusivement en majuscules.",
    "antiemoji": "Limite le spam massif d'emojis.",
    "antibot": "Protège contre les ajouts de bots suspects.",
    "antiaccount": "Filtre les comptes Discord trop récents.",
    "antiscam": "Détecte et bloque les contenus typiques de scam.",
    "antinuke": "Protège les rôles, salons et actions serveur sensibles.",
}


def _row_get(row: Any, key: str, default: Any = None) -> Any:
    if row is None:
        return default
    try:
        value = row[key]
    except (KeyError, IndexError, TypeError):
        return default
    return default if value is None else value


async def _selected_protections(view: v74.SentriXSetupV74) -> set[str]:
    row = await view.bot.db.fetchone(
        "SELECT * FROM automod_settings WHERE guild_id = ?",
        (view.guild.id,),
    )
    selected = {
        field
        for field, _label in setup_ui.AUTOMOD
        if bool(_row_get(row, field, 0))
    }

    try:
        advanced = await security_v71.settings(view.bot, view.guild.id)
    except Exception:
        logger.debug("Lecture des réglages sécurité V71 impossible", exc_info=True)
        advanced = {}

    if bool(advanced.get("honeypot_enabled", False)):
        selected.add("honeypot")
    if bool(advanced.get("verification_enabled", False)):
        selected.add("verification")
    return selected


async def _refresh_security_runtime(view: v74.SentriXSetupV74) -> None:
    security_v71._invalidate_automod(view.bot, view.guild.id)
    runtime = getattr(view.bot, "_sentrix_security_v71_runtime", None)
    if runtime is not None:
        try:
            await runtime.refresh_gateway_panels(view.guild)
        except Exception:
            logger.debug("Rafraîchissement du runtime sécurité indisponible", exc_info=True)


async def _save_protections(
    view: v74.SentriXSetupV74,
    chosen: set[str],
    *,
    actor_id: int,
) -> None:
    automod_fields = {field for field, _label in setup_ui.AUTOMOD}
    chosen_automod = chosen & automod_fields

    await view.bot.db.execute(
        "INSERT INTO automod_settings(guild_id) VALUES(?) ON CONFLICT(guild_id) DO NOTHING",
        (view.guild.id,),
    )
    columns = ", ".join(f"{field} = ?" for field, _label in setup_ui.AUTOMOD)
    values = tuple(1 if field in chosen_automod else 0 for field, _label in setup_ui.AUTOMOD)
    await view.bot.db.execute(
        f"UPDATE automod_settings SET {columns} WHERE guild_id = ?",
        (*values, view.guild.id),
    )

    await security_v71.ensure_schema(view.bot)
    honeypot_enabled = int("honeypot" in chosen)
    verification_enabled = int("verification" in chosen)
    await security_v71.update_setting(
        view.bot,
        view.guild.id,
        "honeypot_enabled",
        honeypot_enabled,
        actor_id,
    )
    await security_v71.update_setting(
        view.bot,
        view.guild.id,
        "verification_enabled",
        verification_enabled,
        actor_id,
    )

    await view.bot.db.execute(
        "INSERT INTO honeypot_verification(guild_id,enabled,created_at) "
        "VALUES(?,?,strftime('%s','now')) "
        "ON CONFLICT(guild_id) DO UPDATE SET enabled=excluded.enabled",
        (view.guild.id, honeypot_enabled),
    )

    await core.set_module_enabled(
        view.bot,
        view.guild.id,
        "security",
        bool(chosen),
        actor_id=actor_id,
    )
    await _refresh_security_runtime(view)


async def _effective_states_v75(self: v74.SentriXSetupV74) -> dict[str, str]:
    previous = getattr(_effective_states_v75, "_sentrix_previous")
    states = await previous(self)
    selected = await _selected_protections(self)
    states["security"] = "● ACTIF" if selected else "○ INACTIF"
    return states


async def _build_security_v75(self: v74.SentriXSetupV74) -> None:
    selected = await _selected_protections(self)
    _ok, missing = v74._bot_permission_audit(self.guild)

    option_specs: list[tuple[str, str, str]] = [
        (
            field,
            label,
            AUTOMOD_DESCRIPTIONS.get(field, f"Protection {label} SentriX."),
        )
        for field, label in setup_ui.AUTOMOD
    ]
    option_specs.extend(EXTRA_PROTECTIONS)
    total = len(option_specs)

    status = discord.ui.Button(
        label=f"{len(selected)}/{total} actives",
        style=discord.ButtonStyle.success if selected else discord.ButtonStyle.secondary,
        disabled=True,
    )

    container = discord.ui.Container(accent_colour=v74.v73.ACCENT)
    container.add_item(
        discord.ui.Section(
            discord.ui.TextDisplay(
                "# 🔒 Sécurité\n"
                "Choisissez **exactement les protections anti** que vous voulez utiliser. "
                "Vous pouvez en activer une seule, plusieurs ou toutes.\n\n"
                "Les permissions **Kick, Ban, Timeout, Gérer les messages, Gérer les rôles, "
                "Gérer les salons, etc. ne se règlent pas ici** : SentriX vérifie automatiquement "
                "les permissions Discord réelles de la personne qui lance la commande et respecte "
                "la hiérarchie des rôles."
            ),
            accessory=v74.v73._thumbnail(self.bot),
        )
    )
    container.add_item(discord.ui.Separator())

    permissions_text = (
        "### Permissions gérées automatiquement\n"
        "✅ SentriX possède actuellement les permissions nécessaires pour ses fonctions principales.\n"
        "Aucun rôle `kick`, `ban` ou autre n'est à configurer dans ce panneau."
        if not missing
        else (
            "### Permissions gérées automatiquement\n"
            "SentriX choisit automatiquement les permissions requises pour chaque action, "
            "mais **son propre rôle Discord** ne possède pas encore : "
            + ", ".join(missing[:12])
            + ".\nDiscord ne permet pas au bot de modifier lui-même son rôle d'intégration géré ; "
            "ces permissions doivent être accordées au rôle SentriX dans les paramètres du serveur."
        )
    )
    container.add_item(
        discord.ui.Section(
            discord.ui.TextDisplay(permissions_text),
            accessory=status,
        )
    )

    container.add_item(discord.ui.Separator())
    container.add_item(discord.ui.TextDisplay("### Protections actives"))

    protection_select = discord.ui.Select(
        placeholder="Choisir les protections anti à activer",
        min_values=0,
        max_values=total,
        options=[
            discord.SelectOption(
                label=label,
                value=key,
                description=description[:100],
                default=key in selected,
            )
            for key, label, description in option_specs
        ],
    )

    async def save_selection(interaction: discord.Interaction):
        if not interaction.response.is_done():
            await interaction.response.defer()
        await _save_protections(
            self,
            set(protection_select.values),
            actor_id=interaction.user.id,
        )
        await self.refresh(interaction)

    protection_select.callback = save_selection
    container.add_item(discord.ui.ActionRow(protection_select))

    all_on = discord.ui.Button(label="Tout activer", style=discord.ButtonStyle.success)
    all_off = discord.ui.Button(label="Tout désactiver", style=discord.ButtonStyle.danger)

    async def enable_all(interaction: discord.Interaction):
        if not interaction.response.is_done():
            await interaction.response.defer()
        await _save_protections(
            self,
            {key for key, _label, _description in option_specs},
            actor_id=interaction.user.id,
        )
        await self.refresh(interaction)

    async def disable_all(interaction: discord.Interaction):
        if not interaction.response.is_done():
            await interaction.response.defer()
        await _save_protections(self, set(), actor_id=interaction.user.id)
        await self.refresh(interaction)

    all_on.callback = enable_all
    all_off.callback = disable_all
    container.add_item(discord.ui.ActionRow(all_on, all_off))

    active_labels = [label for key, label, _description in option_specs if key in selected]
    if active_labels:
        container.add_item(discord.ui.TextDisplay("**Actuellement :** " + " · ".join(active_labels)))
    else:
        container.add_item(discord.ui.TextDisplay("**Actuellement :** aucune protection active."))

    self._add_navigation(container)
    self.add_item(container)


def install(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_setup_security_choice_v75", False):
        return

    cls = v74.SentriXSetupV74

    current_security = cls._build_security
    if not getattr(current_security, "_sentrix_security_choice_v75", False):
        _build_security_v75._sentrix_security_choice_v75 = True
        _build_security_v75._sentrix_previous = current_security
        cls._build_security = _build_security_v75

    current_states = cls._effective_states
    if not getattr(current_states, "_sentrix_security_choice_v75", False):
        _effective_states_v75._sentrix_security_choice_v75 = True
        _effective_states_v75._sentrix_previous = current_states
        cls._effective_states = _effective_states_v75

    v74.CATEGORY_META["security"] = (
        "🔒",
        "Sécurité",
        "Choisissez individuellement les protections anti ; les permissions Discord sont automatiques.",
    )

    from . import setup_moderation_clear_v76 as moderation_v76
    moderation_v76.install(bot)

    # Le help officiel est déjà chargé à ce stade du finaliseur runtime. V77 peut donc
    # remplacer uniquement son rendu sans toucher aux commandes +help et /help elles-mêmes.
    from . import help_components_v77 as help_v77
    help_v77.install(bot)

    bot._sentrix_setup_security_choice_v75 = True
    logger.info(
        "%s installé : protections anti sélectionnables, permissions Kick/Ban/etc. automatiques.",
        RUNTIME_MARKER,
    )


__all__ = ["install"]
