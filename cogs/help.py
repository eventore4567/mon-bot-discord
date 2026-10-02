"""Centre d'aide officiel SentriX.

+help et /aide partagent la même logique. L'accueil reste volontairement léger :
il sert à trouver une commande, pas à configurer le serveur.
"""
from __future__ import annotations

import os
import re
import unicodedata
from collections import OrderedDict
from urllib.parse import urlparse

import discord
from discord import app_commands
from discord.ext import commands

import config
from utils import embeds
from utils import sentrix_panels as panels
from utils.command_permissions import command_example, command_requirement

PAGE_SIZE = 7

CATEGORY_NAMES = {
    "Moderation": "Modération",
    "Automod": "Sécurité",
    "Security": "Sécurité",
    "SecurityTools": "Sécurité",
    "Configuration": "Configuration",
    "Logs": "Configuration",
    "ServerBuilder": "Configuration",
    "Verification": "Sécurité",
    "Owner": "Configuration",
    "EmbedBuilder": "Configuration",
    "Design": "Configuration",
    "Notifications": "Configuration",
    "Utility": "Informations",
    "Stats": "Informations",
    "Invites": "Invitations",
    "Economy": "Économie",
    "Levels": "Niveaux",
    "GamesEconomy": "Jeux",
    "Minigames": "Jeux",
    "Music": "Musique",
    "Events": "Événements",
    "Tickets": "Tickets",
    "Ai": "IA",
}

CATEGORY_ORDER = (
    "Modération",
    "Sécurité",
    "Tickets",
    "Musique",
    "Économie",
    "Niveaux",
    "Jeux",
    "Événements",
    "Invitations",
    "Informations",
    "IA",
    "Configuration",
)

CATEGORY_DESCRIPTIONS = {
    "Modération": "Sanctions, avertissements et gestion des membres.",
    "Sécurité": "AutoMod, anti-raid, vérification et protections.",
    "Tickets": "Support, panneaux et gestion des tickets.",
    "Musique": "Lecture, file, playlists et contrôles vocaux.",
    "Économie": "Argent, banque, boutique et récompenses.",
    "Niveaux": "XP, progression et classements.",
    "Jeux": "Mini-jeux et activités interactives.",
    "Événements": "Événements, concours et animations.",
    "Invitations": "Invitations, statistiques et récompenses.",
    "Informations": "Serveur, membres, rôles, statistiques et utilitaires.",
    "IA": "Assistant SentriX et outils IA.",
    "Configuration": "Réglages, logs, design et administration du serveur.",
}

INVITE_PERMISSION_NAMES = (
    "view_channel", "manage_channels", "manage_roles", "kick_members", "ban_members",
    "moderate_members", "manage_messages", "read_message_history", "send_messages",
    "send_messages_in_threads", "embed_links", "attach_files", "add_reactions",
    "mention_everyone", "manage_nicknames", "change_nickname", "manage_webhooks",
    "manage_emojis_and_stickers", "connect", "speak", "move_members", "mute_members",
    "deafen_members", "use_application_commands", "create_public_threads",
    "create_private_threads", "manage_threads", "manage_events",
)


def _cog_name(command: commands.Command) -> str:
    return getattr(command.cog, "qualified_name", "Utility") if command.cog else "Utility"


def _category(command: commands.Command) -> str:
    return CATEGORY_NAMES.get(_cog_name(command), "Informations")


def _container_only(command: commands.Command) -> bool:
    """Vrai pour un groupe qui n'est qu'un dossier de sous-commandes."""
    children = list(getattr(command, "commands", ()) or ())
    return bool(children) and not bool(getattr(command, "invoke_without_command", False))


