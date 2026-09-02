"""SentriX V75 — protections de sécurité choisies, permissions Discord automatiques.

Cette couche corrige la page Sécurité de V74 :
- l'administrateur choisit exactement les protections anti-* à activer ;
- les permissions Kick/Ban/Timeout/Gérer les messages/etc. ne sont jamais demandées ici ;
- SentriX s'appuie sur les permissions Discord réelles et la hiérarchie au moment de l'action ;
- les permissions propres au bot sont seulement auditées, car Discord interdit à un bot de
  modifier lui-même son rôle d'intégration géré.

Elle possède aussi la page Logs finale. Cette page n'utilise plus les anciens Select du
backend V69/V70 déplacés dans Components V2 : catégorie et salon sont des composants natifs
de la façade finale, ce qui évite les erreurs de parent/rebuild et rend le choix du salon
visible immédiatement.
"""
from __future__ import annotations

import logging
from typing import Any

import discord
from discord.ext import commands

from utils import log_service
from utils import sentrix_panels as panels
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


def _log_options() -> list[discord.SelectOption]:
    """Construit les catégories au moment du rendu afin d'inclure les extensions runtime."""
    return [
        discord.SelectOption(
            label=str(meta.get("label") or meta.get("category") or key).strip()[:100],
            value=key,
            description=(
                f"Choisir le salon pour {str(meta.get('label') or key).strip()}"
            )[:100],
        )
        for key, meta in log_service.LOG_TYPES.items()
        if meta.get("emits", True)
    ][:25]


async def _audit_log_choice(
    view: v74.SentriXSetupV74,
    actor_id: int,
    log_type: str,
    value: object,
) -> None:
    try:
        await view.backend.audit(actor_id, f"log:{log_type}", value)
    except Exception:
        logger.debug("Audit du choix de salon de logs indisponible", exc_info=True)


async def _safe_log_refresh(
    view: v74.SentriXSetupV74,
    interaction: discord.Interaction,
) -> None:
    """ACK puis refresh du message Components V2 sans réutiliser la vue legacy."""
    if not interaction.response.is_done():
        await interaction.response.defer()
    await view.refresh(interaction)


