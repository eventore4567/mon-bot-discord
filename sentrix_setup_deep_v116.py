"""SentriX V116 — centre de configuration hiérarchique.

V116 ne remplace pas les moteurs métier existants : il les organise dans /setup.
Le but est d'obtenir une navigation courte et prévisible (Accueil -> Module -> Réglage)
sans dupliquer la logique des Cogs. Les réglages que le setup sait déjà modifier restent
branchés sur leurs callbacks historiques ; les protections AutoMod ont en plus une page
individuelle avec activation directe.

Garanties :
- aucune suppression automatique de rôle/salon ;
- aucune écriture dans une clé DB inconnue ;
- les protections AutoMod ne sont modifiées qu'après clic explicite ;
- les assistants métier existants restent l'autorité quand ils sont plus complets ;
- retour et accueil sont présents sur toutes les pages V116.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable

import discord

import sentrix_setup_compact_v113 as v4
import sentrix_setup_polish_v114 as v114

logger = logging.getLogger("bot.setup-v116")
_INSTALLED = False

PAGE_V116_MODULES = 116
PAGE_V116_DETAIL = 117


@dataclass(frozen=True)
class DetailSpec:
    key: str
    label: str
    description: str
    target: str


@dataclass(frozen=True)
class ModuleSpec:
    key: str
    label: str
    description: str
    details: tuple[DetailSpec, ...]


def _d(key: str, label: str, description: str, target: str) -> DetailSpec:
    return DetailSpec(key, label, description, target)


MODULES: tuple[ModuleSpec, ...] = (
    ModuleSpec(
        "security", "Sécurité", "Protections, anti-raid et exceptions.", (
            _d("antiraid", "Anti-Raid", "Bloquer les arrivées/actions anormales.", "automod:antiraid"),
            _d("antispam", "Anti-Spam", "Limiter les messages répétés ou trop rapides.", "automod:antispam"),
            _d("antilink", "Anti-Liens", "Contrôler les liens envoyés sur le serveur.", "automod:antilink"),
            _d("antiinvite", "Anti-Invitations", "Bloquer les invitations Discord non autorisées.", "automod:antiinvite"),
            _d("antiscam", "Anti-Scam", "Détecter les messages et liens suspects.", "automod:antiscam"),
            _d("antinuke", "Anti-Nuke", "Protéger la structure contre les actions massives.", "automod:antinuke"),
            _d("precision", "Protections avancées", "Mentions, majuscules, emojis, comptes et bots.", "page:security"),
            _d("exceptions", "Exceptions", "Rôles et cas autorisés par la politique de sécurité.", "page:security"),
        ),
    ),
    ModuleSpec(
        "moderation", "Modération", "Sanctions, rôles staff et historique.", (
            _d("warn", "Avertissements", "Règles et historique des avertissements.", "hint:+warn"),
            _d("mute", "Mute / Timeout", "Durées, permissions et comportement des timeouts.", "hint:+mute"),
            _d("kickban", "Kick / Ban", "Sanctions lourdes et historique des dossiers.", "hint:+ban"),
            _d("automatic", "Sanctions automatiques", "Lier les protections à des sanctions graduées.", "page:security"),
            _d("staff", "Rôles staff", "Choisir le rôle de modération utilisé par SentriX.", "config:mod_role"),
            _d("history", "Historique", "Voir les dernières modifications et sanctions.", "action:history"),
        ),
    ),
    ModuleSpec(
        "members", "Membres", "Arrivées, départs, vérification et autorôles.", (
            _d("welcome", "Bienvenue", "Salon et message d'accueil des nouveaux membres.", "config:welcome_channel"),
            _d("goodbye", "Départ", "Salon utilisé pour les messages de départ.", "config:goodbye_channel"),
            _d("verification", "Vérification", "Rôle vérifié et parcours de validation.", "config:verify_role"),
            _d("autorole", "Autorôle", "Rôle attribué automatiquement aux membres.", "config:autorole"),
            _d("rules", "Règlement", "Parcours règlement/CAPTCHA de SentriX.", "hint:+verification-setup"),
        ),
    ),
    ModuleSpec(
        "logs", "Logs", "Journalisation globale et par type d'événement.", (
            _d("general", "Général", "Destination principale des journaux.", "config:log_channel"),
            _d("messages", "Messages", "Suppressions et modifications de messages.", "page:logs"),
            _d("moderation", "Modération", "Warn, mute, kick, ban et actions staff.", "page:logs"),
            _d("members", "Membres", "Arrivées, départs et changements de profils.", "page:logs"),
            _d("voice", "Vocal", "Connexions, déplacements et déconnexions vocales.", "page:logs"),
            _d("roles", "Rôles", "Créations, suppressions et modifications de rôles.", "page:logs"),
            _d("channels", "Salons", "Créations, suppressions et modifications de salons.", "page:logs"),
            _d("tickets", "Tickets", "Ouvertures, claims, fermetures et transcripts.", "hint:+ticketlogs"),
        ),
    ),
    ModuleSpec(
        "levels", "Niveaux", "XP, récompenses, annonces et restrictions.", (
            _d("text", "XP texte", "Progression liée aux messages.", "page:levels"),
            _d("voice", "XP vocal", "Progression liée à l'activité vocale.", "page:levels"),
            _d("cooldown", "Cooldown", "Fréquence de gain d'expérience.", "page:levels"),
            _d("multipliers", "Multiplicateurs", "Bonus par rôle, salon ou événement.", "page:levels"),
            _d("rewards", "Récompenses", "Rôles attribués à certains niveaux.", "page:levels"),
            _d("announcements", "Annonces", "Salon des annonces de montée de niveau.", "config:level_channel"),
            _d("restrictions", "Restrictions", "Limiter les gains selon rôles ou salons.", "page:levels"),
        ),
    ),
    ModuleSpec(
        "economy", "Économie", "Monnaie, banque, boutique et récompenses.", (
            _d("currency", "Monnaie", "Solde, transferts et gains des membres.", "hint:+balance"),
            _d("bank", "Banque", "Dépôts, retraits et épargne.", "hint:+bank"),
            _d("shop", "Boutique", "Articles, rôles et achats.", "hint:+shop"),
            _d("rewards", "Récompenses", "Récompenses économiques et staff.", "hint:+rewards"),
            _d("limits", "Limites", "Contrôles anti-abus et plafonds.", "hint:+economy"),
        ),
    ),
    ModuleSpec(
        "tickets", "Tickets", "Panels, types, formulaires et équipe support.", (
            _d("panels", "Panels", "Créer, modifier et publier les panels.", "hint:+ticketsetup"),
            _d("types", "Types", "Catégories, rôles staff et formats de tickets.", "hint:+tickettype"),
            _d("forms", "Formulaires", "Questions demandées à l'ouverture.", "hint:+ticketform"),
            _d("staff", "Boutons staff", "Claim, transfert, note, fermeture et permissions.", "hint:+ticketconfig"),
            _d("automation", "Automatisation", "Limites, fermeture automatique et transcripts.", "hint:+ticketconfig"),
        ),
    ),
    ModuleSpec(
        "roles", "Rôles", "Autorôles, rôles de niveau et panels.", (
            _d("staff", "Rôle staff", "Rôle de modération principal.", "config:mod_role"),
            _d("autorole", "Autorôle", "Rôle donné automatiquement à l'arrivée.", "config:autorole"),
            _d("levels", "Rôles de niveau", "Récompenses de progression.", "page:levels"),
            _d("panels", "Panels de rôles", "Rôles sélectionnables par les membres.", "page:roles"),
            _d("notifications", "Rôles notifications", "Rôles opt-in pour les annonces.", "hint:+notifs-list"),
        ),
    ),
    ModuleSpec(
        "notifications", "Notifications", "YouTube, TikTok, Twitch et annonces.", (
            _d("youtube", "YouTube", "Notifications de nouvelles vidéos.", "hint:+notifs-list"),
            _d("tiktok", "TikTok", "Notifications de nouvelles publications.", "hint:+notifs-list"),
            _d("twitch", "Twitch", "Alertes de live et changements d'état.", "hint:+notifs-list"),
            _d("announcements", "Annonces", "Salon principal des annonces.", "config:announce_channel"),
        ),
    ),
    ModuleSpec(
        "ai", "IA", "Assistant, génération et accès IA.", (
            _d("assistant", "Assistant", "Réponses et comportement de SentriX IA.", "hint:+aisetup"),
            _d("images", "Images", "Génération d'images et limites d'usage.", "hint:+aisetup"),
            _d("permissions", "Accès", "Qui peut utiliser les fonctions IA.", "hint:+aisetup"),
            _d("moderation", "Filtre IA", "Sécurité et sujets sensibles.", "hint:+aisetup"),
        ),
    ),
    ModuleSpec(
        "suggestions", "Suggestions", "Salon et parcours des suggestions.", (
            _d("channel", "Salon", "Salon utilisé pour les suggestions.", "config:suggest_channel"),
            _d("votes", "Votes", "Réactions et décisions communautaires.", "hint:+suggestion"),
            _d("staff", "Décisions staff", "Acceptation, refus et suivi.", "hint:+suggestion"),
        ),
    ),
    ModuleSpec(
        "profile", "Profil", "Profil membre, statistiques et visibilité.", (
            _d("identity", "Identité", "Informations affichées sur le profil.", "hint:+profile"),
            _d("levels", "Niveau", "XP, rang et progression affichés.", "page:levels"),
            _d("economy", "Économie", "Solde et informations économiques.", "hint:+balance"),
            _d("stats", "Statistiques", "Messages et activité du membre.", "hint:+profile"),
        ),
    ),
    ModuleSpec(
        "smart", "Smart Setup", "Analyse et configuration automatique sûre.", (
            _d("automatic", "Configuration automatique", "Analyser puis appliquer un plan sûr.", "page:auto"),
            _d("diagnostic", "Diagnostic", "Contrôler la santé du serveur.", "page:summary"),
            _d("history", "Historique", "Voir les dernières modifications.", "action:history"),
            _d("snapshot", "Snapshot", "Créer une sauvegarde avant modification.", "action:snapshot"),
        ),
    ),
)

MODULE_BY_KEY = {module.key: module for module in MODULES}
AUTOMOD_FIELDS = frozenset({
    "antispam", "antilink", "antiinvite", "antimention", "anticaps", "antiemoji",
    "antiraid", "antibot", "antiaccount", "antiscam", "antinuke",
})
CONFIG_TARGETS = {
    "mod_role", "log_channel", "welcome_channel", "announce_channel", "autorole",
    "verify_role", "goodbye_channel", "suggest_channel", "giveaway_channel", "level_channel",
}


def _ensure_state(view) -> None:
    if not hasattr(view, "_v116_module"):
        view._v116_module = None
    if not hasattr(view, "_v116_detail"):
        view._v116_detail = None


def _module(key: str | None) -> ModuleSpec | None:
    return MODULE_BY_KEY.get(str(key or ""))


def _detail(module: ModuleSpec | None, key: str | None) -> DetailSpec | None:
    if module is None:
        return None
    return next((item for item in module.details if item.key == key), None)


def _find_command(bot, raw: str) -> bool:
    name = str(raw or "").strip().lstrip("+/")
    if not name:
        return False
    root = name.split()[0]
    return bot.get_command(root) is not None


async def _module_status(view, module: ModuleSpec) -> str:
    if module.key == "security":
        row = await view.bot.db.get_automod(view.guild_id)
        active = sum(1 for key in AUTOMOD_FIELDS if bool((row or {}).get(key, 0))) if row else 0
        return f"{active}/{len(AUTOMOD_FIELDS)} protections actives"
    if module.key == "tickets":
        try:
            row = await view.bot.db.fetchone(
                "SELECT COUNT(*) AS n FROM ticket_panels_v2 WHERE guild_id = ?", (view.guild_id,)
            )
            return f"{int(row['n'] if row else 0)} panel(s)"
        except Exception:
            return "Disponible"
    if module.key in {"members", "logs", "levels", "roles", "notifications", "suggestions"}:
        conf = await view.bot.db.get_guild_config(view.guild_id)
        data = dict(conf) if conf else {}
        keys = {
            "members": ("welcome_channel", "goodbye_channel", "autorole", "verify_role"),
            "logs": ("log_channel",),
            "levels": ("level_channel",),
            "roles": ("mod_role", "autorole"),
            "notifications": ("announce_channel",),
            "suggestions": ("suggest_channel",),
        }[module.key]
        configured = sum(1 for key in keys if data.get(key))
        return f"{configured}/{len(keys)} réglage(s) principal(aux)"
    available = sum(1 for item in module.details if item.target.startswith("page:") or item.target.startswith("config:") or item.target.startswith("action:") or (item.target.startswith("hint:") and _find_command(view.bot, item.target[5:])))
    return f"{available}/{len(module.details)} outils disponibles"


async def _modules_embed(view) -> discord.Embed:
    _ensure_state(view)
    if view._v116_module:
        module = _module(view._v116_module)
        if module is not None:
            status = await _module_status(view, module)
            lines = [f"**{item.label}** — {item.description}" for item in module.details[:7]]
            if len(module.details) > 7:
                lines.append(f"+{len(module.details) - 7} autre(s) réglage(s)")
            return discord.Embed(
                title=module.label,
                description=(f"{module.description}\n**État** · {status}\n\n" + "\n".join(lines))[:900],
                colour=v4._CONFIG_MODULE.SETUP_COLOR_MAIN,
            ).set_footer(text="SentriX • Setup • Module")

    lines = []
    for module in MODULES:
        status = await _module_status(view, module)
        lines.append(f"**{module.label}** · {status}")
    return discord.Embed(
        title="Centre de configuration",
        description=("Choisis un module. Chaque réglage s'ouvre sur sa propre page.\n\n" + "\n".join(lines))[:1200],
        colour=v4._CONFIG_MODULE.SETUP_COLOR_MAIN,
    ).set_footer(text="SentriX • Setup • Modules")


async def _detail_embed(view) -> discord.Embed:
    _ensure_state(view)
    module = _module(view._v116_module)
    detail = _detail(module, view._v116_detail)
    if module is None or detail is None:
        return discord.Embed(
            title="Réglage introuvable",
            description="Retourne au centre de configuration.",
            colour=v4._CONFIG_MODULE.SETUP_COLOR_MAIN,
        )

    status = "Prêt à configurer"
    target = detail.target
    if target.startswith("automod:"):
        field = target.split(":", 1)[1]
        row = await view.bot.db.get_automod(view.guild_id)
        enabled = bool((row or {}).get(field, 0)) if row else False
        status = "Activé" if enabled else "Désactivé"
    elif target.startswith("config:"):
        field = target.split(":", 1)[1]
        conf = await view.bot.db.get_guild_config(view.guild_id)
        status = v4._mention(view, field, conf)
    elif target.startswith("hint:"):
        command = target.split(":", 1)[1]
        status = "Assistant disponible" if _find_command(view.bot, command) else "Module chargé, assistant à vérifier"
    elif target == "page:auto":
        status = "Analyse, aperçu, snapshot et application sûre"
    elif target == "page:summary":
        status = "Diagnostic complet du serveur"

    return discord.Embed(
        title=f"{module.label} • {detail.label}",
        description=(
            f"{detail.description}\n\n"
            f"**État actuel**\n{status}\n\n"
            "Modifie uniquement ce réglage, puis reviens au module."
        )[:700],
        colour=v4._CONFIG_MODULE.SETUP_COLOR_MAIN,
    ).set_footer(text="SentriX • Setup • Réglage")


def _home_button(view, *, row: int = 4) -> discord.ui.Button:
    button = discord.ui.Button(label="Accueil", style=discord.ButtonStyle.secondary, row=row)
    async def callback(interaction: discord.Interaction):
        view.page = v4.PAGE_HOME
        view._v116_module = None
        view._v116_detail = None
        view.render_page()
        await view.persist_session()
        await view._refresh_message(interaction)
    button.callback = callback
    return button


def _back_modules_button(view, *, row: int = 4) -> discord.ui.Button:
    button = discord.ui.Button(label="Retour", style=discord.ButtonStyle.secondary, row=row)
    async def callback(interaction: discord.Interaction):
        view.page = PAGE_V116_MODULES
        view._v116_detail = None
        view.render_page()
        await view._refresh_message(interaction)
    button.callback = callback
    return button


def _module_select_callback(view, select: discord.ui.Select):
    async def callback(interaction: discord.Interaction):
        if select.values:
            view._v116_module = select.values[0]
            view._v116_detail = None
        view.page = PAGE_V116_MODULES
        view.render_page()
        await view._refresh_message(interaction)
    return callback


def _detail_select_callback(view, select: discord.ui.Select):
    async def callback(interaction: discord.Interaction):
        if select.values:
            view._v116_detail = select.values[0]
            view.page = PAGE_V116_DETAIL
        view.render_page()
        await view._refresh_message(interaction)
    return callback


async def _toggle_automod(view, interaction: discord.Interaction, field: str) -> None:
    if field not in AUTOMOD_FIELDS:
        return await interaction.response.send_message("Protection inconnue.", ephemeral=True)
    row = await view.bot.db.get_automod(view.guild_id)
    old = int((row or {}).get(field, 0) or 0) if row else 0
    new = 0 if old else 1
    await view.bot.db.set_automod(view.guild_id, field, new)
    automod = view.bot.get_cog("Automod")
    if automod is not None:
        getattr(automod, "automod_cache", {}).pop(view.guild_id, None)
    view.security_choices[field] = new
    view.security_touched = True
    try:
        await view.bot.db.log_setup_history(
            view.guild_id, interaction.user.id, "Sécurité", f"{field} {'activé' if new else 'désactivé'}",
            old_value=str(old), new_value=str(new),
        )
    except Exception:
        logger.exception("V116 : historique AutoMod impossible guild=%s field=%s", view.guild_id, field)
    v4._invalidate_health(view)
    view.render_page()
    await view._refresh_message(interaction)


def _config_selector(view, field: str, row: int = 1):
    role_fields = {"mod_role", "autorole", "verify_role"}
    if field in role_fields:
        select = discord.ui.RoleSelect(placeholder="Choisir un rôle", row=row)
        select.callback = view._make_picker_role_value_callback(field, select)
    else:
        select = discord.ui.ChannelSelect(
            placeholder="Choisir un salon", channel_types=[discord.ChannelType.text], row=row,
        )
        select.callback = view._make_picker_channel_value_callback(field, select)
    return select


def _route_button(view, target: str, *, row: int = 0) -> discord.ui.Button | None:
    if target.startswith("automod:"):
        field = target.split(":", 1)[1]
        button = discord.ui.Button(label="Activer / Désactiver", style=discord.ButtonStyle.primary, row=row)
        async def callback(interaction: discord.Interaction):
            await _toggle_automod(view, interaction, field)
        button.callback = callback
        return button

    page_map = {
        "page:security": v4.PAGE_SECURITY,
        "page:logs": v4.PAGE_LOGS,
        "page:levels": v4.PAGE_LEVELS,
        "page:roles": v4.PAGE_ROLES,
        "page:auto": v4.PAGE_AUTO,
        "page:summary": v4.PAGE_SUMMARY,
    }
    if target in page_map:
        button = discord.ui.Button(label="Ouvrir", style=discord.ButtonStyle.primary, row=row)
        async def callback(interaction: discord.Interaction):
            view.page = page_map[target]
            view.render_page()
            await view.persist_session()
            await view._refresh_message(interaction)
        button.callback = callback
        return button

    if target == "action:history":
        button = discord.ui.Button(label="Voir l'historique", style=discord.ButtonStyle.primary, row=row)
        async def callback(interaction: discord.Interaction):
            await v4._show_history(view, interaction)
        button.callback = callback
        return button

    if target == "action:snapshot":
        button = discord.ui.Button(label="Créer un snapshot", style=discord.ButtonStyle.primary, row=row)
        async def callback(interaction: discord.Interaction):
            ops = getattr(view.bot, "sentrix_ops", None)
            if ops is None:
                return await interaction.response.send_message("Snapshots indisponibles.", ephemeral=True)
            try:
                sid = await ops.capture_snapshot(
                    view.guild_id, interaction.user.id, label="Snapshot manuel /setup V116", source="setup-v116",
                )
                view._v4_last_snapshot = sid
                await interaction.response.send_message(f"Snapshot **#{sid}** créé.", ephemeral=True)
            except Exception:
                logger.exception("V116 : snapshot impossible guild=%s", view.guild_id)
                await interaction.response.send_message("Impossible de créer le snapshot.", ephemeral=True)
        button.callback = callback
        return button

    if target.startswith("hint:"):
        command = target.split(":", 1)[1]
        button = discord.ui.Button(label="Comment configurer", style=discord.ButtonStyle.secondary, row=row)
        async def callback(interaction: discord.Interaction):
            await interaction.response.send_message(
                f"Ce réglage utilise actuellement l'assistant métier **`{command}`**. "
                "Il reste accessible depuis ce centre sans modifier sa logique interne.",
                ephemeral=True,
            )
        button.callback = callback
        return button
    return None


def _render_v116(view) -> None:
    _ensure_state(view)
    view.clear_items()
    if view.page == PAGE_V116_MODULES:
        module = _module(view._v116_module)
        if module is None:
            select = discord.ui.Select(
                placeholder="Choisir un module",
                options=[
                    discord.SelectOption(label=item.label, value=item.key, description=item.description[:100])
                    for item in MODULES[:25]
                ],
                row=0,
            )
            select.callback = _module_select_callback(view, select)
            view.add_item(select)
            view.add_item(_home_button(view, row=1))
            return

        select = discord.ui.Select(
            placeholder=f"Réglages • {module.label}"[:100],
            options=[
                discord.SelectOption(label=item.label, value=item.key, description=item.description[:100])
                for item in module.details[:25]
            ],
            row=0,
        )
        select.callback = _detail_select_callback(view, select)
        view.add_item(select)
        change = discord.ui.Button(label="Changer de module", style=discord.ButtonStyle.secondary, row=1)
        async def change_callback(interaction: discord.Interaction):
            view._v116_module = None
            view._v116_detail = None
            view.page = PAGE_V116_MODULES
            view.render_page()
            await view._refresh_message(interaction)
        change.callback = change_callback
        view.add_item(change)
        view.add_item(_home_button(view, row=1))
        return

    if view.page == PAGE_V116_DETAIL:
        module = _module(view._v116_module)
        detail = _detail(module, view._v116_detail)
        if detail is None:
            view.page = PAGE_V116_MODULES
            return _render_v116(view)
        target = detail.target
        action = _route_button(view, target, row=0)
        if action is not None:
            view.add_item(action)
        if target.startswith("config:"):
            field = target.split(":", 1)[1]
            if field in CONFIG_TARGETS:
                view.add_item(_config_selector(view, field, row=1))
                save = v4._CONFIG_MODULE.SetupNavButton(
                    "save", view.message_id, label="Enregistrer", style=discord.ButtonStyle.success, row=2,
                )
                view.add_item(save)
        view.add_item(_back_modules_button(view, row=3))
        view.add_item(_home_button(view, row=3))


def _render_page(self):
    _ensure_state(self)
    if self.page in {PAGE_V116_MODULES, PAGE_V116_DETAIL}:
        _render_v116(self)
        return
    self._sentrix_v116_original_render_page()


async def _build_embed(self) -> discord.Embed:
    _ensure_state(self)
    if self.page == PAGE_V116_MODULES:
        return await _modules_embed(self)
    if self.page == PAGE_V116_DETAIL:
        return await _detail_embed(self)
    return await self._sentrix_v116_original_build_embed()


async def _handle_nav_action(self, interaction: discord.Interaction, action: str):
    _ensure_state(self)
    # Le bouton Modules de l'accueil V114 porte historiquement l'action "preview".
    if self.page == v4.PAGE_HOME and action == "preview":
        self.page = PAGE_V116_MODULES
        self._v116_module = None
        self._v116_detail = None
        self.render_page()
        await self.persist_session()
        return await self._refresh_message(interaction)
    if action == "home" and self.page in {PAGE_V116_MODULES, PAGE_V116_DETAIL}:
        self.page = v4.PAGE_HOME
        self._v116_module = None
        self._v116_detail = None
        self.render_page()
        await self.persist_session()
        return await self._refresh_message(interaction)
    return await self._sentrix_v116_original_handle_nav_action(interaction, action)


def install_for_bot(bot) -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    configuration = bot.get_cog("Configuration")
    if configuration is None:
        logger.warning("V116 non installé : cog Configuration absent.")
        return

    from cogs import configuration as config_module
    view_cls = config_module.SetupView
    if getattr(view_cls, "_sentrix_v116", False):
        _INSTALLED = True
        return

    # V114 doit déjà être installé par V112. Si ce n'est pas le cas, on l'installe avant.
    if not getattr(v4, "_V114_INSTALLED", False):
        v114.install_for_bot(bot)

    view_cls._sentrix_v116_original_render_page = view_cls.render_page
    view_cls._sentrix_v116_original_build_embed = view_cls.build_embed
    view_cls._sentrix_v116_original_handle_nav_action = view_cls.handle_nav_action
    view_cls.render_page = _render_page
    view_cls.build_embed = _build_embed
    view_cls.handle_nav_action = _handle_nav_action
    view_cls._sentrix_v116 = True

    for active in list(getattr(configuration, "active_setups", {}).values()):
        try:
            _ensure_state(active)
            active.render_page()
        except Exception:
            logger.exception("V116 : migration d'une session active impossible.")

    _INSTALLED = True
    logger.info("SentriX Setup V116 actif : centre hiérarchique Modules -> Réglage installé.")


__all__ = [
    "AUTOMOD_FIELDS", "CONFIG_TARGETS", "DetailSpec", "MODULES", "MODULE_BY_KEY",
    "ModuleSpec", "PAGE_V116_DETAIL", "PAGE_V116_MODULES", "install_for_bot",
]
