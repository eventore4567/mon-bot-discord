"""Interface finale, minimale et uniforme de +setup / /setup.

La logique métier de Configuration reste intacte : persistance, permissions, callbacks,
création de rôles/logs et protections ne sont pas remplacés ici. Cette couche ne fait
qu'imposer un flux visuel simple : accueil court -> choix d'une catégorie -> page dédiée.
"""
from __future__ import annotations

import logging

import discord
from discord.ext import commands

logger = logging.getLogger("bot.setup-clean-style")
_INSTALLED = False

PURPLE_MAIN = 0x6C5CE7
PURPLE_SECONDARY = 0x8B5CF6


STEP_META = {
    "general": {
        "title": "Base du serveur",
        "summary": "Préfixe, rôle staff, accueil et réglages principaux.",
        "icon": "⚙️",
    },
    "roles": {
        "title": "Rôles",
        "summary": "Rôles automatiques et rôles utilisés par SentriX.",
        "icon": "👥",
    },
    "tickets": {
        "title": "Tickets",
        "summary": "Support, staff à prévenir et réglages des tickets.",
        "icon": "🎫",
    },
    "channels": {
        "title": "Salons",
        "summary": "Salons utilisés pour les annonces et systèmes du bot.",
        "icon": "#️⃣",
    },
    "levels": {
        "title": "Niveaux",
        "summary": "Paliers XP et récompenses de niveaux.",
        "icon": "📈",
    },
    "logs": {
        "title": "Logs",
        "summary": "Salons de logs et surveillance du serveur.",
        "icon": "📋",
    },
    "managers": {
        "title": "Gestionnaires",
        "summary": "Personnes autorisées à gérer certaines parties du bot.",
        "icon": "🔐",
    },
    "security": {
        "title": "Sécurité",
        "summary": "AutoMod, anti-spam, liens, raids et protections.",
        "icon": "🛡️",
    },
    "summary": {
        "title": "Résumé",
        "summary": "Vérifier rapidement les réglages importants.",
        "icon": "📋",
    },
}


def _avatar_url(bot: commands.Bot) -> str | None:
    user = getattr(bot, "user", None)
    if user is None:
        return None
    try:
        return str(user.display_avatar.url)
    except Exception:
        return None


def _set_author(embed: discord.Embed, bot: commands.Bot) -> None:
    icon = _avatar_url(bot)
    if icon:
        embed.set_author(name="SentriX", icon_url=icon)
    else:
        embed.set_author(name="SentriX")