def _visible(bot: commands.Bot, _member=None) -> list[commands.Command]:
    """Catalogue logique de l'aide.

    On montre toutes les vraies actions, même si le membre n'a pas encore la
    permission, mais pas les simples conteneurs ni plusieurs façades du même
    callback métier. Les anciens alias restent indiqués dans la fiche.
    """
    rows: list[commands.Command] = []
    seen_names: set[str] = set()
    seen_callbacks: set[tuple[str, str]] = set()

    for command in bot.walk_commands():
        if command.hidden or _container_only(command):
            continue
        name_key = command.qualified_name.casefold().strip()
        if not name_key or name_key in seen_names:
            continue

        callback = _callback_key(getattr(command, "callback", None))
        if callback is not None and callback in seen_callbacks:
            continue

        seen_names.add(name_key)
        if callback is not None:
            seen_callbacks.add(callback)
        rows.append(command)

    return rows


def _callback_key(callback) -> tuple[str, str] | None:
    if callback is None:
        return None
    seen: set[int] = set()
    current = callback
    while getattr(current, "__wrapped__", None) is not None and id(current) not in seen:
        seen.add(id(current))
        current = current.__wrapped__
    module = str(getattr(current, "__module__", "") or "")
    qualname = str(getattr(current, "__qualname__", "") or "")
    return (module, qualname) if module or qualname else None


def _slash_indexes(bot: commands.Bot) -> tuple[dict[str, str], dict[tuple[str, str], str]]:
    by_name: dict[str, str] = {}
    by_callback: dict[tuple[str, str], str] = {}

    def walk(node, parent: str = "") -> None:
        name = f"{parent} {node.name}".strip()
        by_name[name.casefold()] = name
        key = _callback_key(getattr(node, "callback", None))
        if key is not None:
            by_callback.setdefault(key, name)
        for child in getattr(node, "commands", []):
            walk(child, name)

    for node in bot.tree.get_commands(type=discord.AppCommandType.chat_input):
        walk(node)
    return by_name, by_callback


def _slash_map(bot: commands.Bot) -> dict[str, str]:
    return _slash_indexes(bot)[0]


def _slash_name(bot: commands.Bot, command: commands.Command) -> str | None:
    by_name, by_callback = _slash_indexes(bot)
    direct = by_name.get(command.qualified_name.casefold())
    if direct:
        return direct

    app_command = getattr(command, "app_command", None)
    app_qualified = str(getattr(app_command, "qualified_name", "") or "")
    if app_qualified:
        published = by_name.get(app_qualified.casefold())
        if published:
            return published

    key = _callback_key(getattr(command, "callback", None))
    if key is not None:
        published = by_callback.get(key)
        if published:
            return published
    return None


def _description(command: commands.Command) -> str:
    raw = (command.description or command.help or "Aucune description.").strip()
    return raw.split("\n", 1)[0][:220]


def _display_name(command: commands.Command) -> str:
    try:
        from . import common_command_names

        return common_command_names.display_name(command)
    except Exception:
        return str(command.qualified_name)


def _example(command: commands.Command, prefix: str) -> str:
    example = command_example(command, prefix)
    long_call = f"{prefix}{command.qualified_name}"
    short_call = f"{prefix}{_display_name(command)}"
    if example.startswith(long_call):
        return short_call + example[len(long_call):]
    return example


def _usage(command: commands.Command, prefix: str) -> str:
    name = _display_name(command)
    if command.usage:
        return f"{prefix}{name} {command.usage}".strip()
    signature = getattr(command, "signature", "") or ""
    return f"{prefix}{name} {signature}".strip()


def _command_label(bot: commands.Bot, command: commands.Command, prefix: str) -> str:
    slash = _slash_name(bot, command)
    prefix_name = f"{prefix}{_display_name(command)}"
    label = f"/{slash}  ·  {prefix_name}" if slash else prefix_name
    return label[:256]


def _decorate(panel: discord.Embed, bot: commands.Bot) -> discord.Embed:
    user = getattr(bot, "user", None)
    avatar = getattr(getattr(user, "display_avatar", None), "url", None)
    if avatar:
        panel.set_thumbnail(url=str(avatar))
    return panel


