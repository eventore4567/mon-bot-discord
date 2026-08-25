"""Interface canonique de +setup et /setup.

Cette couche est l'unique propriétaire du rendu Setup. Elle garde la logique métier de
``cogs.configuration`` (DB, sauvegarde, sécurité, rôles, logs, tickets) et ajoute la langue
directement dans le même menu, sans sous-classe V5/V6/V7 ni second renderer.
"""
from __future__ import annotations

import logging

import discord
from discord.ext import commands

from . import language_runtime

logger = logging.getLogger("bot.setup-policy")
_INSTALLED = False
PURPLE_MAIN = 0x6C5CE7
PURPLE_SECONDARY = 0x8B5CF6
LANGUAGE_PAGE = -20260825
LANGUAGE_VALUE = "__sentrix_language__"

STEP_META = {
    "general": ("Base du serveur", "Préfixe, rôle staff, accueil et réglages principaux.", "⚙️"),
    "roles": ("Rôles", "Rôles automatiques et rôles utilisés par SentriX.", "👥"),
    "tickets": ("Tickets", "Support, staff à prévenir et réglages des tickets.", "🎫"),
    "channels": ("Salons", "Salons utilisés pour les annonces et systèmes du bot.", "#️⃣"),
    "levels": ("Niveaux", "Paliers XP et récompenses de niveaux.", "📈"),
    "logs": ("Logs", "Salons de logs et surveillance du serveur.", "📋"),
    "managers": ("Gestionnaires", "Personnes autorisées à gérer certaines parties du bot.", "🔐"),
    "security": ("Sécurité", "AutoMod, anti-spam, liens, raids et protections.", "🛡️"),
    "summary": ("Résumé", "Vérifier rapidement les réglages importants.", "📋"),
}


def _english(view) -> bool:
    return language_runtime.cached_language(view.bot, view.guild_id) == language_runtime.LANG_EN


def _avatar(bot: commands.Bot) -> str | None:
    try:
        return str(bot.user.display_avatar.url) if bot.user else None
    except Exception:
        return None


def _author(embed: discord.Embed, bot: commands.Bot) -> None:
    icon = _avatar(bot)
    if icon:
        embed.set_author(name="SentriX", icon_url=icon)
    else:
        embed.set_author(name="SentriX")


def _clean_label(value: object, fallback: str = "Option") -> str:
    text = str(value or "").strip()
    for prefix in ("● ", "○ ", "◉ ", "◈ "):
        if text.startswith(prefix):
            text = text[len(prefix):].lstrip()
    return text or fallback


def _short(value: object, *, lines: int = 3, limit: int = 420) -> str:
    content = [line.strip() for line in str(value or "").splitlines() if line.strip()]
    text = "\n".join(content[:lines])
    if len(content) > lines:
        text += f"\n+{len(content) - lines} autre{'s' if len(content) - lines > 1 else ''}"
    return text[:limit]


def _useful_field(field) -> bool:
    name = str(getattr(field, "name", "") or "").replace("\u200b", "").strip()
    value = str(getattr(field, "value", "") or "").replace("\u200b", "").strip()
    return bool(name and value and name.casefold() not in {"information", "détails", "details", "conseil", "astuce"})


