"""SentriX V3.2 — interface Discord plus sobre et plus professionnelle.

Objectifs :
- sécuriser +ai avec un chemin de secours qui contourne les wrappers runtime défaillants ;
- réponses IA en texte natif Discord plutôt qu'en gros embed ;
- retirer les emojis décoratifs du design, des boutons et des menus ;
- rendre publiques les réponses des commandes membres qui étaient inutilement ephemeral ;
- convertir les petits embeds sans champs en texte natif, tout en gardant les vraies fiches ;
- enrichir +help avec un menu d'actions rapides inspiré des bots à panneaux interactifs.

Les réponses privées de sécurité (configuration staff, refus de permissions, interaction
avec le panneau d'un autre membre) restent volontairement privées.
"""
from __future__ import annotations

import logging
import re
import types
from dataclasses import replace
from typing import Any

import discord
from discord.ext import commands

from utils import ai_service, design_system, embeds, premium_style, stats_service
from . import community_v3, community_v31

logger = logging.getLogger("bot.community-v32")

_EMOJI_RE = re.compile(
    "["
    "\U0001F1E6-\U0001F1FF"
    "\U0001F300-\U0001FAFF"
    "\u2300-\u23FF"
    "\u2600-\u27BF"
    "\uFE0F"
    "]+",
    flags=re.UNICODE,
)
_CUSTOM_EMOJI_RE = re.compile(r"<a?:[A-Za-z0-9_]{2,32}:[0-9]{15,22}>")
_SPACE_RE = re.compile(r"[ \t]{2,}")

# Une réponse de ces commandes peut être rendue publiquement sans exposer de réglage staff.
# Les commandes de signalement / configuration restent exclues volontairement.
PRIVATE_PUBLIC_EXCEPTIONS = {
    "report-bug",
    "suggest",
    "feedback",
}

KEEP_RICH_COMMANDS = {
    "help",
    "avatar",
    "info",
    "userinfo",
    "channelinfo",
    "profile",
    "stats",
    "level",
    "leaderboard-levels",
    "economyleaderboard",
    "repleaderboard",
    "shop",
    "inventory",
    "ticket",
    "bot-status",
    "server-growth",
    "command-stats",
    "botinfo",
}


def strip_decorative_emoji(value: Any) -> str:
    """Retire uniquement les pictogrammes décoratifs des textes générés par SentriX."""
    text = str(value or "")
    text = _CUSTOM_EMOJI_RE.sub("", text)
    text = _EMOJI_RE.sub("", text)
    text = text.replace("\u200d", "")
    text = _SPACE_RE.sub(" ", text)
    text = re.sub(r"(?m)^[ \t]+", "", text)
    return text.strip()


def _root_name(ctx: commands.Context) -> str:
    command = getattr(ctx, "command", None)
    if command is None:
        return ""
    root = getattr(command, "root_parent", None) or command
    return str(getattr(root, "name", "") or "").casefold()


def _is_public_root(root: str) -> bool:
    if not root or root in PRIVATE_PUBLIC_EXCEPTIONS:
        return False
    try:
        import main
        return root in main.PUBLIC_COMMANDS
    except Exception:
        return root in {
            "help", "ping", "profile", "stats", "level", "balance", "economy",
            "daily", "weekly", "work", "shop", "inventory", "ai", "sentrix",
            "summarize", "explain", "rewrite", "ticket", "botinfo",
        }


def _embed_has_media(embed: discord.Embed) -> bool:
    image = getattr(embed, "image", None)
    thumbnail = getattr(embed, "thumbnail", None)
    return bool(
        (image and getattr(image, "url", None))
        or (thumbnail and getattr(thumbnail, "url", None))
    )


def _simple_embed(embed: discord.Embed | None, *, has_view: bool, root: str) -> bool:
    if not isinstance(embed, discord.Embed):
        return False
    if root in KEEP_RICH_COMMANDS or has_view:
        return False
    if embed.fields or _embed_has_media(embed):
        return False
    description = str(embed.description or "").strip()
    return bool(description) and len(description) <= 3500


def simple_embed_text(embed: discord.Embed) -> str:
    """Transforme un petit embed d'état en texte Discord natif."""
    title = strip_decorative_emoji(embed.title or "")
    description = strip_decorative_emoji(embed.description or "")
    generic = (
        not title
        or title.casefold().startswith("sentrix /")
        or title.casefold() in {
            "information", "action terminée", "action terminee", "action impossible",
            "à vérifier", "a verifier", "vérification nécessaire", "verification necessaire",
            "erreur", "succès", "succes", "avertissement",
        }
    )
    if generic:
        return description
    return f"**{title}**\n{description}".strip()