def _home(bot: commands.Bot, member=None) -> discord.Embed:
    grouped = _ordered_categories(bot, member)
    panel = embeds.help_embed(
        "Centre d’aide",
        "Retrouvez rapidement les commandes et fonctionnalités de SentriX.",
    )
    lines = []
    for category, count in grouped.items():
        description = CATEGORY_DESCRIPTIONS.get(category, "Commandes SentriX.")
        lines.append(f"**{category}** — {description} `{count}`")
    panel.add_field(name="Catégories", value="\n".join(lines), inline=False)
    panel.add_field(
        name="Recherche rapide",
        value="Tapez `+help ban`, `/aide commande:ban` ou utilisez **Rechercher**.",
        inline=False,
    )
    panel.add_field(
        name="Permissions",
        value="Toutes les commandes sont visibles. La fiche d’une commande indique clairement la permission nécessaire.",
        inline=False,
    )
    panel.set_footer(text="SentriX Core · Centre d’aide")
    return _decorate(panel, bot)


def _detail(bot: commands.Bot, command: commands.Command, prefix: str) -> discord.Embed:
    slash = _slash_name(bot, command)
    requirement = command_requirement(command)
    panel = embeds.help_embed(_display_name(command), _description(command))
    panel.add_field(name="Commande", value=f"`{_usage(command, prefix)}`", inline=False)
    if slash:
        panel.add_field(name="Slash", value=f"`/{slash}`", inline=True)
    panel.add_field(name="Permission nécessaire", value=requirement, inline=True)
    panel.add_field(name="Catégorie", value=_category(command), inline=True)
    panel.add_field(name="Exemple", value=f"`{_example(command, prefix)}`", inline=False)
    alternate_names = []
    short_name = _display_name(command)
    if short_name != command.qualified_name:
        alternate_names.append(command.qualified_name)
    alternate_names.extend(
        alias
        for alias in (command.aliases or [])
        if alias not in alternate_names and alias != short_name
    )
    if alternate_names:
        panel.add_field(
            name="Autres noms",
            value=", ".join(f"`{prefix}{alias}`" for alias in alternate_names[:10]),
            inline=False,
        )
    panel.set_footer(text="SentriX Core · Aide commande")
    return _decorate(panel, bot)


def _pages(bot: commands.Bot, command_rows: list[commands.Command], prefix: str, title: str) -> list[discord.Embed]:
    chunks = [command_rows[i:i + PAGE_SIZE] for i in range(0, len(command_rows), PAGE_SIZE)] or [[]]
    pages: list[discord.Embed] = []
    for page_index, chunk in enumerate(chunks, start=1):
        panel = embeds.help_embed(
            title,
            "Sélectionnez ou recherchez une commande pour afficher sa fiche complète.",
        )
        if not chunk:
            panel.add_field(name="Aucun résultat", value="Aucune commande trouvée.", inline=False)
        else:
            for command in chunk:
                panel.add_field(
                    name=_command_label(bot, command, prefix),
                    value=f"{_description(command)}\n**Permission :** {command_requirement(command)}",
                    inline=False,
                )
        panel.set_footer(text=f"SentriX Core · Page {page_index}/{len(chunks)}")
        pages.append(_decorate(panel, bot))
    return pages


def _ordered_categories(bot: commands.Bot, member=None) -> OrderedDict[str, int]:
    counts: dict[str, int] = {}
    for command in _visible(bot, member):
        category = _category(command)
        counts[category] = counts.get(category, 0) + 1

    result: OrderedDict[str, int] = OrderedDict()
    for category in CATEGORY_ORDER:
        if category in counts:
            result[category] = counts.pop(category)
    for category in sorted(counts, key=str.casefold):
        result[category] = counts[category]
    return result


def _search_key(value: object) -> str:
    raw = unicodedata.normalize("NFKD", str(value or "").casefold())
    raw = "".join(char for char in raw if not unicodedata.combining(char))
    raw = raw.replace("_", " ").replace("-", " ")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", raw)).strip()


