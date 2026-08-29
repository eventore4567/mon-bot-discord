"""SentriX V73 — Control Center Components V2.

Cette couche remplace uniquement le rendu de +setup et /setup. Les réglages, callbacks,
permissions, migrations et moteurs métier restent ceux du Setup final déjà installé
(V66 -> V72). Les contrôles existants sont réutilisés au lieu d'être dupliqués.
"""
from __future__ import annotations

import logging
import types
from typing import Iterable

import discord
from discord.ext import commands

from utils import embeds
from . import setup_control_center as setup_ui
from . import setup_ticket_autoconfig_v72 as v72

logger = logging.getLogger("bot.setup-components-v73")

RUNTIME_MARKER = "Control Center Components V2 V73"
ACCENT = discord.Colour(0x6D5DFB)

CATEGORY_META: dict[str, tuple[str, str, str]] = {
    "moderation": (
        "🛡️",
        "Modération",
        "Rôles staff, sanctions et outils de modération.",
    ),
    "security": (
        "🔒",
        "Sécurité",
        "Anti-spam, anti-raid, anti-liens et protections du serveur.",
    ),
    "tickets": (
        "🎫",
        "Tickets",
        "Panels, types de tickets, support, catégories et journaux.",
    ),
    "welcome": (
        "👋",
        "Bienvenue & départ",
        "Messages d’arrivée, de départ et rôles automatiques.",
    ),
    "roles": (
        "🏷️",
        "Rôles",
        "Autorôles, vérification, rôles membres et récompenses.",
    ),
    "logs": (
        "📜",
        "Logs du serveur",
        "Messages, membres, rôles, salons, vocal, tickets et sécurité.",
    ),
    "levels": (
        "🪙",
        "Niveaux & économie",
        "XP, activité, argent, banque, récompenses et boutique.",
    ),
    "notifications": (
        "🔔",
        "Notifications",
        "YouTube, Twitch, TikTok, salons et rôles de notification.",
    ),
    "ai": (
        "🧠",
        "Intelligence artificielle",
        "Assistant SentriX, limites, permissions et génération d’images.",
    ),
    "permissions": (
        "👥",
        "Permissions",
        "Restrictions SentriX sans contourner les permissions Discord.",
    ),
}

# Ordre pensé comme le panneau de référence : protection -> communauté -> services.
CATEGORY_ORDER = (
    "moderation",
    "security",
    "tickets",
    "welcome",
    "roles",
    "logs",
    "levels",
    "notifications",
    "ai",
    "permissions",
)

_NAV_LABELS = {"accueil", "actualiser", "fermer", "retour"}


def _plain(value: object) -> str:
    return str(value or "").strip()


def _status_button_text(state: str) -> tuple[str, discord.ButtonStyle]:
    state = _plain(state)
    if "CORRIGER" in state:
        return "À corriger", discord.ButtonStyle.danger
    if "CONFIGURER" in state or "NON CONFIG" in state:
        return "À configurer", discord.ButtonStyle.secondary
    if "INACTIF" in state:
        return "Inactif", discord.ButtonStyle.secondary
    if "ACTIF" in state:
        return "Activé", discord.ButtonStyle.success
    return "État", discord.ButtonStyle.secondary


def _short_state(state: str) -> str:
    if "CORRIGER" in state:
        return "🔴 À corriger"
    if "CONFIGURER" in state or "NON CONFIG" in state:
        return "🟠 À configurer"
    if "INACTIF" in state:
        return "⚪ Inactif"
    if "ACTIF" in state:
        return "🟢 Activé"
    return state or "—"


def _thumbnail(bot: commands.Bot) -> discord.ui.Thumbnail:
    # display_avatar possède toujours une URL, même si le bot utilise l'avatar Discord par défaut.
    return discord.ui.Thumbnail(str(bot.user.display_avatar.url), description="SentriX")


def _summary_from_embed(panel: discord.Embed) -> str:
    """Transforme le dernier rendu V72 en texte Components V2 sans perdre ses informations."""
    blocks: list[str] = []
    description = _plain(panel.description)
    if description:
        # Le titre de page est déjà affiché dans le header V73 ; on conserve le contexte utile.
        blocks.append(description[:1200])

    ignored = {"navigation"}
    for field in panel.fields:
        name = _plain(field.name)
        value = _plain(field.value)
        if not name or not value or name.casefold() in ignored:
            continue
        blocks.append(f"**{name}**\n{value}")
        if len("\n\n".join(blocks)) >= 3000:
            break

    text = "\n\n".join(blocks).strip()
    return text[:3600] if text else "Les réglages de cette catégorie sont disponibles ci-dessous."