def _clean_embed(embed: discord.Embed) -> discord.Embed:
    if embed.title:
        embed.title = strip_decorative_emoji(embed.title)[:256] or "SentriX"
    footer = getattr(embed, "footer", None)
    if footer and getattr(footer, "text", None):
        icon = getattr(footer, "icon_url", None)
        text = strip_decorative_emoji(footer.text)[:2048] or "SentriX"
        if icon:
            embed.set_footer(text=text, icon_url=icon)
        else:
            embed.set_footer(text=text)
    for index, field in enumerate(list(embed.fields)):
        name = strip_decorative_emoji(field.name)[:256] or "Information"
        embed.set_field_at(index, name=name, value=field.value, inline=field.inline)
    return embed


def _clean_component(component) -> None:
    if isinstance(component, discord.ui.Button):
        component.emoji = None
        if component.label:
            component.label = strip_decorative_emoji(component.label)[:80] or "Action"
    elif isinstance(component, discord.ui.Select):
        if component.placeholder:
            component.placeholder = strip_decorative_emoji(component.placeholder)[:150]
        for option in component.options:
            option.emoji = None
            option.label = strip_decorative_emoji(option.label)[:100] or "Option"
            if option.description:
                option.description = strip_decorative_emoji(option.description)[:100]


def _install_global_visual_style() -> None:
    if getattr(premium_style, "_sentrix_v32_clean", False):
        return

    original_style_embed = premium_style.style_embed
    original_style_view = premium_style.style_view

    def style_embed_clean(*args, **kwargs):
        embed = original_style_embed(*args, **kwargs)
        return _clean_embed(embed) if isinstance(embed, discord.Embed) else embed

    def style_view_clean(view):
        view = original_style_view(view)
        if view is not None:
            for child in getattr(view, "children", []):
                _clean_component(child)
        return view

    premium_style.style_embed = style_embed_clean
    premium_style.style_view = style_view_clean

    # Le système de design historique utilisait encore des emojis comme identifiant de
    # catégorie et comme barre de progression. V3.2 passe sur une esthétique typographique.
    for style in design_system.CATEGORY_STYLES.values():
        style["emoji"] = ""
    design_system.DEFAULT_DESIGN_SETTINGS["progress_filled"] = "■"
    design_system.DEFAULT_DESIGN_SETTINGS["progress_empty"] = "□"

    original_create_embed = design_system.create_embed

    def create_embed_clean(*, title: str, description=None, colour=design_system.COLORS.primary,
                           user=None, thumbnail=None, footer=None):
        return _clean_embed(original_create_embed(
            title=strip_decorative_emoji(title),
            description=strip_decorative_emoji(description) if description else description,
            colour=colour,
            user=user,
            thumbnail=thumbnail,
            footer=strip_decorative_emoji(footer) if footer else footer,
        ))

    design_system.create_embed = create_embed_clean

    # Les helpers standards ne doivent plus réinjecter de pictogrammes dans les descriptions.
    original_base = embeds._base

    def base_clean(title, description, color, *, category=None, kind=None):
        return _clean_embed(original_base(
            strip_decorative_emoji(title),
            strip_decorative_emoji(description) if description else description,
            color,
            category=category,
            kind=kind,
        ))

    embeds._base = base_clean
    premium_style._sentrix_v32_clean = True


def _install_context_send_policy() -> None:
    """Rend les commandes membres publiques et aplatit les petits embeds en texte."""
    current = commands.Context.send
    if getattr(current, "_sentrix_v32_send_policy", False):
        return

    async def professional_send(self: commands.Context, *args, **kwargs):
        root = _root_name(self)
        is_public = _is_public_root(root)

        # Les commandes publiques ne doivent pas donner l'impression d'être secrètes.
        # Les vrais panneaux staff et les refus d'interaction restent ephemeral car ils
        # ne passent pas par cette liste.
        if is_public and kwargs.get("ephemeral") is True:
            kwargs["ephemeral"] = False

        embed = kwargs.get("embed")
        if is_public and _simple_embed(embed, has_view=kwargs.get("view") is not None, root=root):
            text = simple_embed_text(embed)
            if text:
                kwargs.pop("embed", None)
                if args:
                    mutable = list(args)
                    if not mutable[0]:
                        mutable[0] = text
                    else:
                        mutable[0] = f"{mutable[0]}\n{text}"
                    args = tuple(mutable)
                else:
                    existing = kwargs.get("content")
                    kwargs["content"] = f"{existing}\n{text}" if existing else text

        return await current(self, *args, **kwargs)

    professional_send._sentrix_v32_send_policy = True
    professional_send._sentrix_original = current
    commands.Context.send = professional_send