def _search_terms(bot: commands.Bot, command: commands.Command) -> dict[str, str]:
    slash = _slash_name(bot, command) or ""
    aliases = " ".join(str(alias) for alias in (command.aliases or ()))
    return {
        "slash": _search_key(slash),
        "display": _search_key(_display_name(command)),
        "qualified": _search_key(command.qualified_name),
        "name": _search_key(command.name),
        "aliases": _search_key(aliases),
        "category": _search_key(_category(command)),
        "description": _search_key(_description(command)),
        "permission": _search_key(command_requirement(command)),
    }


def _search(
    bot: commands.Bot,
    command_rows: list[commands.Command],
    query: str,
) -> list[commands.Command]:
    needle = _search_key(str(query or "").lstrip("+/"))
    if not needle:
        return []

    ranked: list[tuple[int, int, commands.Command]] = []
    for command in command_rows:
        terms = _search_terms(bot, command)
        exact = {
            terms["slash"],
            terms["display"],
            terms["qualified"],
            terms["name"],
        }
        exact.update(_search_key(alias) for alias in (command.aliases or ()))

        haystack = " ".join(value for value in terms.values() if value)
        if needle not in haystack:
            continue

        if needle in exact:
            rank = 0
        elif terms["slash"].startswith(needle) or terms["display"].startswith(needle):
            rank = 1
        elif needle in terms["slash"] or needle in terms["display"]:
            rank = 2
        elif needle in terms["qualified"] or needle in terms["aliases"]:
            rank = 3
        elif needle in terms["category"] or needle in terms["permission"]:
            rank = 4
        else:
            rank = 5

        # Les commandes réellement publiées en slash gagnent à rang égal.
        slash_bonus = 0 if terms["slash"] else 1
        ranked.append((rank, slash_bonus, command))

    ranked.sort(
        key=lambda row: (
            row[0],
            row[1],
            _search_key(_display_name(row[2])),
            _search_key(row[2].qualified_name),
        )
    )
    return [command for _, _, command in ranked]


def _recommended_invite_permissions() -> discord.Permissions:
    permissions = discord.Permissions.none()
    for name in INVITE_PERMISSION_NAMES:
        if hasattr(permissions, name):
            setattr(permissions, name, True)
    return permissions


def _invite_url(bot: commands.Bot) -> str | None:
    client_id = getattr(getattr(bot, "user", None), "id", None)
    if client_id is None:
        configured = str(getattr(config, "DISCORD_CLIENT_ID", "") or "").strip()
        if configured.isdigit():
            client_id = int(configured)
    if client_id is None:
        return None
    return discord.utils.oauth_url(
        int(client_id), permissions=_recommended_invite_permissions(), scopes=("bot", "applications.commands")
    )


def _valid_http_url(value: str) -> str | None:
    value = str(value or "").strip()
    if not value:
        return None
    parsed = urlparse(value)
    if parsed.scheme not in {"https", "http"} or not parsed.netloc:
        return None
    return value


def _dashboard_url() -> str | None:
    legacy = os.getenv("DASHBOARD_URL", "").strip()
    return (
        _valid_http_url(legacy)
        or _valid_http_url(getattr(config, "DASHBOARD_SHARE_URL", ""))
        or _valid_http_url(getattr(config, "DASHBOARD_APP_URL", ""))
    )


def _support_url() -> str | None:
    for env_name in ("SENTRIX_SUPPORT_URL", "SUPPORT_SERVER_URL"):
        value = _valid_http_url(os.getenv(env_name, ""))
        if value:
            return value
    return None


def _add_growth_links(view: discord.ui.View, bot: commands.Bot) -> None:
    for label, url in (
        ("Ajouter SentriX", _invite_url(bot)),
        ("Dashboard", _dashboard_url()),
        ("Serveur support", _support_url()),
    ):
        if url:
            view.add_item(discord.ui.Button(label=label, style=discord.ButtonStyle.link, url=url, row=3))


async def _private_error(interaction: discord.Interaction, text: str) -> None:
    panel = embeds.error(text)
    if interaction.response.is_done():
        await panels.envoyer(interaction.followup, panels.depuis_embed(panel), ephemere=True)
    else:
        await panels.envoyer(interaction.response, panels.depuis_embed(panel), ephemere=True)