def _is_legacy_navigation(item: discord.ui.Item) -> bool:
    # Les couches V69/V70 réservent la ligne 0 au sélecteur de page.
    if getattr(item, "row", None) == 0:
        return True
    if isinstance(item, discord.ui.Button):
        return _plain(item.label).casefold() in _NAV_LABELS
    options = getattr(item, "options", None)
    if options:
        values = {str(option.value) for option in options}
        if "__home__" in values:
            return True
    return False


def _can_move_to_action_row(item: discord.ui.Item) -> bool:
    return isinstance(
        item,
        (
            discord.ui.Button,
            discord.ui.Select,
            discord.ui.ChannelSelect,
            discord.ui.RoleSelect,
            discord.ui.UserSelect,
            discord.ui.MentionableSelect,
        ),
    )


class V73AiLimitsModal(discord.ui.Modal, title="Limites de l’IA"):
    """Remplace le seul modal legacy qui rééditait directement l'ancien embed."""

    def __init__(self, shell: "SentriXSetupV73", values):
        super().__init__(timeout=300)
        self.shell = shell
        get = setup_ui._get
        self.cooldown = discord.ui.TextInput(
            label="Cooldown (secondes)",
            default=str(get(values, "cooldown_seconds", 8)),
            min_length=1,
            max_length=4,
        )
        self.per_minute = discord.ui.TextInput(
            label="Limite par minute",
            default=str(get(values, "per_minute_limit", 5)),
            min_length=1,
            max_length=4,
        )
        self.daily = discord.ui.TextInput(
            label="Limite par jour",
            default=str(get(values, "daily_limit", 50)),
            min_length=1,
            max_length=6,
        )
        self.add_item(self.cooldown)
        self.add_item(self.per_minute)
        self.add_item(self.daily)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            values = [
                max(0, int(self.cooldown.value)),
                max(1, int(self.per_minute.value)),
                max(1, int(self.daily.value)),
            ]
        except ValueError:
            return await interaction.response.send_message(
                embed=embeds.error("Les limites doivent être des nombres entiers."),
                ephemeral=True,
            )

        backend = self.shell.backend
        await backend.ensure_ai()
        await backend.bot.db.execute(
            "UPDATE ai_settings SET cooldown_seconds = ?, per_minute_limit = ?, daily_limit = ?, "
            "updated_at = strftime('%s','now') WHERE guild_id = ?",
            (*values, backend.guild.id),
        )
        try:
            await backend.audit(interaction.user.id, "ai_limits", "/".join(map(str, values)))
        except Exception:
            logger.debug("Audit ai_limits indisponible", exc_info=True)
        await self.shell.refresh(interaction)


