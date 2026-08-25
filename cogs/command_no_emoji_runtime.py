"""Compatibilité de l'ancienne couche « commandes sans emoji ».

La politique visuelle actuelle autorise les petits pictogrammes utiles dans les boutons,
menus et champs. Ce module conserve l'API historique attendue par ``cogs.__init__`` et
``plain_response_policy``, mais ne supprime plus les emojis et n'empile plus de wrappers
sur les transports discord.py.

Il reste volontairement un nettoyeur léger : espaces multiples, lignes vides excessives
et limites Discord. La logique des commandes et des composants n'est jamais modifiée.
"""
from __future__ import annotations

import re
import sys
from typing import Any

import discord
from discord.ext import commands

_MULTI_SPACE_RE = re.compile(r"[ \t]{2,}")
_MANY_BLANKS_RE = re.compile(r"\n{3,}")


def has_emoji(value: object | None) -> bool:
    """Compatibilité : la détection n'est plus utilisée pour supprimer du contenu."""
    if value is None:
        return False
    text = str(value)
    return any(
        0x1F000 <= ord(char) <= 0x1FAFF
        or 0x2600 <= ord(char) <= 0x27BF
        or 0x2B00 <= ord(char) <= 0x2BFF
        for char in text
    ) or bool(re.search(r"<a?:[A-Za-z0-9_~]+:\d+>", text))


