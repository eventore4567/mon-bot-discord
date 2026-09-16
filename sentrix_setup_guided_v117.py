"""SentriX V117 — setup guidé, simple et étape par étape.

V117 s'installe après V116 et simplifie TOUT le parcours `/setup` :
Accueil -> choisir un module -> une seule étape visible -> résumé -> terminer.

Les moteurs métier existants restent réutilisés. Les réglages simples rôle/salon sont
modifiés directement avec les sélecteurs Discord natifs, sans page intermédiaire.
"""
from __future__ import annotations

import logging
from typing import Any

import discord

import sentrix_setup_compact_v113 as v4
import sentrix_setup_v116 as v116

logger = logging.getLogger("bot.setup-v117")
_INSTALLED = False

# V116 conserve ses clés historiques pour compatibilité. V117 n'affiche à l'accueil que
# les vrais domaines utiles : les doublons Rôles/Vérification/Profil sont intégrés dans
# Membres, Niveaux et Économie.
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

ROLE_FIELDS = {"mod_role", "autorole", "verify_role", "warn_role"}


def _home_modules():
    return tuple(v116.MODULE_BY_KEY[key] for key in HOME_MODULE_KEYS if key in v116.MODULE_BY_KEY)


def _ensure_state(view) -> None:
    v116._ensure_state(view)
    module = v116.MODULE_BY_KEY[view._v116_module]
    keys = [section.key for section in module.sections]
    try:
        index = keys.index(view._v116_section)
    except (ValueError, AttributeError):
        index = 0
        view._v116_section = module.sections[0].key
    # len(sections) représente l'étape Résumé.
    view._v117_step = max(0, min(int(getattr(view, "_v117_step", index)), len(module.sections)))


def _current(view):
    _ensure_state(view)
    module = v116.MODULE_BY_KEY[view._v116_module]
    index = max(0, min(int(getattr(view, "_v117_step", 0)), len(module.sections)))
    if index >= len(module.sections):
        return module, None, index
    section = module.sections[index]
    view._v116_section = section.key
    return module, section, index


def _field_for_section(section) -> str | None:
    if section is None:
        return None
    if section.action.startswith("config:"):
        return section.action.split(":", 1)[1]
    if section.action == "verification":
        return "verify_role"
    return None


def _action_label(section) -> str:
    if section is None:
        return "Terminer"
    field = _field_for_section(section)
    if field:
        return "Choisir le rôle" if field in ROLE_FIELDS or field.endswith("_role") else "Choisir le salon"
    action = section.action
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
    if action.startswith("hint:"):
        return "Configurer"
    return "Configurer"


async def _current_value(view, module, section) -> str | None:
    if section is None:
        return None
    action = section.action
    field = _field_for_section(section)
    guild = view._guild()
    try:
        conf = await view.bot.db.get_guild_config(view.guild_id)
    except Exception:
        conf = None

    if field:
        return v116._mention(guild, conf, field, role=field in ROLE_FIELDS or field.endswith("_role"))
    if module.key in {"security", "logs", "levels", "economy", "profile", "tickets"}:
        try:
            return await v116._module_status(view, module.key)
        except Exception:
            return None
    return None


async def _home_embed(view) -> discord.Embed:
    embed = discord.Embed(
        title="Configurer SentriX",
        description=(
            "Choisis simplement ce que tu veux configurer.\n"
            "Ensuite SentriX te guide **une étape à la fois**."
        ),
        colour=v4._CONFIG_MODULE.SETUP_COLOR_MAIN,
    )
    embed.set_footer(text="SentriX • Setup guidé")
    return embed


async def _summary_embed(view, module) -> discord.Embed:
    lines = [
        "Tu as parcouru tous les réglages de ce module.",
        "",
        "**Résumé**",
    ]
    for section in module.sections:
        value = await _current_value(view, module, section)
        if value and value not in {"Module disponible", "Configuration tickets disponible"}:
            lines.append(f"• **{section.label}** — {value}")
        else:
            lines.append(f"• **{section.label}**")
    lines.extend(["", "Tu peux revenir en arrière ou terminer."])
    embed = discord.Embed(
        title=f"{module.label} — Terminé",
        description="\n".join(lines),
        colour=v4._CONFIG_MODULE.SETUP_COLOR_SUCCESS,
    )
    embed.set_footer(text="Précédent • Terminer • Accueil")
    return embed