class SentriXSetupV73(discord.ui.LayoutView):
    """Façade Components V2 au-dessus du Setup final V72."""

    def __init__(self, bot: commands.Bot, guild: discord.Guild, author_id: int):
        super().__init__(timeout=900)
        self.bot = bot
        self.guild = guild
        self.author_id = int(author_id)
        self.page: str | None = None
        self.backend = self._new_backend(None)

    def _new_backend(self, page: str | None):
        backend = setup_ui.SetupView(self.bot, self.guild, self.author_id)
        backend.category = page

        async def refresh_proxy(_backend, interaction: discord.Interaction):
            await self.refresh(interaction)

        # Tous les contrôles hérités appellent owner.refresh(). On les redirige vers
        # la façade V73 pour qu'aucun clic ne ressorte l'ancien embed.
        backend.refresh = types.MethodType(refresh_proxy, backend)
        return backend

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if int(interaction.user.id) != self.author_id:
            await interaction.response.send_message(
                embed=embeds.error("Ce panneau appartient à une autre personne."),
                ephemeral=True,
            )
            return False
        return True

    async def prepare(self) -> None:
        await self.rebuild()

    async def refresh(self, interaction: discord.Interaction) -> None:
        # Les opérations Setup peuvent inclure SQL/API Discord. ACK immédiat pour éviter
        # « L'application ne répond plus », puis réédition du message d'origine.
        if not interaction.response.is_done():
            await interaction.response.defer()
        await self.rebuild()
        await interaction.edit_original_response(
            content=None,
            embed=None,
            attachments=[],
            view=self,
        )

    async def rebuild(self) -> None:
        self.clear_items()
        if self.page is None:
            await self._build_home()
        else:
            await self._build_page(self.page)

    async def _effective_states(self) -> dict[str, str]:
        effective, _statuses = await v72._effective_states(self.backend)
        if effective.get("tickets") != "! À CORRIGER":
            try:
                enabled = "ACTIF" in effective.get("tickets", "")
                if enabled and not await v72.ticket_configuration_ready(self.bot, self.guild):
                    effective["tickets"] = "— À CONFIGURER"
            except Exception:
                logger.debug("État de préparation Tickets V73 indisponible", exc_info=True)
        return effective

    async def _build_home(self) -> None:
        # Le backend final reste la source de vérité pour les états V72.
        self.backend.category = None
        states = await self._effective_states()
        active = sum("ACTIF" in value and "INACTIF" not in value for value in states.values())
        problems = sum("CORRIGER" in value for value in states.values())

        container = discord.ui.Container(accent_colour=ACCENT)
        container.add_item(
            discord.ui.Section(
                discord.ui.TextDisplay(
                    "# Configuration de SentriX\n"
                    f"**Bienvenue dans le panneau de configuration de SentriX !** "
                    f"Sélectionnez une catégorie pour configurer les fonctionnalités du bot sur **{self.guild.name}**.\n"
                    f"{active}/{len(CATEGORY_ORDER)} modules actifs"
                    + (f" · {problems} à corriger" if problems else "")
                ),
                accessory=_thumbnail(self.bot),
            )
        )
        for index, key in enumerate(CATEGORY_ORDER):
            emoji, label, description = CATEGORY_META[key]
            state = _short_state(states.get(key, "—"))
            button = discord.ui.Button(label="Configurer", style=discord.ButtonStyle.secondary)

            async def open_page(interaction: discord.Interaction, category=key):
                self.page = category
                self.backend = self._new_backend(category)
                await self.refresh(interaction)

            button.callback = open_page
            container.add_item(
                discord.ui.Section(
                    discord.ui.TextDisplay(
                        f"## {emoji} {label}\n{description}\n**{state}**"
                    ),
                    accessory=button,
                )
            )

            # Deux séparateurs structurants : le rendu reste proche de la référence sans
            # dépasser la limite globale des composants imbriqués.
            if index in {1, 4}:
                container.add_item(discord.ui.Separator())

        refresh = discord.ui.Button(label="Actualiser", style=discord.ButtonStyle.secondary, emoji="🔄")
        close = discord.ui.Button(label="Fermer", style=discord.ButtonStyle.danger)

        async def refresh_home(interaction: discord.Interaction):
            await self.refresh(interaction)

        async def close_home(interaction: discord.Interaction):
            await self._close(interaction)

        refresh.callback = refresh_home
        close.callback = close_home
        container.add_item(discord.ui.ActionRow(refresh, close))
        self.add_item(container)

    async def _build_page(self, page: str) -> None:
        self.backend.category = page
        self.backend.render()
        legacy_panel = await self.backend.build_embed()
        states = await self._effective_states()
        emoji, label, description = CATEGORY_META.get(
            page,
            ("⚙️", setup_ui.CATEGORIES.get(page, (page.title(), ""))[0], "Configuration SentriX."),
        )
        state = states.get(page, "—")
        status_label, status_style = _status_button_text(state)
        status = discord.ui.Button(label=status_label, style=status_style, disabled=True)

        container = discord.ui.Container(accent_colour=ACCENT)
        container.add_item(
            discord.ui.Section(
                discord.ui.TextDisplay(
                    f"# {emoji} {label}\n{description}\nConfiguration sur **{self.guild.name}**."
                ),
                accessory=_thumbnail(self.bot),
            )
        )
        container.add_item(discord.ui.Separator())
        container.add_item(
            discord.ui.Section(
                discord.ui.TextDisplay(_summary_from_embed(legacy_panel)),
                accessory=status,
            )
        )

        controls = list(self.backend.children)
        movable: list[discord.ui.Item] = []
        for item in controls:
            if _is_legacy_navigation(item):
                continue
            if not _can_move_to_action_row(item):
                logger.warning("Contrôle Setup V73 ignoré car incompatible: %r", item)
                continue
            self.backend.remove_item(item)
            self._normalise_control(page, item)
            movable.append(item)

        if movable:
            container.add_item(discord.ui.Separator())
            container.add_item(discord.ui.TextDisplay("### Réglages"))
            self._append_controls(container, movable)
        else:
            container.add_item(discord.ui.Separator())
            container.add_item(discord.ui.TextDisplay("Aucun réglage supplémentaire n’est nécessaire sur cette page."))

        back = discord.ui.Button(label="Retour", style=discord.ButtonStyle.primary, emoji="↩️")
        refresh = discord.ui.Button(label="Actualiser", style=discord.ButtonStyle.secondary, emoji="🔄")
        close = discord.ui.Button(label="Fermer", style=discord.ButtonStyle.danger)

        async def go_back(interaction: discord.Interaction):
            self.page = None
            self.backend = self._new_backend(None)
            await self.refresh(interaction)

        async def do_refresh(interaction: discord.Interaction):
            await self.refresh(interaction)

        async def do_close(interaction: discord.Interaction):
            await self._close(interaction)

        back.callback = go_back
        refresh.callback = do_refresh
        close.callback = do_close
        container.add_item(discord.ui.Separator())
        container.add_item(discord.ui.ActionRow(back, refresh, close))
        self.add_item(container)

    def _normalise_control(self, page: str, item: discord.ui.Item) -> None:
        if isinstance(item, discord.ui.Button):
            label = _plain(item.label)
            folded = label.casefold()
            if "activer / désactiver" in folded or "activer / desactiver" in folded:
                item.label = "Activer / Désactiver"
            elif folded == "modifier les limites":
                item.label = "Modifier les limites"

            # Le modal IA historique éditait directement un embed ; V73 le remplace afin
            # de rester en Components V2 après validation.
            if page == "ai" and "limite" in folded:
                async def open_ai_limits(interaction: discord.Interaction):
                    await self.backend.ensure_ai()
                    row = await self.bot.db.fetchone(
                        "SELECT cooldown_seconds, per_minute_limit, daily_limit "
                        "FROM ai_settings WHERE guild_id = ?",
                        (self.guild.id,),
                    )
                    await interaction.response.send_modal(V73AiLimitsModal(self, row))

                item.callback = open_ai_limits

    @staticmethod
    def _append_controls(container: discord.ui.Container, items: Iterable[discord.ui.Item]) -> None:
        button_buffer: list[discord.ui.Button] = []

        def flush_buttons() -> None:
            nonlocal button_buffer
            if button_buffer:
                container.add_item(discord.ui.ActionRow(*button_buffer[:5]))
                button_buffer = button_buffer[5:]
                while button_buffer:
                    container.add_item(discord.ui.ActionRow(*button_buffer[:5]))
                    button_buffer = button_buffer[5:]

        for item in items:
            if isinstance(item, discord.ui.Button):
                button_buffer.append(item)
                if len(button_buffer) == 5:
                    flush_buttons()
                continue
            flush_buttons()
            container.add_item(discord.ui.ActionRow(item))
        flush_buttons()

    async def _close(self, interaction: discord.Interaction) -> None:
        if not interaction.response.is_done():
            await interaction.response.defer()
        self.clear_items()
        closed = discord.ui.Container(
            discord.ui.TextDisplay(
                "# Configuration fermée\nLe panneau SentriX a été fermé. Relancez `+setup` ou `/setup` pour le rouvrir."
            ),
            accent_colour=ACCENT,
        )
        self.add_item(closed)
        await interaction.edit_original_response(
            content=None,
            embed=None,
            attachments=[],
            view=self,
        )
        self.stop()

    async def on_error(self, interaction: discord.Interaction, error: Exception, item=None) -> None:
        logger.error("Erreur Control Center V73", exc_info=(type(error), error, error.__traceback__))
        try:
            panel = embeds.error("Une erreur est survenue dans le panneau de configuration SentriX.")
            if interaction.response.is_done():
                await interaction.followup.send(embed=panel, ephemeral=True)
            else:
                await interaction.response.send_message(embed=panel, ephemeral=True)
        except discord.HTTPException:
            pass