def _clean_component_label(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    for prefix in ("● ", "○ ", "◉ ", "◈ "):
        if text.startswith(prefix):
            text = text[len(prefix):].lstrip()
    return text or None


def _short_preview(value: object, *, lines: int = 3, limit: int = 420) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    content = [line.strip() for line in text.splitlines() if line.strip()]
    result = "\n".join(content[:lines])
    if len(content) > lines:
        result += f"\n+{len(content) - lines} autre{'s' if len(content) - lines > 1 else ''}"
    return result[:limit]


def _is_useful_field(field: discord.EmbedProxy) -> bool:
    name = str(getattr(field, "name", "") or "").replace("\u200b", "").strip()
    value = str(getattr(field, "value", "") or "").replace("\u200b", "").strip()
    if not name or not value:
        return False
    if name.casefold() in {"information", "détails", "details", "conseil", "astuce"}:
        return False
    return True


def install(bot: commands.Bot) -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    from . import configuration

    configuration.SETUP_COLOR_MAIN = PURPLE_MAIN
    configuration.SETUP_COLOR_SECONDARY = PURPLE_SECONDARY

    # Les titres/phrases de la source restent courts afin que les autres couches visuelles
    # n'aient plus plusieurs paragraphes à retransformer.
    for step in configuration.SETUP_STEPS:
        meta = STEP_META.get(step["key"])
        if meta is None:
            continue
        step["title"] = meta["title"]
        step["description"] = meta["summary"]
        step["icon"] = meta["icon"]

    original_build_embed = configuration.SetupView.build_embed
    original_render_page = configuration.SetupView.render_page

    async def build_home_embed(self) -> discord.Embed:
        guild = self._guild()
        embed = discord.Embed(
            title="SentriX • Configuration",
            description=(
                "Configure SentriX depuis un seul menu.\n"
                "Choisis ci-dessous ce que tu veux modifier ; les changements sont enregistrés pour ce serveur."
            ),
            color=PURPLE_MAIN,
        )
        _set_author(embed, self.bot)
        embed.set_thumbnail(url=None)
        embed.clear_fields()
        embed.set_footer(text=f"SentriX • {guild.name if guild else 'Serveur'}")
        return embed

    async def build_embed(self) -> discord.Embed:
        if self.page == -1:
            return await build_home_embed(self)

        original = await original_build_embed(self)
        step = configuration.SETUP_STEPS[self.page]
        meta = STEP_META.get(step["key"], {
            "title": step["title"],
            "summary": "Modifie les réglages de cette catégorie.",
            "icon": "⚙️",
        })

        embed = discord.Embed(
            title=f"SentriX • {meta['title']}",
            description=meta["summary"],
            color=PURPLE_MAIN,
        )
        _set_author(embed, self.bot)
        embed.set_thumbnail(url=None)

        # Les pages à sélecteur n'ont pas besoin d'un inventaire complet des valeurs : le
        # contrôle indique quoi choisir. On montre uniquement le réglage actuellement ciblé.
        if step["key"] in {"roles", "channels"}:
            noun = "rôle" if step["key"] == "roles" else "salon"
            embed.description = f"{meta['summary']}\nSélectionne un réglage puis le {noun} correspondant."
            selected = getattr(self, "picker_selected", None)
            if selected:
                conf = await self.bot.db.get_guild_config(self.guild_id)
                fields = configuration.PICKER_FIELDS[step["key"]]
                label = next((label for field, _kind, label in fields if field == selected), selected)
                embed.add_field(
                    name="Sélection actuelle",
                    value=f"**{label}** — {self._mention_current(selected, conf)}",
                    inline=False,
                )
        else:
            # Certaines pages (sécurité, niveaux, gestionnaires, logs) ont un état utile
            # calculé par le moteur d'origine. On conserve au maximum deux petits blocs,
            # sans répéter descriptions, conseils ou gros inventaires.
            kept = 0
            seen: set[str] = set()
            for field in list(original.fields):
                if not _is_useful_field(field):
                    continue
                name = str(field.name).replace("\u200b", "").strip()
                value = _short_preview(field.value)
                if not value:
                    continue
                signature = f"{name.casefold()}|{value.casefold()}"
                if signature in seen:
                    continue
                seen.add(signature)
                embed.add_field(name=name[:72], value=value, inline=False)
                kept += 1
                if kept >= (4 if step["key"] == "summary" else 2):
                    break

        save_state = "Modifications en attente" if getattr(self, "dirty", False) else "Enregistré"
        embed.set_footer(text=f"SentriX • {save_state}")
        return embed

    def render_home(self) -> None:
        self.clear_items()
        options: list[discord.SelectOption] = []
        for index, step in enumerate(configuration.SETUP_STEPS):
            if step["key"] == "summary":
                continue
            meta = STEP_META.get(step["key"])
            if meta is None:
                continue
            options.append(discord.SelectOption(
                label=meta["title"][:100],
                value=str(index),
                description=meta["summary"][:100],
                emoji=meta["icon"],
            ))

        category_select = discord.ui.Select(
            placeholder="Choisis ce que tu veux configurer…",
            options=options[:25],
            min_values=1,
            max_values=1,
            row=0,
        )
        category_select.callback = self._make_home_category_callback(category_select)
        self.add_item(category_select)

        # Un seul bouton secondaire : il libère proprement la session. L'accueil ne doit
        # plus ressembler à un dashboard rempli de raccourcis.
        self.add_item(configuration.SetupNavButton(
            "cancel",
            self.message_id,
            label="Fermer",
            style=discord.ButtonStyle.secondary,
            row=1,
        ))

    def render_page(self) -> None:
        if self.page == -1:
            render_home(self)
            return

        original_render_page(self)

        # Chaque page est autonome : accueil, sauvegarde éventuelle et fermeture. Les
        # boutons Précédent/Suivant/Résumé/Aperçu/Historique créaient plusieurs parcours
        # concurrents et rendaient l'affichage différent d'une catégorie à l'autre.
        for item in list(self.children):
            if isinstance(item, configuration.SetupNavButton) and item.action in {
                "prev", "next", "preview", "history", "summary",
            }:
                self.remove_item(item)

        for item in list(self.children):
            try:
                if isinstance(item, discord.ui.Button):
                    action = getattr(item, "action", "")
                    labels = {
                        "home": "Accueil",
                        "save": "Enregistrer",
                        "cancel": "Fermer",
                    }
                    item.label = labels.get(action, _clean_component_label(item.label))
                    # Les pages setup utilisent des contrôles fonctionnels, pas des emojis
                    # décoratifs. Le style global pourra garder un pictogramme simple sur
                    # les contrôles génériques sans empiler plusieurs icônes.
                    item.emoji = None
                elif isinstance(item, discord.ui.Select):
                    placeholder = str(item.placeholder or "").strip()
                    placeholder = placeholder.replace("Choisissez", "Choisis").replace("Choisir", "Choisis")
                    item.placeholder = (placeholder or "Choisis une option…")[:150]
                    for option in list(getattr(item, "options", ()) or ()):
                        # Une option = un libellé clair ; jamais un emoji écrit deux fois
                        # dans le label ET dans la propriété Discord de l'option.
                        option.label = _clean_component_label(option.label) or "Option"
            except Exception:
                logger.debug("Composant +setup impossible à simplifier.", exc_info=True)

    configuration.SetupView._build_home_embed = build_home_embed
    configuration.SetupView.build_embed = build_embed
    configuration.SetupView._render_home = render_home
    configuration.SetupView.render_page = render_page

    _INSTALLED = True
    logger.info("+setup uniforme actif : accueil minimal, catégorie dédiée, contenu sans doublon.")