def clean_text(value: object | None, *, fallback: str = "") -> str:
    if value is None:
        return fallback
    text = str(value)
    text = _MULTI_SPACE_RE.sub(" ", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = _MANY_BLANKS_RE.sub("\n\n", text)
    text = text.strip()
    return text or fallback


def clean_embed(embed: discord.Embed | None) -> discord.Embed | None:
    if embed is None:
        return None
    cleaned = embed.copy()
    if cleaned.title is not None:
        cleaned.title = clean_text(cleaned.title, fallback="SentriX")[:256]
    if cleaned.description is not None:
        cleaned.description = clean_text(cleaned.description)[:4096]
    for index, field in enumerate(list(cleaned.fields)):
        cleaned.set_field_at(
            index,
            name=clean_text(field.name, fallback="Information")[:256],
            value=clean_text(field.value, fallback="—")[:1024],
            inline=bool(field.inline),
        )
    footer_text = getattr(cleaned.footer, "text", None)
    footer_icon = getattr(cleaned.footer, "icon_url", None)
    if footer_text is not None or footer_icon:
        kwargs: dict[str, Any] = {"text": clean_text(footer_text, fallback="SentriX")[:2048]}
        if footer_icon:
            kwargs["icon_url"] = str(footer_icon)
        cleaned.set_footer(**kwargs)
    author_name = getattr(cleaned.author, "name", None)
    if author_name is not None:
        kwargs = {"name": clean_text(author_name, fallback="SentriX")[:256]}
        author_url = getattr(cleaned.author, "url", None)
        author_icon = getattr(cleaned.author, "icon_url", None)
        if author_url:
            kwargs["url"] = str(author_url)
        if author_icon:
            kwargs["icon_url"] = str(author_icon)
        cleaned.set_author(**kwargs)
    return cleaned


def clean_view(view):
    """Conserve les emojis fonctionnels et nettoie uniquement les libellés."""
    if view is None:
        return None
    for item in list(getattr(view, "children", ()) or ()):
        label = getattr(item, "label", None)
        if label is not None:
            try:
                item.label = clean_text(label, fallback="Action")[:80]
            except Exception:
                pass
        placeholder = getattr(item, "placeholder", None)
        if placeholder is not None:
            try:
                item.placeholder = clean_text(placeholder, fallback="Choisir une option…")[:150]
            except Exception:
                pass
        options = getattr(item, "options", None)
        if options:
            for option in options:
                try:
                    option.label = clean_text(option.label, fallback="Option")[:100]
                except Exception:
                    pass
                try:
                    if option.description is not None:
                        option.description = clean_text(option.description)[:100] or None
                except Exception:
                    pass
    return view


def clean_modal(modal):
    if modal is None:
        return None
    return clean_view(modal)


def _clean_send_args(args: tuple, kwargs: dict) -> tuple[tuple, dict]:
    args = list(args)
    kwargs = dict(kwargs)
    missing = getattr(discord.utils, "MISSING", object())

    if args and args[0] is not None and args[0] is not missing:
        args[0] = clean_text(args[0], fallback="SentriX")
    content = kwargs.get("content", missing)
    if content is not missing and content is not None:
        kwargs["content"] = clean_text(content, fallback="SentriX")
    embed = kwargs.get("embed", missing)
    if embed is not missing and embed is not None:
        kwargs["embed"] = clean_embed(embed)
    embeds = kwargs.get("embeds", missing)
    if embeds is not missing and embeds is not None:
        kwargs["embeds"] = [clean_embed(item) for item in embeds]
    view = kwargs.get("view", missing)
    if view is not missing and view is not None:
        kwargs["view"] = clean_view(view)
    return tuple(args), kwargs


def _clean_edit_kwargs(kwargs: dict) -> dict:
    cleaned = dict(kwargs)
    missing = getattr(discord.utils, "MISSING", object())
    content = cleaned.get("content", missing)
    if content is not missing and content is not None:
        cleaned["content"] = clean_text(content, fallback="SentriX")
    embed = cleaned.get("embed", missing)
    if embed is not missing and embed is not None:
        cleaned["embed"] = clean_embed(embed)
    embeds = cleaned.get("embeds", missing)
    if embeds is not missing and embeds is not None:
        cleaned["embeds"] = [clean_embed(item) for item in embeds]
    view = cleaned.get("view", missing)
    if view is not missing and view is not None:
        cleaned["view"] = clean_view(view)
    return cleaned


def install(bot: commands.Bot) -> None:
    """API historique : aucun transport n'est patché, le renderer final s'en charge."""
    try:
        from utils import command_style_v2
        command_style_v2.install(bot)
    except Exception:
        # Le style premium historique reste fonctionnel même si le thème V2 est absent.
        pass

    # L'installateur de compatibilité passe déjà à chaque chargement d'extension. On en
    # profite pour brancher l'annonceur des releases sans ajouter une nouvelle commande
    # publique ni modifier le budget slash. L'annonceur est lui-même idempotent.
    try:
        from .release_announcer import install as install_release_announcer
        install_release_announcer(bot)
        # V64 : aucune release ordinaire n'est annoncée ; seules celles marquées
        # explicitement [MAJOR] / [PING] sont publiées sur le serveur officiel.
        from .release_ping_policy_v63 import install as install_release_ping_policy_v63
        install_release_ping_policy_v63(bot)
    except Exception:
        # Une annonce de mise à jour ne doit jamais empêcher SentriX de démarrer.
        pass

    # Les correctifs de logs V60/V61 sont chargés seulement une fois que le renderer
    # V50/V53 existe réellement. V60 fiabilise les identités ; V61 reste la dernière
    # couche source afin de fusionner les événements techniques liés et d'éviter les
    # mentions/noms de salon répétés.
    if "cogs.log_fixed_height_v50" in sys.modules:
        try:
            from .log_identity_context_v60 import install as install_log_identity_context_v60
            install_log_identity_context_v60(bot)
            from .log_consolidation_v61 import install as install_log_consolidation_v61
            install_log_consolidation_v61(bot)
        except Exception:
            # Le rendu d'un journal ne doit jamais empêcher SentriX de démarrer.
            pass

    # Le constructeur officiel dépend du vrai Cog ServerBuilder. Ne pas importer son
    # module avant le chargement de cette extension évite de conserver une ancienne
    # référence Python si discord.py recharge ensuite cogs.server_builder.
    if bot.get_cog("ServerBuilder") is not None:
        try:
            from .official_server import install as install_official_server
            install_official_server(bot)
            from .official_server_polish import install as install_official_server_polish
            install_official_server_polish(bot)
            # Toujours après official_server : ce correctif remplace son ancien wrapper
            # par une version qui conserve la signature originale de create-server.
            from .official_server_command_fix import install as install_official_server_command_fix
            install_official_server_command_fix(bot)
        except Exception:
            # Un outil de construction du serveur officiel ne doit jamais bloquer le bot.
            pass

    # Fondation SentriX V3 : cette couche est réaffirmée après les anciens systèmes
    # help/style à chaque chargement d'extension. Elle ne crée aucune commande et ne
    # modifie pas les protections métier ; elle choisit seulement l'expérience finale.
    try:
        from .sentrix_v3_ux import install as install_sentrix_v3_ux
        install_sentrix_v3_ux(bot)
    except Exception:
        # Une évolution UX ne doit jamais empêcher le bot de démarrer.
        pass

    # +help et /help sont des commandes de navigation. Elles doivent rester accessibles
    # même quand l'utilisateur vient d'utiliser plusieurs commandes, sans désactiver les
    # protections anti-spam des actions réelles du bot.
    try:
        from .help_cooldown_exemption_v3 import install as install_help_cooldown_exemption_v3
        install_help_cooldown_exemption_v3(bot)
    except Exception:
        # Un correctif de confort ne doit jamais empêcher SentriX de démarrer.
        pass

    # V3 : une faute de frappe ou un mauvais argument doit produire une aide utile, pas
    # un silence ou un message Python. Le handler conserve toutes les protections métier
    # et délègue les permissions/cooldowns au système historique.
    try:
        from .error_experience_v3 import install as install_error_experience_v3
        install_error_experience_v3(bot)
    except Exception:
        # Une amélioration UX ne doit jamais empêcher SentriX de démarrer.
        pass

    # V3.6.1 : doit rester après les renderers historiques et V3.6. Il protège le token
    # complet <a:emoji:id> contre les nettoyeurs de titres qui supprimaient le caractère
    # '<' et répare les fragments a:sxv36_...> lors des prochaines éditions de panneaux.
    try:
        from .sentrix_emoji_markup_guard_v361 import install as install_emoji_markup_guard_v361
        install_emoji_markup_guard_v361(bot)
    except Exception:
        # Un garde purement visuel ne doit jamais empêcher le bot de démarrer.
        pass

    bot._sentrix_no_emoji_commands = False
    bot._sentrix_command_style_v2 = True