async def _step_embed(view) -> discord.Embed:
    module, section, index = _current(view)
    if section is None:
        return await _summary_embed(view, module)

    current = await _current_value(view, module, section)
    lines = [
        f"Étape **{index + 1}/{len(module.sections)}**",
        "",
        f"**{section.label}**",
        section.description,
    ]
    if current and current not in {"Module disponible", "Configuration tickets disponible"}:
        lines.extend(["", f"Actuel : {current}"])

    embed = discord.Embed(
        title=module.label,
        description="\n".join(lines),
        colour=v4._CONFIG_MODULE.SETUP_COLOR_MAIN,
    )
    embed.set_footer(text="Précédent • Suivant • Accueil")
    return embed


def _module_select_callback(view, select: discord.ui.Select):
    async def callback(interaction: discord.Interaction):
        if not select.values:
            return await interaction.response.defer()
        view._v116_module = select.values[0]
        view._v117_step = 0
        module = v116.MODULE_BY_KEY[view._v116_module]
        view._v116_section = module.sections[0].key
        view.page = v116.PAGE_V116_MODULE
        view.render_page()
        await view.persist_session()
        await view._refresh_message(interaction)
    return callback


async def _move(view, interaction: discord.Interaction, delta: int) -> None:
    module, _, index = _current(view)
    next_index = max(0, min(index + delta, len(module.sections)))
    view._v117_step = next_index
    if next_index < len(module.sections):
        view._v116_section = module.sections[next_index].key
    view.render_page()
    await view.persist_session()
    await view._refresh_message(interaction)


async def _save_simple_field(view, interaction: discord.Interaction, field: str, value: Any) -> None:
    raw = getattr(value, "id", value)
    await view.bot.db.set_guild_config(view.guild_id, field, int(raw))
    try:
        v4._invalidate_health(view)
    except Exception:
        pass
    # Une sélection valide fait naturellement avancer l'assistant.
    await _move(view, interaction, 1)


def _add_native_picker(view, section) -> bool:
    field = _field_for_section(section)
    if not field:
        return False

    if field in ROLE_FIELDS or field.endswith("_role"):
        select = discord.ui.RoleSelect(placeholder="Choisir un rôle", min_values=1, max_values=1, row=0)
    else:
        select = discord.ui.ChannelSelect(
            placeholder="Choisir un salon",
            min_values=1,
            max_values=1,
            channel_types=[discord.ChannelType.text, discord.ChannelType.news],
            row=0,
        )

    async def callback(interaction: discord.Interaction):
        if not select.values:
            return await interaction.response.defer()
        await _save_simple_field(view, interaction, field, select.values[0])

    select.callback = callback
    view.add_item(select)
    return True


def _render_home(view) -> None:
    view.clear_items()
    select = discord.ui.Select(
        placeholder="Que veux-tu configurer ?",
        options=[
            discord.SelectOption(
                label=module.label,
                value=module.key,
                description=module.description[:100],
            )
            for module in _home_modules()
        ],
        row=0,
    )
    select.callback = _module_select_callback(view, select)
    view.add_item(select)

    button = v4._CONFIG_MODULE.SetupNavButton
    view.add_item(button("restart", view.message_id, label="Smart Setup", style=discord.ButtonStyle.success, row=1))
    view.add_item(button("summary", view.message_id, label="Diagnostic", style=discord.ButtonStyle.secondary, row=1))


def _render_step(view) -> None:
    module, section, index = _current(view)
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
        configure = discord.ui.Button(
            label=_action_label(section),
            style=discord.ButtonStyle.primary,
            row=0,
        )

        async def configure_callback(interaction: discord.Interaction):
            await v116._run_action(view, interaction)

        configure.callback = configure_callback
        view.add_item(configure)

    previous = discord.ui.Button(
        label="Précédent",
        style=discord.ButtonStyle.secondary,
        disabled=index == 0,
        row=1,
    )

    async def previous_callback(interaction: discord.Interaction):
        await _move(view, interaction, -1)

    previous.callback = previous_callback
    view.add_item(previous)

    following = discord.ui.Button(
        label="Suivant",
        style=discord.ButtonStyle.secondary,
        disabled=index >= len(module.sections),
        row=1,
    )

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
    logger.info("SentriX Setup V117 actif : tous les modules utilisent un parcours guidé étape par étape.")


__all__ = ["HOME_MODULE_KEYS", "install_for_bot"]
