"""SentriX V117 — setup guidé, simple et entièrement intégré.

Le setup reste sur un seul parcours : Accueil -> module -> étape -> résumé. Les réglages
simples sont modifiés directement avec les sélecteurs/modals Discord et les assistants
complexes existants sont ouverts depuis /setup sans demander de lancer une autre commande.
"""
from __future__ import annotations

import logging
from typing import Any

import discord
from discord.ext import commands

import sentrix_setup_compact_v113 as v4
import sentrix_setup_v116 as v116

logger = logging.getLogger("bot.setup-v117")
_INSTALLED = False

HOME_MODULE_KEYS: tuple[str, ...] = (
    "security",
    "moderation",
    "members",
    "logs",
    "levels",
    "economy",
    "tickets",
    "notifications",
    "ai",
    "suggestions",
)
ROLE_FIELDS = {"autorole", "verify_role", "warn_role"}


def _s(key: str, label: str, description: str, action: str) -> v116.SectionSpec:
    return v116.SectionSpec(key, label, description, action)


GUIDED_SECTIONS: dict[str, tuple[v116.SectionSpec, ...]] = {
    "moderation": (
        _s("warn_threshold", "Avertissements automatiques", "Choisis après combien d'avertissements un bannissement automatique peut être appliqué.", "number:warn_ban_threshold"),
        _s("warn_role", "Rôle d'avertissement", "Choisis le rôle appliqué aux membres avertis, si tu veux en utiliser un.", "config:warn_role"),
    ),
    "members": (
        _s("welcome", "Salon de bienvenue", "Choisis le salon où les nouveaux membres sont accueillis.", "config:welcome_channel"),
        _s("welcome_message", "Message de bienvenue", "Écris le message envoyé lorsqu'un membre rejoint le serveur.", "text:welcome_message"),
        _s("goodbye", "Salon de départ", "Choisis le salon utilisé lors du départ d'un membre.", "config:goodbye_channel"),
        _s("goodbye_message", "Message de départ", "Écris le message envoyé lorsqu'un membre quitte le serveur.", "text:goodbye_message"),
        _s("autorole", "Rôle automatique", "Choisis le rôle attribué automatiquement à l'arrivée.", "config:autorole"),
        _s("verification", "Rôle après vérification", "Choisis le rôle reçu après validation.", "config:verify_role"),
    ),
    "economy": (
        _s("currency", "Monnaie et affichage", "Configure la monnaie, son affichage et les informations économiques du profil.", "levels-config"),
        _s("reputation", "Réputation", "Configure le cooldown et l'affichage de la réputation.", "levels-config"),
    ),
    "tickets": (
        _s("tickets", "Configuration des tickets", "Gère les panels, types, formulaires, permissions et boutons staff directement depuis le setup.", "internal:ticketsetup"),
    ),
    "notifications": (
        _s("social", "Notifications sociales", "Ajoute ou modifie une source YouTube, TikTok, Twitch ou autre réseau pris en charge.", "internal:notifications"),
    ),
    "ai": (
        _s("ai", "Configuration de l'IA", "Active l'IA et règle ses accès, limites, mémoire et comportement.", "internal:aisetup"),
    ),
    "suggestions": (
        _s("channel", "Salon des suggestions", "Choisis le salon utilisé pour les suggestions.", "config:suggest_channel"),
    ),
}


def _home_modules():
    return tuple(v116.MODULE_BY_KEY[key] for key in HOME_MODULE_KEYS if key in v116.MODULE_BY_KEY)


def _sections_for(module) -> tuple[v116.SectionSpec, ...]:
    return GUIDED_SECTIONS.get(module.key, module.sections)


def _ensure_state(view) -> None:
    if not hasattr(view, "_v116_module") or view._v116_module not in v116.MODULE_BY_KEY:
        view._v116_module = "security"
    module = v116.MODULE_BY_KEY[view._v116_module]
    sections = _sections_for(module)
    keys = [section.key for section in sections]
    if not hasattr(view, "_v116_section") or view._v116_section not in keys:
        view._v116_section = sections[0].key
    try:
        index = keys.index(view._v116_section)
    except ValueError:
        index = 0
    view._v117_step = max(0, min(int(getattr(view, "_v117_step", index)), len(sections)))


def _current(view):
    _ensure_state(view)
    module = v116.MODULE_BY_KEY[view._v116_module]
    sections = _sections_for(module)
    index = max(0, min(int(getattr(view, "_v117_step", 0)), len(sections)))
    if index >= len(sections):
        return module, sections, None, index
    section = sections[index]
    view._v116_section = section.key
    return module, sections, section, index