async def _send_setup_v73(self, target):
    guild = getattr(target, "guild", None)
    member = getattr(target, "author", None) or getattr(target, "user", None)
    if not await setup_ui._can_setup(self.bot, member, guild):
        return await setup_ui._permission_error(target)

    view = SentriXSetupV73(self.bot, guild, member.id)
    await view.prepare()

    if isinstance(target, commands.Context):
        return await target.send(view=view)
    if target.response.is_done():
        return await target.followup.send(view=view)
    return await target.response.send_message(view=view)


def install(bot: commands.Bot) -> None:
    """Installe V73 après V72, sans toucher aux données ni aux callbacks métier."""
    if getattr(bot, "_sentrix_setup_components_v73", False):
        return
    if not hasattr(discord.ui, "LayoutView"):
        raise RuntimeError("SentriX V73 exige discord.py 2.6+ (Components V2).")

    current = setup_ui.OfficialSetup.send_setup
    if not getattr(current, "_sentrix_components_v73", False):
        _send_setup_v73._sentrix_components_v73 = True
        _send_setup_v73._sentrix_previous = current
        setup_ui.OfficialSetup.send_setup = _send_setup_v73

    bot._sentrix_setup_components_v73 = True
    logger.info("%s installé : +setup et /setup utilisent désormais Components V2.", RUNTIME_MARKER)


__all__ = ["SentriXSetupV73", "install"]