def _exact_match(
    bot: commands.Bot,
    rows: list[commands.Command],
    query: str,
) -> commands.Command | None:
    needle = _search_key(str(query or "").lstrip("+/"))
    for command in rows:
        terms = {
            _search_key(command.name),
            _search_key(command.qualified_name),
            _search_key(_display_name(command)),
            _search_key(_slash_name(bot, command) or ""),
            *(_search_key(alias) for alias in (command.aliases or ())),
        }
        if needle and needle in terms:
            return command
    return None


def _lots(command_rows: list[commands.Command]) -> list[list[commands.Command]]:
    """Decoupe la liste en pages. Remplace _pages, qui fabriquait des embeds."""
    return [
        command_rows[i:i + PAGE_SIZE] for i in range(0, len(command_rows), PAGE_SIZE)
    ] or [[]]


class SearchModal(discord.ui.Modal, title="Rechercher une commande"):
    query = discord.ui.TextInput(label="Nom ou mot-clé", max_length=60, placeholder="ban, ticket, image, logs...")

    def __init__(self, view: "HelpView"):
        super().__init__()
        self.help_view = view

    async def on_submit(self, interaction: discord.Interaction):
        vue = self.help_view
        recherche = str(self.query.value)
        rows = _search(vue.bot, _visible(vue.bot, interaction.user), recherche)
        exact = _exact_match(vue.bot, rows, recherche)
        if exact:
            nouvelle = VueAide(
                vue.bot, vue.prefix, interaction.user.id,
                titre=_display_name(exact),
                resume=_description(exact),
                sections=_sections_detail(vue.bot, exact, vue.prefix),
                member=interaction.user,
            )
        else:
            nouvelle = VueAide(
                vue.bot, vue.prefix, interaction.user.id,
                titre=f"Recherche · {recherche[:40]}",
                lots=_lots(rows), index=0, member=interaction.user,
            )
        await _remplacer(interaction, nouvelle)


class CategorySelect(discord.ui.Select):
    def __init__(self, owner: "HelpView"):
        self.owner = owner
        options = [
            discord.SelectOption(
                label=f"{name} · {count}"[:100],
                value=name,
                description=CATEGORY_DESCRIPTIONS.get(name, "Commandes SentriX.")[:100],
            )
            for name, count in _ordered_categories(owner.bot, owner.member).items()
        ]
        if not options:
            options = [discord.SelectOption(label="Aucune catégorie", value="__empty__")]
        super().__init__(placeholder="Choisir une catégorie", options=options[:25], row=0)

    async def callback(self, interaction: discord.Interaction):
        category = self.values[0]
        if category == "__empty__":
            return await _private_error(interaction, "Aucune catégorie disponible.")
        rows = [c for c in _visible(self.owner.bot, interaction.user) if _category(c) == category]
        await _remplacer(
            interaction,
            VueAide(
                self.owner.bot, self.owner.prefix, interaction.user.id,
                titre=category,
                lots=_lots(rows), index=0, member=interaction.user,
            ),
        )


def _sections_accueil(bot: commands.Bot, member=None) -> list[panels.Section]:
    """Accueil de l'aide : les categories, puis comment chercher."""
    groupes = _ordered_categories(bot, member)
    total = sum(groupes.values())
    return [
        panels.Section(
            f"Catégories ({len(groupes)})",
            [
                panels.Ligne(
                    categorie,
                    f"`{compte}` commande{'s' if compte > 1 else ''}",
                    indice=CATEGORY_DESCRIPTIONS.get(categorie, "Commandes SentriX."),
                )
                for categorie, compte in groupes.items()
            ],
        ),
        panels.Section(
            "Trouver une commande",
            [
                panels.Ligne("Par son nom", "`/aide commande:ban` ou `+help ban`"),
                panels.Ligne("Par catégorie", "Le menu déroulant ci-dessous"),
                panels.Ligne("Par mot-clé", "Le bouton **Rechercher**"),
            ],
        ),
        panels.Section(
            "Bon à savoir",
            [
                panels.Ligne("Commandes visibles", f"**{total}** au total"),
                panels.Ligne(
                    "Permissions",
                    "La fiche de chaque commande indique celle qu'elle exige",
                ),
            ],
        ),
    ]