def _field_for_section(section) -> str | None:
    if section is None or not section.action.startswith("config:"):
        return None
    return section.action.split(":", 1)[1]


def _action_label(section) -> str:
    if section is None:
        return "Terminer"
    field = _field_for_section(section)
    if field:
        return "Choisir le rôle" if field in ROLE_FIELDS or field.endswith("_role") else "Choisir le salon"
    action = section.action
    if action.startswith("text:"):
        return "Modifier le message"
    if action.startswith("number:"):
        return "Modifier le nombre"
    if action == "security":
        return "Configurer la protection"
    if action == "logs":
        return "Configurer les logs"
    if action == "levels-config":
        return "Configurer"
    if action == "diagnostic":
        return "Vérifier"
    if action == "history":
        return "Voir l'historique"
    if action == "internal:ticketsetup":
        return "Configurer les tickets"
    if action == "internal:notifications":
        return "Configurer les notifications"
    if action == "internal:aisetup":
        return "Configurer l'IA"
    return "Configurer"


async def _current_value(view, module, section) -> str | None:
    if section is None:
        return None
    field = _field_for_section(section)
    guild = view._guild()
    try:
        conf = await view.bot.db.get_guild_config(view.guild_id)
    except Exception:
        conf = None
    if field:
        return v116._mention(guild, conf, field, role=field in ROLE_FIELDS or field.endswith("_role"))
    if section.action.startswith("text:"):
        key = section.action.split(":", 1)[1]
        try:
            value = conf[key] if conf else None
        except Exception:
            value = None
        return "Configuré" if value else "Non configuré"
    if section.action.startswith("number:"):
        key = section.action.split(":", 1)[1]
        try:
            value = int(conf[key] or 0) if conf else 0
        except Exception:
            value = 0
        return "Désactivé" if value <= 0 else str(value)
    if module.key in {"security", "logs", "levels", "economy", "tickets"}:
        try:
            return await v116._module_status(view, module.key)
        except Exception:
            return None
    return None


async def _home_embed(view) -> discord.Embed:
    embed = discord.Embed(
        title="Configurer SentriX",
        description="Choisis ce que tu veux configurer. SentriX te guide ensuite **une étape à la fois**.",
        colour=v4._CONFIG_MODULE.SETUP_COLOR_MAIN,
    )
    embed.set_footer(text="SentriX • Setup guidé")
    return embed


async def _summary_embed(view, module, sections) -> discord.Embed:
    lines = ["Configuration parcourue.", "", "**Résumé**"]
    for section in sections:
        value = await _current_value(view, module, section)
        lines.append(f"• **{section.label}**" + (f" — {value}" if value else ""))
    lines.extend(["", "Tu peux revenir en arrière ou terminer."])
    embed = discord.Embed(title=f"{module.label} — Terminé", description="\n".join(lines), colour=v4._CONFIG_MODULE.SETUP_COLOR_SUCCESS)
    embed.set_footer(text="Précédent • Terminer • Accueil")
    return embed


async def _step_embed(view) -> discord.Embed:
    module, sections, section, index = _current(view)
    if section is None:
        return await _summary_embed(view, module, sections)
    current = await _current_value(view, module, section)
    lines = [f"Étape **{index + 1}/{len(sections)}**", "", f"**{section.label}**", section.description]
    if current:
        lines.extend(["", f"Actuel : {current}"])
    embed = discord.Embed(title=module.label, description="\n".join(lines), colour=v4._CONFIG_MODULE.SETUP_COLOR_MAIN)
    embed.set_footer(text="Précédent • Suivant • Accueil")
    return embed


def _module_select_callback(view, select: discord.ui.Select):
    async def callback(interaction: discord.Interaction):
        if not select.values:
            return await interaction.response.defer()
        view._v116_module = select.values[0]
        module = v116.MODULE_BY_KEY[view._v116_module]
        sections = _sections_for(module)
        view._v117_step = 0
        view._v116_section = sections[0].key
        view.page = v116.PAGE_V116_MODULE
        view.render_page()
        await view.persist_session()
        await view._refresh_message(interaction)
    return callback


async def _move(view, interaction: discord.Interaction, delta: int) -> None:
    module, sections, _, index = _current(view)
    next_index = max(0, min(index + delta, len(sections)))
    view._v117_step = next_index
    if next_index < len(sections):
        view._v116_section = sections[next_index].key
    view.render_page()
    await view.persist_session()
    await view._refresh_message(interaction)