async def _build_logs_v75(self: v74.SentriXSetupV74) -> None:
    """Page Logs native Components V2 : catégorie ET salon sont toujours accessibles."""
    self.backend.category = "logs"

    options = _log_options()
    available = [option.value for option in options]
    if not available:
        container = discord.ui.Container(accent_colour=v74.v73.ACCENT)
        container.add_item(
            discord.ui.Section(
                discord.ui.TextDisplay(
                    "# 📜 Logs du serveur\nAucune catégorie de logs n'est disponible dans ce runtime."
                ),
                accessory=v74.v73._thumbnail(self.bot),
            )
        )
        self._add_navigation(container)
        self.add_item(container)
        return

    selected = getattr(self.backend, "selected_log", None)
    if selected not in available:
        selected = "moderation" if "moderation" in available else available[0]
        self.backend.selected_log = selected

    # Statut complet du routage. Le salon dédié est affiché en priorité ; sinon on montre
    # le fallback général afin que l'administrateur voie immédiatement pourquoi un log est
    # envoyé dans un autre salon.
    route_lines: list[str] = []
    all_settings: dict[str, dict] = {}
    for key in available:
        meta = log_service.LOG_TYPES.get(key, {})
        setting = await log_service.get_log_setting(self.bot, self.guild.id, key)
        all_settings[key] = setting
        enabled = bool(setting.get("enabled"))
        dedicated = setting.get("dedicated_channel_id")
        fallback = setting.get("fallback_channel_id")
        effective = setting.get("channel_id")
        channel_id = dedicated or effective
        channel = self.guild.get_channel(int(channel_id)) if channel_id else None
        if channel is not None:
            destination = channel.mention
            if not dedicated and fallback:
                destination += " *(repli général)*"
        elif channel_id:
            destination = f"`{channel_id}` *(salon introuvable)*"
        else:
            destination = "*aucun salon*"
        label = str(meta.get("label") or meta.get("category") or key)
        route_lines.append(
            f"**{label}** — {'ACTIF' if enabled else 'INACTIF'} — {destination}"
        )

    selected_meta = log_service.LOG_TYPES.get(selected, {})
    selected_label = str(
        selected_meta.get("label") or selected_meta.get("category") or selected
    )
    selected_setting = all_settings[selected]
    selected_channel_id = (
        selected_setting.get("dedicated_channel_id")
        or selected_setting.get("channel_id")
    )
    selected_channel = (
        self.guild.get_channel(int(selected_channel_id)) if selected_channel_id else None
    )

    if selected_channel is not None:
        valid, detail = log_service.validate_channel(
            self.guild,
            selected_channel.id,
            needs_file=(selected == "tickets"),
        )
        selected_route = selected_channel.mention
        permission_line = "● TOUT EST PRÊT" if valid else f"⚠️ {detail}"
    else:
        selected_route = "aucun salon choisi"
        permission_line = "⚠️ Choisissez un salon ci-dessous."

    status = discord.ui.Button(
        label="Actif" if bool(selected_setting.get("enabled")) else "Inactif",
        style=(
            discord.ButtonStyle.success
            if bool(selected_setting.get("enabled"))
            else discord.ButtonStyle.secondary
        ),
        disabled=True,
    )

    container = discord.ui.Container(accent_colour=v74.v73.ACCENT)
    container.add_item(
        discord.ui.Section(
            discord.ui.TextDisplay(
                "# 📜 Logs du serveur\n"
                "Choisissez une catégorie puis **le salon exact** où SentriX doit envoyer ces logs.\n"
                "Les deux menus restent visibles en permanence : aucun ancien panneau caché n'est utilisé."
            ),
            accessory=v74.v73._thumbnail(self.bot),
        )
    )
    container.add_item(discord.ui.Separator())
    container.add_item(
        discord.ui.Section(
            discord.ui.TextDisplay(
                "### ROUTAGE\n"
                + "\n".join(route_lines)[:3000]
                + "\n\n### PERMISSIONS DU BOT\n"
                + permission_line
            ),
            accessory=status,
        )
    )

    container.add_item(discord.ui.Separator())
    container.add_item(
        discord.ui.TextDisplay(
            f"### Réglages\n**Catégorie sélectionnée : {selected_label}**\n"
            f"Salon actuel : {selected_route}"
        )
    )

    category_select = discord.ui.Select(
        placeholder="1. Choisir la catégorie de logs",
        min_values=1,
        max_values=1,
        options=[
            discord.SelectOption(
                label=option.label,
                value=option.value,
                description=option.description,
                default=option.value == selected,
            )
            for option in options
        ],
    )

    async def choose_category(interaction: discord.Interaction):
        try:
            self.backend.selected_log = category_select.values[0]
            await _safe_log_refresh(self, interaction)
        except Exception as exc:
            logger.error(
                "Erreur choix catégorie logs Setup guild=%s user=%s",
                self.guild.id,
                interaction.user.id,
                exc_info=(type(exc), exc, exc.__traceback__),
            )
            if not interaction.response.is_done():
                await panels.envoyer(interaction.response, panels.depuis_embed(discord.Embed(title='Action impossible', description='Impossible de charger cette catégorie de logs. Réessayez après un instant.', colour=discord.Colour.red())), ephemere=True)

    category_select.callback = choose_category
    container.add_item(discord.ui.ActionRow(category_select))

    channel_select = discord.ui.ChannelSelect(
        placeholder=f"2. Choisir le salon pour {selected_label}"[:150],
        min_values=0,
        max_values=1,
        channel_types=[discord.ChannelType.text, discord.ChannelType.news],
    )

    async def choose_channel(interaction: discord.Interaction):
        log_type = getattr(self.backend, "selected_log", None) or selected
        try:
            if not interaction.response.is_done():
                await interaction.response.defer()
            channel = channel_select.values[0] if channel_select.values else None
            channel_id = int(channel.id) if channel is not None else None

            await log_service.set_log_channel(
                self.bot,
                self.guild.id,
                log_type,
                channel_id,
            )
            await log_service.set_log_enabled(
                self.bot,
                self.guild.id,
                log_type,
                channel_id is not None,
            )
            await _audit_log_choice(
                self,
                interaction.user.id,
                log_type,
                channel_id,
            )
            await self.refresh(interaction)
        except Exception as exc:
            logger.error(
                "Erreur choix salon logs Setup guild=%s type=%s user=%s",
                self.guild.id,
                log_type,
                interaction.user.id,
                exc_info=(type(exc), exc, exc.__traceback__),
            )
            message = (
                "Impossible d'enregistrer ce salon. Vérifiez que SentriX peut le voir et y envoyer des messages."
            )
            try:
                await panels.envoyer(interaction.followup, panels.depuis_embed(discord.Embed(title='Salon non enregistré', description=message, colour=discord.Colour.red())), ephemere=True)
            except discord.HTTPException:
                pass

    channel_select.callback = choose_channel
    container.add_item(discord.ui.ActionRow(channel_select))

    toggle = discord.ui.Button(
        label=(
            "Désactiver cette catégorie"
            if bool(selected_setting.get("enabled"))
            else "Activer cette catégorie"
        ),
        style=(
            discord.ButtonStyle.danger
            if bool(selected_setting.get("enabled"))
            else discord.ButtonStyle.success
        ),
    )

    async def toggle_category(interaction: discord.Interaction):
        log_type = getattr(self.backend, "selected_log", None) or selected
        try:
            if not interaction.response.is_done():
                await interaction.response.defer()
            current = await log_service.get_log_setting(self.bot, self.guild.id, log_type)
            new_enabled = not bool(current.get("enabled"))
            if new_enabled and not current.get("channel_id"):
                await panels.envoyer(interaction.followup, panels.depuis_embed(discord.Embed(title="Choisissez d'abord un salon", description='Sélectionnez le salon de cette catégorie avec le deuxième menu, puis activez-la.', colour=discord.Colour.orange())), ephemere=True)
                return
            await log_service.set_log_enabled(
                self.bot,
                self.guild.id,
                log_type,
                new_enabled,
            )
            await _audit_log_choice(
                self,
                interaction.user.id,
                log_type,
                "enabled" if new_enabled else "disabled",
            )
            await self.refresh(interaction)
        except Exception as exc:
            logger.error(
                "Erreur toggle logs Setup guild=%s type=%s user=%s",
                self.guild.id,
                log_type,
                interaction.user.id,
                exc_info=(type(exc), exc, exc.__traceback__),
            )
            try:
                await panels.envoyer(interaction.followup, panels.depuis_embed(discord.Embed(title='Action impossible', description="Impossible de modifier l'état de cette catégorie de logs.", colour=discord.Colour.red())), ephemere=True)
            except discord.HTTPException:
                pass

    toggle.callback = toggle_category
    container.add_item(discord.ui.ActionRow(toggle))

    self._add_navigation(container)
    self.add_item(container)