def _sections_detail(bot: commands.Bot, command: commands.Command, prefix: str) -> list[panels.Section]:
    """Fiche d'une commande : comment l'appeler, qui peut, un exemple."""
    slash = _slash_map(bot).get(command.qualified_name.casefold())
    appel = [panels.Ligne("Préfixe", f"`{_usage(command, prefix)}`")]
    if slash:
        appel.append(panels.Ligne("Slash", f"`/{slash}`"))
    appel.append(panels.Ligne("Exemple", f"`{_example(command, prefix)}`"))

    sections = [
        panels.Section("Comment l'utiliser", appel),
        panels.Section(
            "Accès",
            [
                panels.Ligne("Permission nécessaire", command_requirement(command)),
                panels.Ligne("Catégorie", _category(command)),
            ],
        ),
    ]
    alias = []
    short_name = _display_name(command)
    if short_name != command.qualified_name:
        alias.append(command.qualified_name)
    alias.extend(
        a
        for a in (getattr(command, "aliases", ()) or ())
        if a and a not in alias and a != short_name
    )
    if alias:
        sections.append(
            panels.Section(
                "Autres noms",
                texte=" · ".join(f"`{prefix}{a}`" for a in alias[:8]),
            )
        )
    return sections


def _sections_liste(bot: commands.Bot, lot, prefix: str) -> list[panels.Section]:
    """Une page de resultats : une ligne par commande, avec sa permission."""
    if not lot:
        return [
            panels.Section(
                "Aucun résultat",
                [panels.Ligne("Essayez", "Un autre mot-clé, ou le menu par catégorie")],
            )
        ]
    return [
        panels.Section(
            "Commandes",
            [
                panels.Ligne(
                    _command_label(bot, command, prefix),
                    _description(command),
                    indice=f"Permission : {command_requirement(command)}",
                )
                for command in lot
            ],
        )
    ]