def _install_ai_instructions(ai_cog) -> None:
    current = ai_cog._build_system_instructions
    if getattr(current, "_sentrix_v32_no_emoji", False):
        return

    async def build_clean(this, user_id: int | None, author_name: str | None = None):
        instructions = await current(user_id, author_name)
        return instructions + (
            "\n\nStyle Discord SentriX : n'utilise aucun emoji, aucun pictogramme décoratif "
            "et évite les introductions inutiles. Réponds comme un assistant professionnel, "
            "direct et naturel."
        )

    build_clean._sentrix_v32_no_emoji = True
    ai_cog._build_system_instructions = types.MethodType(build_clean, ai_cog)


async def _direct_ai_fallback(bot: commands.Bot, question: str, *, guild_id: int | None,
                              channel_id: int | None, user_id: int, forced_advanced: bool) -> dict:
    """Chemin indépendant des wrappers runtime, utilisé uniquement après une exception."""
    model_key = ai_service.pick_model(question, forced_advanced=forced_advanced)
    effort = ai_service.pick_reasoning_effort(model_key, "medium")
    instructions = ai_service.SYSTEM_PROMPT + (
        "\n\nN'utilise aucun emoji. Réponds de manière professionnelle, concise et directement utile."
    )
    try:
        instructions += await community_v3._server_context(bot, guild_id, channel_id)
    except Exception:
        pass

    generated = await ai_service.generate(
        question,
        model_key=model_key,
        reasoning_effort=effort,
        instructions=instructions,
        guild_id=guild_id,
        channel_id=channel_id,
        user_id=user_id,
        command="ai-v32-fallback",
        web_search=ai_service.needs_web_search(question),
    )
    if not generated.ok:
        return {"ok": False, "error": ai_service.error_message(generated.error)}
    if guild_id:
        try:
            tokens = ai_service.estimate_tokens(question) + ai_service.estimate_tokens(generated.text)
            await ai_service.record_usage(bot, guild_id, user_id, tokens_estimate=tokens)
        except Exception:
            pass
    return {"ok": True, "text": generated.text, "model_key": generated.model_key or model_key}


def _clean_ai_view(view: discord.ui.View | None) -> discord.ui.View | None:
    if view is None:
        return None
    for child in getattr(view, "children", []):
        _clean_component(child)
    return view


def _install_ai_recovery(bot: commands.Bot) -> None:
    ai_cog = bot.get_cog("Ai")
    if ai_cog is None:
        return
    _install_ai_instructions(ai_cog)
    if getattr(ai_cog, "_sentrix_v32_ai_handler", False):
        return

    async def professional_ai(this, ctx: commands.Context, question: str, *, forced_advanced: bool = False):
        guild_id = ctx.guild.id if ctx.guild else None
        channel_id = ctx.channel.id

        if guild_id:
            settings = await ai_service.get_settings(bot, guild_id)
            if not ai_service.is_channel_allowed(settings, channel_id):
                return await ctx.send("L'IA n'est pas autorisée dans ce salon sur ce serveur.")
            role_ids = [role.id for role in getattr(ctx.author, "roles", [])]
            if not ai_service.is_role_allowed(settings, role_ids):
                return await ctx.send("Tu n'as pas le rôle nécessaire pour utiliser l'IA sur ce serveur.")

        thinking = None
        if ctx.interaction:
            await ctx.defer()
        else:
            thinking = await ctx.send("SentriX réfléchit…")

        command = getattr(ctx, "command", None)
        command_name = command.qualified_name if command else "ai"
        try:
            async with ctx.typing():
                result = await this._prepare_and_generate(
                    guild_id=guild_id,
                    channel_id=channel_id,
                    user_id=ctx.author.id,
                    author_name=getattr(ctx.author, "display_name", str(ctx.author)),
                    question=question,
                    forced_advanced=forced_advanced,
                    command=command_name,
                )
        except Exception:
            logger.exception("V3.2 : pipeline +ai principal en erreur, activation du fallback direct.")
            try:
                result = await _direct_ai_fallback(
                    bot,
                    question,
                    guild_id=guild_id,
                    channel_id=channel_id,
                    user_id=ctx.author.id,
                    forced_advanced=forced_advanced,
                )
            except Exception:
                logger.exception("V3.2 : fallback direct +ai en erreur.")
                result = {"ok": False, "error": "Le service IA ne répond pas correctement pour le moment. Réessaie dans quelques instants."}

        if not result.get("ok"):
            message = strip_decorative_emoji(result.get("error") or "L'IA est momentanément indisponible.")
            if thinking is not None:
                try:
                    return await thinking.edit(content=message, embed=None, view=None)
                except discord.HTTPException:
                    pass
            return await ctx.send(message)

        answer = strip_decorative_emoji(result.get("text") or "Aucune réponse générée.")
        model_key = result.get("model_key") or ai_service.MODEL_TERRA
        chunks = ai_service.split_for_discord(answer, limit=1900)
        if not chunks:
            chunks = ["Aucune réponse générée."]

        try:
            from . import ai as ai_module
            view = ai_module.AiResponseView(
                this,
                author_id=ctx.author.id,
                guild_id=guild_id,
                channel_id=channel_id,
                question=question,
                model_key=model_key,
            )
            _clean_ai_view(view)
        except Exception:
            logger.exception("V3.2 : impossible de créer les actions rapides IA.")
            view = None

        if thinking is not None:
            try:
                await thinking.edit(content=chunks[0], embed=None, view=view)
                if view is not None:
                    view.message = thinking
            except discord.HTTPException:
                msg = await ctx.send(chunks[0], view=view)
                if view is not None:
                    view.message = msg
        else:
            msg = await ctx.send(chunks[0], view=view)
            if view is not None:
                view.message = msg

        for chunk in chunks[1:]:
            await ctx.channel.send(chunk)

    ai_cog._handle_ai_command = types.MethodType(professional_ai, ai_cog)
    ai_cog._sentrix_v32_ai_handler = True


