"""SentriX V116 — centre de configuration profond et hiérarchique.

Objectif : garder le rendu compact de V114 mais donner à /setup une profondeur de
configuration comparable aux grands bots Discord : Accueil -> Module -> Sous-module ->
Réglage, sans mur de texte ni longue liste de boutons.

La couche ne duplique pas les moteurs métier. Elle réutilise les pages V113/V114 et les
assistants déjà présents (sécurité, niveaux, rôles, logs, configuration) puis fournit un
point d'entrée unique, clair et cohérent.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import discord

import sentrix_setup_compact_v113 as v4
import sentrix_setup_polish_v114 as v114
from utils import embeds
from utils import sentrix_panels as panels

logger = logging.getLogger("bot.setup-v116")
_INSTALLED = False

PAGE_V116_MODULE = 116


@dataclass(frozen=True)
class SectionSpec:
    key: str
    label: str
    description: str
    action: str


@dataclass(frozen=True)
class ModuleSpec:
    key: str
    label: str
    description: str
    sections: tuple[SectionSpec, ...]


def _s(key: str, label: str, description: str, action: str) -> SectionSpec:
    return SectionSpec(key, label, description, action)


MODULES: tuple[ModuleSpec, ...] = (
    ModuleSpec("security", "Sécurité", "AutoMod, anti-raid, anti-nuke et exceptions.", (
        _s("automod", "Protections", "Activer et régler précisément les protections AutoMod.", "security"),
        _s("raid", "Anti-Raid", "Renforcer les protections contre arrivées et actions massives.", "security"),
        _s("nuke", "Anti-Nuke", "Protéger les salons, rôles, webhooks et actions critiques.", "security"),
        _s("exceptions", "Exceptions", "Choisir les rôles et salons qui doivent être ignorés.", "security"),
        _s("diagnostic", "Diagnostic", "Vérifier permissions, hiérarchie et protections manquantes.", "diagnostic"),
    )),
    ModuleSpec("moderation", "Modération", "Sanctions, staff, historique et automatisations.", (
        _s("warn", "Avertissements", "Avertissements, dossiers et raisons de sanction.", "hint:+warn"),
        _s("mute", "Timeouts", "Durées, raisons et contrôles de timeout.", "hint:+mute"),
        _s("ban", "Kick & Ban", "Sanctions fortes et historique des actions.", "hint:+ban"),
        _s("staff", "Rôle staff", "Choisir le rôle principal utilisé par les outils de modération.", "config:mod_role"),
        _s("history", "Historique", "Consulter les dernières modifications et actions setup.", "history"),
    )),
    ModuleSpec("members", "Membres", "Bienvenue, départ, vérification, autorôles et règlement.", (
        _s("welcome", "Bienvenue", "Salon et paramètres d'accueil des nouveaux membres.", "config:welcome_channel"),
        _s("goodbye", "Départ", "Salon et comportement lors du départ d'un membre.", "config:goodbye_channel"),
        _s("verify", "Vérification", "Rôle vérifié, salon et parcours de vérification.", "verification"),
        _s("autorole", "Autorôle", "Rôle distribué automatiquement à l'arrivée.", "config:autorole"),
        _s("rules", "Règlement", "Parcours règlement/validation et panneau dédié.", "hint:+verify-setup"),
    )),
    ModuleSpec("logs", "Logs", "Journalisation granulaire du serveur.", (
        _s("general", "Général", "Salon principal et création/réparation des logs.", "logs"),
        _s("messages", "Messages", "Suppressions, modifications et événements de messages.", "logs"),
        _s("moderation", "Modération", "Warn, mute, kick, ban et actions staff.", "logs"),
        _s("members", "Membres", "Arrivées, départs et changements de profil.", "logs"),
        _s("voice", "Vocal", "Connexions, déplacements et déconnexions vocales.", "logs"),
        _s("roles", "Rôles", "Création, suppression et modifications de rôles.", "logs"),
        _s("channels", "Salons", "Création, suppression et modifications de salons.", "logs"),
        _s("tickets", "Tickets", "Ouvertures, fermetures et actions liées aux tickets.", "logs"),
    )),
    ModuleSpec("levels", "Niveaux", "XP, vocal, paliers, annonces et exclusions.", (
        _s("xp", "XP texte", "Cooldown, XP min/max, salons et rôles exclus.", "levels-config"),
        _s("voice", "Vocal", "Salons vocaux ignorés et suivi du temps vocal.", "levels-config"),
        _s("rewards", "Récompenses", "Paliers de niveaux et rôles attribués.", "levels-config"),
        _s("announce", "Annonces", "Activer et choisir le salon des montées de niveau.", "levels-config"),
        _s("appearance", "Profil & affichage", "Couleur, titre, footer et champs visibles.", "levels-config"),
    )),
    ModuleSpec("economy", "Économie", "Banque, monnaie, boutique, inventaire et réputation.", (
        _s("currency", "Monnaie", "Emoji, affichage et paramètres économiques liés aux profils.", "levels-config"),
        _s("bank", "Banque", "Portefeuille et banque des membres.", "hint:+banque"),
        _s("shop", "Boutique", "Objets, rôles et achats disponibles.", "hint:+shop"),
        _s("inventory", "Inventaire", "Objets possédés et gestion des récompenses.", "hint:+inventory"),
        _s("reputation", "Réputation", "Cooldown et affichage de la réputation.", "levels-config"),
    )),
    ModuleSpec("tickets", "Tickets", "Panels, formulaires, permissions et logs.", (
        _s("panels", "Panels", "Créer et gérer les panneaux de tickets.", "hint:+ticketsetup"),
        _s("forms", "Formulaires", "Questions, types et données demandées à l'ouverture.", "hint:+ticketsetup"),
        _s("staff", "Prise en charge", "Rôles staff, accès et comportement de claim.", "hint:+ticketsetup"),
        _s("logs", "Logs tickets", "Salon de suivi et historique des tickets.", "hint:+ticketsetup"),
    )),
    ModuleSpec("roles", "Rôles", "Staff, autorôles, vérification et rôles de niveau.", (
        _s("staff", "Staff", "Rôle modérateur principal utilisé par SentriX.", "config:mod_role"),
        _s("autorole", "Autorôle", "Rôle distribué automatiquement à l'arrivée.", "config:autorole"),
        _s("verification", "Vérification", "Rôle reçu après validation.", "verification"),
        _s("levels", "Rôles de niveau", "Paliers et rôles automatiques liés aux niveaux.", "levels-config"),
        _s("reaction", "Rôles réactions", "Panels et rôles auto-attribuables.", "hint:+rolepanel"),
    )),
    ModuleSpec("verification", "Vérification", "CAPTCHA, rôle, salon et panneau de validation.", (
        _s("role", "Rôle vérifié", "Choisir le rôle attribué après validation.", "verification"),
        _s("channel", "Salon", "Choisir où publier le panneau de vérification.", "hint:+verify-setup"),
        _s("captcha", "CAPTCHA", "Configurer le parcours et les contrôles de validation.", "hint:+verify-setup"),
        _s("panel", "Panneau", "Publier ou mettre à jour le panneau de vérification.", "hint:+verify-panel"),
    )),
    ModuleSpec("notifications", "Notifications", "YouTube, TikTok, Twitch et autres sources.", (
        _s("list", "Sources", "Voir les notifications actuellement configurées.", "hint:+notifs-list"),
        _s("youtube", "YouTube", "Configurer une source YouTube et sa destination.", "hint:+notifs-ping"),
        _s("tiktok", "TikTok", "Configurer une source TikTok et sa destination.", "hint:+notifs-ping"),
        _s("twitch", "Twitch", "Configurer une source Twitch et sa destination.", "hint:+notifs-ping"),
    )),
    ModuleSpec("ai", "Intelligence artificielle", "Accès, génération, modération et limites IA.", (
        _s("access", "Accès", "Contrôler qui peut utiliser les fonctions IA.", "hint:+aisetup"),
        _s("text", "Réponses IA", "Réponses textuelles SentriX et comportement assistant.", "hint:+aisetup"),
        _s("images", "Images", "Génération d'images et cooldowns.", "hint:+aisetup"),
        _s("moderation", "Filtrage", "Dataset multilingue et modération contextuelle.", "hint:+aisetup"),
    )),
    ModuleSpec("suggestions", "Suggestions", "Salon de suggestions et parcours communautaire.", (
        _s("channel", "Salon", "Choisir le salon utilisé pour les suggestions.", "config:suggest_channel"),
        _s("flow", "Fonctionnement", "Configurer le flux de suggestion existant.", "hint:+suggest"),
    )),
    ModuleSpec("profile", "Profil", "Affichage membre, statistiques et réputation.", (
        _s("appearance", "Apparence", "Titre, couleur et footer des statistiques.", "levels-config"),
        _s("visibility", "Champs visibles", "Économie, vocal, messages, date et prochain rôle.", "levels-config"),
        _s("privacy", "Consultation", "Autoriser ou non la consultation des autres profils.", "levels-config"),
        _s("reputation", "Réputation", "Cooldown et présentation de la réputation.", "levels-config"),
    )),
)

MODULE_BY_KEY = {module.key: module for module in MODULES}


def module_keys() -> tuple[str, ...]:
    return tuple(module.key for module in MODULES)


def section_keys(module_key: str) -> tuple[str, ...]:
    module = MODULE_BY_KEY[module_key]
    return tuple(section.key for section in module.sections)


def _ensure_state(view) -> None:
    if not hasattr(view, "_v116_module") or view._v116_module not in MODULE_BY_KEY:
        view._v116_module = "security"
    module = MODULE_BY_KEY[view._v116_module]
    valid = {section.key for section in module.sections}
    if not hasattr(view, "_v116_section") or view._v116_section not in valid:
        view._v116_section = module.sections[0].key


def _mention(guild: discord.Guild | None, conf: Any, key: str, *, role: bool = False) -> str:
    try:
        value = conf[key] if conf is not None else None
    except Exception:
        value = None
    if not value:
        return "Non configuré"
    obj = guild.get_role(int(value)) if role and guild else guild.get_channel(int(value)) if guild else None
    return obj.mention if obj else "Introuvable"


async def _module_status(view, module_key: str) -> str:
    guild = view._guild()
    conf = await view.bot.db.get_guild_config(view.guild_id)
    if module_key == "security":
        row = await view.bot.db.get_automod(view.guild_id)
        active = sum(1 for key in v4._CONFIG_MODULE.AUTOMOD_TOGGLE_LABELS if row and int(row[key] or 0))
        return f"{active}/{len(v4._CONFIG_MODULE.AUTOMOD_TOGGLE_LABELS)} protections actives"
    if module_key == "moderation":
        return f"Staff : {_mention(guild, conf, 'mod_role', role=True)}"
    if module_key == "members":
        return f"Bienvenue : {_mention(guild, conf, 'welcome_channel')} · Autorôle : {_mention(guild, conf, 'autorole', role=True)}"
    if module_key == "logs":
        return f"Salon principal : {_mention(guild, conf, 'log_channel')}"
    if module_key in {"levels", "economy", "profile"}:
        settings = await view.bot.db.get_stats_settings(view.guild_id)
        if module_key == "levels":
            return f"XP {settings.get('xp_min', 10)}–{settings.get('xp_max', 25)} · cooldown {settings.get('xp_cooldown', 60)}s"
        if module_key == "economy":
            return f"Monnaie {settings.get('economy_emoji', '🪙')} · réputation {int(settings.get('reputation_cooldown', 86400)) // 3600}h"
        visible = sum(1 for key in ("show_economy", "show_reputation", "show_voice", "show_messages", "show_join_date", "show_next_role") if settings.get(key, True))
        return f"{visible}/6 champs de profil visibles"
    if module_key == "roles":
        return f"Staff : {_mention(guild, conf, 'mod_role', role=True)} · Autorôle : {_mention(guild, conf, 'autorole', role=True)}"
    if module_key == "verification":
        return f"Rôle : {_mention(guild, conf, 'verify_role', role=True)}"
    if module_key == "suggestions":
        return f"Salon : {_mention(guild, conf, 'suggest_channel')}"
    if module_key == "tickets":
        try:
            row = await view.bot.db.fetchone("SELECT COUNT(*) AS n FROM ticket_panels_v2 WHERE guild_id = ?", (view.guild_id,))
            return f"{int(row['n'] if row else 0)} panel(s) configuré(s)"
        except Exception:
            return "Configuration tickets disponible"
    return "Module disponible"


async def _home_embed(view) -> discord.Embed:
    health = await v4._health_snapshot(view)
    description = (
        "Configure SentriX par module. Chaque page ne montre que ce qui concerne le réglage choisi.\n\n"
        f"Santé **{health['score']}/100** · Sécurité **{health['security_score']}/100** · "
        f"Essentiel **{health['essential_done']}/5**\n\n"
        "Choisis un module dans le menu ci-dessous."
    )
    embed = discord.Embed(title="SentriX Setup", description=description, colour=v4._score_colour(health["score"]))
    embed.set_footer(text="SentriX • Setup V116")
    return embed


async def _module_embed(view) -> discord.Embed:
    _ensure_state(view)
    module = MODULE_BY_KEY[view._v116_module]
    section = next(s for s in module.sections if s.key == view._v116_section)
    status = await _module_status(view, module.key)
    embed = discord.Embed(
        title=module.label,
        description=f"{module.description}\n\n**État actuel**\n{status}\n\n**{section.label}**\n{section.description}",
        colour=v4._CONFIG_MODULE.SETUP_COLOR_MAIN,
    )
    embed.set_footer(text=f"SentriX • Setup V116 • {module.label}")
    return embed


def _module_select_callback(view, select: discord.ui.Select):
    async def callback(interaction: discord.Interaction):
        if not select.values:
            return await interaction.response.defer()
        view._v116_module = select.values[0]
        view._v116_section = MODULE_BY_KEY[view._v116_module].sections[0].key
        view.page = PAGE_V116_MODULE
        view.render_page()
        await view.persist_session()
        await view._refresh_message(interaction)
    return callback


def _section_select_callback(view, select: discord.ui.Select):
    async def callback(interaction: discord.Interaction):
        if select.values:
            view._v116_section = select.values[0]
        view.render_page()
        await view._refresh_message(interaction)
    return callback


async def _open_levels_config(view, interaction: discord.Interaction) -> None:
    levels = view.bot.get_cog("Levels")
    if levels is None:
        return await interaction.response.send_message("Le module Niveaux n'est pas disponible.", ephemeral=True)
    try:
        from cogs.levels import StatsConfigView
        settings = await view.bot.db.get_stats_settings(view.guild_id)
        subview = StatsConfigView(levels, interaction.guild, interaction.user.id, settings)
        conf = await view.bot.db.get_guild_config(view.guild_id)
        if conf:
            try:
                subview.pending["_xp_channel_disabled"] = conf["xp_channel_disabled"] or ""
            except Exception:
                pass
            try:
                subview.pending["_level_channel"] = conf["level_channel"]
            except Exception:
                pass
        embed = subview.build_summary_embed()
        message = await panels.envoyer(interaction.response, panels.avec_composants(panels.depuis_embed(embed), subview), ephemere=True)
        subview.message = message
    except Exception:
        logger.exception("V116 : ouverture StatsConfigView impossible guild=%s", view.guild_id)
        await interaction.response.send_message("Impossible d'ouvrir la configuration des niveaux pour le moment.", ephemeral=True)


def _route_to_config(view, field: str) -> None:
    view.page = v4.PAGE_CONFIGURATION
    view._v4_expert = field in {item[0] for item in v4._EXPERT_SETTINGS}
    view.picker_selected = field


async def _run_action(view, interaction: discord.Interaction) -> None:
    _ensure_state(view)
    module = MODULE_BY_KEY[view._v116_module]
    section = next(s for s in module.sections if s.key == view._v116_section)
    action = section.action

    if action == "security":
        view.page = v4.PAGE_SECURITY
    elif action == "logs":
        view.page = v4.PAGE_LOGS
    elif action == "diagnostic":
        view.page = v4.PAGE_SUMMARY
    elif action == "levels-config":
        return await _open_levels_config(view, interaction)
    elif action == "verification":
        _route_to_config(view, "verify_role")
    elif action == "history":
        return await v4._show_history(view, interaction)
    elif action.startswith("config:"):
        _route_to_config(view, action.split(":", 1)[1])
    elif action.startswith("hint:"):
        command = action.split(":", 1)[1]
        return await interaction.response.send_message(
            f"Ce réglage utilise déjà un assistant dédié. Lance **`{command}`** ; il reste séparé pour éviter de dupliquer son moteur dans `/setup`.",
            ephemeral=True,
        )
    else:
        return await interaction.response.defer()

    view.render_page()
    await view.persist_session()
    await view._refresh_message(interaction)


def _render_home(view) -> None:
    view.clear_items()
    select = discord.ui.Select(
        placeholder="Choisir un module à configurer",
        options=[discord.SelectOption(label=m.label, value=m.key, description=m.description[:100]) for m in MODULES],
        row=0,
    )
    select.callback = _module_select_callback(view, select)
    view.add_item(select)

    button = v4._CONFIG_MODULE.SetupNavButton
    view.add_item(button("restart", view.message_id, label="Smart Setup", style=discord.ButtonStyle.success, row=1))
    view.add_item(button("summary", view.message_id, label="Diagnostic", style=discord.ButtonStyle.primary, row=1))
    view.add_item(button("prev", view.message_id, label="Configuration rapide", style=discord.ButtonStyle.secondary, row=1))


def _render_module(view) -> None:
    _ensure_state(view)
    view.clear_items()
    module = MODULE_BY_KEY[view._v116_module]
    select = discord.ui.Select(
        placeholder=f"{module.label} — choisir un réglage",
        options=[
            discord.SelectOption(label=s.label, value=s.key, description=s.description[:100], default=s.key == view._v116_section)
            for s in module.sections
        ],
        row=0,
    )
    select.callback = _section_select_callback(view, select)
    view.add_item(select)

    open_button = discord.ui.Button(label="Ouvrir ce réglage", style=discord.ButtonStyle.primary, row=1)
    async def open_callback(interaction: discord.Interaction):
        await _run_action(view, interaction)
    open_button.callback = open_callback
    view.add_item(open_button)

    button = v4._CONFIG_MODULE.SetupNavButton
    view.add_item(button("home", view.message_id, label="Accueil", style=discord.ButtonStyle.secondary, row=1))
    view.add_item(button("restart", view.message_id, label="Smart Setup", style=discord.ButtonStyle.success, row=1))
    view.add_item(button("summary", view.message_id, label="Diagnostic", style=discord.ButtonStyle.secondary, row=1))


async def _build_embed(view) -> discord.Embed:
    if view.page == v4.PAGE_HOME:
        return await _home_embed(view)
    if view.page == PAGE_V116_MODULE:
        return await _module_embed(view)
    return await view._sentrix_v116_previous_build_embed()


def _render_page(view) -> None:
    if view.page == v4.PAGE_HOME:
        _render_home(view)
        return
    if view.page == PAGE_V116_MODULE:
        _render_module(view)
        return
    return view._sentrix_v116_previous_render_page()


async def _handle_nav(view, interaction: discord.Interaction, action: str):
    if action == "home" and view.page == PAGE_V116_MODULE:
        view.page = v4.PAGE_HOME
        view.render_page()
        await view.persist_session()
        return await view._refresh_message(interaction)
    return await view._sentrix_v116_previous_handle_nav_action(interaction, action)


def install_for_bot(bot) -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    configuration = bot.get_cog("Configuration")
    if configuration is None:
        logger.warning("V116 non installé : cog Configuration absent.")
        return

    view_cls = type(next(iter(getattr(configuration, "active_setups", {}).values()), None))
    if view_cls is type(None):
        from cogs.configuration import SetupView as view_cls

    if getattr(view_cls, "_sentrix_v116", False):
        _INSTALLED = True
        return

    view_cls._sentrix_v116_previous_render_page = view_cls.render_page
    view_cls._sentrix_v116_previous_build_embed = view_cls.build_embed
    view_cls._sentrix_v116_previous_handle_nav_action = view_cls.handle_nav_action
    view_cls.render_page = _render_page
    view_cls.build_embed = _build_embed
    view_cls.handle_nav_action = _handle_nav
    view_cls._sentrix_v116 = True

    for active in list(getattr(configuration, "active_setups", {}).values()):
        try:
            _ensure_state(active)
            active.render_page()
        except Exception:
            logger.exception("V116 : migration d'une session active impossible.")

    _INSTALLED = True
    logger.info("SentriX Setup V116 actif : centre profond Accueil -> Module -> Réglage, moteurs existants réutilisés.")


__all__ = ["MODULES", "MODULE_BY_KEY", "PAGE_V116_MODULE", "module_keys", "section_keys", "install_for_bot"]