class VueAide(discord.ui.LayoutView):
    """Centre d'aide compose : banniere, sections, menu et navigation.

    Une LayoutView ne se modifie pas en place : chaque navigation reconstruit une
    vue complete et remplace le message. C'est plus simple que de synchroniser
    l'etat de dix composants, et cela garantit qu'aucun reste de la page
    precedente ne subsiste.
    """

    def __init__(
        self,
        bot: commands.Bot,
        prefix: str,
        author_id: int,
        *,
        titre: str = "Centre d'aide",
        resume: str | None = None,
        sections: list[panels.Section] | None = None,
        lots: list[list] | None = None,
        index: int = 0,
        member=None,
    ) -> None:
        super().__init__(timeout=180)
        self.bot = bot
        self.prefix = prefix
        self.author_id = int(author_id)
        self.member = member or bot.get_user(author_id)
        self.lots = lots
        self.index = index
        self.kind = "brand"

        if sections is None:
            sections = (
                _sections_liste(bot, lots[index], prefix)
                if lots
                else _sections_accueil(bot, self.member)
            )
        if resume is None:
            resume = (
                f"Page **{index + 1}** sur **{len(lots)}**"
                if lots
                else "Toutes les commandes de SentriX, classées et cherchables."
            )

        conteneur = discord.ui.Container(
            accent_colour=discord.Colour(panels.INTENTIONS[self.kind][0])
        )
        galerie = discord.ui.MediaGallery()
        galerie.add_item(media=f"attachment://{panels.nom_banniere(self.kind)}")
        conteneur.add_item(galerie)
        conteneur.add_item(
            discord.ui.TextDisplay(f"-# {panels.signature_core('special')}")
        )
        conteneur.add_item(discord.ui.TextDisplay(f"## {titre}\n{resume}"))

        for section_index, section in enumerate(sections, start=1):
            rendu = section.rendu(section_index)
            if rendu:
                conteneur.add_item(discord.ui.Separator())
                conteneur.add_item(discord.ui.TextDisplay(rendu[:3800]))

        conteneur.add_item(
            discord.ui.TextDisplay(f"-# {panels.pied_core('special', 'Centre d’aide')}")
        )
        conteneur.add_item(discord.ui.Separator())
        conteneur.add_item(discord.ui.ActionRow(CategorySelect(self)))
        conteneur.add_item(discord.ui.ActionRow(*self._navigation()))
        liens = self._liens()
        if liens:
            conteneur.add_item(discord.ui.ActionRow(*liens))
        self.add_item(conteneur)

    # -- boutons ----------------------------------------------------------
    def _navigation(self) -> list[discord.ui.Button]:
        precedent = discord.ui.Button(
            label="Précédent", style=discord.ButtonStyle.secondary,
            custom_id="sentrix:aide:prec",
            disabled=not self.lots or self.index <= 0,
        )
        accueil = discord.ui.Button(
            label="Accueil", style=discord.ButtonStyle.secondary, custom_id="sentrix:aide:accueil"
        )
        suivant = discord.ui.Button(
            label="Suivant", style=discord.ButtonStyle.secondary,
            custom_id="sentrix:aide:suiv",
            disabled=not self.lots or self.index >= len(self.lots or []) - 1,
        )
        rechercher = discord.ui.Button(
            label="Rechercher", style=discord.ButtonStyle.primary, custom_id="sentrix:aide:cherche"
        )

        async def aller(interaction, delta: int):
            vue = VueAide(
                self.bot, self.prefix, self.author_id,
                lots=self.lots, index=max(0, min(len(self.lots) - 1, self.index + delta)),
                member=interaction.user,
            )
            await _remplacer(interaction, vue)

        async def cb_prec(interaction):
            await aller(interaction, -1)

        async def cb_suiv(interaction):
            await aller(interaction, 1)

        async def cb_accueil(interaction):
            await _remplacer(
                interaction,
                VueAide(self.bot, self.prefix, self.author_id, member=interaction.user),
            )

        async def cb_cherche(interaction):
            await interaction.response.send_modal(SearchModal(self))

        precedent.callback = cb_prec
        suivant.callback = cb_suiv
        accueil.callback = cb_accueil
        rechercher.callback = cb_cherche
        return [precedent, accueil, suivant, rechercher]

    def _liens(self) -> list[discord.ui.Button]:
        """Invitation, tableau de bord, support — seulement s'ils sont configures."""
        boutons: list[discord.ui.Button] = []
        for libelle, url in (
            ("Ajouter SentriX", _invite_url(self.bot)),
            ("Tableau de bord", _dashboard_url()),
            ("Support", _support_url()),
        ):
            if url:
                boutons.append(discord.ui.Button(label=libelle, url=url))
        return boutons[:5]

    def fichiers(self) -> list[discord.File]:
        """Banniere a joindre. Meme contrat que panels.Panneau, pour que
        panels.envoyer traite les deux sans savoir lequel il tient."""
        fichier = panels.fichier_banniere(self.kind)
        return [fichier] if fichier is not None else []

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.author_id:
            return True
        await _private_error(interaction, "Ce panneau d'aide appartient à une autre personne.")
        return False


async def _remplacer(interaction: discord.Interaction, vue: "VueAide") -> None:
    """Remplace le message par la nouvelle vue, banniere comprise.

    `attachments=` doit reprendre la banniere : sans elle, l'edition la retire et
    la galerie pointerait vers une piece jointe disparue.
    """
    await interaction.response.edit_message(
        content=None,
        embeds=[],
        view=vue,
        attachments=[f for f in (panels.fichier_banniere(vue.kind),) if f is not None],
    )