def _install_help_cleanup(bot: commands.Bot) -> None:
    """Conserve la riche navigation de +help mais la rend sobre et plus actionnable."""
    try:
        from . import help_complete, utility
    except Exception:
        return

    if not getattr(help_complete, "_sentrix_v32_clean", False):
        help_complete.CATEGORIES = tuple(replace(category, emoji="") for category in help_complete.CATEGORIES)
        help_complete.CATEGORY_BY_KEY = {category.key: category for category in help_complete.CATEGORIES}
        help_complete.SECTION_TITLES.update({
            "essential": "Essentiels",
            "community": "Communauté",
            "staff": "Administration",
        })
        for key, label in list(utility.CATEGORY_LABELS.items()):
            utility.CATEGORY_LABELS[key] = strip_decorative_emoji(label)
        utility.CATEGORY_EMOJI = {name: None for name in utility.CATEGORY_LABELS}
        help_complete._sentrix_v32_clean = True

    # Autorise tout le monde à parcourir une aide déjà affichée : aucune donnée sensible
    # n'est modifiée par ces boutons et cela évite un message privé inutile.
    async def shared_navigation(self, interaction: discord.Interaction) -> bool:
        return True

    utility.CategoryHelpView.interaction_check = shared_navigation

    if getattr(utility.HelpView, "_sentrix_v32_quick_select", False):
        return

    base_init = utility.HelpView.__init__

    class QuickActionSelect(discord.ui.Select):
        def __init__(self, active_bot: commands.Bot, prefix: str, is_staff: bool):
            options = [
                discord.SelectOption(label="Mon profil", value="profile", description="Profil, saison et progression"),
                discord.SelectOption(label="Missions du jour", value="missions", description="Voir les objectifs quotidiens"),
                discord.SelectOption(label="Classement de saison", value="season", description="Voir le classement mensuel"),
                discord.SelectOption(label="Mon économie", value="economy", description="Portefeuille et banque"),
                discord.SelectOption(label="Intelligence artificielle", value="ai", description="Comment parler à SentriX"),
                discord.SelectOption(label="Tickets", value="tickets", description="Ouvrir ou utiliser le support"),
            ]
            if is_staff:
                options.extend([
                    discord.SelectOption(label="Configuration", value="setup", description="Ouvrir le centre de configuration"),
                    discord.SelectOption(label="Sécurité", value="security", description="Accéder aux outils de protection"),
                ])
            super().__init__(placeholder="Accès rapide…", options=options, row=2)
            self.bot = active_bot
            self.prefix = prefix
            self.is_staff = is_staff

        async def callback(self, interaction: discord.Interaction):
            selected = self.values[0]
            guild = interaction.guild
            member = interaction.user
            if guild is None or not isinstance(member, discord.Member):
                return await interaction.response.send_message("Cette option doit être utilisée sur un serveur.", ephemeral=True)

            if selected in {"profile", "missions", "season"}:
                page = {"profile": "overview", "missions": "missions", "season": "season"}[selected]
                embed = await community_v31.build_profile_page(self.bot, guild, member, member.id, page)
                view = community_v31.ProfileHubView(self.bot, guild, member, member.id)
                _clean_ai_view(view)
                return await interaction.response.edit_message(content=None, embed=_clean_embed(embed), view=view)

            if selected == "economy":
                row = await self.bot.db.fetchone(
                    "SELECT cash,bank FROM economy WHERE guild_id=? AND user_id=?",
                    (guild.id, member.id),
                )
                cash = int(row["cash"] or 0) if row else 0
                bank = int(row["bank"] or 0) if row else 0
                text = (
                    f"**Économie de {member.display_name}**\n"
                    f"Portefeuille : **{stats_service.format_number(cash)}**\n"
                    f"Banque : **{stats_service.format_number(bank)}**\n"
                    f"Total : **{stats_service.format_number(cash + bank)}**\n\n"
                    f"Commandes utiles : `{self.prefix}daily`, `{self.prefix}work`, `{self.prefix}shop`, `{self.prefix}economyleaderboard`."
                )
                return await interaction.response.edit_message(content=text, embed=None, view=utility.HelpView(self.bot, self.prefix, self.is_staff))

            if selected == "ai":
                text = (
                    "**SentriX AI**\n"
                    f"Pose directement une question avec `{self.prefix}ai <question>` ou écris `SentriX ...` dans le salon.\n"
                    "Après une réponse, les boutons permettent de régénérer, simplifier, détailler ou obtenir un plan d'action."
                )
            elif selected == "tickets":
                text = f"**Tickets**\nUtilise `{self.prefix}ticket` puis choisis le type de demande dans le menu."
            elif selected == "setup":
                text = f"**Configuration**\nUtilise `{self.prefix}setup`. Le centre permet de choisir les modules, rôles, salons, logs et réglages sans mémoriser les anciennes commandes."
            else:
                text = (
                    "**Sécurité**\n"
                    f"Commence par `{self.prefix}security-check` pour l'audit ou `{self.prefix}setup` pour configurer les protections. "
                    "Les catégories de sécurité restent réservées au staff."
                )
            return await interaction.response.edit_message(content=text, embed=None, view=utility.HelpView(self.bot, self.prefix, self.is_staff))

    def help_init(self, active_bot: commands.Bot, prefix: str, is_staff: bool):
        base_init(self, active_bot, prefix, is_staff)
        try:
            self.add_item(QuickActionSelect(active_bot, prefix, is_staff))
        except ValueError:
            pass
        for child in self.children:
            _clean_component(child)

    help_init._sentrix_v32_quick_select = True
    utility.HelpView.__init__ = help_init
    utility.HelpView._sentrix_v32_quick_select = True


