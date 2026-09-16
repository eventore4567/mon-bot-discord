"""SentriX V117 — setup guidé, simple et étape par étape.

Cette couche s'installe après V116. Elle conserve tous les moteurs existants mais
supprime l'écran intermédiaire "choisir un réglage + ouvrir" : après avoir choisi un
module, l'utilisateur avance avec Précédent / Suivant et ne voit qu'une seule étape à la
fois. Les vrais assistants existants restent réutilisés pour éviter toute duplication.
"""
from __future__ import annotations

import logging

import discord

import sentrix_setup_compact_v113 as v4
import sentrix_setup_v116 as v116

logger = logging.getLogger("bot.setup-v117")
_INSTALLED = False


def _ensure_state(view) -> None:
    v116._ensure_state(view)
    module = v116.MODULE_BY_KEY[view._v116_module]
    keys = [section.key for section in module.sections]
    try:
        index = keys.index(view._v116_section)
    except (ValueError, AttributeError):
        index = 0
        view._v116_section = module.sections[0].key
    view._v117_step = max(0, min(index, len(module.sections) - 1))


def _current(view):
    _ensure_state(view)
    module = v116.MODULE_BY_KEY[view._v116_module]
    index = max(0, min(int(getattr(view, "_v117_step", 0)), len(module.sections) - 1))
    section = module.sections[index]
    view._v116_section = section.key
    return module, section, index


def _action_label(section) -> str:
    action = section.action
    if action.startswith("config:"):
        field = action.split(":", 1)[1]
        if field in {"mod_role", "autorole", "verify_role"}:
            return "Choisir le rôle"
        return "Choisir le salon"
    if action == "verification":
        return "Choisir le rôle"
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
        return "Ouvrir l'assistant"
    return "Configurer"


async def _current_value(view, module, section) -> str | None:
    action = section.action
    guild = view._guild()
    try:
        conf = await view.bot.db.get_guild_config(view.guild_id)
    except Exception:
        conf = None

    if action.startswith("config:"):
        field = action.split(":", 1)[1]
        is_role = field in {"mod_role", "autorole", "verify_role"}
        return v116._mention(guild, conf, field, role=is_role)
    if action == "verification":
        return v116._mention(guild, conf, "verify_role", role=True)
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
            "Choisis ce que tu veux configurer.\n"
            "SentriX te guide ensuite **étape par étape**."
        ),
        colour=v4._CONFIG_MODULE.SETUP_COLOR_MAIN,
    )
    embed.set_footer(text="SentriX • Setup guidé")
    return embed


async def _step_embed(view) -> discord.Embed:
    module, section, index = _current(view)
    current = await _current_value(view, module, section)

    lines = [
        f"Étape **{index + 1}/{len(module.sections)}**",
        "",
        f"**{section.label}**",
        section.description,
    ]
    if current:
        lines.extend(["", f"Actuel : **{current}**"])

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
    next_index = max(0, min(index + delta, len(module.sections) - 1))
    view._v117_step = next_index
    view._v116_section = module.sections[next_index].key
    view.render_page()
    await view.persist_session()
    await view._refresh_message(interaction)


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
            for module in v116.MODULES
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
        disabled=index >= len(module.sections) - 1,
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
    logger.info("SentriX Setup V117 actif : accueil simple et configuration guidée étape par étape.")


__all__ = ["install_for_bot"]