class HelpView(discord.ui.View):
    def __init__(self, bot: commands.Bot, prefix: str, author_id: int, *, pages=None, member=None):
        super().__init__(timeout=180)
        self.bot = bot
        self.prefix = prefix
        self.author_id = int(author_id)
        self.pages = pages
        self.index = 0
        self.member = member or bot.get_user(author_id)
        self.add_item(CategorySelect(self))
        _add_growth_links(self, bot)
        self._sync()

    def _sync(self) -> None:
        self.previous.disabled = not self.pages or self.index <= 0
        self.next.disabled = not self.pages or self.index >= len(self.pages) - 1

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.author_id:
            return True
        await _private_error(interaction, "Ce panneau d’aide appartient à une autre personne.")
        return False

    @discord.ui.button(label="Rechercher", style=discord.ButtonStyle.secondary, row=1)
    async def search(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await interaction.response.send_modal(SearchModal(self))

    @discord.ui.button(label="Précédent", style=discord.ButtonStyle.secondary, row=2)
    async def previous(self, interaction: discord.Interaction, _button: discord.ui.Button):
        if not self.pages:
            return
        self.index = max(0, self.index - 1)
        self._sync()
        await interaction.response.edit_message(content=None, embed=self.pages[self.index], view=self)

    @discord.ui.button(label="Accueil", style=discord.ButtonStyle.secondary, row=2)
    async def home(self, interaction: discord.Interaction, _button: discord.ui.Button):
        view = HelpView(self.bot, self.prefix, self.author_id, member=interaction.user)
        await interaction.response.edit_message(content=None, embed=_home(self.bot, interaction.user), view=view)

    @discord.ui.button(label="Suivant", style=discord.ButtonStyle.secondary, row=2)
    async def next(self, interaction: discord.Interaction, _button: discord.ui.Button):
        if not self.pages:
            return
        self.index = min(len(self.pages) - 1, self.index + 1)
        self._sync()
        await interaction.response.edit_message(content=None, embed=self.pages[self.index], view=self)


class OfficialHelp(commands.Cog, name="SentriXHelp"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def send_help(self, target, query: str | None = None):
        prefix = "+"
        member = getattr(target, "author", None) or getattr(target, "user", None)
        if member is None:
            return

        if query:
            rows = _search(self.bot, _visible(self.bot, member), query)
            exact = _exact_match(self.bot, rows, query)
            if exact:
                vue = VueAide(
                    self.bot, prefix, member.id,
                    titre=_display_name(exact),
                    resume=_description(exact),
                    sections=_sections_detail(self.bot, exact, prefix),
                    member=member,
                )
            else:
                vue = VueAide(
                    self.bot, prefix, member.id,
                    titre=f"Recherche · {query[:40]}",
                    lots=_lots(rows), index=0, member=member,
                )
        else:
            vue = VueAide(self.bot, prefix, member.id, member=member)

        return await panels.envoyer(target, vue)

    @commands.command(name="help", aliases=["aide"])
    async def prefix_help(self, ctx: commands.Context, *, query: str | None = None):
        await self.send_help(ctx, query)

    @app_commands.command(name="aide", description="Ouvrir le centre d’aide SentriX")
    @app_commands.describe(commande="Nom, slash, catégorie ou mot-clé")
    async def slash_help(self, interaction: discord.Interaction, commande: str | None = None):
        await self.send_help(interaction, commande)

    @slash_help.autocomplete("commande")
    async def slash_help_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        rows = _visible(self.bot, interaction.user)
        matches = _search(self.bot, rows, current) if current.strip() else rows
        choices: list[app_commands.Choice[str]] = []
        for command in matches[:25]:
            slash = _slash_name(self.bot, command)
            public = f"/{slash}" if slash else f"+{_display_name(command)}"
            label = f"{public} · {_description(command)}"[:100]
            value = (slash or _display_name(command))[:100]
            choices.append(app_commands.Choice(name=label, value=value))
        return choices


async def setup(bot: commands.Bot):
    old = bot.get_command("help")
    if old is not None:
        bot.remove_command("help")
    bot.tree.remove_command("help", type=discord.AppCommandType.chat_input)
    bot.tree.remove_command("aide", type=discord.AppCommandType.chat_input)
    await bot.add_cog(OfficialHelp(bot))