def _clean_profile_components() -> None:
    """Le profil reste un embed riche, mais sans pictogrammes décoratifs."""
    current_build = community_v31.build_profile_page
    if not getattr(current_build, "_sentrix_v32_clean", False):
        async def build_clean(*args, **kwargs):
            embed = await current_build(*args, **kwargs)
            return _clean_embed(embed)
        build_clean._sentrix_v32_clean = True
        community_v31.build_profile_page = build_clean

    current_init = community_v31.ProfileHubView.__init__
    if not getattr(current_init, "_sentrix_v32_clean", False):
        def profile_init(self, *args, **kwargs):
            current_init(self, *args, **kwargs)
            for child in self.children:
                _clean_component(child)
        profile_init._sentrix_v32_clean = True
        community_v31.ProfileHubView.__init__ = profile_init


def install(bot: commands.Bot) -> None:
    """Installation idempotente de la refonte UX V3.2."""
    _install_global_visual_style()
    _install_context_send_policy()
    _clean_profile_components()
    _install_help_cleanup(bot)
    _install_ai_recovery(bot)

    if getattr(bot, "_sentrix_community_v32_installed", False):
        return

    async def ready_listener():
        _install_global_visual_style()
        _install_context_send_policy()
        _clean_profile_components()
        _install_help_cleanup(bot)
        _install_ai_recovery(bot)

    bot.add_listener(ready_listener, "on_ready")
    bot._sentrix_community_v32_installed = True
    bot._sentrix_community_v32_state = {
        "ready": True,
        "features": (
            "ai_recovery",
            "plain_ai",
            "public_member_responses",
            "plain_simple_responses",
            "emoji_free_ui",
            "quick_action_menus",
        ),
    }
    logger.info("SentriX V3.2 installé : IA robuste, réponses sobres, visibilité publique et menus rapides.")
