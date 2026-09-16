"""SentriX V116 — centre de configuration hiérarchique de /setup.

Cette couche ne réécrit pas les moteurs métier déjà fiables. Elle transforme la page
Modules en véritable centre de contrôle : Accueil -> Module -> Réglage, puis ouvre soit
un réglage natif de SetupView, soit le panneau métier existant (Tickets, Niveaux, IA).

Principes :
- pages courtes, pas de mur de boutons ;
- état actuel visible avant toute action ;
- aucun rôle/salon supprimé automatiquement ;
- aucune clé DB inconnue ;
- les réglages sensibles restent derrière leurs validations existantes ;
- après redémarrage, une sous-page V116 revient proprement au centre Modules plutôt que
  de restaurer un numéro de page inconnu par l'ancien assistant.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import discord

import sentrix_setup_compact_v113 as v4
import sentrix_setup_polish_v114 as v114
from utils import embeds
from utils import sentrix_panels as panels

logger = logging.getLogger("bot.setup-v116")
_INSTALLED = False

# Le centre V116 remplace réellement l'ancienne page Modules V114. Ainsi une session
# reconstruite après redémarrage retombe sur une page connue par le stockage historique.
PAGE_V116_MODULES = v4.PAGE_MODULES
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
            _d("precision", "Filtres avancés", "Mentions, majuscules, emojis, comptes et bots.", "page:security"),
            _d("exceptions", "Exceptions", "Rôles et cas autorisés par la politique de sécurité.", "page:security"),
        ),
    ),
    ModuleSpec(
        "moderation", "Modération", "Sanctions, rôles staff et historique.", (
            _d("warn", "Avertissements", "Avertissements et dossiers de modération.", "hint:+warn"),
            _d("mute", "Mute / Timeout", "Timeouts et sanctions temporaires.", "hint:+mute"),
            _d("kickban", "Kick / Ban", "Sanctions lourdes et historique.", "hint:+ban"),
            _d("automatic", "Sanctions automatiques", "Lier les protections aux sanctions graduées.", "page:security"),
            _d("staff", "Rôle staff", "Choisir le rôle de modération utilisé par SentriX.", "config:mod_role"),
            _d("history", "Historique", "Voir les dernières modifications du setup.", "action:history"),
        ),
    ),
    ModuleSpec(
        "members", "Membres", "Arrivées, départs, vérification et autorôles.", (
            _d("welcome_channel", "Salon de bienvenue", "Salon des messages d'arrivée.", "config:welcome_channel"),
            _d("welcome_message", "Message de bienvenue", "Texte et image utilisés à l'arrivée.", "native:welcome_message"),
            _d("goodbye", "Départ", "Salon utilisé pour les messages de départ.", "config:goodbye_channel"),
            _d("verification", "Vérification", "Rôle attribué après validation.", "config:verify_role"),
            _d("autorole", "Autorôle", "Rôle attribué automatiquement aux membres.", "config:autorole"),
            _d("rules", "Règlement / CAPTCHA", "Parcours de validation complet des nouveaux membres.", "hint:+verification-setup"),
        ),
    ),
    ModuleSpec(
        "logs", "Logs", "Journalisation globale et par type d'événement.", (
            _d("general", "Salon principal", "Destination principale des journaux.", "config:log_channel"),
            _d("messages", "Messages", "Suppressions et modifications de messages.", "page:logs"),
            _d("moderation", "Modération", "Warn, mute, kick, ban et actions staff.", "page:logs"),
            _d("members", "Membres", "Arrivées, départs et changements de profils.", "page:logs"),
            _d("voice", "Vocal", "Connexions, déplacements et déconnexions vocales.", "page:logs"),
            _d("roles", "Rôles", "Créations, suppressions et modifications de rôles.", "page:logs"),
            _d("channels", "Salons", "Créations, suppressions et modifications de salons.", "page:logs"),
            _d("tickets", "Tickets", "Ouvertures, claims, fermetures et transcripts.", "bridge:tickets"),
        ),
    ),
    ModuleSpec(
        "levels", "Niveaux", "XP, récompenses, annonces et restrictions.", (
            _d("text", "XP texte", "Bornes XP, cooldown et exclusions.", "bridge:levels:xp"),
            _d("voice", "XP vocal", "Salons vocaux ignorés et comportement en solo.", "bridge:levels:voice"),
            _d("cooldown", "Cooldown", "Fréquence de gain d'expérience.", "bridge:levels:xp"),
            _d("multipliers", "Multiplicateur global", "Multiplier les gains XP du serveur.", "native:xp_multiplier"),
            _d("rewards", "Récompenses", "Rôles attribués à certains niveaux.", "bridge:levels:levels"),
            _d("announcements", "Annonces", "Salon et activation des annonces de niveau.", "bridge:levels:levels"),
            _d("restrictions", "Restrictions", "Rôles et salons qui ne gagnent pas d'XP.", "bridge:levels:xp"),
        ),
    ),
    ModuleSpec(
        "economy", "Économie", "Monnaie, banque, boutique et réputation.", (
            _d("currency", "Affichage monnaie", "Emoji de monnaie et affichage du profil.", "bridge:levels:economy"),
            _d("bank", "Banque", "Dépôts, retraits et épargne des membres.", "hint:+banque"),
            _d("shop", "Boutique de rôles", "Rôles achetables et prix.", "bridge:shop"),
            _d("reputation", "Réputation", "Emoji économie et cooldown de réputation.", "bridge:levels:economy"),
            _d("rewards", "Récompenses", "Daily, weekly, work et gains économiques.", "hint:+daily"),
        ),
    ),
    ModuleSpec(
        "tickets", "Tickets", "Panels, types, formulaires et équipe support.", (
            _d("panels", "Panels", "Créer, modifier et publier les panels.", "bridge:tickets"),
            _d("types", "Types", "Catégories, rôles staff et formats de tickets.", "bridge:tickets"),
            _d("forms", "Formulaires", "Questions demandées à l'ouverture.", "bridge:tickets"),
            _d("staff", "Boutons staff", "Claim, transfert, note, fermeture et permissions.", "bridge:tickets"),
            _d("automation", "Automatisation", "Limites, fermeture automatique et transcripts.", "bridge:tickets"),
        ),
    ),
    ModuleSpec(
        "roles", "Rôles", "Autorôles, rôles de niveau et panels.", (
            _d("staff", "Rôle staff", "Rôle de modération principal.", "config:mod_role"),
            _d("autorole", "Autorôle", "Rôle donné automatiquement à l'arrivée.", "config:autorole"),
            _d("levels", "Rôles de niveau", "Récompenses de progression.", "bridge:levels:levels"),
            _d("panels", "Panels de rôles", "Rôles sélectionnables par les membres.", "page:roles"),
            _d("notifications", "Rôles notifications", "Rôles utilisés par les alertes sociales.", "bridge:notifications"),
        ),
    ),
    ModuleSpec(
        "notifications", "Notifications", "YouTube, TikTok, Twitch et annonces.", (
            _d("sources", "Sources surveillées", "Voir les abonnements sociaux du serveur.", "bridge:notifications"),
            _d("youtube", "YouTube", "Notifications de nouvelles vidéos.", "bridge:notifications"),
            _d("tiktok", "TikTok", "Notifications de nouvelles publications.", "bridge:notifications"),
            _d("twitch", "Twitch", "Alertes de live et changements d'état.", "bridge:notifications"),
            _d("announcements", "Salon d'annonces", "Salon principal des annonces SentriX.", "config:announce_channel"),
        ),
    ),
    ModuleSpec(
        "ai", "IA", "Assistant, génération et accès IA.", (
            _d("assistant", "Assistant", "Activation et comportement général de l'IA.", "bridge:ai"),
            _d("models", "Modèle / raisonnement", "Modèle par défaut et niveau de raisonnement.", "bridge:ai"),
            _d("limits", "Limites", "Cooldown, limites minute/jour et longueur max.", "bridge:ai"),
            _d("permissions", "Accès", "Salons et rôles autorisés.", "bridge:ai"),
            _d("memory", "Mémoire", "Activer ou désactiver la mémoire conversationnelle.", "bridge:ai"),
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
            _d("appearance", "Apparence", "Titre, footer, couleur et champs visibles.", "bridge:levels:appearance"),
            _d("identity", "Identité", "Informations affichées sur le profil.", "hint:+profile"),
            _d("levels", "Niveau", "XP, rang et progression affichés.", "bridge:levels:visibility"),
            _d("economy", "Économie", "Solde et informations économiques affichées.", "bridge:levels:visibility"),
            _d("stats", "Statistiques", "Messages, vocal, réputation et visibilité.", "bridge:levels:visibility"),
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
BRIDGE_TARGETS = frozenset({"ai", "tickets", "shop", "notifications", "levels"})


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


def _row_value(row, key: str, default=None):
    return v4._row_value(row, key, default)


def _find_command(bot, raw: str) -> bool:
    name = str(raw or "").strip().lstrip("+/")
    if not name:
        return False
    return bot.get_command(name.split()[0]) is not None


def _persisted_page(page: int) -> int:
    """La DB historique ne connaît pas 117 : reprise sûre sur le centre Modules."""
    return PAGE_V116_MODULES if page == PAGE_V116_DETAIL else page


async def _module_status(view, module: ModuleSpec) -> str:
    if module.key == "security":
        row = await view.bot.db.get_automod(view.guild_id)
        active = sum(1 for key in AUTOMOD_FIELDS if bool(_row_value(row, key, 0)))
        return f"{active}/{len(AUTOMOD_FIELDS)} protections actives"
    if module.key == "tickets":
        try:
            panels_row = await view.bot.db.fetchone(
                "SELECT COUNT(*) AS n FROM ticket_panels_v2 WHERE guild_id = ?", (view.guild_id,)
            )
            open_row = await view.bot.db.fetchone(
                "SELECT COUNT(*) AS n FROM tickets WHERE guild_id = ? AND status = 'ouvert'", (view.guild_id,)
            )
            return f"{int(_row_value(panels_row, 'n', 0))} panel(s) · {int(_row_value(open_row, 'n', 0))} ouvert(s)"
        except Exception:
            return "Disponible"
    if module.key == "levels":
        settings = await view.bot.db.get_stats_settings(view.guild_id)
        return f"XP {settings.get('xp_min', 10)}–{settings.get('xp_max', 25)} · cooldown {settings.get('xp_cooldown', 60)}s"
    if module.key == "ai":
        try:
            from utils import ai_service
            settings = await ai_service.get_settings(view.bot, view.guild_id)
            return f"{'Activée' if settings['enabled'] else 'Désactivée'} · {settings['default_model']}"
        except Exception:
            return "Disponible"
    if module.key == "notifications":
        try:
            row = await view.bot.db.fetchone(
                "SELECT COUNT(*) AS n FROM social_notifications WHERE guild_id = ? AND enabled = 1",
                (view.guild_id,),
            )
            return f"{int(_row_value(row, 'n', 0))} source(s) active(s)"
        except Exception:
            return "Disponible"
    if module.key == "economy":
        try:
            row = await view.bot.db.fetchone(
                "SELECT COUNT(*) AS n FROM shop_items WHERE guild_id = ?", (view.guild_id,)
            )
            return f"{int(_row_value(row, 'n', 0))} article(s) en boutique"
        except Exception:
            return "Disponible"
    if module.key in {"members", "logs", "roles", "suggestions"}:
        conf = await view.bot.db.get_guild_config(view.guild_id)
        keys = {
            "members": ("welcome_channel", "goodbye_channel", "autorole", "verify_role"),
            "logs": ("log_channel",),
            "roles": ("mod_role", "autorole"),
            "suggestions": ("suggest_channel",),
        }[module.key]
        configured = sum(1 for key in keys if _row_value(conf, key, None))
        return f"{configured}/{len(keys)} réglage(s) principal(aux)"
    return f"{len(module.details)} réglages"


async def _modules_embed(view) -> discord.Embed:
    _ensure_state(view)
    module = _module(view._v116_module)
    if module is not None:
        status = await _module_status(view, module)
        lines = [f"**{item.label}** — {item.description}" for item in module.details]
        return discord.Embed(
            title=module.label,
            description=(f"{module.description}\n**État :** {status}\n\n" + "\n".join(lines))[:1800],
            colour=v4._CONFIG_MODULE.SETUP_COLOR_MAIN,
        ).set_footer(text="SentriX • Setup • Choisis un réglage")

    lines = []
    for item in MODULES:
        status = await _module_status(view, item)
        lines.append(f"**{item.label}** · {status}")
    return discord.Embed(
        title="Centre de configuration",
        description=("Choisis un module. Chaque réglage s'ouvre sur sa propre page.\n\n" + "\n".join(lines))[:2000],
        colour=v4._CONFIG_MODULE.SETUP_COLOR_MAIN,
    ).set_footer(text="SentriX • Setup • Modules")


async def _detail_status(view, detail: DetailSpec) -> str:
    target = detail.target
    if target.startswith("automod:"):
        field = target.split(":", 1)[1]
        row = await view.bot.db.get_automod(view.guild_id)
        return "Activé" if bool(_row_value(row, field, 0)) else "Désactivé"
    if target.startswith("config:"):
        field = target.split(":", 1)[1]
        conf = await view.bot.db.get_guild_config(view.guild_id)
        return v4._mention(view, field, conf)
    if target == "native:welcome_message":
        conf = await view.bot.db.get_guild_config(view.guild_id)
        message = str(_row_value(conf, "welcome_message", "") or "").strip()
        image = str(_row_value(conf, "welcome_image_url", "") or "").strip()
        return f"{'Message personnalisé' if message else 'Message par défaut'} · {'image activée' if image else 'sans image'}"
    if target == "native:xp_multiplier":
        conf = await view.bot.db.get_guild_config(view.guild_id)
        return f"x{float(_row_value(conf, 'xp_multiplier', 1.0) or 1.0):g}"
    if target.startswith("bridge:levels:"):
        settings = await view.bot.db.get_stats_settings(view.guild_id)
        category = target.rsplit(":", 1)[1]
        if category == "xp":
            return f"{settings.get('xp_min', 10)}–{settings.get('xp_max', 25)} XP · {settings.get('xp_cooldown', 60)}s"
        if category == "voice":
            return f"{len(settings.get('voice_ignored_channel_ids', []))} salon(s) ignoré(s)"
        if category == "levels":
            row = await view.bot.db.fetchone("SELECT COUNT(*) AS n FROM level_roles WHERE guild_id = ?", (view.guild_id,))
            return f"{int(_row_value(row, 'n', 0))} palier(s) de rôle"
        return "Panneau complet disponible"
    if target == "bridge:tickets":
        return await _module_status(view, MODULE_BY_KEY["tickets"])
    if target == "bridge:ai":
        return await _module_status(view, MODULE_BY_KEY["ai"])
    if target == "bridge:notifications":
        return await _module_status(view, MODULE_BY_KEY["notifications"])
    if target == "bridge:shop":
        return await _module_status(view, MODULE_BY_KEY["economy"])
    if target.startswith("hint:"):
        command = target.split(":", 1)[1]
        return "Assistant disponible" if _find_command(view.bot, command) else "Assistant à vérifier"
    if target == "page:auto":
        return "Analyse, aperçu, snapshot et application sûre"
    if target == "page:summary":
        return "Diagnostic complet du serveur"
    return "Prêt à configurer"


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
    status = await _detail_status(view, detail)
    return discord.Embed(
        title=f"{module.label} • {detail.label}",
        description=(
            f"{detail.description}\n\n"
            f"**État actuel**\n{status}\n\n"
            "Les autres réglages restent cachés tant que tu n'en as pas besoin."
        )[:900],
        colour=v4._CONFIG_MODULE.SETUP_COLOR_MAIN,
    ).set_footer(text="SentriX • Setup • Réglage")


class WelcomeMessageModal(discord.ui.Modal, title="Message de bienvenue"):
    def __init__(self, setup_view, conf):
        super().__init__()
        self.setup_view = setup_view
        self.message_input = discord.ui.TextInput(
            label="Message",
            style=discord.TextStyle.paragraph,
            default=str(_row_value(conf, "welcome_message", "") or "")[:1000],
            required=False,
            max_length=1000,
            placeholder="Ex: Bienvenue {member} sur {server} !",
        )
        self.image_input = discord.ui.TextInput(
            label="Image HTTPS (optionnel)",
            default=str(_row_value(conf, "welcome_image_url", "") or "")[:300],
            required=False,
            max_length=300,
        )
        self.add_item(self.message_input)
        self.add_item(self.image_input)

    async def on_submit(self, interaction: discord.Interaction):
        image = str(self.image_input.value or "").strip()
        if image and not image.startswith("https://"):
            return await interaction.response.send_message("L'image doit utiliser une URL HTTPS.", ephemeral=True)
        message = str(self.message_input.value or "").strip()
        await self.setup_view.bot.db.set_guild_config(self.setup_view.guild_id, "welcome_message", message or None)
        await self.setup_view.bot.db.set_guild_config(self.setup_view.guild_id, "welcome_image_url", image or None)
        try:
            await self.setup_view.bot.db.log_setup_history(
                self.setup_view.guild_id, interaction.user.id, "Bienvenue", "message modifié",
                new_value="personnalisé" if message else "par défaut",
            )
        except Exception:
            logger.exception("V116 : historique bienvenue impossible guild=%s", self.setup_view.guild_id)
        self.setup_view.render_page()
        await self.setup_view._refresh_message(interaction)


class XPMultiplierModal(discord.ui.Modal, title="Multiplicateur XP"):
    def __init__(self, setup_view, current: float):
        super().__init__()
        self.setup_view = setup_view
        self.value_input = discord.ui.TextInput(
            label="Multiplicateur (0.1 à 10)",
            default=f"{current:g}",
            max_length=5,
            placeholder="1.0",
        )
        self.add_item(self.value_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            value = float(str(self.value_input.value).replace(",", "."))
        except ValueError:
            return await interaction.response.send_message("Entre un nombre valide, par exemple `1.5`.", ephemeral=True)
        if not 0.1 <= value <= 10:
            return await interaction.response.send_message("Le multiplicateur doit être compris entre 0.1 et 10.", ephemeral=True)
        await self.setup_view.bot.db.set_guild_config(self.setup_view.guild_id, "xp_multiplier", value)
        try:
            await self.setup_view.bot.db.log_setup_history(
                self.setup_view.guild_id, interaction.user.id, "Niveaux", "multiplicateur XP modifié",
                new_value=str(value),
            )
        except Exception:
            logger.exception("V116 : historique multiplicateur impossible guild=%s", self.setup_view.guild_id)
        self.setup_view.render_page()
        await self.setup_view._refresh_message(interaction)


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
        await view.persist_session()
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
        await view.persist_session()
        await view._refresh_message(interaction)

    return callback


def _detail_select_callback(view, select: discord.ui.Select):
    async def callback(interaction: discord.Interaction):
        if select.values:
            view._v116_detail = select.values[0]
            view.page = PAGE_V116_DETAIL
        view.render_page()
        await view.persist_session()
        await view._refresh_message(interaction)

    return callback


async def _toggle_automod(view, interaction: discord.Interaction, field: str) -> None:
    if field not in AUTOMOD_FIELDS:
        return await interaction.response.send_message("Protection inconnue.", ephemeral=True)
    row = await view.bot.db.get_automod(view.guild_id)
    old = int(_row_value(row, field, 0) or 0)
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


async def _open_levels_bridge(view, interaction: discord.Interaction, category: str) -> None:
    cog = view.bot.get_cog("Levels")
    if cog is None:
        return await interaction.response.send_message("Le module Niveaux n'est pas chargé.", ephemeral=True)
    from cogs.levels import StatsConfigView

    settings = await view.bot.db.get_stats_settings(view.guild_id)
    conf = await view.bot.db.get_guild_config(view.guild_id)
    panel = StatsConfigView(cog, interaction.guild, interaction.user.id, settings)
    if conf and _row_value(conf, "xp_channel_disabled", None):
        panel.pending["_xp_channel_disabled"] = _row_value(conf, "xp_channel_disabled", "")
    panel.pending["_level_channel"] = _row_value(conf, "level_channel", None) if conf else None
    panel.category = category if category in {"appearance", "visibility", "xp", "voice", "levels", "economy"} else "xp"
    panel.rebuild_items()
    message = await panels.envoyer(
        interaction.response,
        panels.avec_composants(panels.depuis_embed(panel.build_summary_embed()), panel),
        ephemere=True,
    )
    panel.message = message


async def _open_ai_bridge(view, interaction: discord.Interaction) -> None:
    cog = view.bot.get_cog("Ai")
    if cog is None:
        return await interaction.response.send_message("Le module IA n'est pas chargé.", ephemeral=True)
    from cogs.ai import AiSetupView
    from utils import ai_service

    settings = await ai_service.get_settings(view.bot, view.guild_id)
    panel = AiSetupView(cog, view.guild_id, interaction.user.id, settings)
    await panels.envoyer(
        interaction.response,
        panels.avec_composants(panels.depuis_embed(panel.build_embed()), panel),
        ephemere=True,
    )


async def _open_tickets_bridge(view, interaction: discord.Interaction) -> None:
    cog = view.bot.get_cog("Tickets")
    if cog is None:
        return await interaction.response.send_message("Le module Tickets n'est pas chargé.", ephemeral=True)
    from cogs.tickets import TicketSetupHubView

    panel_rows = await view.bot.db.fetchall("SELECT * FROM ticket_panels_v2 WHERE guild_id = ?", (view.guild_id,))
    type_rows = await view.bot.db.fetchall("SELECT * FROM ticket_types WHERE guild_id = ?", (view.guild_id,))
    open_row = await view.bot.db.fetchone(
        "SELECT COUNT(*) AS c FROM tickets WHERE guild_id = ? AND status = 'ouvert'", (view.guild_id,)
    )
    e = embeds.brand(
        "Configuration des tickets",
        f"**Panels :** {len(panel_rows)} · **Types :** {len(type_rows)} · **Ouverts :** {int(_row_value(open_row, 'c', 0))}\n"
        "Gère les panels, types, boutons staff et statistiques sans quitter le parcours setup.",
    )
    panel = TicketSetupHubView(cog, interaction.user.id)
    await panels.envoyer(interaction.response, panels.avec_composants(panels.depuis_embed(e), panel), ephemere=True)


async def _open_notifications_bridge(view, interaction: discord.Interaction) -> None:
    rows = await view.bot.db.fetchall(
        "SELECT * FROM social_notifications WHERE guild_id = ? ORDER BY id ASC", (view.guild_id,)
    )
    if rows:
        lines = []
        for row in rows[:12]:
            state = "actif" if _row_value(row, "enabled", 0) else "inactif"
            lines.append(
                f"**#{_row_value(row, 'id')} {_row_value(row, 'platform', 'Source')}** · {state} · "
                f"<#{_row_value(row, 'discord_channel_id')}> · <@&{_row_value(row, 'role_id')}>"
            )
        text = "\n".join(lines)
    else:
        text = "Aucune source sociale configurée."
    e = embeds.neutral(
        "Notifications sociales",
        text + "\n\nAjouter une source : `+notifs-ping @Rôle <lien>` dans le salon de destination. "
        "SentriX vérifie ensuite automatiquement la source toutes les 5 minutes.",
    )
    await panels.envoyer(interaction.response, panels.depuis_embed(e), ephemere=True)


async def _open_shop_bridge(view, interaction: discord.Interaction) -> None:
    rows = await view.bot.db.fetchall(
        "SELECT * FROM shop_items WHERE guild_id = ? ORDER BY price ASC, id ASC", (view.guild_id,)
    )
    if rows:
        lines = []
        for row in rows[:15]:
            role_id = _row_value(row, "role_id", None)
            role = interaction.guild.get_role(role_id) if role_id else None
            name = role.mention if role else str(_row_value(row, "name", "Article"))
            lines.append(f"**#{_row_value(row, 'id')}** {name} · {_row_value(row, 'price', 0)} pièces")
        text = "\n".join(lines)
    else:
        text = "La boutique est vide."
    e = embeds.neutral(
        "Boutique de rôles",
        text + "\n\nConfigurer : `+shoprole add @Rôle <prix>` · modifier : `+shoprole price @Rôle <prix>` · publier : `+shoppanel`.",
    )
    await panels.envoyer(interaction.response, panels.depuis_embed(e), ephemere=True)


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

    if target.startswith("bridge:levels:"):
        category = target.rsplit(":", 1)[1]
        button = discord.ui.Button(label="Ouvrir le panneau complet", style=discord.ButtonStyle.primary, row=row)

        async def callback(interaction: discord.Interaction):
            await _open_levels_bridge(view, interaction, category)

        button.callback = callback
        return button

    if target == "bridge:ai":
        button = discord.ui.Button(label="Ouvrir le panneau IA", style=discord.ButtonStyle.primary, row=row)
        button.callback = lambda interaction: _open_ai_bridge(view, interaction)
        return button

    if target == "bridge:tickets":
        button = discord.ui.Button(label="Ouvrir le panneau Tickets", style=discord.ButtonStyle.primary, row=row)
        button.callback = lambda interaction: _open_tickets_bridge(view, interaction)
        return button

    if target == "bridge:notifications":
        button = discord.ui.Button(label="Voir les sources", style=discord.ButtonStyle.primary, row=row)
        button.callback = lambda interaction: _open_notifications_bridge(view, interaction)
        return button

    if target == "bridge:shop":
        button = discord.ui.Button(label="Voir la boutique", style=discord.ButtonStyle.primary, row=row)
        button.callback = lambda interaction: _open_shop_bridge(view, interaction)
        return button

    if target == "native:welcome_message":
        button = discord.ui.Button(label="Modifier le message", style=discord.ButtonStyle.primary, row=row)

        async def callback(interaction: discord.Interaction):
            conf = await view.bot.db.get_guild_config(view.guild_id)
            await interaction.response.send_modal(WelcomeMessageModal(view, conf))

        button.callback = callback
        return button

    if target == "native:xp_multiplier":
        button = discord.ui.Button(label="Modifier le multiplicateur", style=discord.ButtonStyle.primary, row=row)

        async def callback(interaction: discord.Interaction):
            conf = await view.bot.db.get_guild_config(view.guild_id)
            current = float(_row_value(conf, "xp_multiplier", 1.0) or 1.0)
            await interaction.response.send_modal(XPMultiplierModal(view, current))

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
                    view.guild_id, interaction.user.id,
                    label="Snapshot manuel /setup V116", source="setup-v116",
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
        button = discord.ui.Button(label="Voir l'assistant disponible", style=discord.ButtonStyle.secondary, row=row)

        async def callback(interaction: discord.Interaction):
            available = _find_command(view.bot, command)
            text = (
                f"Ce réglage possède déjà un assistant métier : **`{command}`**. "
                "Il reste la source de vérité pour cette action afin d'éviter deux configurations différentes."
                if available else
                f"Le raccourci **`{command}`** n'est pas chargé sur cette instance. Utilise le module correspondant dans `/help`."
            )
            await interaction.response.send_message(text, ephemeral=True)

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
            await view.persist_session()
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

        action = _route_button(view, detail.target, row=0)
        if action is not None:
            view.add_item(action)

        if detail.target.startswith("config:"):
            field = detail.target.split(":", 1)[1]
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


async def _persist_session(self):
    """Stocke la sous-page V116 comme Modules pour une reconstruction post-redémarrage."""
    original_page = self.page
    self.page = _persisted_page(original_page)
    try:
        return await self._sentrix_v116_original_persist_session()
    finally:
        self.page = original_page


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

    if not getattr(v4, "_V114_INSTALLED", False):
        v114.install_for_bot(bot)

    view_cls._sentrix_v116_original_render_page = view_cls.render_page
    view_cls._sentrix_v116_original_build_embed = view_cls.build_embed
    view_cls._sentrix_v116_original_handle_nav_action = view_cls.handle_nav_action
    view_cls._sentrix_v116_original_persist_session = view_cls.persist_session
    view_cls.render_page = _render_page
    view_cls.build_embed = _build_embed
    view_cls.handle_nav_action = _handle_nav_action
    view_cls.persist_session = _persist_session
    view_cls._sentrix_v116 = True

    for active in list(getattr(configuration, "active_setups", {}).values()):
        try:
            _ensure_state(active)
            active.render_page()
        except Exception:
            logger.exception("V116 : migration d'une session active impossible.")

    _INSTALLED = True
    logger.info(
        "SentriX Setup V116 actif : centre hiérarchique, ponts Tickets/Niveaux/IA et reprise de session sûre."
    )


__all__ = [
    "AUTOMOD_FIELDS", "BRIDGE_TARGETS", "CONFIG_TARGETS", "DetailSpec", "MODULES",
    "MODULE_BY_KEY", "ModuleSpec", "PAGE_V116_DETAIL", "PAGE_V116_MODULES",
    "_persisted_page", "install_for_bot",
]