async def _save_field(view, interaction: discord.Interaction, field: str, value: Any, *, advance: bool = True) -> None:
    raw = getattr(value, "id", value)
    await view.bot.db.set_guild_config(view.guild_id, field, raw)
    try:
        v4._invalidate_health(view)
    except Exception:
        pass
    if advance:
        await _move(view, interaction, 1)
    else:
        view.render_page()
        await view.persist_session()
        await view._refresh_message(interaction)


class TextSettingModal(discord.ui.Modal):
    def __init__(self, view, field: str, title: str, current: str = ""):
        super().__init__(title=title[:45])
        self.view_ref = view
        self.field = field
        self.value_input = discord.ui.TextInput(label="Message", style=discord.TextStyle.paragraph, default=current[:1000], max_length=1000, required=False)
        self.add_item(self.value_input)

    async def on_submit(self, interaction: discord.Interaction):
        await _save_field(self.view_ref, interaction, self.field, self.value_input.value.strip(), advance=True)


class NumberSettingModal(discord.ui.Modal):
    def __init__(self, view, field: str, title: str, current: int = 0):
        super().__init__(title=title[:45])
        self.view_ref = view
        self.field = field
        self.value_input = discord.ui.TextInput(label="Nombre (0 = désactivé)", default=str(current), max_length=3)
        self.add_item(self.value_input)

    async def on_submit(self, interaction: discord.Interaction):
        raw = self.value_input.value.strip()
        if not raw.isdigit() or not 0 <= int(raw) <= 100:
            return await interaction.response.send_message("Entre un nombre entre 0 et 100.", ephemeral=True)
        await _save_field(self.view_ref, interaction, self.field, int(raw), advance=True)


class NotificationSourceModal(discord.ui.Modal, title="Source de notification"):
    def __init__(self, view: "NotificationSetupView"):
        super().__init__()
        self.view_ref = view
        self.url = discord.ui.TextInput(label="Lien de la chaîne / source", placeholder="https://...", max_length=300)
        self.text = discord.ui.TextInput(label="Texte personnalisé (optionnel)", style=discord.TextStyle.paragraph, required=False, max_length=600)
        self.add_item(self.url)
        self.add_item(self.text)

    async def on_submit(self, interaction: discord.Interaction):
        from cogs.notifications import _is_supported_social_url, _normalize_source_url
        value = self.url.value.strip()
        if not _is_supported_social_url(value):
            return await interaction.response.send_message("Lien non pris en charge. Utilise une URL HTTPS publique de la chaîne.", ephemeral=True)
        self.view_ref.source_url = _normalize_source_url(value)
        self.view_ref.custom_text = self.text.value.strip()
        await interaction.response.edit_message(embed=self.view_ref.build_embed(), view=self.view_ref)