async def _build_page_v75(self: v74.SentriXSetupV74, page: str) -> None:
    """Intercepte uniquement Logs ; toutes les autres pages gardent V74/V75."""
    if page == "logs":
        return await _build_logs_v75(self)
    previous = getattr(_build_page_v75, "_sentrix_previous")
    return await previous(self, page)


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

    current_page = cls._build_page
    if not getattr(current_page, "_sentrix_native_logs_v75", False):
        _build_page_v75._sentrix_native_logs_v75 = True
        _build_page_v75._sentrix_previous = current_page
        cls._build_page = _build_page_v75

    v74.CATEGORY_META["security"] = (
        "🔒",
        "Sécurité",
        "Choisissez individuellement les protections anti ; les permissions Discord sont automatiques.",
    )
    v74.CATEGORY_META["logs"] = (
        "📜",
        "Logs du serveur",
        "Choisissez chaque catégorie et son salon de destination directement dans le panneau.",
    )

    from . import setup_moderation_clear_v76 as moderation_v76
    moderation_v76.install(bot)

    # Le help officiel est déjà chargé à ce stade du finaliseur runtime. V77 remplace
    # son rendu, puis V78 garde le même style tout en respectant la limite Discord de
    # composants sur la page d'accueil.
    from . import help_components_v77 as help_v77
    help_v77.install(bot)
    from . import help_components_v78 as help_v78
    help_v78.install(bot)

    bot._sentrix_setup_security_choice_v75 = True
    logger.info(
        "%s installé : protections anti sélectionnables + page Logs native avec choix de salon.",
        RUNTIME_MARKER,
    )


__all__ = ["install"]