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
    ModuleSpec("security", "Sécurité", "AutoMod, anti-raid, anti-nuke et protections avancées.", (
        _s("automod", "Protections", "Activer et régler précisément toutes les protections AutoMod.", "security"),
        _s("raid", "Anti-Raid", "Renforcer les protections contre les arrivées et actions massives.", "security"),
        _s("nuke", "Anti-Nuke", "Protéger les salons, rôles, webhooks et actions critiques.", "security"),
        _s("vanity", "Vanity URL", "Détecter et restaurer les changements suspects du lien vanity.", "security"),
        _s("prune", "Member Prune", "Détecter les prunes massifs via le journal d'audit.", "security"),
        _s("permissions", "Permissions dangereuses", "Bloquer les élévations critiques de rôles et salons.", "security"),
        _s("join_gate", "Join Gate", "Combiner âge du compte, avatar et vitesse d'arrivée.", "security"),
        _s("risk", "Risk Score", "Combiner plusieurs signaux de risque avec décroissance temporelle.", "security"),
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
    ModuleSpec("automation", "Automatisations", "Réactions automatiques et règles de contenu par salon.", (
        _s("reactions", "Réactions automatiques", "Choisir un salon et faire réagir SentriX à tous les messages ou à un mot-clé.", "automation:reactions"),
        _s("channel_rules", "Règles de salons", "Limiter un salon aux images uniquement ou y interdire les messages des membres.", "automation:channel-rules"),
    )),
    ModuleSpec("music", "Musique", "Lecteur vocal, salon musique et panneau interactif dans le chat du vocal.", (
        _s("system", "Système musique", "Activer ou désactiver la musique et choisir le vocal qui héberge le lecteur.", "music-config"),
    )),
    ModuleSpec("members", "Membres", "Bienvenue, départ, vérification, autorôles et règlement.", (
        _s("welcome", "Bienvenue", "Salon et paramètres d'accueil des nouveaux membres.", "config:welcome_channel"),
        _s("goodbye", "Départ", "Salon et comportement lors du départ d'un membre.", "config:goodbye_channel"),
        _s("verify", "Rôle vérifié", "Choisir le rôle attribué après vérification.", "verification"),
        _s("verify_portal", "Portail de vérification", "Activer ou réparer verification et stay-muted avec leurs panneaux SentriX.", "internal:verification"),
        _s("autorole", "Autorôle", "Rôle distribué automatiquement à l'arrivée.", "config:autorole"),
        _s("rules", "Règlement", "Configurer le texte, le salon, l'image et l'acceptation versionnée des règles.", "internal:rules"),
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
    ModuleSpec("invitations", "Invitations", "Tracker d'invitations, salon public et logs techniques.", (
        _s("tracker", "Tracker public", "Afficher qui a invité chaque nouveau membre et le total d'invitations.", "internal:invitations"),
        _s("history", "Historique", "Consulter l'historique et les statistiques d'invitations.", "hint:+invite-stats"),
        _s("codes", "Codes d'invitation", "Voir et gérer les codes suivis par SentriX.", "hint:+invite-codes"),
    )),
    ModuleSpec("rules", "Règlement", "Règles du serveur, acceptation versionnée et lien avec la vérification.", (
        _s("panel", "Panneau public", "Choisir le salon, écrire les règles et publier le panneau d'acceptation.", "internal:rules"),
        _s("image", "Image", "Ajouter ou retirer l'image du règlement.", "internal:rules"),
        _s("role", "Rôle final", "Choisir le rôle reçu après le parcours de vérification complet.", "verification"),
        _s("simple_captcha", "CAPTCHA simple", "Configurer le CAPTCHA de secours utilisé si la vérification renforcée est désactivée.", "internal:rules"),
        _s("chain", "Chaînage", "Règlement d'abord, puis vérification renforcée si elle est active.", "internal:rules"),
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
        _s("channel", "Portail", "Créer ou réparer le salon de vérification.", "internal:verification"),
        _s("captcha", "Contrôles humains", "Configurer le parcours renforcé anti-automatisation.", "internal:verification"),
        _s("panel", "Panneaux", "Publier ou réparer les panneaux verification et stay-muted.", "internal:verification"),
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
    if module_key == "automation":
        try:
            from cogs import setup_v2_ui as setup_v2
            reactions = await setup_v2._automation_reaction_rows(view.bot, view.guild_id)
            rules = await setup_v2.channel_message_rules.list_rules(view.bot, guild)
            active_reactions = sum(bool(row["enabled"]) for row in reactions)
            active_rules = sum(bool(row.get("enabled")) for row in rules)
            return (
                f"Réactions : {active_reactions}/{len(reactions)} actives · "
                f"Règles de salons : {active_rules}/{len(rules)} actives"
            )
        except Exception:
            logger.exception("V116 : lecture des automatisations impossible guild=%s", view.guild_id)
            return "Automatisations disponibles"
    if module_key == "music":
        music = view.bot.get_cog("Music")
        if music is None:
            return "Module musique indisponible"
        settings = await music.get_system_settings(view.guild_id)
        channel = guild.get_channel(settings["voice_channel_id"]) if settings["voice_channel_id"] else None
        state = "activé" if settings["enabled"] else "désactivé"
        return f"Système {state} · Vocal : {channel.mention if channel else 'non configuré'}"
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
        try:
            row = await view.bot.db.fetchone(
                "SELECT enabled,verify_channel_id,trap_channel_id FROM honeypot_verification WHERE guild_id=?",
                (view.guild_id,),
            )
            active = bool(row and row["enabled"])
            verify = guild.get_channel(int(row["verify_channel_id"])) if active and row["verify_channel_id"] else None
            return f"Rôle : {_mention(guild, conf, 'verify_role', role=True)} · Portail : {verify.mention if verify else 'non actif'}"
        except Exception:
            return f"Rôle : {_mention(guild, conf, 'verify_role', role=True)}"
    if module_key == "rules":
        try:
            row = await view.bot.db.fetchone(
                "SELECT message_id,updated_at FROM dashboard_verification_panels WHERE guild_id=?",
                (view.guild_id,),
            )
            published = bool(row and row["message_id"])
            channel = _mention(guild, conf, "verification_channel")
            return f"Panneau : {'publié' if published else 'non publié'} · Salon : {channel}"
        except Exception:
            return f"Salon : {_mention(guild, conf, 'verification_channel')}"
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


async def _open_automation(view, interaction: discord.Interaction, kind: str) -> None:
    from types import SimpleNamespace
    from cogs import setup_v2_ui as setup_v2

    guild = view._guild()
    if guild is None:
        return await interaction.response.send_message("Serveur introuvable.", ephemeral=True)

    adapter = SimpleNamespace(bot=view.bot, guild=guild)

    if kind == "reactions":
        rows = await setup_v2._automation_reaction_rows(view.bot, view.guild_id)
        embed = embeds.info(
            "Choisis un salon, puis si SentriX doit réagir à tous les messages ou seulement à un mot-clé. "
            "Tu peux ajouter jusqu’à 8 emojis et gérer les règles déjà enregistrées.",
            title="Réactions automatiques",
        )
        subview = setup_v2.AutoReactionSetupView(adapter, interaction.user.id, rows)
    elif kind == "channel-rules":
        rows = await setup_v2.channel_message_rules.list_rules(view.bot, guild)
        embed = embeds.info(
            "**Images uniquement** : une vraie image doit être jointe, sans texte ni autre fichier.\n"
            "**Messages interdits** : les messages des membres sont supprimés.\n\n"
            "SentriX ne crée aucun salon et le staff disposant des permissions de gestion n’est pas bloqué.",
            title="Règles de salons",
        )
        subview = setup_v2.ChannelRuleSetupView(adapter, interaction.user.id, rows)
    else:
        return await interaction.response.send_message("Automatisation inconnue.", ephemeral=True)

    await panels.envoyer(
        interaction.response,
        panels.avec_composants(panels.depuis_embed(embed), subview),
        ephemere=True,
    )


class MusicSetupView(discord.ui.View):
    def __init__(self, bot, guild: discord.Guild, owner_id: int, settings: dict):
        super().__init__(timeout=180)
        self.bot = bot
        self.guild = guild
        self.owner_id = int(owner_id)
        self.enabled = bool(settings.get("enabled"))
        self.channel_id = settings.get("voice_channel_id")

        select = discord.ui.ChannelSelect(
            placeholder="Choisir le vocal musique",
            min_values=1,
            max_values=1,
            channel_types=[discord.ChannelType.voice],
            row=0,
        )

        async def select_cb(interaction: discord.Interaction):
            self.channel_id = select.values[0].id
            await interaction.response.send_message(
                f"Vocal sélectionné : {select.values[0].mention}. Appuyez sur Activer pour enregistrer.",
                ephemeral=True,
            )

        select.callback = select_cb
        self.add_item(select)

        activate = discord.ui.Button(label="Activer", style=discord.ButtonStyle.success, row=1)
        disable = discord.ui.Button(label="Désactiver", style=discord.ButtonStyle.danger, row=1)

        async def activate_cb(interaction: discord.Interaction):
            if not self.channel_id:
                return await interaction.response.send_message(
                    "Choisissez d'abord le vocal musique.",
                    ephemeral=True,
                )
            music = self.bot.get_cog("Music")
            if music is None:
                return await interaction.response.send_message("Module musique indisponible.", ephemeral=True)
            try:
                await music.configure_system(
                    self.guild,
                    enabled=True,
                    voice_channel_id=self.channel_id,
                    actor_id=interaction.user.id,
                )
            except ValueError as exc:
                return await interaction.response.send_message(str(exc), ephemeral=True)
            self.enabled = True
            await interaction.response.send_message(
                "Système musique activé. Le panneau apparaîtra dans le chat du vocal quand un membre le rejoint.",
                ephemeral=True,
            )

        async def disable_cb(interaction: discord.Interaction):
            music = self.bot.get_cog("Music")
            if music is None:
                return await interaction.response.send_message("Module musique indisponible.", ephemeral=True)
            await music.configure_system(
                self.guild,
                enabled=False,
                voice_channel_id=self.channel_id,
                actor_id=interaction.user.id,
            )
            self.enabled = False
            await interaction.response.send_message(
                "Système musique désactivé et SentriX a quitté le vocal.",
                ephemeral=True,
            )

        activate.callback = activate_cb
        disable.callback = disable_cb
        self.add_item(activate)
        self.add_item(disable)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("Ce menu ne vous appartient pas.", ephemeral=True)
            return False
        return True


async def _open_music_config(view, interaction: discord.Interaction) -> None:
    guild = view._guild()
    music = view.bot.get_cog("Music")
    if guild is None or music is None:
        return await interaction.response.send_message("Module musique indisponible.", ephemeral=True)
    settings = await music.get_system_settings(view.guild_id)
    channel = guild.get_channel(settings["voice_channel_id"]) if settings["voice_channel_id"] else None
    embed = embeds.info(
        (
            f"État : **{'Activé' if settings['enabled'] else 'Désactivé'}**\n"
            f"Vocal : **{channel.mention if channel else 'Non configuré'}**\n\n"
            "Quand un membre rejoint le vocal configuré, SentriX le mentionne dans le chat du vocal "
            "et affiche un petit lecteur pour choisir une musique, mettre en pause, passer ou arrêter."
        ),
        title="Système musique",
    )
    await panels.envoyer(
        interaction.response,
        panels.avec_composants(
            panels.depuis_embed(embed),
            MusicSetupView(view.bot, guild, interaction.user.id, settings),
        ),
        ephemere=True,
    )


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
    elif action.startswith("automation:"):
        return await _open_automation(view, interaction, action.split(":", 1)[1])
    elif action == "music-config":
        return await _open_music_config(view, interaction)
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
