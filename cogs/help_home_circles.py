"""Rend uniquement l'accueil de +help sobre avec des puces noires."""

from __future__ import annotations

import logging

import discord
from discord.ext import commands

from .antigif_runtime import install as install_antigif_runtime
from .command_clarity import install as install_command_clarity
from .help_category_rework import install as install_help_category_rework

logger = logging.getLogger("bot.help-home-circles")
_INSTALLED = False
_CIRCLE = "●"
_SECTION_NAMES = {"Essentiels", "Communauté", "Administration"}


def _remove_leading_symbol(value: str) -> str:
    """Retire un emoji ou symbole placé avant un libellé, sans toucher au texte."""
    text = str(value or "").strip()
    if text.startswith(f"{_CIRCLE} "):
        text = text[len(_CIRCLE) + 1 :].lstrip()
    first, separator, rest = text.partition(" ")
    if separator and first and not any(character.isalnum() for character in first):
        return rest.strip()
    return text


def _circle_label(value: str) -> str:
    clean = _remove_leading_symbol(value)
    return f"{_CIRCLE} {clean}" if clean else _CIRCLE


def _circle_category_lines(value: str) -> str:
    lines: list[str] = []
    for raw_line in str(value or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        # Les catégories sont en gras. On supprime tout symbole situé avant le premier
        # marqueur Markdown, puis on ajoute une seule puce noire.
        bold_index = line.find("**")
        if bold_index >= 0:
            line = line[bold_index:]
        else:
            line = _remove_leading_symbol(line)
        lines.append(_circle_label(line))
    return "\n".join(lines)


def _apply_circle_home(embed: discord.Embed) -> discord.Embed:
    """Modifie l'embed en place et reste sûre lorsqu'elle est appelée deux fois."""
    if embed.title:
        embed.title = _remove_leading_symbol(str(embed.title))

    for index, field in enumerate(list(embed.fields)):
        clean_name = _remove_leading_symbol(str(field.name))
        new_value = str(field.value)
        if clean_name in _SECTION_NAMES:
            new_value = _circle_category_lines(new_value)
        embed.set_field_at(
            index,
            name=_circle_label(clean_name),
            value=new_value,
            inline=bool(field.inline),
        )
    return embed


def _clean_home_components(view: discord.ui.View) -> None:
    """Retire aussi les emojis du menu et des boutons sans pouvoir casser +help."""
    for item in view.children:
        try:
            if isinstance(item, discord.ui.Select):
                item.placeholder = "Choisissez une catégorie..."
                for option in item.options:
                    option.label = _circle_label(option.label)[:100]
                    option.emoji = None
            elif isinstance(item, discord.ui.Button):
                if item.label:
                    item.label = _circle_label(item.label)[:80]
                item.emoji = None
        except Exception:
            # Une différence de version de discord.py ne doit jamais empêcher l'aide
            # principale de s'afficher. L'embed reste nettoyé même si un composant refuse.
            logger.debug("Composant de l'accueil help non modifiable.", exc_info=True)


async def _configured_prefix(bot: commands.Bot, message: discord.Message) -> str:
    """Retourne le préfixe configuré sans faire de requête DB inutile."""
    if message.guild is None:
        return "+"

    cached = getattr(bot, "prefix_cache", {}).get(message.guild.id)
    if cached:
        return str(cached)

    try:
        conf = await bot.db.get_guild_config(message.guild.id)
        prefix = conf["prefix"] if conf and conf["prefix"] else "+"
    except Exception:
        prefix = "+"
    return str(prefix)


def _install_plus_help_shortcut(bot: commands.Bot) -> None:
    """Garantit que le message exact ``+help`` ouvre toujours l'aide.

    Le préfixe d'un serveur peut être personnalisé. Historiquement, dans ce cas,
    ``+help`` n'était plus reconnu. On garde donc ``+help`` comme raccourci universel
    sans modifier le préfixe des autres commandes et sans demander d'argument après help.
    """
    if getattr(bot, "_sentrix_plus_help_shortcut", False):
        return

    async def plus_help_listener(message: discord.Message):
        if message.author.bot:
            return
        if str(message.content or "").strip().casefold() != "+help":
            return

        # Si + est déjà le préfixe actif, le moteur normal de discord.py traite la
        # commande. Ne rien faire ici évite une double réponse.
        if await _configured_prefix(bot, message) == "+":
            return

        help_command = bot.get_command("help")
        if help_command is None:
            return

        try:
            ctx = await bot.get_context(message)
            if ctx.command is not None:
                return

            # get_context n'a pas reconnu le préfixe +, donc sa vue pointe encore sur
            # le texte brut « +help ». On la place en fin de message pour que la
            # commande help ne reçoive AUCUN argument parasite.
            ctx.command = help_command
            ctx.invoked_with = "help"
            ctx.prefix = "+"
            view = getattr(ctx, "view", None)
            if view is not None:
                view.index = len(view.buffer)
                view.previous = view.index

            await bot.invoke(ctx)
        except Exception:
            logger.exception("Le raccourci universel +help a échoué.")

    bot.add_listener(plus_help_listener, "on_message")
    bot._sentrix_plus_help_shortcut = True
    logger.info("Raccourci universel +help actif : aucun argument requis.")


def install(bot: commands.Bot) -> None:
    """Installe les catégories canoniques puis le style sobre de +help."""
    global _INSTALLED
    if _INSTALLED:
        return

    # Le classement doit être en place avant que le dashboard et le style n'enveloppent
    # l'accueil. Cela garantit que menu, recherche et pages utilisent les mêmes catégories.
    install_help_category_rework(bot)

    # Le filtre anti-GIF est chargé ici car ce runtime est lui-même installé une fois
    # pendant le chargement du cog Utility. Il reste indépendant de l'interface d'aide.
    try:
        install_antigif_runtime(bot)
    except Exception:
        logger.exception("Impossible d'installer le runtime anti-GIF.")

    from . import help_complete, utility

    original_module_home = help_complete._home_embed

    def module_home_with_circles(*args, **kwargs):
        return _apply_circle_home(original_module_home(*args, **kwargs))

    help_complete._home_embed = module_home_with_circles

    # Le dashboard enveloppe déjà build_help_home et ajoute son propre champ. Cette
    # seconde couche nettoie donc également ce champ sans supprimer le lien.
    original_utility_home = utility.build_help_home

    def utility_home_with_circles(*args, **kwargs):
        return _apply_circle_home(original_utility_home(*args, **kwargs))

    utility.build_help_home = utility_home_with_circles

    original_help_view_init = utility.HelpView.__init__

    def help_view_init(self, *args, **kwargs):
        original_help_view_init(self, *args, **kwargs)
        _clean_home_components(self)

    utility.HelpView.__init__ = help_view_init

    # +help reste toujours disponible directement, même si le serveur utilise un autre
    # préfixe pour le reste des commandes.
    _install_plus_help_shortcut(bot)

    # Dernière couche : les commandes restent exactement les mêmes, mais leur fiche
    # devient compréhensible pour quelqu'un qui ne connaît ni le jargon Discord ni les
    # noms techniques. Comme elle est installée après le classement et le style, elle
    # s'applique à toutes les pages, à la recherche et à +help <commande>.
    install_command_clarity(bot)

    _INSTALLED = True
    logger.info("Accueil de +help simplifié : catégories canoniques, cercles noirs et aide claire actifs.")