def install(bot: commands.Bot) -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    from . import configuration

    configuration.SETUP_COLOR_MAIN = PURPLE_MAIN
    configuration.SETUP_COLOR_SECONDARY = PURPLE_SECONDARY
    for step in configuration.SETUP_STEPS:
        meta = STEP_META.get(step.get("key"))
        if meta:
            step["title"], step["description"], step["icon"] = meta

    base_view = configuration.SetupView
    original_build = base_view.build_embed
    original_render = base_view.render_page

    async def build_home(self) -> discord.Embed:
        guild = self._guild()
        english = _english(self)
        embed = discord.Embed(
            title="SentriX • Configuration",
            description=(
                "Choose a category below. Changes are saved only for this server."
                if english else
                "Choisis une catégorie ci-dessous. Les changements sont enregistrés uniquement pour ce serveur."
            ),
            colour=discord.Colour(PURPLE_MAIN),
        )
        _author(embed, self.bot)
        embed.set_footer(text=f"SentriX • {guild.name if guild else 'Serveur'}")
        return embed

    async def build_language(self) -> discord.Embed:
        guild = self._guild()
        english = _english(self)
        embed = discord.Embed(
            title="SentriX • Language" if english else "SentriX • Langue",
            description=(
                "Choose the language used by SentriX on this server."
                if english else
                "Choisis la langue utilisée par SentriX sur ce serveur."
            ),
            colour=discord.Colour(PURPLE_MAIN),
        )
        _author(embed, self.bot)
        embed.set_footer(text=f"SentriX • {guild.name if guild else 'Serveur'}")
        return embed

    async def build_embed(self) -> discord.Embed:
        if self.page == -1:
            return await build_home(self)
        if self.page == LANGUAGE_PAGE:
            return await build_language(self)

        source = await original_build(self)
        step = configuration.SETUP_STEPS[self.page]
        title, summary, _icon = STEP_META.get(
            step.get("key"),
            (_clean_label(step.get("title"), "Configuration"), "Modifie les réglages de cette catégorie.", "⚙️"),
        )
        if _english(self):
            title = language_runtime._english_setup_text(title) or title
            summary = language_runtime._english_setup_text(summary) or summary

        embed = discord.Embed(title=f"SentriX • {title}", description=summary, colour=discord.Colour(PURPLE_MAIN))
        _author(embed, self.bot)

        if step.get("key") in {"roles", "channels"}:
            noun = "role" if _english(self) and step["key"] == "roles" else (
                "channel" if _english(self) else ("rôle" if step["key"] == "roles" else "salon")
            )
            embed.description = f"{summary}\n" + (
                f"Select a setting, then the corresponding {noun}." if _english(self)
                else f"Sélectionne un réglage puis le {noun} correspondant."
            )
            selected = getattr(self, "picker_selected", None)
            if selected:
                conf = await self.bot.db.get_guild_config(self.guild_id)
                fields = configuration.PICKER_FIELDS[step["key"]]
                label = next((label for field, _kind, label in fields if field == selected), selected)
                embed.add_field(name="Current selection" if _english(self) else "Sélection actuelle", value=f"**{_clean_label(label)}** — {self._mention_current(selected, conf)}", inline=False)
        else:
            kept = 0
            seen: set[str] = set()
            for field in list(source.fields):
                if not _useful_field(field):
                    continue
                name = _clean_label(field.name, "Information")
                value = _short(field.value)
                signature = f"{name.casefold()}|{value.casefold()}"
                if not value or signature in seen:
                    continue
                seen.add(signature)
                embed.add_field(name=name[:72], value=value, inline=False)
                kept += 1
                if kept >= (4 if step.get("key") == "summary" else 2):
                    break

        if _english(self):
            try:
                language_runtime._translate_setup_embed(embed)
            except Exception:
                logger.debug("Traduction Setup impossible.", exc_info=True)
        state = "Unsaved changes" if _english(self) and getattr(self, "dirty", False) else (
            "Saved" if _english(self) else ("Modifications en attente" if getattr(self, "dirty", False) else "Enregistré")
        )
        embed.set_footer(text=f"SentriX • {state}")
        return embed

    def category_callback(self, selector: discord.ui.Select):
        async def callback(interaction: discord.Interaction):
            if not selector.values:
                return await interaction.response.defer()
            value = selector.values[0]
            if value == LANGUAGE_VALUE:
                self.page = LANGUAGE_PAGE
            else:
                try:
                    self.page = int(value)
                except (TypeError, ValueError):
                    return await interaction.response.send_message("Catégorie invalide.", ephemeral=True)
            self.render_page()
            await self.persist_session()
            await interaction.response.edit_message(embed=await self.build_embed(), view=self)
        return callback

    def render_home(self) -> None:
        self.clear_items()
        english = _english(self)
        options = [discord.SelectOption(
            label="Server language" if english else "Langue du serveur",
            value=LANGUAGE_VALUE,
            description="Choose SentriX language" if english else "Choisir la langue utilisée par SentriX",
            emoji="🌐",
        )]
        for index, step in enumerate(configuration.SETUP_STEPS):
            if step.get("key") == "summary":
                continue
            title, summary, icon = STEP_META.get(step.get("key"), (_clean_label(step.get("title")), "Configurer ce module.", "⚙️"))
            if english:
                title = language_runtime._english_setup_text(title) or title
                summary = language_runtime._english_setup_text(summary) or summary
            options.append(discord.SelectOption(label=title[:100], value=str(index), description=summary[:100], emoji=icon))
        selector = discord.ui.Select(
            placeholder="Choose what you want to configure…" if english else "Choisis ce que tu veux configurer…",
            options=options[:25], min_values=1, max_values=1, row=0,
            custom_id="sentrix:setup:category:canonical",
        )
        selector.callback = category_callback(self, selector)
        self.add_item(selector)
        self.add_item(configuration.SetupNavButton(
            "cancel", self.message_id,
            label="Close" if english else "Fermer",
            style=discord.ButtonStyle.secondary, row=1,
        ))

    def render_language(self) -> None:
        self.clear_items()
        english = _english(self)
        current = language_runtime.LANG_EN if english else language_runtime.LANG_FR
        fr = discord.ui.Button(label="Français", style=discord.ButtonStyle.primary if current == language_runtime.LANG_FR else discord.ButtonStyle.secondary, row=0)
        en = discord.ui.Button(label="English", style=discord.ButtonStyle.primary if current == language_runtime.LANG_EN else discord.ButtonStyle.secondary, row=0)
        home = discord.ui.Button(label="Home" if english else "Accueil", style=discord.ButtonStyle.secondary, row=1)

        async def choose(interaction: discord.Interaction, language: str):
            member = interaction.user
            allowed = bool(isinstance(member, discord.Member) and interaction.guild and (member.guild_permissions.administrator or member.guild_permissions.manage_guild or member.id == interaction.guild.owner_id))
            if not allowed:
                return await interaction.response.send_message("Permission Administrateur/Gérer le serveur requise.", ephemeral=True)
            await language_runtime.set_language(self.bot, self.guild_id, language)
            self.page = -1
            self.render_page()
            await self.persist_session()
            await interaction.response.edit_message(embed=await self.build_embed(), view=self)

        async def choose_fr(interaction: discord.Interaction):
            await choose(interaction, language_runtime.LANG_FR)
        async def choose_en(interaction: discord.Interaction):
            await choose(interaction, language_runtime.LANG_EN)
        async def go_home(interaction: discord.Interaction):
            self.page = -1
            self.render_page()
            await self.persist_session()
            await interaction.response.edit_message(embed=await self.build_embed(), view=self)

        fr.callback, en.callback, home.callback = choose_fr, choose_en, go_home
        self.add_item(fr); self.add_item(en); self.add_item(home)

    def render_page(self) -> None:
        if self.page == -1:
            render_home(self)
            return
        if self.page == LANGUAGE_PAGE:
            render_language(self)
            return
        original_render(self)
        for item in list(self.children):
            if isinstance(item, configuration.SetupNavButton) and item.action in {"prev", "next", "preview", "history", "summary"}:
                self.remove_item(item)
        for item in list(self.children):
            try:
                if isinstance(item, discord.ui.Button):
                    action = getattr(item, "action", "")
                    item.label = {"home": "Accueil", "save": "Enregistrer", "cancel": "Fermer"}.get(action, _clean_label(item.label, "Action"))
                    item.emoji = None
                elif isinstance(item, discord.ui.Select):
                    item.placeholder = str(item.placeholder or "Choisis une option…").replace("Choisissez", "Choisis").replace("Choisir", "Choisis")[:150]
                    for option in list(getattr(item, "options", ()) or ()):
                        option.label = _clean_label(option.label)
            except Exception:
                logger.debug("Composant Setup impossible à normaliser.", exc_info=True)

    base_view.build_embed = build_embed
    base_view._build_home_embed = build_home
    base_view._build_language_embed = build_language
    base_view._render_home = render_home
    base_view._render_language = render_language
    base_view.render_page = render_page
    base_view._sentrix_setup_canonical = True

    _INSTALLED = True
    bot._sentrix_setup_policy_owner = "cogs.setup_oxyde_style"
    logger.info("Setup canonique actif : une classe, un renderer, langue intégrée.")


__all__ = ["install", "STEP_META", "LANGUAGE_PAGE", "LANGUAGE_VALUE"]