class NotificationSetupView(discord.ui.View):
    def __init__(self, bot, guild_id: int, author_id: int):
        super().__init__(timeout=300)
        self.bot = bot
        self.guild_id = guild_id
        self.author_id = author_id
        self.source_url: str | None = None
        self.custom_text = ""
        self.channel_id: int | None = None
        self.role_id: int | None = None
        self.saved = False

        source_btn = discord.ui.Button(label="Source & texte", style=discord.ButtonStyle.primary, row=0)
        async def source_cb(interaction: discord.Interaction):
            await interaction.response.send_modal(NotificationSourceModal(self))
        source_btn.callback = source_cb
        self.add_item(source_btn)

        channel_select = discord.ui.ChannelSelect(placeholder="Salon de notification", min_values=1, max_values=1, channel_types=[discord.ChannelType.text, discord.ChannelType.news], row=1)
        async def channel_cb(interaction: discord.Interaction):
            self.channel_id = channel_select.values[0].id
            await interaction.response.edit_message(embed=self.build_embed(), view=self)
        channel_select.callback = channel_cb
        self.add_item(channel_select)

        role_select = discord.ui.RoleSelect(placeholder="Rôle à ping", min_values=1, max_values=1, row=2)
        async def role_cb(interaction: discord.Interaction):
            role = role_select.values[0]
            if role.is_default():
                return await interaction.response.send_message("@everyone ne peut pas être utilisé ici.", ephemeral=True)
            self.role_id = role.id
            await interaction.response.edit_message(embed=self.build_embed(), view=self)
        role_select.callback = role_cb
        self.add_item(role_select)

        save_btn = discord.ui.Button(label="Enregistrer", style=discord.ButtonStyle.success, row=3)
        async def save_cb(interaction: discord.Interaction):
            await self.save(interaction)
        save_btn.callback = save_cb
        self.add_item(save_btn)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Ce panneau appartient à la personne qui a lancé /setup.", ephemeral=True)
            return False
        return True

    def build_embed(self) -> discord.Embed:
        guild = self.bot.get_guild(self.guild_id)
        channel = guild.get_channel(self.channel_id) if guild and self.channel_id else None
        role = guild.get_role(self.role_id) if guild and self.role_id else None
        lines = [
            "Configure la notification ici, sans autre commande.", "",
            f"Source : **{self.source_url or 'à choisir'}**",
            f"Salon : {channel.mention if channel else '**à choisir**'}",
            f"Rôle : {role.mention if role else '**à choisir**'}",
            f"Texte : **{'personnalisé' if self.custom_text else 'par défaut'}**",
        ]
        if self.saved:
            lines.extend(["", "**Enregistré.**"])
        return discord.Embed(title="Notifications sociales", description="\n".join(lines), colour=v4._CONFIG_MODULE.SETUP_COLOR_MAIN)

    async def save(self, interaction: discord.Interaction) -> None:
        if not self.source_url or not self.channel_id or not self.role_id:
            return await interaction.response.send_message("Choisis d'abord la source, le salon et le rôle.", ephemeral=True)
        from cogs.notifications import _extract_latest, _item_url, _platform_details
        await interaction.response.defer()
        try:
            latest = await _extract_latest(self.source_url)
        except Exception:
            logger.exception("V117 : validation notification impossible")
            return await interaction.followup.send("Impossible de lire cette source pour le moment. Vérifie le lien et réessaie.", ephemeral=True)
        if not latest or not latest.get("id"):
            return await interaction.followup.send("Aucune publication publique trouvée sur cette source.", ephemeral=True)
        platform, _ = _platform_details(self.source_url)
        latest_id = str(latest["id"])
        latest_url = _item_url(platform, self.source_url, latest)
        import time
        now = int(time.time())
        await self.bot.db.execute(
            "INSERT INTO social_notifications (guild_id, source_url, platform, discord_channel_id, role_id, custom_text, image_url, last_item_id, last_item_url, enabled, created_at, last_checked_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?) ON CONFLICT(guild_id, source_url) DO UPDATE SET platform = excluded.platform, discord_channel_id = excluded.discord_channel_id, role_id = excluded.role_id, custom_text = excluded.custom_text, last_item_id = excluded.last_item_id, last_item_url = excluded.last_item_url, enabled = 1, last_checked_at = excluded.last_checked_at",
            (self.guild_id, self.source_url, platform, self.channel_id, self.role_id, self.custom_text or None, None, latest_id, latest_url, now, now),
        )
        self.saved = True
        await interaction.edit_original_response(embed=self.build_embed(), view=self)


async def _open_internal(view, interaction: discord.Interaction, name: str) -> None:
    if name == "notifications":
        subview = NotificationSetupView(view.bot, view.guild_id, interaction.user.id)
        return await interaction.response.send_message(embed=subview.build_embed(), view=subview, ephemeral=True)
    command_name = {"tickets": "ticketsetup", "ai": "aisetup"}.get(name)
    command = view.bot.get_command(command_name) if command_name else None
    if command is None:
        return await interaction.response.send_message("Ce module de configuration est momentanément indisponible.", ephemeral=True)
    try:
        ctx = await commands.Context.from_interaction(interaction)
        await ctx.invoke(command)
    except Exception:
        logger.exception("V117 : ouverture interne impossible module=%s", name)
        if interaction.response.is_done():
            await interaction.followup.send("Impossible d'ouvrir ce réglage pour le moment.", ephemeral=True)
        else:
            await interaction.response.send_message("Impossible d'ouvrir ce réglage pour le moment.", ephemeral=True)


async def _run_step_action(view, interaction: discord.Interaction, section) -> None:
    action = section.action
    if action.startswith("text:"):
        field = action.split(":", 1)[1]
        conf = await view.bot.db.get_guild_config(view.guild_id)
        try:
            current = str(conf[field] or "") if conf else ""
        except Exception:
            current = ""
        return await interaction.response.send_modal(TextSettingModal(view, field, section.label, current))
    if action.startswith("number:"):
        field = action.split(":", 1)[1]
        conf = await view.bot.db.get_guild_config(view.guild_id)
        try:
            current = int(conf[field] or 0) if conf else 0
        except Exception:
            current = 0
        return await interaction.response.send_modal(NumberSettingModal(view, field, section.label, current))
    if action.startswith("internal:"):
        return await _open_internal(view, interaction, action.split(":", 1)[1])
    await v116._run_action(view, interaction)


