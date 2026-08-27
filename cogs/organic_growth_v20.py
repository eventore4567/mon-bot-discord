"""Croissance organique discrète dans +help / /help.

Ajoute uniquement des boutons-liens utiles aux vues d'aide existantes :
- Ajouter SentriX
- Dashboard
- Serveur support (uniquement si une URL est configurée)

Aucun message automatique, DM, listener de spam ou publicité après chaque commande.
"""

from __future__ import annotations

import os
from urllib.parse import urlparse

import discord
from discord.ext import commands

import config
from cogs import utility


_PATCH_MARKER = "_sentrix_organic_growth_v20"
_SUPPORT_ENV_NAMES = ("SENTRIX_SUPPORT_URL", "SUPPORT_SERVER_URL")

# Permissions réellement utiles aux systèmes SentriX. On ne demande volontairement pas
# Administrateur : l'installation reste compréhensible et le propriétaire du serveur garde
# la possibilité de retirer une permission précise sans casser tout le rôle du bot.
_RECOMMENDED_PERMISSION_NAMES = (
    "view_channel",
    "manage_channels",
    "manage_roles",
    "kick_members",
    "ban_members",
    "moderate_members",
    "manage_messages",
    "read_message_history",
    "send_messages",
    "send_messages_in_threads",
    "embed_links",
    "attach_files",
    "add_reactions",
    "mention_everyone",
    "manage_nicknames",
    "change_nickname",
    "manage_webhooks",
    "manage_emojis_and_stickers",
    "connect",
    "speak",
    "move_members",
    "mute_members",
    "deafen_members",
    "use_application_commands",
    "create_public_threads",
    "create_private_threads",
    "manage_threads",
    "manage_events",
)


def recommended_invite_permissions() -> discord.Permissions:
    """Construit la permission OAuth à partir des flags supportés par discord.py."""
    permissions = discord.Permissions.none()
    for name in _RECOMMENDED_PERMISSION_NAMES:
        if hasattr(permissions, name):
            setattr(permissions, name, True)
    return permissions


def build_invite_url(bot: commands.Bot) -> str | None:
    """Génère l'URL OAuth depuis l'ID réel du bot, jamais depuis un lien figé."""
    client_id = getattr(getattr(bot, "user", None), "id", None)
    if client_id is None:
        configured_id = str(getattr(config, "DISCORD_CLIENT_ID", "") or "").strip()
        if configured_id.isdigit():
            client_id = int(configured_id)
    if client_id is None:
        return None

    return discord.utils.oauth_url(
        int(client_id),
        permissions=recommended_invite_permissions(),
        scopes=("bot", "applications.commands"),
    )


def _valid_http_url(value: str) -> str | None:
    value = str(value or "").strip()
    if not value:
        return None
    parsed = urlparse(value)
    if parsed.scheme not in {"https", "http"} or not parsed.netloc:
        return None
    return value


def dashboard_url() -> str | None:
    return _valid_http_url(getattr(config, "DASHBOARD_APP_URL", ""))


def support_url() -> str | None:
    """Le bouton support n'apparaît que lorsqu'une vraie URL a été configurée."""
    for env_name in _SUPPORT_ENV_NAMES:
        url = _valid_http_url(os.getenv(env_name, ""))
        if url:
            return url
    return None


def add_growth_links(view: discord.ui.View, bot: commands.Bot, *, row: int) -> None:
    """Ajoute les liens sans dupliquer un bouton déjà présent dans la vue."""
    existing_labels = {
        str(getattr(item, "label", "") or "").strip().casefold()
        for item in view.children
    }

    links = (
        ("Ajouter SentriX", build_invite_url(bot)),
        ("Dashboard", dashboard_url()),
        ("Serveur support", support_url()),
    )
    for label, url in links:
        if not url or label.casefold() in existing_labels:
            continue
        view.add_item(
            discord.ui.Button(
                label=label,
                style=discord.ButtonStyle.link,
                url=url,
                row=row,
            )
        )
        existing_labels.add(label.casefold())


def _patch_help_view(view_cls: type[discord.ui.View], *, growth_row: int) -> None:
    original_init = view_cls.__init__
    if getattr(original_init, _PATCH_MARKER, False):
        return

    def patched_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        bot = kwargs.get("bot") or (args[0] if args else None)
        if bot is not None:
            add_growth_links(self, bot, row=growth_row)

    setattr(patched_init, _PATCH_MARKER, True)
    setattr(patched_init, "_sentrix_original", original_init)
    view_cls.__init__ = patched_init


def install(_bot: commands.Bot | None = None) -> None:
    """Patche seulement les deux vues d'aide officielles de SentriX."""
    _patch_help_view(utility.HelpView, growth_row=2)
    _patch_help_view(utility.CategoryHelpView, growth_row=3)


async def setup(bot: commands.Bot) -> None:
    install(bot)