def _add_native_picker(view, section) -> bool:
    field = _field_for_section(section)
    if not field:
        return False
    if field in ROLE_FIELDS or field.endswith("_role"):
        select = discord.ui.RoleSelect(placeholder="Choisir un rôle", min_values=1, max_values=1, row=0)
    else:
        select = discord.ui.ChannelSelect(placeholder="Choisir un salon", min_values=1, max_values=1, channel_types=[discord.ChannelType.text, discord.ChannelType.news], row=0)
    async def callback(interaction: discord.Interaction):
        if not select.values:
            return await interaction.response.defer()
        await _save_field(view, interaction, field, select.values[0], advance=True)
    select.callback = callback
    view.add_item(select)
    return True


def _render_home(view) -> None:
    view.clear_items()
    select = discord.ui.Select(
        placeholder="Que veux-tu configurer ?",
        options=[discord.SelectOption(label=module.label, value=module.key, description=module.description[:100]) for module in _home_modules()],
        row=0,
    )
    select.callback = _module_select_callback(view, select)
    view.add_item(select)
    button = v4._CONFIG_MODULE.SetupNavButton
    view.add_item(button("restart", view.message_id, label="Smart Setup", style=discord.ButtonStyle.success, row=1))
    view.add_item(button("summary", view.message_id, label="Diagnostic", style=discord.ButtonStyle.secondary, row=1))


def _render_step(view) -> None:
    module, sections, section, index = _current(view)
    view.clear_items()
    if section is None:
        finish = discord.ui.Button(label="Terminer", style=discord.ButtonStyle.success, row=0)
        async def finish_callback(interaction: discord.Interaction):
            view.page = v4.PAGE_HOME
            view._v117_step = 0
            view.render_page()
            await view.persist_session()
            await view._refresh_message(interaction)
        finish.callback = finish_callback
        view.add_item(finish)
    elif not _add_native_picker(view, section):
        configure = discord.ui.Button(label=_action_label(section), style=discord.ButtonStyle.primary, row=0)
        async def configure_callback(interaction: discord.Interaction):
            await _run_step_action(view, interaction, section)
        configure.callback = configure_callback
        view.add_item(configure)

    previous = discord.ui.Button(label="Précédent", style=discord.ButtonStyle.secondary, disabled=index == 0, row=1)
    async def previous_callback(interaction: discord.Interaction):
        await _move(view, interaction, -1)
    previous.callback = previous_callback
    view.add_item(previous)

    following = discord.ui.Button(label="Suivant", style=discord.ButtonStyle.secondary, disabled=index >= len(sections), row=1)
    async def following_callback(interaction: discord.Interaction):
        await _move(view, interaction, 1)
    following.callback = following_callback
    view.add_item(following)

    home = discord.ui.Button(label="Accueil", style=discord.ButtonStyle.secondary, row=1)
    async def home_callback(interaction: discord.Interaction):
        view.page = v4.PAGE_HOME
        view.render_page()
        await view.persist_session()
        await view._refresh_message(interaction)
    home.callback = home_callback
    view.add_item(home)


async def _build_embed(view) -> discord.Embed:
    if view.page == v4.PAGE_HOME:
        return await _home_embed(view)
    if view.page == v116.PAGE_V116_MODULE:
        return await _step_embed(view)
    return await view._sentrix_v117_previous_build_embed()


def _render_page(view) -> None:
    if view.page == v4.PAGE_HOME:
        _render_home(view)
        return
    if view.page == v116.PAGE_V116_MODULE:
        _render_step(view)
        return
    return view._sentrix_v117_previous_render_page()


def install_for_bot(bot) -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    configuration = bot.get_cog("Configuration")
    if configuration is None:
        logger.warning("V117 non installé : cog Configuration absent.")
        return
    from cogs.configuration import SetupView as view_cls
    if getattr(view_cls, "_sentrix_v117", False):
        _INSTALLED = True
        return
    view_cls._sentrix_v117_previous_render_page = view_cls.render_page
    view_cls._sentrix_v117_previous_build_embed = view_cls.build_embed
    view_cls.render_page = _render_page
    view_cls.build_embed = _build_embed
    view_cls._sentrix_v117 = True
    for active in list(getattr(configuration, "active_setups", {}).values()):
        try:
            _ensure_state(active)
            active.render_page()
        except Exception:
            logger.exception("V117 : migration d'une session active impossible.")
    _INSTALLED = True
    logger.info("SentriX Setup V117 actif : configuration guidée intégrée, sans redirection vers des commandes externes.")


__all__ = ["HOME_MODULE_KEYS", "GUIDED_SECTIONS", "install_for_bot"]
