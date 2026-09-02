"""
Cog CONFIGURATION.
/setup (centre de configuration : page d'accueil + menu de catégories, façon +help — plus
besoin de taper une commande différente par réglage) /setprefix /setmodrole /setlogchannel
/create-logs /logs-status /setwelcomechannel /setgoodbyechannel /setwelcomemessage
/setgoodbyemessage /setticketlogchannel /setautorole /disablecommand /enablecommand
/ignorechannel /unignorechannel /config-view /config-reset /setlevelchannel
/setsuggestchannel /setannouncechannel /setgiveawaychannel /setwarnrole /setwarnbanthreshold

Le système de tickets (panels, types, formulaires, boutons staff) se configure entièrement
via +ticketsetup (cogs/tickets.py) — /setticketlogchannel ne reste que comme salon de logs
de repli si un type de ticket n'a pas son propre salon de logs dédié.

REFONTE /setup (Phase 1 — base technique, voir les phases suivantes pour les catégories
manquantes : modération, anti-raid, anti-nuke, vérification, bienvenue, débannissements,
invitations, niveaux, économie, réputation, giveaways, sauvegardes, mode urgence...) :
- Page d'accueil "⚙️ CENTRE DE CONFIGURATION SENTRIX" avec un menu déroulant de catégories
  (au lieu d'un parcours linéaire forcé page par page) — on choisit directement ce qu'on
  veut configurer, comme avec +help.
- Navigation par catégorie : 🏠 Accueil / 💾 Enregistrer / 📋 Résumé / ○ Fermer.
- Plus aucune barre de progression en blocs (▓░) : uniquement du texte ("X sur Y modules").
- Verrouillage de session : si un autre administrateur a déjà /setup ouvert sur ce serveur,
  proposition de Voir uniquement / Prendre le contrôle / Annuler, au lieu de laisser deux
  personnes modifier la même chose sans le savoir.
- Historique des modifications (table setup_history), consultable depuis la page d'accueil.
- Page Rôles : bouton "➕ Créer un nouveau rôle" — crée un VRAI rôle Discord (nom, couleur,
  permissions, affiché séparément, mentionnable) directement depuis /setup, sans avoir à
  passer par les paramètres du serveur Discord. Confirmation obligatoire si Administrateur
  est sélectionné parmi les permissions.
"""

import json
import logging
import re
import discord
from discord import app_commands
from discord.ext import commands

import config
from utils import embeds, checks, helpers, log_service
from utils import sentrix_panels as panels
from cogs.automod import AUTOMOD_TOGGLE_LABELS, SECURITY_PRESETS
from database.db import MANAGER_CATEGORIES

log = logging.getLogger("bot.configuration")
# Le système de tickets (panels/types/formulaires) est entièrement géré depuis cogs/tickets.py
# via +ticketsetup — rien à importer ici, /setup se contente d'y rediriger (page 3/9).

ROLE_MENTION_RE = re.compile(r"<@&(\d+)>")

# ---------------------------------------------------------------- PALETTE /setup
# Couleurs dédiées à l'assistant de configuration (distinctes de la couleur de marque
# générale du bot, qui reste inchangée partout ailleurs : /theme, embeds.brand()...).
SETUP_COLOR_MAIN = 0x5865F2
SETUP_COLOR_SECONDARY = 0x7C5CFC
SETUP_COLOR_SUCCESS = 0x23A559
SETUP_COLOR_WARNING = 0xF0B232
SETUP_COLOR_DANGER = 0xF23F43

# (colonne guild_config, nom du salon, description) — utilisé par /create-logs pour
# générer toute la catégorie de logs d'un coup, et par les listeners de logging.py.
async def repair_member_log_access(
    bot,
    guild: discord.Guild,
    member: discord.Member,
) -> int:
    """Garantit lecture/écriture des logs au configurateur autorisé.

    Les salons de logs sont privés (@everyone refusé). Sans overwrite explicite, la
    personne qui vient de lancer +create-logs / +create-server voit « Aucun accès » si
    elle ne possède pas encore un rôle staff. On n'accorde rien globalement : uniquement
    au membre qui exécute un flux déjà protégé par les checks existants.
    """
    if not isinstance(member, discord.Member) or member.guild.id != guild.id:
        return 0
    conf = await bot.db.get_guild_config(guild.id)
    if not conf:
        return 0

    channel_ids: set[int] = set()
    for column, _name, _description in LOG_CHANNEL_DEFINITIONS:
        try:
            channel_id = int(conf[column] or 0)
        except (KeyError, TypeError, ValueError):
            channel_id = 0
        if channel_id:
            channel_ids.add(channel_id)

    categories: dict[int, discord.CategoryChannel] = {}
    repaired = 0
    reason = f"Accès aux logs pour le configurateur autorisé {member}"

    def needs_fix(overwrite) -> bool:
        return (
            overwrite.view_channel is not True
            or overwrite.read_message_history is not True
            or overwrite.send_messages is not True
        )

    def grant(overwrite):
        overwrite.view_channel = True
        overwrite.read_message_history = True
        overwrite.send_messages = True
        return overwrite

    for channel_id in channel_ids:
        channel = guild.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            continue
        overwrite = channel.overwrites_for(member)
        if needs_fix(overwrite):
            await channel.set_permissions(member, overwrite=grant(overwrite), reason=reason)
            repaired += 1
        if channel.category is not None:
            categories[channel.category.id] = channel.category

    # Discord masque aussi visuellement une catégorie privée sans overwrite explicite.
    for category in categories.values():
        overwrite = category.overwrites_for(member)
        if needs_fix(overwrite):
            await category.set_permissions(member, overwrite=grant(overwrite), reason=reason)
            repaired += 1

    return repaired


LOG_CHANNEL_DEFINITIONS = [
    ("log_server", "logs-serveur", "Création/suppression/modification de salons, catégories et rôles du serveur."),
    ("log_messages", "logs-messages", "Messages modifiés ou supprimés."),
    ("log_members", "logs-membre", "Arrivées et départs de membres."),
    ("log_voice", "logs-vocal", "Connexions, déconnexions et changements de salon vocal."),
    ("log_roles", "logs-roles", "Rôles ajoutés ou retirés à un membre."),
    ("log_moderation", "logs-moderation", "Sanctions : avertissements, mutes, kicks, bans."),
    ("log_automod", "logs-securite", "Actions AutoMod et anti-nuke (spam, liens, protection du serveur)."),
]

# Colonne guild_config -> catégorie canonique de log_config. /create-logs doit écrire
# dans les DEUX : la colonne (compatibilité des écrans existants) et log_config, qui est
# la seule table lue par le transport.
LOG_COLUMN_TO_CATEGORY = {
    "log_server": "channels",
    "log_messages": "messages",
    "log_members": "members",
    "log_voice": "voice",
    "log_roles": "roles",
    "log_moderation": "moderation",
    "log_automod": "automod",
    "log_channel": "server",
    "ticket_log_channel": "tickets",
}

# Libellés affichés par /logs-status pour chaque colonne de LOG_CHANNEL_DEFINITIONS.
LOG_KIND_LABELS = {
    "log_server": "Logs serveur",
    "log_messages": "Logs messages",
    "log_members": "Logs membres",
    "log_voice": "Logs vocal",
    "log_roles": "Logs rôles",
    "log_moderation": "Logs modération",
    "log_automod": "Logs sécurité (AutoMod)",
}


def parse_role_input(guild: discord.Guild, value: str):
    """Accepte une mention de rôle (@Role), un ID brut, ou un nom exact."""
    value = value.strip()
    m = ROLE_MENTION_RE.match(value)
    if m:
        return guild.get_role(int(m.group(1)))
    if value.isdigit():
        return guild.get_role(int(value))
    return discord.utils.get(guild.roles, name=value)



# Description de chaque reglage : son libelle, ce qu'il change concretement, et
# ou le verifier. Ces trois informations manquaient a la confirmation d'une ligne.
REGLAGES = {
    "prefix": ("Préfixe des commandes", "Toutes les commandes préfixées répondent à ce caractère.", "`+setup`"),
    "mod_role": ("Rôle staff", "Ce rôle peut utiliser les commandes de modération.", "`+setup` › Modération"),
    "log_channel": ("Salon des logs de sanctions", "Chaque sanction y sera consignée.", "`+setup` › Logs"),
    "welcome_channel": ("Salon de bienvenue", "Les arrivées y seront annoncées.", "`+setup` › Bienvenue"),
    "goodbye_channel": ("Salon de départ", "Les départs y seront annoncés.", "`+setup` › Bienvenue"),
    "welcome_message": ("Message de bienvenue", "Texte envoyé à chaque arrivée.", "`+setup` › Bienvenue"),
    "goodbye_message": ("Message de départ", "Texte envoyé à chaque départ.", "`+setup` › Bienvenue"),
    "ticket_log_channel": ("Salon des logs de tickets", "L'ouverture et la fermeture des tickets y sont consignées.", "`+setup` › Tickets"),
    "autorole": ("Rôle automatique", "Chaque nouveau membre le recevra à son arrivée.", "`+setup` › Rôles"),
    "warn_role": ("Rôle d'avertissement", "Appliqué aux membres avertis.", "`+setup` › Modération"),
    "warn_ban_threshold": ("Seuil de bannissement", "Nombre d'avertissements avant bannissement automatique.", "`+setup` › Modération"),
    "level_channel": ("Salon des montées de niveau", "Les passages de niveau y sont annoncés.", "`+setup` › Niveaux"),
    "suggest_channel": ("Salon des suggestions", "`+suggest` y publiera les propositions.", "`+setup`"),
    "announce_channel": ("Salon des annonces", "Utilisé par les annonces programmées.", "`+setup`"),
    "giveaway_channel": ("Salon des giveaways", "Les tirages au sort y seront publiés.", "`+setup`"),
}


def _valeur_lisible(guild: discord.Guild, cle: str, brut) -> str:
    """Rend une valeur de configuration lisible : un identifiant ne dit rien."""
    # Un seuil a 0 n'est pas « aucune valeur », c'est une desactivation explicite.
    if cle == "warn_ban_threshold":
        return "Désactivé" if not brut else f"**{brut}** avertissement(s)"
    if brut in (None, "", 0):
        return "Aucune"
    if cle.endswith("_channel"):
        salon = guild.get_channel(int(brut)) if str(brut).isdigit() else None
        return salon.mention if salon else f"Salon supprimé (`{brut}`)"
    if cle.endswith("_role"):
        role = guild.get_role(int(brut)) if str(brut).isdigit() else None
        return role.mention if role else f"Rôle supprimé (`{brut}`)"
    return f"`{brut}`"


async def _appliquer_reglage(cog, ctx: commands.Context, cle: str, valeur) -> None:
    """Ecrit un reglage et repond par un panneau compose.

    La confirmation disait « Le salon de bienvenue a été défini sur #accueil ».
    Elle ne disait pas ce que le reglage change, ni surtout quelle etait la valeur
    PRECEDENTE — l'information qu'on cherche quand on se demande si on vient
    d'ecraser quelque chose. Elle est lue avant l'ecriture.
    """
    libelle, effet, ou_verifier = REGLAGES.get(
        cle, (cle.replace("_", " ").capitalize(), "Réglage enregistré.", "`+setup`")
    )
    conf = await cog.bot.db.get_guild_config(ctx.guild.id)
    ancienne = _valeur_lisible(ctx.guild, cle, conf[cle] if conf is not None else None)

    await cog.bot.db.set_guild_config(ctx.guild.id, cle, valeur)
    nouvelle = _valeur_lisible(ctx.guild, cle, valeur)

    reglage = [
        panels.Ligne("Paramètre", libelle),
        panels.Ligne("Nouvelle valeur", nouvelle),
    ]
    if ancienne != "Aucune":
        reglage.append(
            panels.Ligne("Valeur précédente", ancienne, indice="Elle vient d'être remplacée.")
        )

    await panels.envoyer(
        ctx,
        panels.Panneau(
            titre="SentriX — Configuration",
            sous_titre=f"**{libelle}** est maintenant {nouvelle}.",
            kind="configuration",
            sections=[
                panels.Section("Réglage", reglage),
                panels.Section(
                    "Effet",
                    [
                        panels.Ligne("Ce qui change", effet),
                        panels.Ligne("Vérifier", ou_verifier),
                    ],
                ),
            ],
            pied="SentriX • Configuration",
        ),
    )


class Configuration(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Assistants /setup actuellement ouverts, indexés par ID du message. Permet de
        # retrouver l'instance vivante d'un SetupView quand un bouton est cliqué. Si le
        # bot a redémarré entre-temps (Railway redéploie souvent), l'entrée n'existe plus
        # ici : on reconstruit alors l'assistant depuis la table setup_sessions (voir
        # handle_setup_nav ci-dessous et SetupNavButton, le composant "dynamique" qui
        # survit aux redémarrages).
        self.active_setups: dict[int, "SetupView"] = {}
        # Verrouillage "un seul /setup actif à la fois par serveur" (en mémoire — ce n'est
        # pas grave si ça se réinitialise à un redémarrage, ça évite juste que deux admins
        # modifient la même chose sans le savoir PENDANT que le bot tourne). Valeur :
        # (message_id, author_id, author_name).
        self.active_by_guild: dict[int, tuple[int, int, str]] = {}

    def release_lock(self, guild_id: int, message_id: int):
        """Libère le verrou UNIQUEMENT s'il appartient bien à cette session précise (évite
        qu'une vieille session fermée en retard n'efface le verrou d'une session plus
        récente qui aurait pris le contrôle entre-temps)."""
        current = self.active_by_guild.get(guild_id)
        if current and current[0] == message_id:
            self.active_by_guild.pop(guild_id, None)

    @commands.hybrid_command(name="setprefix", description="Changer le préfixe des commandes textuelles.")
    @app_commands.describe(prefixe="Le nouveau préfixe (ex: !, ?, +)")
    @checks.is_owner_or_admin()
    async def setprefix(self, ctx: commands.Context, prefixe: str):
        if len(prefixe) > 5:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Le préfixe doit faire 5 caractères maximum.')))
        self.bot.prefix_cache[ctx.guild.id] = prefixe
        await _appliquer_reglage(self, ctx, "prefix", prefixe)

    @commands.hybrid_command(name="setmodrole", description="Définir le rôle du staff/modération.")
    @app_commands.describe(role="Le rôle à définir comme rôle staff")
    @checks.is_owner_or_admin()
    async def setmodrole(self, ctx: commands.Context, role: discord.Role):
        await _appliquer_reglage(self, ctx, "mod_role", role.id)

    @commands.hybrid_command(name="setlogchannel", description="Définir le salon de logs des sanctions.")
    @app_commands.describe(salon="Le salon où seront envoyés les logs")
    @checks.is_owner_or_admin()
    async def setlogchannel(self, ctx: commands.Context, salon: discord.TextChannel):
        await _appliquer_reglage(self, ctx, "log_channel", salon.id)

    async def create_log_channels(self, guild: discord.Guild, author: discord.Member) -> list[discord.TextChannel]:
        """Crée (une seule fois) toute la catégorie de logs SentriX : un salon dédié par
        type d'évènement, avec les bonnes permissions. Réutilisé par /create-logs et par
        la page "Logs" de /setup. Ne recrée jamais un salon déjà configuré et toujours valide."""
        conf = await self.bot.db.get_guild_config(guild.id)

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True),
        }
        if conf and conf["mod_role"]:
            role = guild.get_role(conf["mod_role"])
            if role:
                overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
        if author.guild_permissions.administrator:
            overwrites[author] = discord.PermissionOverwrite(view_channel=True, send_messages=True)

        missing = [d for d in LOG_CHANNEL_DEFINITIONS if not (conf and conf[d[0]] and guild.get_channel(conf[d[0]]))]
        if not missing:
            return []

        category = await guild.create_category("📡 SentriX — Logs", overwrites=overwrites, reason=f"Système de logs créé par {author}")

        created = []
        for db_column, channel_name, topic in missing:
            channel = await guild.create_text_channel(
                channel_name, category=category, overwrites=overwrites, topic=topic,
                reason=f"Système de logs créé par {author}",
            )
            await self.bot.db.set_guild_config(guild.id, db_column, channel.id)
            # Point d'écriture unique du routage : sans ça le salon serait créé mais
            # jamais routé, puisque le transport ne lit que log_config.
            category_key = LOG_COLUMN_TO_CATEGORY.get(db_column)
            if category_key:
                try:
                    await log_service.set_log_config(
                        self.bot, guild.id, category_key,
                        channel_id=channel.id, enabled=True,
                    )
                except Exception:
                    log.exception(
                        "Route de log non enregistrée guild=%s category=%s",
                        guild.id, category_key,
                    )
            created.append(channel)
            await panels.envoyer(channel, panels.depuis_embed(embeds.brand('📡 Journal SentriX', topic)))

        try:
            repaired = await repair_member_log_access(self.bot, guild, author)
            if repaired:
                log.info(
                    "Accès logs réparé pour %s sur %s (%s overwrite(s)).",
                    author, guild.id, repaired,
                )
        except discord.HTTPException:
            log.exception("Impossible de réparer les permissions des salons de logs.")

        return created

    @commands.hybrid_command(
        name="create-logs",
        # BUG CORRIGÉ (critique) : cette description dépassait la limite Discord de 100
        # caractères (elle en faisait 125). Discord REFUSE alors la synchronisation de
        # TOUTES les commandes slash globales (pas juste celle-ci) — c'est exactement ce
        # qui faisait que /ticketsetup, /ticketpanel, etc. semblaient "ne plus répondre" :
        # le bot n'arrivait plus à publier la moindre commande à jour sur Discord.
        description="Créer automatiquement une catégorie de salons de logs (messages, vocal, modération, sécurité...).",
    )
    @checks.is_owner_or_admin()
    async def create_logs(self, ctx: commands.Context):
        await ctx.defer() if ctx.interaction else None
        created = await self.create_log_channels(ctx.guild, ctx.author)

        if not created:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.warning('Tous les salons de logs étaient déjà configurés. Utilisez `/setup` pour les changer un par un.')))

        e = embeds.brand(
            "📡 Système de logs créé",
            f"**{len(created)}** salon(s) de logs ont été créés et configurés automatiquement — "
            "rien d'autre à faire, le bot y écrit tout seul à partir de maintenant.",
        )
        e.add_field(name="Salons créés", value="\n".join(c.mention for c in created), inline=False)
        await panels.envoyer(ctx, panels.depuis_embed(e))

    @commands.hybrid_command(
        name="logs-status",
        description="Diagnostiquer le système de logs : quel salon reçoit quoi, et ce qui ne fonctionne pas.",
    )
    @checks.is_owner_or_admin()
    async def logs_status(self, ctx: commands.Context):
        conf = await self.bot.db.get_guild_config(ctx.guild.id)
        e = embeds.neutral("📡 Diagnostic des logs")
        if not conf:
            e.description = "Aucune configuration définie pour l'instant. Utilisez `/create-logs` ou `/setup`."
            return await panels.envoyer(ctx, panels.depuis_embed(e))

        def check_channel(channel_id: int):
            """Retourne (emoji, texte) pour un salon donné : introuvable, permissions
            manquantes, ou OK. C'est exactement la même logique que helpers.send_log,
            pour que ce diagnostic reflète fidèlement ce qui se passe réellement."""
            channel = ctx.guild.get_channel(channel_id)
            if not channel:
                return "○", "salon introuvable (a probablement été supprimé)"
            perms = channel.permissions_for(ctx.guild.me)
            if not (perms.view_channel and perms.send_messages):
                return "⚠️", f"{channel.mention} — le bot n'a pas la permission de voir/écrire ici"
            return "●", channel.mention

        general_id = conf["log_channel"]
        lines = []
        any_problem = False

        if general_id:
            status, detail = check_channel(general_id)
            any_problem = any_problem or status != "●"
            lines.append(f"{status} **Salon général** (`/setlogchannel`) — {detail}")
        else:
            lines.append("⚪ **Salon général** (`/setlogchannel`) — non défini (sert de repli si un salon dédié manque)")

        for column, _slug, _desc in LOG_CHANNEL_DEFINITIONS:
            label = LOG_KIND_LABELS.get(column, column)
            dedicated_id = conf[column]
            if dedicated_id:
                status, detail = check_channel(dedicated_id)
            elif general_id:
                status, detail = check_channel(general_id)
                detail = f"{detail} (via le repli sur le salon général)"
            else:
                status, detail = "○", "aucun salon configuré (ni dédié, ni général)"
            any_problem = any_problem or status != "●"
            lines.append(f"{status} **{label}** — {detail}")

        e.description = "\n".join(lines)
        if any_problem:
            e.add_field(
                name="Comment corriger",
                value=(
                    "Lancez `/create-logs` pour créer automatiquement les salons manquants, "
                    "ou `/setup` (page Logs) pour les redéfinir un par un. Si un ○ ou ⚠️ persiste "
                    "après ça, vérifiez que le rôle du bot a bien la permission **Voir le salon** "
                    "et **Envoyer des messages** dans le salon concerné."
                ),
                inline=False,
            )
        else:
            e.add_field(name="Résultat", value="Tous les logs configurés fonctionnent correctement. ●", inline=False)
        await panels.envoyer(ctx, panels.depuis_embed(e))

    # ================================================================== LOGS INDÉPENDANTS (/logsetup)
    #
    # Refonte demandée par Jayden : chaque catégorie de log peut désormais être activée/
    # désactivée indépendamment, avec son propre salon — voir utils/log_service.py pour le
    # catalogue complet (13 catégories) et la logique de migration non destructive depuis
    # l'ancien système (aucune configuration existante n'est perdue ni remplacée).
    #
    # Granularité : une "catégorie" du panneau correspond à un seul `log_type` (voir
    # log_service.LOG_TYPES) — ce n'est PAS encore un contrôle événement par événement
    # (ex: "message supprimé" et "message modifié" partagent le même réglage "Messages").
    # Descendre à ce niveau de détail nécessiterait de retoucher chaque listener un par un ;
    # ce n'est pas fait dans cette phase pour ne pas risquer de casser des listeners déjà
    # fonctionnels. Le panneau l'indique honnêtement (colonne "Émis actuellement").

    async def _build_logs_home(self, guild_id: int) -> tuple[discord.Embed, "LogsSetupView"]:
        all_settings = await log_service.get_all_log_settings(self.bot, guild_id)
        active = sum(1 for s in all_settings.values() if s["enabled"])
        disabled = len(all_settings) - active
        incomplete = sum(1 for log_type, s in all_settings.items() if not s["enabled"] and s["channel_id"])
        conf = await self.bot.db.get_guild_config(guild_id)
        error_channel_id = conf["error_channel"] if conf else None
        guild_obj = self.bot.get_guild(guild_id)
        error_channel = guild_obj.get_channel(error_channel_id) if (guild_obj and error_channel_id) else None

        e = embeds.brand(
            "📋 Configuration des logs SentriX",
            "Choisissez une catégorie ci-dessous pour l'activer/la désactiver et choisir son salon.",
        )
        e.add_field(name="Logs actifs", value=str(active), inline=True)
        e.add_field(name="Logs désactivés", value=str(disabled), inline=True)
        e.add_field(name="Salons configurés mais désactivés", value=str(incomplete), inline=True)
        e.add_field(name="Salon d'erreurs", value=error_channel.mention if error_channel else "Non configuré", inline=False)
        view = LogsSetupView(self, author_id=None, guild_id=guild_id)
        return e, view

    @commands.hybrid_command(
        name="logsetup",
        description="Configurer chaque type de log séparément (activer/désactiver, choisir le salon, tester).",
        with_app_command=False,  # budget de commandes slash très serré (voir +createrole/+levelcheck) — reste en préfixe
    )
    @checks.is_owner_or_admin_for("configuration")
    async def logsetup(self, ctx: commands.Context):
        e, view = await self._build_logs_home(ctx.guild.id)
        view.author_id = ctx.author.id
        msg = await panels.envoyer(ctx, panels.avec_composants(panels.depuis_embed(e), view))
        view.message = msg

    @commands.hybrid_group(name="logs", description="Commandes rapides pour les logs (voir aussi +logsetup pour le panneau complet).", with_app_command=False)
    @checks.is_owner_or_admin_for("configuration")
    async def logs_group(self, ctx: commands.Context):
        if ctx.invoked_subcommand is None:
            await panels.envoyer(ctx, panels.depuis_embed(embeds.info('Sous-commandes : `+logs enable`, `+logs disable`, `+logs channel`, `+logs test`, `+logs status`, `+logs list`, `+logs reset`. Ou utilisez `+logsetup` pour le panneau interactif.')))

    def _resolve_log_type(self, value: str) -> str | None:
        value = value.strip().lower().replace("-", "_")
        if value in log_service.LOG_TYPES:
            return value
        # Alias pratiques vus dans la demande de Jayden (ex: "ban", "ticket_open").
        aliases = {
            "ban": "moderation", "unban": "moderation", "kick": "moderation", "warn": "moderation", "mute": "moderation",
            "ticket_open": "tickets", "ticket_close": "tickets", "ticket": "tickets",
            "ai_request": "ai", "message_delete": "messages", "message_edit": "messages",
            "security": "automod", "antiraid": "automod", "antinuke": "automod",
        }
        return aliases.get(value)

    @logs_group.command(name="enable", description="Activer un type de log (nécessite un salon déjà configuré, ou fourni ici).", with_app_command=False)
    async def logs_enable(self, ctx: commands.Context, type_log: str, salon: discord.TextChannel = None):
        log_type = self._resolve_log_type(type_log)
        if not log_type:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error(f'Type de log inconnu : `{type_log}`. Utilisez `+logs list` pour voir les types disponibles.')))
        if salon:
            ok, reason = log_service.validate_channel(ctx.guild, salon.id)
            if not ok:
                return await panels.envoyer(ctx, panels.depuis_embed(embeds.error(f"Impossible d'utiliser {salon.mention} : {reason}.")))
            await log_service.set_log_channel(self.bot, ctx.guild.id, log_type, salon.id)
        try:
            await log_service.set_log_enabled(self.bot, ctx.guild.id, log_type, True)
        except ValueError:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error(f"○ Vous devez d'abord choisir un salon valide avant d'activer ce log (`+logs channel {type_log} #salon` ou `+logs enable {type_log} #salon`).")))
        label = log_service.LOG_TYPES[log_type]["label"]
        await panels.envoyer(ctx, panels.depuis_embed(embeds.success(f'Log **{label}** activé.')))

    @logs_group.command(name="disable", description="Désactiver un type de log.", with_app_command=False)
    async def logs_disable(self, ctx: commands.Context, type_log: str):
        log_type = self._resolve_log_type(type_log)
        if not log_type:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error(f'Type de log inconnu : `{type_log}`. Utilisez `+logs list` pour voir les types disponibles.')))
        await log_service.set_log_enabled(self.bot, ctx.guild.id, log_type, False)
        label = log_service.LOG_TYPES[log_type]["label"]
        await panels.envoyer(ctx, panels.depuis_embed(embeds.success(f'Log **{label}** désactivé.')))

    @logs_group.command(name="channel", description="Définir le salon d'un type de log (sans l'activer automatiquement).", with_app_command=False)
    async def logs_channel(self, ctx: commands.Context, type_log: str, salon: discord.TextChannel):
        log_type = self._resolve_log_type(type_log)
        if not log_type:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error(f'Type de log inconnu : `{type_log}`. Utilisez `+logs list` pour voir les types disponibles.')))
        ok, reason = log_service.validate_channel(ctx.guild, salon.id)
        if not ok:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error(f"Impossible d'utiliser {salon.mention} : {reason}.")))
        await log_service.set_log_channel(self.bot, ctx.guild.id, log_type, salon.id)
        label = log_service.LOG_TYPES[log_type]["label"]
        await panels.envoyer(ctx, panels.depuis_embed(embeds.success(f"Salon du log **{label}** défini sur {salon.mention}. Utilisez `+logs enable {type_log}` pour l'activer.")))

    @logs_group.command(name="test", description="Envoyer un message de test dans le salon d'un type de log.", with_app_command=False)
    async def logs_test(self, ctx: commands.Context, type_log: str):
        log_type = self._resolve_log_type(type_log)
        if not log_type:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error(f'Type de log inconnu : `{type_log}`. Utilisez `+logs list` pour voir les types disponibles.')))
        ok, message = await log_service.send_test_log(self.bot, ctx.guild, log_type, ctx.author)
        await panels.envoyer(ctx, panels.depuis_embed(embeds.success(message) if ok else embeds.error(message)))

    @logs_group.command(name="status", description="Voir l'état d'un type de log précis.", with_app_command=False)
    async def logs_status_one(self, ctx: commands.Context, type_log: str):
        log_type = self._resolve_log_type(type_log)
        if not log_type:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error(f'Type de log inconnu : `{type_log}`. Utilisez `+logs list` pour voir les types disponibles.')))
        setting = await log_service.get_log_setting(self.bot, ctx.guild.id, log_type)
        meta = log_service.LOG_TYPES[log_type]
        e = embeds.neutral(f"📋 {meta['label']}")
        e.add_field(name="État", value="🟢 Activé" if setting["enabled"] else "⚪ Désactivé", inline=True)
        channel = ctx.guild.get_channel(setting["channel_id"]) if setting["channel_id"] else None
        e.add_field(name="Salon", value=channel.mention if channel else "Non configuré", inline=True)
        e.add_field(name="Émis actuellement par le bot", value="● Oui" if meta["emits"] else "⚠️ Pas encore (configuration prête, événement pas encore câblé)", inline=False)
        await panels.envoyer(ctx, panels.depuis_embed(e))

    @logs_group.command(name="list", description="Lister tous les types de logs disponibles et leur état.", with_app_command=False)
    async def logs_list(self, ctx: commands.Context):
        all_settings = await log_service.get_all_log_settings(self.bot, ctx.guild.id)
        lines = []
        for category, types in log_service.categories_with_types().items():
            for log_type in types:
                s = all_settings[log_type]
                status = "🟢" if s["enabled"] else "⚪"
                lines.append(f"{status} `{log_type}` — {log_service.LOG_TYPES[log_type]['label']}")
        e = embeds.neutral("📋 Types de logs disponibles", "\n".join(lines))
        await panels.envoyer(ctx, panels.depuis_embed(e))

    @logs_group.command(name="reset", description="[Admin] Réinitialiser un type de log (désactivé, sans salon).", with_app_command=False)
    async def logs_reset(self, ctx: commands.Context, type_log: str):
        log_type = self._resolve_log_type(type_log)
        if not log_type:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error(f'Type de log inconnu : `{type_log}`. Utilisez `+logs list` pour voir les types disponibles.')))
        await log_service.set_log_enabled(self.bot, ctx.guild.id, log_type, False)
        await log_service.set_log_channel(self.bot, ctx.guild.id, log_type, None)
        label = log_service.LOG_TYPES[log_type]["label"]
        await panels.envoyer(ctx, panels.depuis_embed(embeds.success(f'Log **{label}** réinitialisé (désactivé, aucun salon).')))

    @commands.hybrid_command(name="setwelcomechannel", description="Définir le salon de bienvenue.", with_app_command=False)
    @app_commands.describe(salon="Le salon de bienvenue")
    @checks.is_owner_or_admin()
    async def setwelcomechannel(self, ctx: commands.Context, salon: discord.TextChannel):
        await _appliquer_reglage(self, ctx, "welcome_channel", salon.id)

    @commands.hybrid_command(name="setgoodbyechannel", description="Définir le salon des messages de départ.", with_app_command=False)
    @app_commands.describe(salon="Le salon de départ")
    @checks.is_owner_or_admin()
    async def setgoodbyechannel(self, ctx: commands.Context, salon: discord.TextChannel):
        await _appliquer_reglage(self, ctx, "goodbye_channel", salon.id)

    @commands.hybrid_command(name="setwelcomemessage", description="Personnaliser le message de bienvenue ({member}, {server}).", with_app_command=False)
    @app_commands.describe(message="Le message (utilisez {member} et {server})")
    @checks.is_owner_or_admin()
    async def setwelcomemessage(self, ctx: commands.Context, *, message: str):
        await _appliquer_reglage(self, ctx, "welcome_message", message)

    @commands.hybrid_command(name="setgoodbyemessage", description="Personnaliser le message de départ ({member}, {server}).", with_app_command=False)
    @app_commands.describe(message="Le message (utilisez {member} et {server})")
    @checks.is_owner_or_admin()
    async def setgoodbyemessage(self, ctx: commands.Context, *, message: str):
        await _appliquer_reglage(self, ctx, "goodbye_message", message)

    @commands.hybrid_command(
        name="setticketlogchannel",
        description="Définir le salon de logs de repli des tickets (utilisé si un type de ticket n'a pas son propre salon de logs).",
        with_app_command=False,
    )
    @app_commands.describe(salon="Le salon de logs de repli pour les tickets")
    @checks.is_owner_or_admin()
    async def setticketlogchannel(self, ctx: commands.Context, salon: discord.TextChannel):
        await _appliquer_reglage(self, ctx, "ticket_log_channel", salon.id)

    @commands.hybrid_command(name="setautorole", description="Définir un rôle attribué automatiquement à l'arrivée.")
    @app_commands.describe(role="Le rôle à attribuer automatiquement")
    @checks.is_owner_or_admin()
    async def setautorole(self, ctx: commands.Context, role: discord.Role):
        await _appliquer_reglage(self, ctx, "autorole", role.id)

    @commands.hybrid_command(
        name="createrole",
        description="Créer rapidement un rôle : nom + couleur en un seul message (ex: +createrole Middle Man bleu).",
        with_app_command=False,
    )
    @checks.is_owner_or_admin()
    async def createrole(self, ctx: commands.Context, *, texte: str):
        """Usage : +createrole <nom du rôle> <couleur>
        Exemple : +createrole Middle Man bleu

        La couleur est reconnue si c'est le DERNIER mot du message : un nom courant
        (rouge/red, bleu/blue, vert/green, jaune/yellow, orange, violet/purple, rose/pink,
        turquoise/teal, gris/grey, noir/black, blanc/white, marron/brown, blurple) ou un
        code hexadécimal (ex: 5865F2). Si le dernier mot n'est reconnu comme aucun des
        deux, tout le texte est utilisé comme nom de rôle, sans couleur particulière —
        pour un contrôle plus fin (permissions, affiché séparément, mentionnable), utiliser
        plutôt /setup → 🎭 Rôles → ➕ Créer un nouveau rôle."""
        await ctx.typing()
        if not ctx.guild.me.guild_permissions.manage_roles:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error("⚠️ SentriX n'a pas la permission **Gérer les rôles** sur ce serveur — impossible de créer un rôle.")))
        texte = texte.strip()
        if not texte:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error("Merci d'indiquer un nom de rôle. Exemple : `+createrole Middle Man bleu`")))

        name = texte
        colour_value = 0
        colour_label = "Aucune"
        parts = texte.rsplit(maxsplit=1)
        if len(parts) == 2:
            candidate_name, candidate_colour = parts
            resolved = resolve_named_colour(candidate_colour)
            if resolved is not None and candidate_name.strip():
                name = candidate_name.strip()
                colour_value = resolved
                colour_label = candidate_colour.strip()

        if len(name) > 100:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Le nom du rôle est trop long (100 caractères maximum).')))

        try:
            role = await ctx.guild.create_role(
                name=name, colour=discord.Colour(colour_value),
                reason=f"Créé via +createrole par {ctx.author}",
            )
        except discord.HTTPException as exc:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error(f"○ La création du rôle a échoué (`{type(exc).__name__}`). Le serveur a peut-être atteint la limite de 250 rôles, ou SentriX n'a plus la permission nécessaire.")))

        await self.bot.db.log_setup_history(
            ctx.guild.id, ctx.author.id, "Rôles", "rôle créé (+createrole)", new_value=f"{role.name} (#{role.id})",
        )
        await panels.envoyer(ctx, panels.depuis_embed(embeds.success(f'● Le rôle {role.mention} a été créé (couleur : {colour_label}).\nPour régler ses permissions, utilisez `/setup` → 🎭 Rôles, ou les paramètres du serveur Discord.')))

    @commands.hybrid_command(
        name="setwarnrole",
        description="Définir un rôle attribué automatiquement à chaque avertissement (/warn).",
        with_app_command=False,
    )
    @app_commands.describe(role="Le rôle à attribuer à chaque /warn (laisser vide pour désactiver)")
    @checks.is_owner_or_admin()
    async def setwarnrole(self, ctx: commands.Context, role: discord.Role = None):
        await _appliquer_reglage(self, ctx, "warn_role", role.id if role else None)

    @commands.hybrid_command(
        name="setwarnbanthreshold",
        description="Définir le nombre d'avertissements avant bannissement automatique (0 = désactivé).",
        with_app_command=False,
    )
    @app_commands.describe(nombre="Nombre d'avertissements avant bannissement automatique (0 pour désactiver)")
    @checks.is_owner_or_admin()
    async def setwarnbanthreshold(self, ctx: commands.Context, nombre: int):
        if nombre < 0:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error('Le nombre doit être positif (0 pour désactiver).')))
        await _appliquer_reglage(self, ctx, "warn_ban_threshold", nombre)

    @commands.hybrid_command(name="disablecommand", description="Désactiver une commande sur ce serveur.", with_app_command=False)
    @app_commands.describe(commande="Le nom de la commande à désactiver")
    @checks.is_owner_or_admin()
    async def disablecommand(self, ctx: commands.Context, commande: str):
        cmd = self.bot.get_command(commande)
        if not cmd:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error(f'Commande `{commande}` introuvable.')))
        await self.bot.db.execute(
            "INSERT OR IGNORE INTO disabled_commands (guild_id, command_name) VALUES (?, ?)",
            (ctx.guild.id, commande),
        )
        await panels.envoyer(ctx, panels.depuis_embed(embeds.success(f'La commande `{commande}` a été désactivée sur ce serveur.')))

    @commands.hybrid_command(name="enablecommand", description="Réactiver une commande précédemment désactivée.", with_app_command=False)
    @app_commands.describe(commande="Le nom de la commande à réactiver")
    @checks.is_owner_or_admin()
    async def enablecommand(self, ctx: commands.Context, commande: str):
        await self.bot.db.execute(
            "DELETE FROM disabled_commands WHERE guild_id = ? AND command_name = ?",
            (ctx.guild.id, commande),
        )
        await panels.envoyer(ctx, panels.depuis_embed(embeds.success(f'La commande `{commande}` a été réactivée.')))

    @commands.hybrid_command(name="ignorechannel", description="Ignorer un salon (le bot n'y répondra plus).", with_app_command=False)
    @app_commands.describe(salon="Le salon à ignorer")
    @checks.is_owner_or_admin()
    async def ignorechannel(self, ctx: commands.Context, salon: discord.TextChannel = None):
        salon = salon or ctx.channel
        await self.bot.db.execute(
            "INSERT OR IGNORE INTO ignored_channels (guild_id, channel_id) VALUES (?, ?)",
            (ctx.guild.id, salon.id),
        )
        automod_cog = self.bot.get_cog("Automod")
        if automod_cog:
            automod_cog.ignored_channels_cache.pop(ctx.guild.id, None)
        await panels.envoyer(ctx, panels.depuis_embed(embeds.success(f'Le salon {salon.mention} est maintenant ignoré (y compris par AutoMod).')))

    @commands.hybrid_command(name="unignorechannel", description="Ne plus ignorer un salon.", with_app_command=False)
    @app_commands.describe(salon="Le salon à ne plus ignorer")
    @checks.is_owner_or_admin()
    async def unignorechannel(self, ctx: commands.Context, salon: discord.TextChannel = None):
        salon = salon or ctx.channel
        await self.bot.db.execute(
            "DELETE FROM ignored_channels WHERE guild_id = ? AND channel_id = ?",
            (ctx.guild.id, salon.id),
        )
        automod_cog = self.bot.get_cog("Automod")
        if automod_cog:
            automod_cog.ignored_channels_cache.pop(ctx.guild.id, None)
        await panels.envoyer(ctx, panels.depuis_embed(embeds.success(f"Le salon {salon.mention} n'est plus ignoré.")))

    @commands.hybrid_command(name="setlevelchannel", description="Définir le salon des annonces de niveau.", with_app_command=False)
    @app_commands.describe(salon="Le salon pour les annonces de niveau")
    @checks.is_owner_or_admin()
    async def setlevelchannel(self, ctx: commands.Context, salon: discord.TextChannel):
        await _appliquer_reglage(self, ctx, "level_channel", salon.id)

    @commands.hybrid_command(name="setsuggestchannel", description="Définir le salon des suggestions.", with_app_command=False)
    @app_commands.describe(salon="Le salon des suggestions")
    @checks.is_owner_or_admin()
    async def setsuggestchannel(self, ctx: commands.Context, salon: discord.TextChannel):
        await _appliquer_reglage(self, ctx, "suggest_channel", salon.id)

    @commands.hybrid_command(name="setannouncechannel", description="Définir le salon des annonces générales.", with_app_command=False)
    @app_commands.describe(salon="Le salon des annonces")
    @checks.is_owner_or_admin()
    async def setannouncechannel(self, ctx: commands.Context, salon: discord.TextChannel):
        await _appliquer_reglage(self, ctx, "announce_channel", salon.id)

    @commands.hybrid_command(name="setgiveawaychannel", description="Définir le salon par défaut des giveaways.", with_app_command=False)
    @app_commands.describe(salon="Le salon par défaut des giveaways")
    @checks.is_owner_or_admin()
    async def setgiveawaychannel(self, ctx: commands.Context, salon: discord.TextChannel):
        await _appliquer_reglage(self, ctx, "giveaway_channel", salon.id)

    @commands.hybrid_command(name="config-view", description="Afficher la configuration actuelle du serveur.")
    @checks.is_owner_or_admin()
    async def config_view(self, ctx: commands.Context):
        """Configuration du serveur, groupee par sujet.

        Les onze reglages etaient onze champs de meme poids : il fallait tous les
        lire pour trouver celui qu'on cherchait. Ils sont maintenant regroupes
        comme on y pense — general, moderation, accueil, tickets — et ce qui n'est
        PAS defini est compte dans le resume.
        """
        conf = await self.bot.db.get_guild_config(ctx.guild.id)
        if not conf:
            return await panels.envoyer(
                ctx,
                panels.Panneau(
                    titre="SentriX — Configuration",
                    sous_titre="Aucun réglage n'est encore défini sur ce serveur.",
                    kind="warning",
                    sections=[
                        panels.Section(
                            "Démarrer",
                            [
                                panels.Ligne("`+setup`", "Centre de contrôle, tout se règle au clic"),
                                panels.Ligne("`+create-logs`", "Crée la catégorie de journaux d'un coup"),
                            ],
                        )
                    ],
                    pied="SentriX • Configuration",
                ),
            )

        def salon(cid):
            if not cid:
                return "Non défini"
            ch = ctx.guild.get_channel(cid)
            return ch.mention if ch else "**Salon supprimé**"

        def role(rid):
            if not rid:
                return "Non défini"
            r = ctx.guild.get_role(rid)
            return r.mention if r else "**Rôle supprimé**"

        groupes = {
            "Général": [
                panels.Ligne("Préfixe", f"`{conf['prefix'] or '+'}`"),
                panels.Ligne("Salon des logs", salon(conf["log_channel"])),
            ],
            "Modération": [
                panels.Ligne("Rôle staff", role(conf["mod_role"])),
                panels.Ligne("Rôle d'avertissement", role(conf["warn_role"])),
                panels.Ligne(
                    "Bannissement automatique",
                    f"Au **{conf['warn_ban_threshold']}ᵉ** avertissement"
                    if conf["warn_ban_threshold"] else "Désactivé",
                ),
            ],
            "Accueil et départ": [
                panels.Ligne("Salon de bienvenue", salon(conf["welcome_channel"])),
                panels.Ligne("Salon de départ", salon(conf["goodbye_channel"])),
                panels.Ligne("Rôle automatique", role(conf["autorole"])),
            ],
            "Tickets": [
                panels.Ligne("Salon des logs de tickets", salon(conf["ticket_log_channel"])),
            ],
        }
        sections = [panels.Section(titre, lignes) for titre, lignes in groupes.items()]

        managers = await self.bot.db.list_bot_managers(ctx.guild.id)
        if managers:
            mentions = []
            for ligne in managers:
                membre = ctx.guild.get_member(ligne["user_id"])
                mentions.append(membre.mention if membre else f"<@{ligne['user_id']}>")
            sections.append(
                panels.Section(
                    f"Gestionnaires du bot ({len(mentions)})",
                    [panels.Ligne("Autorisés", ", ".join(mentions))],
                )
            )
        else:
            sections.append(
                panels.Section(
                    "Gestionnaires du bot",
                    [panels.Ligne("Aucun", "Seuls les administrateurs peuvent configurer SentriX")],
                )
            )

        # Ce qui manque est ce qu'on vient chercher : on le compte.
        total = sum(len(l) for l in groupes.values())
        definis = sum(
            1 for lignes in groupes.values() for l in lignes
            if str(l.valeur) not in ("Non défini", "Désactivé")
        )
        await panels.envoyer(
            ctx,
            panels.Panneau(
                titre="SentriX — Configuration du serveur",
                sous_titre=f"**{definis}** réglage(s) définis sur **{total}**.",
                kind="configuration",
                sections=sections,
                pied="SentriX • Configuration",
            ),
        )

    @commands.hybrid_command(name="config-reset", description="Réinitialiser toute la configuration du serveur.", with_app_command=False)
    @checks.is_owner_or_admin()
    async def config_reset(self, ctx: commands.Context):
        await self.bot.db.execute("DELETE FROM guild_config WHERE guild_id = ?", (ctx.guild.id,))
        await self.bot.db.ensure_guild(ctx.guild.id)
        self.bot.db.invalidate_guild_config(ctx.guild.id)
        self.bot.prefix_cache.pop(ctx.guild.id, None)
        await panels.envoyer(
            ctx,
            panels.Panneau(
                titre="SentriX — Configuration réinitialisée",
                sous_titre="Tous les réglages du serveur sont revenus à leur valeur par défaut.",
                kind="warning",
                sections=[
                    panels.Section(
                        "Effacé",
                        [
                            panels.Ligne("Salons", "Logs, bienvenue, départ, tickets"),
                            panels.Ligne("Rôles", "Staff, avertissement, rôle automatique"),
                            panels.Ligne("Préfixe", "Revenu à `+`"),
                        ],
                    ),
                    panels.Section(
                        "Conservé",
                        [
                            panels.Ligne(
                                "Données des membres",
                                "XP, niveaux, argent et sanctions",
                                indice="Une réinitialisation de configuration n'efface aucune donnée de membre.",
                            ),
                            panels.Ligne("Tickets ouverts", "Ils restent accessibles"),
                        ],
                    ),
                    panels.Section(
                        "Reconfigurer",
                        [panels.Ligne("`+setup`", "Tout se règle au clic depuis le centre de contrôle")],
                    ),
                ],
                pied="SentriX • Configuration",
            ),
        )

    @commands.hybrid_command(
        name="setup",
        description="Centre de configuration complet du bot (page d'accueil + catégories).",
    )
    @checks.is_owner_or_admin()
    async def setup_wizard(self, ctx: commands.Context):
        """
        Fonctionnalité phare : configure absolument tout le bot (rôles, salons,
        préfixe, messages de bienvenue/départ, sécurité, tickets...) depuis un seul
        panneau — page d'accueil avec menu de catégories, comme +help, plus besoin
        de taper une commande différente par réglage.
        """
        existing = self.active_by_guild.get(ctx.guild.id)
        if existing and existing[1] != ctx.author.id:
            locked_message_id, locked_author_id, locked_author_name = existing
            view = SetupLockPromptView(self, ctx.guild.id, locked_message_id, locked_author_id, locked_author_name, ctx.author.id)
            return await panels.envoyer(ctx, panels.avec_composants(panels.depuis_embed(embeds.warning(f'⚠️ Une configuration est déjà en cours par **{locked_author_name}**.', title='Configuration déjà ouverte')), view))
        await self._open_setup_panel(ctx)

    async def _open_setup_panel(self, ctx_or_channel, *, author: discord.Member = None):
        """Construit et envoie le vrai panneau /setup. Séparé de la commande pour être
        réutilisable depuis "🔄 Prendre le contrôle" (SetupLockPromptView).

        IMPORTANT : on envoie toujours via `ctx_or_channel.send(...)` (jamais via un objet
        `channel` extrait séparément) — pour un /setup en slash, `commands.Context.send()`
        est ce qui répond correctement à l'interaction (sinon Discord affiche "L'application
        ne répond plus" car l'interaction n'a jamais reçu de réponse). Un `discord.TextChannel`
        (cas de la prise de contrôle, où l'interaction du bouton a déjà été acquittée séparément)
        a le même `.send()`, donc cette fonction marche pour les deux cas sans distinction."""
        guild = ctx_or_channel.guild if hasattr(ctx_or_channel, "guild") else None
        author = author or ctx_or_channel.author
        channel_id = ctx_or_channel.channel.id if hasattr(ctx_or_channel, "channel") else ctx_or_channel.id

        rows = await self.bot.db.list_bot_managers(guild.id)
        existing_managers = {}
        for row in rows:
            member = guild.get_member(row["user_id"])
            existing_managers[row["user_id"]] = member.display_name if member else f"Membre {row['user_id']}"

        automod_conf = await self.bot.db.get_automod(guild.id)
        existing_security = {field: (automod_conf[field] if automod_conf else 0) for field in AUTOMOD_TOGGLE_LABELS}
        exempt_rows = await self.bot.db.list_automod_exempt_roles(guild.id)
        existing_exempt = [r["role_id"] for r in exempt_rows]

        # Envoi en deux temps : on a besoin de l'ID du message AVANT de construire les
        # boutons de navigation (ils encodent cet ID dans leur custom_id pour pouvoir
        # être retrouvés après un redémarrage — voir SetupNavButton plus bas).
        placeholder = embeds.neutral("⚙️ CENTRE DE CONFIGURATION SENTRIX", "Chargement...", color=SETUP_COLOR_MAIN)
        message = await panels.envoyer(ctx_or_channel, panels.depuis_embed(placeholder))

        view = SetupView(
            self.bot, guild.id, author.id, message.id, channel_id,
            existing_managers=existing_managers, existing_security=existing_security,
            existing_exempt_roles=existing_exempt,
        )
        self.active_setups[message.id] = view
        self.active_by_guild[guild.id] = (message.id, author.id, str(author))
        await view.persist_session()
        await message.edit(embed=await view.build_embed(), view=view)
        return message, view

    async def _can_use_setup(self, interaction: discord.Interaction, author_id: int, guild_id: int) -> bool:
        """Autorise la personne qui a lancé /setup, OU un gestionnaire du bot / admin /
        propriétaire du bot — exactement la règle demandée pour la nouvelle version de
        l'assistant. Envoie le message d'erreur exact demandé si refusé."""
        if interaction.user.id == author_id:
            return True
        if interaction.user.id in config.OWNER_IDS:
            return True
        member = interaction.user
        if isinstance(member, discord.Member) and member.guild_permissions.administrator:
            return True
        if await self.bot.db.is_bot_manager(guild_id, interaction.user.id):
            return True
        await interaction.response.send_message("○ Vous n'êtes pas autorisé à utiliser cette configuration.", ephemeral=True)
        return False

    async def handle_setup_nav(self, interaction: discord.Interaction, action: str, message_id: int):
        """Point d'entrée UNIQUE des boutons de navigation du /setup (◀ 💾 ▶ 👁️ ○ et les
        boutons équivalents de la page 9). Fonctionne que le bot ait redémarré entre-temps
        ou non : si l'assistant n'est plus en mémoire, on le reconstruit depuis la table
        setup_sessions (c'est ce qui permet aux boutons de survivre à un redémarrage)."""
        view = self.active_setups.get(message_id)
        if view is None:
            session = await self.bot.db.get_setup_session(message_id)
            if not session or session["guild_id"] != interaction.guild.id:
                return await interaction.response.send_message(
                    "○ Cette session de configuration a expiré ou est introuvable. Relancez `/setup`.", ephemeral=True
                )
            if not await self._can_use_setup(interaction, session["author_id"], session["guild_id"]):
                return
            rows = await self.bot.db.list_bot_managers(session["guild_id"])
            existing_managers = {}
            for row in rows:
                member = interaction.guild.get_member(row["user_id"])
                existing_managers[row["user_id"]] = member.display_name if member else f"Membre {row['user_id']}"
            automod_conf = await self.bot.db.get_automod(session["guild_id"])
            existing_security = {field: (automod_conf[field] if automod_conf else 0) for field in AUTOMOD_TOGGLE_LABELS}
            exempt_rows = await self.bot.db.list_automod_exempt_roles(session["guild_id"])
            existing_exempt = [r["role_id"] for r in exempt_rows]
            view = SetupView(
                self.bot, session["guild_id"], session["author_id"], message_id, session["channel_id"],
                existing_managers=existing_managers, existing_security=existing_security,
                existing_exempt_roles=existing_exempt,
            )
            try:
                view.choices = json.loads(session["choices_json"] or "{}")
            except (json.JSONDecodeError, TypeError):
                view.choices = {}
            raw_page = session["page"] if session["page"] is not None else -1
            view.page = raw_page if raw_page == -1 else max(0, min(len(SETUP_STEPS) - 1, raw_page))
            view.render_page()
            self.active_setups[message_id] = view
            if session["guild_id"] not in self.active_by_guild:
                self.active_by_guild[session["guild_id"]] = (message_id, session["author_id"], str(session["author_id"]))
        else:
            if not await self._can_use_setup(interaction, view.author_id, view.guild_id):
                return

        await view.handle_nav_action(interaction, action)

    # ---------------------------------------------------------------- LOGS AUTOMATIQUES
    # Une fois /create-logs (ou la page "Logs" de /setup) utilisé, le bot alimente ces
    # salons tout seul, sans plus jamais rien demander à l'utilisateur.

    async def _get_actor(self, guild: discord.Guild, action: discord.AuditLogAction, target_id: int = None):
        """Retrouve l'auteur d'une action via l'Audit Log (réutilise le helper du cog Automod).
        Réservé aux événements peu fréquents (salons/rôles/kicks) — jamais utilisé sur les
        messages, trop nombreux, pour ne pas multiplier les appels à l'API."""
        automod_cog = self.bot.get_cog("Automod")
        if not automod_cog:
            return None
        return await automod_cog.get_audit_actor(guild, action, target_id)

    # Les listeners de journalisation ont été retirés d'ici : ils dupliquaient à
    # l'identique ceux de cogs/logs.py, seul pipeline officiel. Deux cogs sur le même
    # événement produisaient deux envois dont un était systématiquement jeté par la
    # déduplication — donc le contenu affiché dépendait de qui gagnait la course.


# Chaque "étape" = une page de l'assistant. "role"/"channel" = type de menu déroulant.
# Pour "channel", on peut préciser les types de salons acceptés (texte, catégorie...).
SETUP_STEPS = [
    {"key": "general", "icon": "⚙️", "title": "Général", "fields": [
        ("mod_role", "role", "🛡️ Rôle staff (modération)"),
        ("log_channel", "channel", "📝 Salon de logs (sanctions)"),
        ("welcome_channel", "channel", "👋 Salon de bienvenue"),
        ("goodbye_channel", "channel", "🚪 Salon de départ"),
    ]},
    {"key": "roles", "icon": "🎭", "title": "Rôles", "fields": [], "custom": "picker"},
    {"key": "tickets", "icon": "🎫", "title": "Tickets", "fields": [], "custom": "tickets"},
    {"key": "channels", "icon": "📢", "title": "Salons annexes", "fields": [], "custom": "picker"},
    {"key": "levels", "icon": "🏆", "title": "Rôles de niveau", "fields": [], "custom": "level_roles"},
    {"key": "logs", "icon": "📡", "title": "Système de logs", "fields": [], "custom": "logs_setup"},
    {"key": "managers", "icon": "👥", "title": "Gestionnaires du bot", "fields": [], "custom": "managers"},
    {"key": "security", "icon": "🛡️", "title": "Sécurité (AutoMod)", "fields": [], "custom": "security"},
    {"key": "summary", "icon": "●", "title": "Résumé et confirmation", "fields": [], "custom": "summary"},
]

# Pages "Rôles" et "Salons annexes" (Phase 2) : trop de champs pour tenir en menus
# déroulants directs sur une seule page (Discord limite un message à 5 lignes de
# composants, et il faut garder de la place pour la navigation). On affiche donc un
# premier menu "quel réglage voulez-vous changer ?", puis un second menu (rôle ou salon)
# apparaît juste en dessous une fois le premier choisi. Voir SetupView._render_picker().
PICKER_FIELDS = {
    "roles": [
        ("autorole", "role", "🎭 Rôle automatique à l'arrivée"),
        ("verify_role", "role", "● Rôle donné après vérification"),
        ("member_role", "role", "👤 Rôle membre"),
        ("booster_role", "role", "🚀 Rôle booster"),
        ("mute_role", "role", "🔇 Rôle mute / quarantaine"),
    ],
    "channels": [
        ("level_channel", "channel", "📈 Annonces de passage de niveau"),
        ("suggest_channel", "channel", "💡 Suggestions"),
        ("announce_channel", "channel", "📢 Annonces générales"),
        ("giveaway_channel", "channel", "🎉 Giveaways par défaut"),
        ("bot_commands_channel", "channel", "🤖 Commandes du bot"),
        ("report_channel", "channel", "🚨 Rapports"),
        ("partner_channel", "channel", "🤝 Partenariats"),
        ("stats_channel", "channel", "📊 Statistiques"),
        ("afk_channel", "channel", "💤 Salon AFK"),
        ("error_channel", "channel", "🐛 Erreurs du bot"),
    ],
}

FIELD_LABELS = {
    "mod_role": "🛡️ Rôle staff", "log_channel": "📝 Salon de logs", "welcome_channel": "👋 Salon de bienvenue",
    "goodbye_channel": "🚪 Salon de départ", "autorole": "🎭 Rôle automatique", "verify_role": "● Rôle de vérification",
    "member_role": "👤 Rôle membre", "booster_role": "🚀 Rôle booster", "mute_role": "🔇 Rôle mute/quarantaine",
    "level_channel": "📈 Annonces de niveau", "suggest_channel": "💡 Suggestions",
    "announce_channel": "📢 Annonces", "giveaway_channel": "🎉 Giveaways",
    "bot_commands_channel": "🤖 Commandes du bot", "report_channel": "🚨 Rapports",
    "partner_channel": "🤝 Partenariats", "stats_channel": "📊 Statistiques",
    "afk_channel": "💤 Salon AFK", "error_channel": "🐛 Erreurs du bot",
    "prefix": "⌨️ Préfixe", "welcome_message": "👋 Message de bienvenue", "goodbye_message": "🚪 Message de départ",
}

ROLE_FIELDS = {"mod_role", "autorole", "verify_role", "member_role", "booster_role", "mute_role"}


def _progress_text(page: int, total: int) -> str:
    """Indication de progression en TEXTE uniquement — aucune barre composée d'emojis, de
    carrés ou de blocs (demande explicite)."""
    percent = round((page + 1) / total * 100)
    return f"Étape {page + 1} sur {total} · {percent}% parcouru"


class SetupTextModal(discord.ui.Modal, title="Préfixe & messages"):
    """Formulaire pour les réglages texte (pas possible avec des menus déroulants)."""

    prefixe = discord.ui.TextInput(label="Préfixe des commandes (ex: +)", required=False, max_length=5)
    bienvenue = discord.ui.TextInput(
        label="Message de bienvenue ({member}, {server})", required=False,
        style=discord.TextStyle.paragraph, max_length=300,
    )
    depart = discord.ui.TextInput(
        label="Message de départ ({member}, {server})", required=False,
        style=discord.TextStyle.paragraph, max_length=300,
    )

    def __init__(self, view: "SetupView"):
        super().__init__()
        self.view_ref = view

    async def on_submit(self, interaction: discord.Interaction):
        if self.prefixe.value:
            self.view_ref.choices["prefix"] = self.prefixe.value
        if self.bienvenue.value:
            self.view_ref.choices["welcome_message"] = self.bienvenue.value
        if self.depart.value:
            self.view_ref.choices["goodbye_message"] = self.depart.value
        self.view_ref.dirty = True
        await self.view_ref.persist_session()
        await interaction.response.edit_message(embed=await self.view_ref.build_embed(), view=self.view_ref)


class LevelRoleModal(discord.ui.Modal, title="Ajouter un rôle de niveau"):
    """Formulaire pour associer un rôle récompense à un niveau atteint.

    Le rôle se choisissait en collant son identifiant, son nom ou une mention, et
    parse_role_input echouait des qu'on se trompait d'un caractere. discord.py 2.7
    permet un vrai selecteur de role dans une modale (composant Label) : la liste
    est celle du serveur, il n'y a plus rien a copier ni d'echec de saisie possible.
    """

    niveau = discord.ui.Label(
        text="Niveau requis",
        description="Le niveau à partir duquel le rôle est attribué.",
        component=discord.ui.TextInput(placeholder="5", required=True, max_length=5),
    )
    role = discord.ui.Label(
        text="Rôle à attribuer",
        description="Choisissez-le dans la liste du serveur.",
        component=discord.ui.RoleSelect(min_values=1, max_values=1),
    )

    def __init__(self, view: "SetupView"):
        super().__init__()
        self.view_ref = view

    async def on_submit(self, interaction: discord.Interaction):
        try:
            level = int(str(self.niveau.component.value).strip())
        except (ValueError, AttributeError):
            return await panels.envoyer(interaction.response, panels.depuis_embed(embeds.error('Entrez un nombre entier, par exemple 5.', title='Niveau invalide')), ephemere=True)
        choisis = list(getattr(self.role.component, "values", ()) or ())
        role = choisis[0] if choisis else None
        if role is not None and not isinstance(role, discord.Role):
            role = interaction.guild.get_role(int(getattr(role, "id", role)))
        if role is None:
            return await panels.envoyer(interaction.response, panels.depuis_embed(embeds.error('Sélectionnez un rôle dans la liste.', title='Aucun rôle choisi')), ephemere=True)

        existing = await self.view_ref.bot.db.fetchone(
            "SELECT * FROM level_roles WHERE guild_id = ? AND level = ?", (self.view_ref.guild_id, level)
        )
        if existing and existing["role_id"] != role.id:
            old_role = interaction.guild.get_role(existing["role_id"])
            confirm = helpers.ConfirmView(interaction.user.id, timeout=30)
            await panels.envoyer(interaction.response, panels.avec_composants(panels.depuis_embed(embeds.warning(f"Le niveau **{level}** est déjà associé à {(old_role.mention if old_role else 'un rôle supprimé')}. Voulez-vous le remplacer par {role.mention} ?")), confirm), ephemere=True)
            await confirm.wait()
            if not confirm.value:
                return

        await self.view_ref.bot.db.execute(
            "INSERT INTO level_roles (guild_id, level, role_id) VALUES (?, ?, ?) "
            "ON CONFLICT(guild_id, level) DO UPDATE SET role_id = excluded.role_id",
            (self.view_ref.guild_id, level, role.id),
        )
        self.view_ref.level_role_additions.append((level, role))
        await self.view_ref.persist_session()
        # _refresh_message gère le cas où la boîte de confirmation ci-dessus a déjà
        # utilisé la réponse de cette interaction (elle irait alors éditer le message
        # éphémère de confirmation par erreur, au lieu du vrai message de l'assistant).
        await self.view_ref._refresh_message(interaction)


class DeleteLevelRoleModal(discord.ui.Modal, title="Supprimer un palier de niveau"):
    """Formulaire minimal pour retirer un palier existant (page Rôles de niveau)."""

    niveau = discord.ui.TextInput(label="Niveau à supprimer (ex: 5)", required=True, max_length=5)

    def __init__(self, view: "SetupView"):
        super().__init__()
        self.view_ref = view

    async def on_submit(self, interaction: discord.Interaction):
        try:
            level = int(self.niveau.value.strip())
        except ValueError:
            return await interaction.response.send_message("Niveau invalide : entrez un nombre entier.", ephemeral=True)
        existing = await self.view_ref.bot.db.fetchone(
            "SELECT * FROM level_roles WHERE guild_id = ? AND level = ?", (self.view_ref.guild_id, level)
        )
        if not existing:
            return await interaction.response.send_message(f"Aucun palier trouvé au niveau **{level}**.", ephemeral=True)
        await self.view_ref.bot.db.execute(
            "DELETE FROM level_roles WHERE guild_id = ? AND level = ?", (self.view_ref.guild_id, level)
        )
        await interaction.response.edit_message(embed=await self.view_ref.build_embed(), view=self.view_ref)


# ---------------------------------------------------------------- CRÉATEUR DE RÔLE (page Rôles)
# Permet de créer un TOUT NOUVEAU rôle Discord (pas juste en assigner un déjà existant à un
# champ) directement depuis /setup : nom + couleur via un formulaire, puis permissions/
# affichage séparé/mentionnable via un second écran à cases à cocher. Volontairement limité
# aux permissions les plus demandées (25 options max pour un menu déroulant Discord).
ROLE_CREATOR_PERMISSIONS = [
    ("administrator", "👑 Administrateur (accès total — à utiliser avec prudence)"),
    ("manage_guild", "⚙️ Gérer le serveur"),
    ("manage_roles", "🎭 Gérer les rôles"),
    ("manage_channels", "📁 Gérer les salons"),
    ("manage_messages", "📝 Gérer les messages"),
    ("kick_members", "👢 Expulser des membres"),
    ("ban_members", "🔨 Bannir des membres"),
    ("moderate_members", "🔇 Rendre muet (timeout)"),
    ("manage_nicknames", "✏️ Gérer les pseudos"),
    ("mention_everyone", "📢 Mentionner @everyone"),
    ("view_channel", "👁️ Voir les salons"),
    ("send_messages", "💬 Envoyer des messages"),
    ("embed_links", "🔗 Intégrer des liens"),
    ("attach_files", "📎 Joindre des fichiers"),
    ("add_reactions", "😀 Ajouter des réactions"),
    ("connect", "🔊 Se connecter (vocal)"),
    ("speak", "🎙️ Parler (vocal)"),
    ("mute_members", "🔈 Couper le son des membres (vocal)"),
    ("move_members", "↔️ Déplacer les membres (vocal)"),
]

HEX_COLOUR_RE = re.compile(r"[0-9A-Fa-f]{6}")

# Noms de couleur courants (français + anglais) reconnus par +createrole quand le dernier
# mot de la commande n'est pas un code hexadécimal. Valeurs choisies en dur (pas via
# discord.Colour.xxx()) pour ne dépendre d'aucune méthode précise de la librairie.
COLOUR_NAME_ALIASES = {
    "rouge": "red", "red": "red",
    "bleu": "blue", "bleue": "blue", "blue": "blue",
    "vert": "green", "verte": "green", "green": "green",
    "jaune": "yellow", "yellow": "yellow",
    "or": "gold", "dore": "gold", "doré": "gold", "gold": "gold",
    "orange": "orange",
    "violet": "purple", "violette": "purple", "mauve": "purple", "purple": "purple",
    "rose": "pink", "pink": "pink", "magenta": "pink",
    "turquoise": "teal", "teal": "teal", "cyan": "teal",
    "gris": "grey", "grise": "grey", "grey": "grey", "gray": "grey",
    "noir": "black", "noire": "black", "black": "black",
    "blanc": "white", "blanche": "white", "white": "white",
    "marron": "brown", "brun": "brown", "brune": "brown", "brown": "brown",
    "blurple": "blurple", "discord": "blurple",
}

COLOUR_NAME_VALUES = {
    "red": 0xED4245,
    "green": 0x57F287,
    "blue": 0x3498DB,
    "yellow": 0xFEE75C,
    "gold": 0xF1C40F,
    "orange": 0xE67E22,
    "purple": 0x9B59B6,
    "pink": 0xEB459E,
    "teal": 0x1ABC9C,
    "grey": 0x95A5A6,
    "black": 0x000000,
    "white": 0xFFFFFF,
    "brown": 0x795548,
    "blurple": 0x5865F2,
}


def resolve_named_colour(text: str) -> int | None:
    """Retourne une valeur de couleur (int) à partir d'un nom courant (français ou
    anglais, voir COLOUR_NAME_ALIASES) ou d'un code hexadécimal (ex: 5865F2 ou #5865F2).
    Retourne None si le mot ne correspond à aucun des deux — dans ce cas, +createrole
    traite tout le texte comme un simple nom de rôle, sans couleur particulière."""
    raw = text.strip().lower()
    hex_candidate = raw.lstrip("#")
    if HEX_COLOUR_RE.fullmatch(hex_candidate):
        return int(hex_candidate, 16)
    canonical = COLOUR_NAME_ALIASES.get(raw)
    if canonical is None:
        return None
    return COLOUR_NAME_VALUES.get(canonical)


class CreateRoleModal(discord.ui.Modal, title="➕ Créer un nouveau rôle"):
    """Étape 1 : nom + couleur. Les permissions sont demandées juste après (étape 2, voir
    RoleCreatorPermsView) car un Modal Discord ne peut contenir que des champs texte —
    pas de menu déroulant possible ici."""

    nom = discord.ui.TextInput(label="Nom du rôle", required=True, max_length=100)
    couleur = discord.ui.TextInput(
        label="Couleur hex (ex: 5865F2) — laisser vide si aucune",
        required=False, max_length=7,
    )

    def __init__(self, view: "SetupView"):
        super().__init__()
        self.view_ref = view

    async def on_submit(self, interaction: discord.Interaction):
        name = self.nom.value.strip()
        if not name:
            return await interaction.response.send_message("○ Le nom du rôle ne peut pas être vide.", ephemeral=True)
        raw = self.couleur.value.strip().lstrip("#")
        if raw and not HEX_COLOUR_RE.fullmatch(raw):
            return await interaction.response.send_message(
                "○ Couleur invalide. Utilisez un code hexadécimal à 6 caractères (ex: `5865F2`), ou laissez le champ vide.",
                ephemeral=True,
            )
        colour_value = int(raw, 16) if raw else 0
        perms_view = RoleCreatorPermsView(self.view_ref, name, colour_value)
        e = embeds.neutral(
            "➕ Créer un nouveau rôle — étape 2/2",
            f"Nom : **{name}**\nCouleur : {'#' + raw.upper() if raw else '*Aucune*'}\n\n"
            "Sélectionnez les permissions à accorder (aucune sélection = simple rôle d'affichage, sans "
            "permission particulière), réglez l'affichage séparé/mentionnable si besoin, puis cliquez sur "
            "**● Créer le rôle**.",
            color=SETUP_COLOR_MAIN,
        )
        await panels.envoyer(interaction.response, panels.avec_composants(panels.depuis_embed(e), perms_view), ephemere=True)


class RoleCreatorPermsView(discord.ui.View):
    """Étape 2 : permissions (menu multi-sélection), affichage séparé (hoist) et
    mentionnable (deux boutons à bascule), puis création réelle du rôle."""

    def __init__(self, setup_view: "SetupView", name: str, colour_value: int):
        super().__init__(timeout=300)
        self.setup_view = setup_view
        self.name = name
        self.colour_value = colour_value
        self.selected_perms: set[str] = set()
        self.hoist = False
        self.mentionable = False
        self._admin_confirm_pending = False

        self.perm_select = discord.ui.Select(
            placeholder="🔑 Permissions à accorder (optionnel)",
            min_values=0, max_values=len(ROLE_CREATOR_PERMISSIONS),
            options=[discord.SelectOption(label=label, value=key) for key, label in ROLE_CREATOR_PERMISSIONS],
            row=0,
        )
        self.perm_select.callback = self._on_perms_changed
        self.add_item(self.perm_select)

        self.hoist_btn = discord.ui.Button(label="🚩 Affiché séparément : Non", style=discord.ButtonStyle.secondary, row=1)
        self.hoist_btn.callback = self._toggle_hoist
        self.add_item(self.hoist_btn)

        self.mention_btn = discord.ui.Button(label="📣 Mentionnable : Non", style=discord.ButtonStyle.secondary, row=1)
        self.mention_btn.callback = self._toggle_mentionable
        self.add_item(self.mention_btn)

        self.create_btn = discord.ui.Button(label="● Créer le rôle", style=discord.ButtonStyle.success, row=2)
        self.create_btn.callback = self._create_clicked
        self.add_item(self.create_btn)

        self.cancel_btn = discord.ui.Button(label="○ Annuler", style=discord.ButtonStyle.danger, row=2)
        self.cancel_btn.callback = self._cancel_clicked
        self.add_item(self.cancel_btn)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await self.setup_view.interaction_check(interaction)

    async def _on_perms_changed(self, interaction: discord.Interaction):
        self.selected_perms = set(self.perm_select.values)
        self._admin_confirm_pending = False  # tout changement de sélection annule une confirmation Administrateur en attente
        await interaction.response.defer()

    async def _toggle_hoist(self, interaction: discord.Interaction):
        self.hoist = not self.hoist
        self.hoist_btn.label = f"🚩 Affiché séparément : {'Oui' if self.hoist else 'Non'}"
        await interaction.response.edit_message(view=self)

    async def _toggle_mentionable(self, interaction: discord.Interaction):
        self.mentionable = not self.mentionable
        self.mention_btn.label = f"📣 Mentionnable : {'Oui' if self.mentionable else 'Non'}"
        await interaction.response.edit_message(view=self)

    async def _cancel_clicked(self, interaction: discord.Interaction):
        for item in self.children:
            item.disabled = True
        await panels.editer(interaction.response, panels.avec_composants(panels.depuis_embed(embeds.neutral('○ Création annulée', "Aucun rôle n'a été créé.", color=SETUP_COLOR_MAIN)), self))

    async def _create_clicked(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild.me.guild_permissions.manage_roles:
            return await interaction.response.send_message(
                "⚠️ SentriX n'a pas la permission **Gérer les rôles** sur ce serveur — impossible de créer un rôle. "
                "Donnez cette permission au bot puis réessayez.",
                ephemeral=True,
            )
        # Comme partout ailleurs dans /setup (voir _validate_role_selection), un rôle
        # Administrateur exige une confirmation explicite avant d'être créé — deuxième clic
        # requis, jamais créé silencieusement.
        if "administrator" in self.selected_perms and not self._admin_confirm_pending:
            self._admin_confirm_pending = True
            return await interaction.response.send_message(
                "⚠️ Ce rôle aura la permission **Administrateur** (accès total au serveur). "
                "Cliquez à nouveau sur **● Créer le rôle** pour confirmer.",
                ephemeral=True,
            )
        try:
            perms_kwargs = {p: True for p in self.selected_perms}
            role = await guild.create_role(
                name=self.name,
                colour=discord.Colour(self.colour_value),
                permissions=discord.Permissions(**perms_kwargs),
                hoist=self.hoist,
                mentionable=self.mentionable,
                reason=f"Créé via /setup par {interaction.user}",
            )
        except discord.HTTPException as exc:
            return await interaction.response.send_message(
                f"○ La création du rôle a échoué (`{type(exc).__name__}`). Le serveur a peut-être atteint la "
                "limite de 250 rôles, ou SentriX n'a plus la permission nécessaire.",
                ephemeral=True,
            )
        await self.setup_view.bot.db.log_setup_history(
            self.setup_view.guild_id, interaction.user.id, "Rôles", "rôle créé",
            new_value=f"{role.name} (#{role.id})",
        )
        for item in self.children:
            item.disabled = True
        e = embeds.success(f"● Le rôle {role.mention} a été créé avec succès.")
        await panels.editer(interaction.response, panels.avec_composants(panels.depuis_embed(e), self))


class SetupNavButton(
    discord.ui.DynamicItem[discord.ui.Button],
    # "prev"/"next" restent acceptés (rétrocompatibilité avec d'anciens messages /setup déjà
    # envoyés avant cette refonte) même s'ils ne sont plus émis par render_page() — retirer
    # une action du template casserait les boutons de vieux messages encore affichés.
    template=r"setup:(?P<action>prev|save|next|preview|cancel|summary|finish|restart|home|history):(?P<message_id>[0-9]+)",
):
    """Bouton de navigation du /setup. Son custom_id encode l'action ET l'ID du message,
    ce qui permet à Discord de le retrouver et de le faire fonctionner même si le bot a
    redémarré entre-temps (voir Configuration.handle_setup_nav, qui reconstruit alors
    l'assistant depuis la table setup_sessions). C'est ce qui rend le /setup persistant."""

    def __init__(self, action: str, message_id: int, *, label: str, style: discord.ButtonStyle, disabled: bool = False, row: int = 4):
        super().__init__(
            discord.ui.Button(label=label, style=style, disabled=disabled, row=row, custom_id=f"setup:{action}:{message_id}")
        )
        self.action = action
        self.message_id = message_id

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button, match: re.Match, /):
        return cls(match["action"], int(match["message_id"]), label=item.label or "…", style=item.style, disabled=item.disabled)

    async def callback(self, interaction: discord.Interaction):
        cog = interaction.client.get_cog("Configuration")
        if cog is None:
            return await interaction.response.send_message("○ Le module de configuration n'est pas chargé.", ephemeral=True)
        await cog.handle_setup_nav(interaction, self.action, self.message_id)


class LogsSetupView(discord.ui.View):
    """Panneau de +logsetup — deux états dans une seule vue : liste des catégories
    (self.current_type is None), ou détail d'une catégorie précise (Activer/Désactiver,
    Choisir le salon, Tester, Retour). Verrouillée à l'auteur de la commande."""

    def __init__(self, cog: "Configuration", *, author_id: int | None, guild_id: int, timeout: float = 300):
        super().__init__(timeout=timeout)
        self.cog = cog
        self.author_id = author_id
        self.guild_id = guild_id
        self.current_type: str | None = None
        self.message: discord.Message | None = None
        self._render_home()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if self.author_id is not None and interaction.user.id != self.author_id:
            await panels.envoyer(interaction.response, panels.depuis_embed(embeds.error("Vous n'êtes pas autorisé à utiliser ce panneau.")), ephemere=True)
            return False
        return True

    async def on_timeout(self):
        if self.message:
            try:
                await self.message.edit(view=None)
            except discord.HTTPException:
                pass

    # ---------------------------------------------------------------- ÉTAT : ACCUEIL

    def _render_home(self):
        self.clear_items()
        options = []
        for category, types in log_service.categories_with_types().items():
            log_type = types[0]  # 1 catégorie == 1 type de log dans cette version
            options.append(discord.SelectOption(
                label=category, value=log_type,
                description=log_service.LOG_TYPES[log_type]["label"][:100],
            ))
        select = discord.ui.Select(placeholder="📂 Choisir une catégorie de logs...", options=options, row=0)
        select.callback = self._make_category_callback(select)
        self.add_item(select)
        # Les symboles typographiques comme "○" ne sont pas des emojis Discord
        # valides dans un composant et provoquent HTTP 400 / Invalid Form Body.
        close_btn = discord.ui.Button(label="Fermer", style=discord.ButtonStyle.secondary, row=1)
        close_btn.callback = self._close_clicked
        self.add_item(close_btn)

    def _make_category_callback(self, select: discord.ui.Select):
        async def callback(interaction: discord.Interaction):
            self.current_type = select.values[0]
            await self._refresh(interaction)
        return callback

    async def _close_clicked(self, interaction: discord.Interaction):
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)
        self.stop()

    # ---------------------------------------------------------------- ÉTAT : DÉTAIL D'UN TYPE

    async def _render_detail(self, guild: discord.Guild) -> discord.Embed:
        self.clear_items()
        log_type = self.current_type
        meta = log_service.LOG_TYPES[log_type]
        setting = await log_service.get_log_setting(self.cog.bot, guild.id, log_type)

        e = embeds.neutral(f"📝 {meta['label']}")
        e.add_field(name="État", value="🟢 Activé" if setting["enabled"] else "⚪ Désactivé", inline=True)
        channel = guild.get_channel(setting["channel_id"]) if setting["channel_id"] else None
        e.add_field(name="Salon", value=channel.mention if channel else "Non configuré", inline=True)
        if not meta["emits"]:
            e.add_field(
                name="⚠️ À savoir",
                value="Cette catégorie est configurable, mais aucun événement du bot ne l'utilise encore pour envoyer un log automatiquement.",
                inline=False,
            )
        if log_type == "messages":
            e.add_field(name="Inclure le contenu", value="Oui" if setting["include_content"] else "Non", inline=True)
            e.add_field(name="Inclure les pièces jointes", value="Oui" if setting["include_attachments"] else "Non", inline=True)
            e.add_field(name="Inclure l'auteur", value="Oui" if setting["include_actor"] else "Non", inline=True)

        toggle_btn = discord.ui.Button(
            label="Désactiver" if setting["enabled"] else "Activer",
            style=discord.ButtonStyle.danger if setting["enabled"] else discord.ButtonStyle.success,
            emoji="🔴" if setting["enabled"] else "🟢", row=0,
        )
        toggle_btn.callback = self._toggle_clicked
        self.add_item(toggle_btn)

        test_btn = discord.ui.Button(label="Tester", style=discord.ButtonStyle.secondary, emoji="🧪", row=0)
        test_btn.callback = self._test_clicked
        self.add_item(test_btn)

        back_btn = discord.ui.Button(label="Retour", style=discord.ButtonStyle.secondary, row=0)
        back_btn.callback = self._back_clicked
        self.add_item(back_btn)

        channel_select = discord.ui.ChannelSelect(
            placeholder="📁 Choisir le salon pour ce log...", channel_types=[discord.ChannelType.text], row=1,
        )
        channel_select.callback = self._make_channel_callback(channel_select)
        self.add_item(channel_select)

        return e

    def _make_channel_callback(self, select: discord.ui.ChannelSelect):
        async def callback(interaction: discord.Interaction):
            salon = select.values[0]
            resolved = interaction.guild.get_channel(salon.id) if hasattr(salon, "id") else salon
            channel_id = resolved.id if resolved else None
            ok, reason = log_service.validate_channel(interaction.guild, channel_id)
            if not ok:
                return await panels.envoyer(interaction.response, panels.depuis_embed(embeds.error(f"Impossible d'utiliser ce salon : {reason}.")), ephemere=True)
            await log_service.set_log_channel(self.cog.bot, interaction.guild.id, self.current_type, channel_id)
            await self._refresh(interaction)
        return callback

    async def _toggle_clicked(self, interaction: discord.Interaction):
        setting = await log_service.get_log_setting(self.cog.bot, interaction.guild.id, self.current_type)
        if not setting["enabled"]:
            try:
                await log_service.set_log_enabled(self.cog.bot, interaction.guild.id, self.current_type, True)
            except ValueError:
                return await panels.envoyer(interaction.response, panels.depuis_embed(embeds.error("○ Vous devez d'abord choisir un salon valide avant d'activer ce log.")), ephemere=True)
        else:
            await log_service.set_log_enabled(self.cog.bot, interaction.guild.id, self.current_type, False)
        await self._refresh(interaction)

    async def _test_clicked(self, interaction: discord.Interaction):
        ok, message = await log_service.send_test_log(self.cog.bot, interaction.guild, self.current_type, interaction.user)
        await panels.envoyer(interaction.response, panels.depuis_embed(embeds.success(message) if ok else embeds.error(message)), ephemere=True)

    async def _back_clicked(self, interaction: discord.Interaction):
        self.current_type = None
        self._render_home()
        e, _ = await self.cog._build_logs_home(self.guild_id)
        await interaction.response.edit_message(embed=e, view=self)

    async def _refresh(self, interaction: discord.Interaction):
        e = await self._render_detail(interaction.guild)
        if interaction.response.is_done():
            await interaction.edit_original_response(embed=e, view=self)
        else:
            await interaction.response.edit_message(embed=e, view=self)


class SetupLockPromptView(discord.ui.View):
    """Affichée quand un admin lance /setup alors qu'une autre session est déjà ouverte sur
    ce serveur (voir "verrouillage de session" demandé). Vue courte (timeout 60s) — pas
    besoin de survivre à un redémarrage, contrairement au panneau /setup lui-même."""

    def __init__(self, cog: "Configuration", guild_id: int, locked_message_id: int,
                 locked_author_id: int, locked_author_name: str, requester_id: int):
        super().__init__(timeout=60)
        self.cog = cog
        self.guild_id = guild_id
        self.locked_message_id = locked_message_id
        self.locked_author_id = locked_author_id
        self.locked_author_name = locked_author_name
        self.requester_id = requester_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message("○ Vous n'êtes pas autorisé à utiliser ce panneau.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="👁️ Voir uniquement", style=discord.ButtonStyle.secondary, row=0)
    async def view_only(self, interaction: discord.Interaction, button: discord.ui.Button):
        live_view = self.cog.active_setups.get(self.locked_message_id)
        if live_view:
            embed = await live_view.build_embed()
        else:
            embed = embeds.neutral(
                "👁️ Aperçu (lecture seule)",
                "Session introuvable en mémoire pour l'instant — relancez `/setup` si besoin.",
                color=SETUP_COLOR_MAIN,
            )
        embed.set_footer(text=f"Lecture seule — session ouverte par {self.locked_author_name}")
        await panels.envoyer(interaction.response, panels.depuis_embed(embed), ephemere=True)

    @discord.ui.button(label="🔄 Prendre le contrôle", style=discord.ButtonStyle.primary, row=0)
    async def take_control(self, interaction: discord.Interaction, button: discord.ui.Button):
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)

        old_view = self.cog.active_setups.pop(self.locked_message_id, None)
        if old_view:
            for child in old_view.children:
                child.disabled = True
            old_view.stop()
            try:
                channel = self.cog.bot.get_channel(old_view.channel_id)
                if channel:
                    old_message = await channel.fetch_message(self.locked_message_id)
                    await panels.editer(old_message, panels.avec_composants(panels.depuis_embed(embeds.neutral('🔄 Contrôle transféré', f'{interaction.user} a pris le contrôle de cette session de configuration.', color=SETUP_COLOR_WARNING)), old_view))
            except discord.HTTPException:
                pass
        await self.cog.bot.db.delete_setup_session(self.locked_message_id)
        self.cog.release_lock(self.guild_id, self.locked_message_id)
        await self.cog.bot.db.log_setup_history(
            self.guild_id, interaction.user.id, "Configuration", "prise de contrôle", old_value=self.locked_author_name,
        )
        message, _view = await self.cog._open_setup_panel(interaction.channel, author=interaction.user)
        await panels.envoyer(interaction.followup, panels.depuis_embed(embeds.success(f'Vous avez pris le contrôle — nouveau panneau : {message.jump_url}')), ephemere=True)

    @discord.ui.button(label="○ Annuler", style=discord.ButtonStyle.danger, row=0)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)

    async def on_error(self, interaction: discord.Interaction, error: Exception, item=None) -> None:
        try:
            if interaction.response.is_done():
                await panels.envoyer(interaction.followup, panels.depuis_embed(embeds.error('Une erreur inattendue est survenue.')), ephemere=True)
            else:
                await panels.envoyer(interaction.response, panels.depuis_embed(embeds.error('Une erreur inattendue est survenue.')), ephemere=True)
        except discord.HTTPException:
            pass


class SetupView(discord.ui.View):
    """
    Assistant /setup complet, en 9 pages. Les réglages "simples" (rôles/salons choisis
    par menu déroulant) restent en attente dans self.choices jusqu'à un clic sur
    💾 Enregistrer (ou la page 9) ; les actions plus lourdes (rôles de niveau, logs,
    gestionnaires, sécurité) restent enregistrées immédiatement comme avant, car elles
    créent ou modifient des choses côté Discord (salons, rôles) qu'on ne veut pas
    "annuler" facilement une fois faites.
    """

    def __init__(
        self, bot: commands.Bot, guild_id: int, author_id: int, message_id: int, channel_id: int,
        existing_managers: dict | None = None, existing_security: dict | None = None,
        existing_exempt_roles: list[int] | None = None,
    ):
        super().__init__(timeout=None)  # timeout=None : géré manuellement, survit aux redémarrages
        self.bot = bot
        self.guild_id = guild_id
        self.author_id = author_id
        self.message_id = message_id
        self.channel_id = channel_id
        self.choices: dict = {}
        self.dirty = False
        self.level_role_additions: list[tuple[int, discord.Role]] = []
        self.logs_created: list[discord.TextChannel] = []
        self.managers: dict[int, str] = dict(existing_managers or {})
        self.security_choices: dict[str, int] = dict(existing_security or {field: 0 for field in AUTOMOD_TOGGLE_LABELS})
        self.security_touched = False  # True dès qu'on clique un préréglage ou qu'on change le menu de filtres
        self.exempt_role_ids: set[int] = set(existing_exempt_roles or [])
        self.picker_selected: str | None = None  # champ en cours de réglage sur la page "picker" (Rôles / Salons)
        self.level_action: str | None = None  # "edit" ou "delete" en attente d'un niveau choisi (page Rôles de niveau)
        self.selected_level: int | None = None
        self.manager_being_edited: int | None = None  # gestionnaire dont on édite les catégories (page Gestionnaires)
        self.manager_categories_cache: dict[int, list[str]] = {}
        self.page = -1  # -1 = page d'accueil (menu de catégories) — plus de parcours forcé
        self.render_page()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        cog = self.bot.get_cog("Configuration")
        if cog is None:
            await interaction.response.send_message("○ Le module de configuration n'est pas chargé.", ephemeral=True)
            return False
        return await cog._can_use_setup(interaction, self.author_id, self.guild_id)

    async def persist_session(self):
        try:
            await self.bot.db.save_setup_session(
                self.message_id, self.guild_id, self.channel_id, self.author_id,
                self.page, json.dumps(self.choices),
            )
        except Exception:
            pass  # la persistance ne doit jamais faire planter l'assistant

    def _guild(self) -> discord.Guild | None:
        return self.bot.get_guild(self.guild_id)

    def _mention_current(self, field: str, conf) -> str:
        """Formate la valeur actuelle d'un champ (choix en attente, sinon valeur déjà
        enregistrée en base) sous forme de mention @rôle / #salon, pour l'afficher
        immédiatement dans l'embed comme demandé."""
        value = self.choices.get(field, conf[field] if conf and field in conf.keys() else None)
        if not value:
            return "*Non défini*"
        guild = self._guild()
        if not guild:
            return f"`{value}`"
        obj = guild.get_role(value) if field in ROLE_FIELDS else guild.get_channel(value)
        return obj.mention if obj else "*Introuvable (supprimé ?)*"

    def _status_indicator(self) -> str:
        if self.dirty:
            return "🟠 Modifications non enregistrées"
        if self.choices or self.level_role_additions or self.logs_created or self.managers or self.security_touched:
            return "🟢 Configuration enregistrée"
        return "⚪ Rien configuré pour l'instant"

    async def build_embed(self) -> discord.Embed:
        if self.page == -1:
            return await self._build_home_embed()
        step = SETUP_STEPS[self.page]
        header = f"🛠️ **Configuration SentriX**\nCatégorie : {step['icon']} {step['title']}"
        conf = await self.bot.db.get_guild_config(self.guild_id)

        if step["key"] in ("roles", "channels"):
            fields = PICKER_FIELDS[step["key"]]
            noun = "rôle" if step["key"] == "roles" else "salon"
            desc = (
                f"Choisissez d'abord **quel réglage** vous voulez changer dans le premier menu, "
                f"puis le {noun} correspondant apparaît juste en dessous.\n\n"
                "Valeurs actuelles :"
            )
            e = embeds.neutral(header, desc, color=SETUP_COLOR_MAIN)
            lines = [f"{label} : {self._mention_current(field, conf)}" for field, kind, label in fields]
            e.add_field(name="📋 État actuel", value="\n".join(lines)[:1024], inline=False)
            if step["key"] == "roles":
                exempt_text = ", ".join(f"<@&{rid}>" for rid in self.exempt_role_ids) if self.exempt_role_ids else "Aucun"
                e.add_field(name="🚫 Rôles exemptés de l'AutoMod", value=exempt_text[:1024], inline=False)
            if self.picker_selected:
                picked_label = next((label for f, k, label in fields if f == self.picker_selected), self.picker_selected)
                e.add_field(name="👉 En cours de réglage", value=picked_label, inline=False)

        elif step["key"] == "levels":
            rows = await self.bot.db.fetchall(
                "SELECT * FROM level_roles WHERE guild_id = ? ORDER BY level ASC", (self.guild_id,)
            )
            desc = (
                "Attribuez automatiquement un rôle quand un membre atteint un certain niveau. "
                "Cliquez sur **➕ Ajouter un rôle de niveau** pour chaque palier souhaité.\n\n"
                "⚠️ Chaque ajout ici est enregistré **immédiatement** (pas besoin de 💾 Enregistrer)."
            )
            e = embeds.neutral(header, desc, color=SETUP_COLOR_MAIN)
            guild = self._guild()
            if rows:
                lines = []
                for r in rows:
                    role = guild.get_role(r["role_id"]) if guild else None
                    lines.append(f"Niveau **{r['level']}** → {role.mention if role else '*rôle supprimé*'}")
                e.add_field(name=f"🏆 Paliers actuels ({len(rows)})", value="\n".join(lines)[:1024], inline=False)
            else:
                e.add_field(name="🏆 Paliers actuels", value="Aucun pour l'instant.", inline=False)

        elif step["key"] == "tickets":
            panels = await self.bot.db.fetchall("SELECT * FROM ticket_panels_v2 WHERE guild_id = ?", (self.guild_id,))
            types = await self.bot.db.fetchall(
                "SELECT tt.* FROM ticket_types tt JOIN ticket_panels_v2 p ON p.id = tt.panel_id WHERE p.guild_id = ?",
                (self.guild_id,),
            )
            desc = (
                "Le système de tickets a sa propre configuration complète (plusieurs panels, types, "
                "formulaires, boutons staff...), bien plus riche que ce que cette page pourrait afficher.\n\n"
                "👉 Utilisez **`+ticketsetup`** pour tout configurer, ou les boutons ci-dessous pour un accès rapide."
            )
            e = embeds.neutral(header, desc, color=SETUP_COLOR_MAIN)
            e.add_field(name="📋 Panels", value=str(len(panels)), inline=True)
            e.add_field(name="🎫 Types de tickets", value=str(len(types)), inline=True)
            ticket_log = f"<#{conf['ticket_log_channel']}>" if conf and conf["ticket_log_channel"] else "*Non défini*"
            e.add_field(name="📝 Salon de logs (repli)", value=ticket_log, inline=True)
            e.add_field(name="⏱️ Suppression après fermeture", value=f"{(conf['ticket_delete_delay'] if conf else 30) or 30}s", inline=True)
            e.add_field(name="📄 Transcript par DM", value="● Activé" if (not conf or conf["ticket_transcript_dm"]) else "○ Désactivé", inline=True)
            e.add_field(name="⭐ Notation du support", value="● Activée" if (not conf or conf["ticket_rating_enabled"]) else "○ Désactivée", inline=True)

        elif step["key"] == "logs":
            desc = (
                "Créez en un clic toute une catégorie de salons de logs privés — le bot y écrit tout seul "
                "ensuite. Les salons déjà configurés ne sont jamais dupliqués.\n\n"
                "Cliquez sur **📡 Créer le système de logs** ci-dessous."
            )
            e = embeds.neutral(header, desc, color=SETUP_COLOR_MAIN)
            general = f"<#{conf['log_channel']}>" if conf and conf["log_channel"] else "*Non défini*"
            e.add_field(name="📝 Salon général de repli", value=general, inline=False)
            if self.logs_created:
                e.add_field(name=f"● Créés dans cette session ({len(self.logs_created)})", value="\n".join(c.mention for c in self.logs_created)[:1024], inline=False)

        elif step["key"] == "managers":
            desc = (
                "Ajoutez des membres de confiance qui pourront configurer le bot sans avoir besoin d'être "
                "administrateur du serveur.\n\nAjout/retrait immédiat. Utilisez **🔑 Définir les permissions** "
                "pour limiter un gestionnaire à certaines catégories seulement (sinon, accès complet par défaut)."
            )
            e = embeds.neutral(header, desc, color=SETUP_COLOR_MAIN)
            if self.managers:
                lines = []
                for uid in self.managers:
                    cats = self.manager_categories_cache.get(uid)
                    if cats is None:
                        cats = await self.bot.db.get_manager_categories(self.guild_id, uid)
                        self.manager_categories_cache[uid] = cats or ["complete"]
                        cats = self.manager_categories_cache[uid]
                    labels = ", ".join(MANAGER_CATEGORIES.get(c, c) for c in cats)
                    lines.append(f"<@{uid}> — {labels}")
                e.add_field(name=f"👥 Gestionnaires actuels ({len(self.managers)})", value="\n".join(lines)[:1024], inline=False)
            else:
                e.add_field(name="👥 Gestionnaires actuels", value="Aucun pour l'instant.", inline=False)

        elif step["key"] == "security":
            desc = (
                "Choisissez un préréglage (Faible, Moyen ou Élevé) pour tout régler en un clic, "
                "ou sélectionnez précisément les filtres actifs dans le menu. "
                "Chaque changement est enregistré immédiatement."
            )
            e = embeds.neutral(header, desc, color=SETUP_COLOR_MAIN)
            active = sum(1 for v in self.security_choices.values() if v)
            score = round(active / len(AUTOMOD_TOGGLE_LABELS) * 100)
            e.add_field(name="Score de sécurité", value=f"**{score}/100** ({active}/{len(AUTOMOD_TOGGLE_LABELS)} filtres actifs)", inline=False)
            lines = [f"**{label}** : {'Actif' if self.security_choices.get(field) else 'Inactif'}" for field, label in AUTOMOD_TOGGLE_LABELS.items()]
            e.add_field(name="État des filtres", value="\n".join(lines), inline=False)

        elif step["key"] == "summary":
            e = await self._build_summary_embed()

        else:
            desc = "Choisissez vos options avec les menus ci-dessous. Laissez vide ce que vous ne voulez pas changer."
            if step["key"] == "general":
                desc += "\nUtilisez **✏️ Préfixe & messages** pour le préfixe et les messages de bienvenue/départ."
            e = embeds.neutral(header, desc, color=SETUP_COLOR_MAIN)
            for field, kind, label in step["fields"]:
                e.add_field(name=label, value=self._mention_current(field, conf), inline=True)

        e.add_field(name="​", value=self._status_indicator(), inline=False)
        return e

    async def _compute_categories(self, conf) -> list[tuple[str, str]]:
        """État textuel de chaque catégorie actuellement implémentée dans /setup. Réutilisé
        par la page d'accueil et le résumé — ne liste QUE les 8 catégories réelles de cette
        phase (les autres modules du bot, comme l'IA ou les statistiques, ont leur propre
        commande de configuration séparée pour l'instant, voir Phases suivantes)."""
        rows_levels = await self.bot.db.fetchall("SELECT COUNT(*) AS n FROM level_roles WHERE guild_id = ?", (self.guild_id,))
        rows_panels = await self.bot.db.fetchall("SELECT COUNT(*) AS n FROM ticket_panels_v2 WHERE guild_id = ?", (self.guild_id,))
        n_levels = rows_levels[0]["n"] if rows_levels else 0
        n_panels = rows_panels[0]["n"] if rows_panels else 0
        active_security = sum(1 for v in self.security_choices.values() if v)

        def cur(field):
            return self.choices.get(field, conf[field] if conf and field in conf.keys() else None)

        return [
            ("Général", "Configuré" if cur("mod_role") and cur("log_channel") else ("Partiel" if cur("mod_role") or cur("log_channel") else "Non configuré")),
            ("Rôles", "Configuré" if cur("autorole") or cur("verify_role") else "Partiel"),
            ("Tickets", "Configuré" if n_panels else "Partiel"),
            ("Salons annexes", "Configuré" if any(cur(f) for f in ("level_channel", "suggest_channel", "announce_channel", "giveaway_channel")) else "Partiel"),
            ("Rôles de niveau", "Configuré" if n_levels else "Partiel"),
            ("Logs", "Configuré" if cur("log_channel") else "Non configuré"),
            ("Gestionnaires", "Configuré" if self.managers else "Partiel"),
            ("Sécurité", "Configuré" if active_security >= 6 else ("Partiel" if active_security > 0 else "Non configuré")),
        ]

    async def _build_home_embed(self) -> discord.Embed:
        """Page d'accueil du centre de configuration — remplace l'ancien parcours linéaire
        forcé : on choisit directement une catégorie dans le menu déroulant, comme +help."""
        conf = await self.bot.db.get_guild_config(self.guild_id)
        guild = self._guild()
        categories = await self._compute_categories(conf)
        configured = sum(1 for _, s in categories if s == "Configuré")
        critical = sum(1 for _, s in categories if s == "Non configuré")
        warnings = sum(1 for _, s in categories if s == "Partiel")

        if critical:
            etat = "Configuration incomplète — éléments critiques manquants"
        elif warnings:
            etat = "Configuration partielle"
        else:
            etat = "Configuration à jour"

        e = embeds.neutral(
            "⚙️ CENTRE DE CONFIGURATION SENTRIX",
            "Configurez les modules de SentriX pour ce serveur. Choisissez une catégorie "
            "dans le menu ci-dessous, ou consultez le résumé complet.",
            color=SETUP_COLOR_MAIN,
        )
        e.add_field(name="Serveur", value=guild.name if guild else "Inconnu", inline=True)
        e.add_field(name="Modules configurés", value=f"{configured} sur {len(categories)}", inline=True)
        e.add_field(name="État général", value=etat, inline=True)
        e.add_field(name="Problèmes critiques", value=str(critical), inline=True)
        e.add_field(name="Avertissements", value=str(warnings), inline=True)

        last = await self.bot.db.list_setup_history(self.guild_id, limit=1)
        if last:
            row = last[0]
            e.add_field(name="Dernière modification", value=f"<t:{row['created_at']}:R> par <@{row['user_id']}>", inline=True)
        else:
            e.add_field(name="Dernière modification", value="Aucune enregistrée pour l'instant", inline=True)

        e.add_field(
            name="Catégories disponibles ici",
            value="\n".join(f"**{name}** : {status}" for name, status in categories),
            inline=False,
        )
        e.add_field(
            name="Autres modules (commandes séparées pour l'instant)",
            value=(
                "🎫 Tickets détaillés → `+ticketsetup` · 🤖 IA → `+aisetup` · 📊 Stats/Niveaux → "
                "`+statsconfig` · 💾 Sauvegardes serveur → `/server-backup`, `/role-snapshot`"
            ),
            inline=False,
        )
        return e

    async def _build_summary_embed(self) -> discord.Embed:
        conf = await self.bot.db.get_guild_config(self.guild_id)
        guild = self._guild()
        header = "🛠️ **Configuration SentriX**\n📋 Résumé et confirmation"
        e = embeds.neutral(header, "Voici l'état actuel de chaque catégorie.", color=SETUP_COLOR_MAIN)

        categories = await self._compute_categories(conf)
        configured_count = sum(1 for _, status in categories if status == "Configuré")
        e.add_field(
            name=f"Modules configurés : {configured_count} sur {len(categories)}",
            value="\n".join(f"**{name}** : {status}" for name, status in categories),
            inline=False,
        )

        checks_lines = await self._run_final_checks(guild, conf)
        e.add_field(name="🔎 Vérifications finales", value="\n".join(checks_lines)[:1024], inline=False)
        return e

    async def _run_final_checks(self, guild: discord.Guild | None, conf) -> list[str]:
        lines = []
        if not guild:
            return ["○ Serveur introuvable (le bot n'y est peut-être plus)."]
        me = guild.me
        perms = me.guild_permissions if me else None
        lines.append("● Permissions de base du bot" if perms and perms.manage_roles and perms.manage_channels else "⚠️ Il manque des permissions au bot (Gérer les rôles / salons)")
        lines.append("● Rôle staff configuré" if conf and conf["mod_role"] else "⚠️ Aucun rôle staff configuré (page Général)")
        lines.append("● Salon de logs configuré" if conf and conf["log_channel"] else "⚠️ Aucun salon de logs configuré (page Logs)")
        active_security = sum(1 for v in self.security_choices.values() if v)
        lines.append("● Sécurité active" if active_security > 0 else "○ Aucune protection AutoMod active — le serveur n'est pas protégé")
        if conf and conf["autorole"]:
            role = guild.get_role(conf["autorole"])
            lines.append("● Rôle automatique valide" if role else "⚠️ Le rôle automatique configuré n'existe plus")
        return lines

    def _render_home(self):
        """Menu déroulant de catégories (façon +help) + accès direct au résumé/historique/
        fermeture — remplace le parcours forcé page par page."""
        self.clear_items()
        cat_select = discord.ui.Select(
            placeholder="📂 Choisir une catégorie à configurer",
            options=[
                discord.SelectOption(label=f"{s['icon']} {s['title']}", value=str(i))
                for i, s in enumerate(SETUP_STEPS) if s["key"] != "summary"
            ],
            row=0,
        )
        cat_select.callback = self._make_home_category_callback(cat_select)
        self.add_item(cat_select)
        self.add_item(SetupNavButton("summary", self.message_id, label="📋 Résumé", style=discord.ButtonStyle.secondary, row=1))
        self.add_item(SetupNavButton("history", self.message_id, label="📜 Historique", style=discord.ButtonStyle.secondary, row=1))
        self.add_item(SetupNavButton("cancel", self.message_id, label="○ Fermer", style=discord.ButtonStyle.danger, row=1))

    def _make_home_category_callback(self, select: discord.ui.Select):
        async def callback(interaction: discord.Interaction):
            if select.values:
                self.page = int(select.values[0])
                self.render_page()
                await self.persist_session()
            await self._refresh_message(interaction)
        return callback

    def render_page(self):
        if self.page == -1:
            self._render_home()
            return
        self.clear_items()
        step = SETUP_STEPS[self.page]

        if step["key"] in ("roles", "channels"):
            fields = PICKER_FIELDS[step["key"]]
            noun = "rôle" if step["key"] == "roles" else "salon"
            cat_select = discord.ui.Select(
                placeholder=f"Choisissez un {noun} à régler",
                options=[discord.SelectOption(label=label, value=field) for field, kind, label in fields],
                row=0,
            )
            cat_select.callback = self._make_picker_category_callback(cat_select)
            self.add_item(cat_select)
            if self.picker_selected:
                kind = next((k for f, k, l in fields if f == self.picker_selected), "role")
                picked_label = next((l for f, k, l in fields if f == self.picker_selected), self.picker_selected)
                if kind == "role":
                    value_select = discord.ui.RoleSelect(placeholder=f"Choisir : {picked_label}"[:100], row=1)
                    value_select.callback = self._make_picker_role_value_callback(self.picker_selected, value_select)
                else:
                    value_select = discord.ui.ChannelSelect(
                        placeholder=f"Choisir : {picked_label}"[:100], channel_types=[discord.ChannelType.text], row=1
                    )
                    value_select.callback = self._make_picker_channel_value_callback(self.picker_selected, value_select)
                self.add_item(value_select)
            if step["key"] == "roles":
                exempt_select = discord.ui.RoleSelect(
                    placeholder="🚫 Rôles exemptés de l'AutoMod (multi-sélection)",
                    min_values=0, max_values=25, row=2,
                    default_values=[discord.Object(id=rid) for rid in self.exempt_role_ids],
                )
                exempt_select.callback = self._make_exempt_roles_callback(exempt_select)
                self.add_item(exempt_select)
                create_role_btn = discord.ui.Button(label="➕ Créer un nouveau rôle", style=discord.ButtonStyle.primary, row=3)
                create_role_btn.callback = self._open_create_role_modal
                self.add_item(create_role_btn)
            else:
                clear_btn = discord.ui.Button(label="🧹 Effacer les salons configurés", style=discord.ButtonStyle.secondary, row=2)
                clear_btn.callback = self._clear_channels_clicked
                self.add_item(clear_btn)
        elif step["key"] == "levels":
            add_btn = discord.ui.Button(label="➕ Ajouter un rôle de niveau", style=discord.ButtonStyle.primary, row=0)
            add_btn.callback = self._open_level_role_modal
            self.add_item(add_btn)
            edit_btn = discord.ui.Button(label="✏️ Modifier un palier", style=discord.ButtonStyle.secondary, row=0)
            edit_btn.callback = self._open_level_role_modal
            self.add_item(edit_btn)
            delete_btn = discord.ui.Button(label="🗑️ Supprimer un palier", style=discord.ButtonStyle.danger, row=0)
            delete_btn.callback = self._open_delete_level_role_modal
            self.add_item(delete_btn)
            list_btn = discord.ui.Button(label="📋 Voir tous les paliers", style=discord.ButtonStyle.secondary, row=0)
            list_btn.callback = self._list_level_roles_clicked
            self.add_item(list_btn)
        elif step["key"] == "tickets":
            open_btn = discord.ui.Button(label="🛠️ Configurer les tickets (+ticketsetup)", style=discord.ButtonStyle.primary, row=0)
            open_btn.callback = self._tickets_hint
            self.add_item(open_btn)
        elif step["key"] == "logs":
            logs_btn = discord.ui.Button(label="📡 Créer le système de logs", style=discord.ButtonStyle.primary, row=0)
            logs_btn.callback = self._create_logs_clicked
            self.add_item(logs_btn)
        elif step["key"] == "managers":
            add_select = discord.ui.UserSelect(placeholder="➕ Ajouter des gestionnaires", min_values=0, max_values=10, row=0)
            add_select.callback = self._make_manager_add_callback(add_select)
            self.add_item(add_select)
            if self.managers:
                remove_select = discord.ui.Select(
                    placeholder="🗑️ Retirer un gestionnaire",
                    options=[discord.SelectOption(label=name[:100], value=str(uid)) for uid, name in list(self.managers.items())[:25]],
                    row=1,
                )
                remove_select.callback = self._make_manager_remove_callback(remove_select)
                self.add_item(remove_select)

                perm_select = discord.ui.Select(
                    placeholder="🔑 Définir les permissions d'un gestionnaire",
                    options=[
                        discord.SelectOption(label=name[:100], value=str(uid), default=(uid == self.manager_being_edited))
                        for uid, name in list(self.managers.items())[:25]
                    ],
                    row=2,
                )
                perm_select.callback = self._make_manager_permedit_callback(perm_select)
                self.add_item(perm_select)

                if self.manager_being_edited is not None and self.manager_being_edited in self.managers:
                    current_cats = self.manager_categories_cache.get(self.manager_being_edited, ["complete"])
                    target_name = self.managers.get(self.manager_being_edited, "ce gestionnaire")
                    cat_select = discord.ui.Select(
                        placeholder=f"Catégories pour {target_name}"[:100],
                        min_values=0, max_values=len(MANAGER_CATEGORIES),
                        options=[
                            discord.SelectOption(label=label, value=cat, default=(cat in current_cats))
                            for cat, label in MANAGER_CATEGORIES.items()
                        ],
                        row=3,
                    )
                    cat_select.callback = self._make_manager_categories_callback(cat_select)
                    self.add_item(cat_select)
        elif step["key"] == "security":
            presets = [
                ("🟢 Faible", "faible", discord.ButtonStyle.success),
                ("🟡 Moyen", "moyen", discord.ButtonStyle.primary),
                ("🔴 Élevé", "eleve", discord.ButtonStyle.danger),
            ]
            for label, level, style in presets:
                btn = discord.ui.Button(label=label, style=style, row=0)
                btn.callback = self._make_security_preset_callback(level)
                self.add_item(btn)
            select = discord.ui.Select(
                placeholder="🎚️ Choisir précisément les filtres actifs",
                min_values=0, max_values=len(AUTOMOD_TOGGLE_LABELS),
                options=[
                    discord.SelectOption(label=label, value=field, default=bool(self.security_choices.get(field)))
                    for field, label in AUTOMOD_TOGGLE_LABELS.items()
                ],
                row=1,
            )
            select.callback = self._make_security_select_callback(select)
            self.add_item(select)
        elif step["key"] == "summary":
            home_btn = SetupNavButton("home", self.message_id, label="🏠 Accueil", style=discord.ButtonStyle.secondary, row=0)
            save_btn = SetupNavButton("save", self.message_id, label="💾 Enregistrer définitivement", style=discord.ButtonStyle.success, row=0)
            restart_btn = SetupNavButton("restart", self.message_id, label="🔄 Recommencer", style=discord.ButtonStyle.secondary, row=0)
            finish_btn = SetupNavButton("finish", self.message_id, label="● Terminer", style=discord.ButtonStyle.success, row=0)
            for item in (home_btn, save_btn, restart_btn, finish_btn):
                self.add_item(item)
        else:
            for i, field in enumerate(step["fields"]):
                key, kind, label = field[0], field[1], field[2]
                if kind == "role":
                    select = discord.ui.RoleSelect(placeholder=label, row=i)
                    select.callback = self._make_role_callback(key, select)
                else:
                    channel_types = field[3] if len(field) > 3 else [discord.ChannelType.text]
                    select = discord.ui.ChannelSelect(placeholder=label, channel_types=channel_types, row=i)
                    select.callback = self._make_channel_callback(key, select)
                self.add_item(select)

        if step["key"] != "summary":
            # Discord limite chaque message à 5 lignes de composants. Les pages "Général" et
            # "Salons annexes" utilisent déjà leurs 4 premières lignes (0-3) pour les menus
            # déroulants : il ne reste qu'UNE ligne (la 4ᵉ) pour les boutons, qui accepte au
            # maximum 5 boutons. Les 4 boutons de navigation essentiels (🏠 💾 📋 ○) sont donc
            # toujours présents (accès direct à une autre catégorie via 🏠 Accueil, plus de
            # parcours forcé page par page), et le 5ᵉ bouton change selon la page : "✏️ Préfixe
            # & messages" sur la page Général (qui en a besoin), "👁️ Aperçu" partout ailleurs.
            self.add_item(SetupNavButton("home", self.message_id, label="🏠 Accueil", style=discord.ButtonStyle.secondary))
            self.add_item(SetupNavButton("save", self.message_id, label="💾 Enregistrer", style=discord.ButtonStyle.success))
            self.add_item(SetupNavButton("summary", self.message_id, label="📋 Résumé", style=discord.ButtonStyle.primary))
            if step["key"] == "general":
                text_btn = discord.ui.Button(label="✏️ Préfixe & messages", style=discord.ButtonStyle.secondary, row=4)
                text_btn.callback = self._open_text_modal
                self.add_item(text_btn)
            else:
                self.add_item(SetupNavButton("preview", self.message_id, label="👁️ Aperçu", style=discord.ButtonStyle.secondary))
            self.add_item(SetupNavButton("cancel", self.message_id, label="○ Fermer", style=discord.ButtonStyle.danger))

    # ---------------------------------------------------------------- ACTIONS SPÉCIFIQUES AUX PAGES

    async def _open_create_role_modal(self, interaction: discord.Interaction):
        await interaction.response.send_modal(CreateRoleModal(self))

    async def _open_level_role_modal(self, interaction: discord.Interaction):
        await interaction.response.send_modal(LevelRoleModal(self))

    async def _open_delete_level_role_modal(self, interaction: discord.Interaction):
        await interaction.response.send_modal(DeleteLevelRoleModal(self))

    async def _list_level_roles_clicked(self, interaction: discord.Interaction):
        rows = await self.bot.db.fetchall(
            "SELECT * FROM level_roles WHERE guild_id = ? ORDER BY level ASC", (self.guild_id,)
        )
        if not rows:
            return await interaction.response.send_message("Aucun rôle de niveau configuré pour l'instant.", ephemeral=True)
        guild = self._guild()
        lines = []
        for r in rows:
            role = guild.get_role(r["role_id"]) if guild else None
            lines.append(f"Niveau **{r['level']}** → {role.mention if role else '*rôle supprimé*'}")
        e = embeds.neutral("🏆 Tous les paliers de niveau", "\n".join(lines)[:4000], color=SETUP_COLOR_MAIN)
        await panels.envoyer(interaction.response, panels.depuis_embed(e), ephemere=True)

    async def _tickets_hint(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            "Tapez `+ticketsetup` (ou `/ticketsetup`) dans ce salon pour ouvrir le menu complet de "
            "configuration des tickets (panels, types, formulaires, boutons staff...).",
            ephemeral=True,
        )

    async def _create_logs_clicked(self, interaction: discord.Interaction):
        await interaction.response.defer()
        cog: "Configuration" = self.bot.get_cog("Configuration")
        created = await cog.create_log_channels(interaction.guild, interaction.user)
        self.logs_created.extend(created)
        await self.persist_session()
        await interaction.edit_original_response(embed=await self.build_embed(), view=self)

    @staticmethod
    async def _warn_ephemeral(interaction: discord.Interaction, text: str):
        """Envoie un avertissement éphémère, que la réponse initiale de l'interaction ait
        déjà été utilisée (ex: par une boîte de confirmation Administrateur) ou non."""
        if interaction.response.is_done():
            await interaction.followup.send(text, ephemeral=True)
        else:
            await interaction.response.send_message(text, ephemeral=True)

    async def _refresh_message(self, interaction: discord.Interaction):
        """Met à jour le VRAI message de l'assistant avec l'état actuel.

        BUG ÉVITÉ ICI : si la réponse de cette interaction a déjà été utilisée pour
        envoyer un message éphémère (ex: la boîte de confirmation "rôle Administrateur,
        continuer ?"), interaction.edit_original_response() éditerait ce message
        éphémère — visible seulement par la personne qui a cliqué — au lieu du VRAI
        message de l'assistant, visible par tout le monde. On va donc chercher le vrai
        message directement via son salon et son ID dans ce cas précis."""
        embed = await self.build_embed()
        if not interaction.response.is_done():
            await interaction.response.edit_message(embed=embed, view=self)
            return
        try:
            channel = self.bot.get_channel(self.channel_id)
            if channel is None:
                channel = await self.bot.fetch_channel(self.channel_id)
            message = await channel.fetch_message(self.message_id)
            await message.edit(embed=embed, view=self)
        except discord.HTTPException:
            pass

    async def _validate_role_selection(self, interaction: discord.Interaction, role: discord.Role) -> bool:
        """Les 4 vérifications demandées avant d'accepter un rôle "sensible" choisi dans
        /setup : jamais @everyone, confirmation si Administrateur, hiérarchie du bot,
        permission Gérer les rôles. Retourne True si le rôle peut être utilisé."""
        if role.id == interaction.guild.default_role.id:
            await interaction.response.send_message("○ `@everyone` ne peut pas être choisi ici.", ephemeral=True)
            return False
        if not interaction.guild.me.guild_permissions.manage_roles:
            await interaction.response.send_message(
                "⚠️ SentriX n'a pas la permission **Gérer les rôles** sur ce serveur — ce réglage ne pourra pas "
                "fonctionner tant que cette permission n'est pas accordée au bot.", ephemeral=True,
            )
            return False
        if role.permissions.administrator:
            confirm = helpers.ConfirmView(interaction.user.id, timeout=30)
            await panels.envoyer(interaction.response, panels.avec_composants(panels.depuis_embed(embeds.warning(f'{role.mention} a la permission **Administrateur**. Continuer quand même ?')), confirm), ephemere=True)
            await confirm.wait()
            if not confirm.value:
                return False
        if interaction.guild.me.top_role <= role:
            await self._warn_ephemeral(
                interaction, f"⚠️ Le rôle du bot doit être placé **au-dessus** de {role.mention} pour pouvoir l'utiliser."
            )
            return False
        return True

    def _make_role_callback(self, field: str, select: discord.ui.RoleSelect):
        async def callback(interaction: discord.Interaction):
            if select.values:
                role = select.values[0]
                if not await self._validate_role_selection(interaction, role):
                    return
                self.choices[field] = role.id
                self.dirty = True
            await self.persist_session()
            await self._refresh_message(interaction)
        return callback

    def _make_channel_callback(self, field: str, select: discord.ui.ChannelSelect):
        async def callback(interaction: discord.Interaction):
            if select.values:
                self.choices[field] = select.values[0].id
                self.dirty = True
            await self.persist_session()
            await interaction.response.edit_message(embed=await self.build_embed(), view=self)
        return callback

    # ---------------------------------------------------------------- PICKER (pages Rôles / Salons)

    def _make_picker_category_callback(self, select: discord.ui.Select):
        async def callback(interaction: discord.Interaction):
            if select.values:
                self.picker_selected = select.values[0]
            self.render_page()
            await interaction.response.edit_message(embed=await self.build_embed(), view=self)
        return callback

    def _make_picker_role_value_callback(self, field: str, select: discord.ui.RoleSelect):
        async def callback(interaction: discord.Interaction):
            if select.values:
                role = select.values[0]
                if not await self._validate_role_selection(interaction, role):
                    return
                self.choices[field] = role.id
                self.dirty = True
            self.picker_selected = None
            await self.persist_session()
            self.render_page()
            await self._refresh_message(interaction)
        return callback

    def _make_picker_channel_value_callback(self, field: str, select: discord.ui.ChannelSelect):
        async def callback(interaction: discord.Interaction):
            if select.values:
                self.choices[field] = select.values[0].id
                self.dirty = True
            self.picker_selected = None
            await self.persist_session()
            self.render_page()
            await interaction.response.edit_message(embed=await self.build_embed(), view=self)
        return callback

    def _make_exempt_roles_callback(self, select: discord.ui.RoleSelect):
        async def callback(interaction: discord.Interaction):
            new_ids = {role.id for role in select.values}
            added = new_ids - self.exempt_role_ids
            removed = self.exempt_role_ids - new_ids
            for rid in added:
                await self.bot.db.add_automod_exempt_role(self.guild_id, rid)
            for rid in removed:
                await self.bot.db.remove_automod_exempt_role(self.guild_id, rid)
            self.exempt_role_ids = new_ids
            automod_cog = self.bot.get_cog("Automod")
            if automod_cog:
                automod_cog.exempt_roles_cache.pop(self.guild_id, None)
            await interaction.response.edit_message(embed=await self.build_embed(), view=self)
        return callback

    async def _clear_channels_clicked(self, interaction: discord.Interaction):
        confirm = helpers.ConfirmView(interaction.user.id, timeout=30)
        await panels.envoyer(interaction.response, panels.avec_composants(panels.depuis_embed(embeds.warning('Voulez-vous vraiment retirer TOUS les salons configurés sur cette page ? Les salons Discord eux-mêmes ne seront **pas** supprimés — seul le lien avec SentriX le sera.', title='🧹 Effacer les salons configurés ?')), confirm), ephemere=True)
        await confirm.wait()
        if not confirm.value:
            return
        for field, kind, label in PICKER_FIELDS["channels"]:
            await self.bot.db.set_guild_config(self.guild_id, field, None)
            self.choices.pop(field, None)
        self.picker_selected = None
        await self.persist_session()
        self.render_page()
        await panels.envoyer(interaction.followup, panels.depuis_embed(embeds.success('Tous les salons annexes ont été retirés de la configuration.')), ephemere=True)
        try:
            channel = self.bot.get_channel(self.channel_id)
            if channel:
                message = await channel.fetch_message(self.message_id)
                await message.edit(embed=await self.build_embed(), view=self)
        except discord.HTTPException:
            pass

    def _make_manager_add_callback(self, select: discord.ui.UserSelect):
        async def callback(interaction: discord.Interaction):
            for user in select.values:
                if user.bot:
                    continue
                await self.bot.db.add_bot_manager(self.guild_id, user.id, self.author_id)
                self.managers[user.id] = user.display_name
            self.render_page()
            await interaction.response.edit_message(embed=await self.build_embed(), view=self)
        return callback

    def _make_manager_remove_callback(self, select: discord.ui.Select):
        async def callback(interaction: discord.Interaction):
            if select.values:
                user_id = int(select.values[0])
                await self.bot.db.remove_bot_manager(self.guild_id, user_id)
                self.managers.pop(user_id, None)
                self.manager_categories_cache.pop(user_id, None)
                if self.manager_being_edited == user_id:
                    self.manager_being_edited = None
            self.render_page()
            await interaction.response.edit_message(embed=await self.build_embed(), view=self)
        return callback

    def _make_manager_permedit_callback(self, select: discord.ui.Select):
        async def callback(interaction: discord.Interaction):
            if select.values:
                user_id = int(select.values[0])
                self.manager_being_edited = user_id
                if user_id not in self.manager_categories_cache:
                    cats = await self.bot.db.get_manager_categories(self.guild_id, user_id)
                    self.manager_categories_cache[user_id] = cats or ["complete"]
            self.render_page()
            await interaction.response.edit_message(embed=await self.build_embed(), view=self)
        return callback

    def _make_manager_categories_callback(self, select: discord.ui.Select):
        async def callback(interaction: discord.Interaction):
            user_id = self.manager_being_edited
            if user_id is None:
                return await interaction.response.defer()
            # Un gestionnaire ne doit JAMAIS pouvoir s'accorder lui-même plus de
            # permissions — seuls le propriétaire du serveur, un administrateur, ou le
            # propriétaire du bot peuvent modifier les catégories d'un gestionnaire.
            is_privileged = (
                interaction.user.id in config.OWNER_IDS
                or interaction.user.id == interaction.guild.owner_id
                or (isinstance(interaction.user, discord.Member) and interaction.user.guild_permissions.administrator)
            )
            if interaction.user.id == user_id and not is_privileged:
                return await interaction.response.send_message(
                    "○ Vous ne pouvez pas modifier vos propres permissions de gestionnaire.", ephemeral=True
                )
            categories = list(select.values)
            await self.bot.db.set_manager_categories(self.guild_id, user_id, categories, interaction.user.id)
            self.manager_categories_cache[user_id] = categories or ["complete"]
            await interaction.response.edit_message(embed=await self.build_embed(), view=self)
        return callback

    def _make_security_preset_callback(self, level: str):
        async def callback(interaction: discord.Interaction):
            for field, value in SECURITY_PRESETS.get(level, {}).items():
                await self.bot.db.set_automod(self.guild_id, field, value)
                self.security_choices[field] = value
            await self.bot.db.set_guild_config(self.guild_id, "security_level", level)
            automod_cog = self.bot.get_cog("Automod")
            if automod_cog:
                automod_cog.automod_cache.pop(self.guild_id, None)
            self.security_touched = True
            await self.bot.db.log_setup_history(self.guild_id, interaction.user.id, "Sécurité", "préréglage appliqué", new_value=level)
            self.render_page()
            await interaction.response.edit_message(embed=await self.build_embed(), view=self)
        return callback

    def _make_security_select_callback(self, select: discord.ui.Select):
        async def callback(interaction: discord.Interaction):
            chosen = set(select.values)
            for field in AUTOMOD_TOGGLE_LABELS:
                value = 1 if field in chosen else 0
                await self.bot.db.set_automod(self.guild_id, field, value)
                self.security_choices[field] = value
            automod_cog = self.bot.get_cog("Automod")
            if automod_cog:
                automod_cog.automod_cache.pop(self.guild_id, None)
            self.security_touched = True
            self.render_page()
            await interaction.response.edit_message(embed=await self.build_embed(), view=self)
        return callback

    async def _open_text_modal(self, interaction: discord.Interaction):
        await interaction.response.send_modal(SetupTextModal(self))

    # ---------------------------------------------------------------- NAVIGATION STANDARD

    async def handle_nav_action(self, interaction: discord.Interaction, action: str):
        if action == "home":
            self.page = -1
            self.render_page()
            await self.persist_session()
            await interaction.response.edit_message(embed=await self.build_embed(), view=self)
        elif action == "summary":
            # Navigue vers la vraie page Résumé (comme les autres catégories) — contrairement
            # à "preview" qui affiche juste un aperçu éphémère sans quitter la page actuelle.
            self.page = next(i for i, s in enumerate(SETUP_STEPS) if s["key"] == "summary")
            self.render_page()
            await self.persist_session()
            await interaction.response.edit_message(embed=await self.build_embed(), view=self)
        elif action == "history":
            await self._show_history(interaction)
        elif action == "prev":
            self.page = max(0, self.page - 1)
            self.render_page()
            await self.persist_session()
            await interaction.response.edit_message(embed=await self.build_embed(), view=self)
        elif action == "next":
            self.page = min(len(SETUP_STEPS) - 1, self.page + 1)
            self.render_page()
            await self.persist_session()
            await interaction.response.edit_message(embed=await self.build_embed(), view=self)
        elif action == "save":
            await self._save_pending(interaction)
        elif action == "preview":
            await self._show_preview(interaction)
        elif action == "cancel":
            await self._ask_cancel(interaction)
        elif action == "finish":
            await self._finish(interaction)
        elif action == "restart":
            await self._restart(interaction)

    async def _show_history(self, interaction: discord.Interaction):
        rows = await self.bot.db.list_setup_history(self.guild_id, limit=15)
        if not rows:
            return await interaction.response.send_message(
                "Aucune modification enregistrée dans l'historique pour l'instant.", ephemeral=True
            )
        lines = []
        for r in rows:
            lines.append(
                f"<t:{r['created_at']}:R> — <@{r['user_id']}> — **{r['module']}** : {r['action']}"
                + (f" (`{r['old_value']}` → `{r['new_value']}`)" if r["new_value"] is not None else "")
            )
        e = embeds.neutral("📜 Historique des modifications", "\n".join(lines)[:4000], color=SETUP_COLOR_MAIN)
        await panels.envoyer(interaction.response, panels.depuis_embed(e), ephemere=True)

    async def _save_pending(self, interaction: discord.Interaction):
        if not self.choices:
            self.dirty = False
            await interaction.response.edit_message(embed=await self.build_embed(), view=self)
            return
        for field, value in self.choices.items():
            await self.bot.db.set_guild_config(self.guild_id, field, value)
            await self.bot.db.log_setup_history(
                self.guild_id, self.author_id, FIELD_LABELS.get(field, field), "réglage modifié",
                old_value=None, new_value=str(value),
            )
        if "prefix" in self.choices:
            self.bot.prefix_cache[self.guild_id] = self.choices["prefix"]
        self.dirty = False
        await self.persist_session()
        await interaction.response.edit_message(embed=await self.build_embed(), view=self)

    async def _show_preview(self, interaction: discord.Interaction):
        e = await self._build_summary_embed()
        e.title = "👁️ Aperçu de la configuration"
        if not interaction.response.is_done():
            await panels.envoyer(interaction.response, panels.depuis_embed(e), ephemere=True)
        else:
            await panels.envoyer(interaction.followup, panels.depuis_embed(e), ephemere=True)

    async def _ask_cancel(self, interaction: discord.Interaction):
        confirm = helpers.ConfirmView(interaction.user.id, timeout=30)
        await panels.envoyer(interaction.response, panels.avec_composants(panels.depuis_embed(embeds.warning('Voulez-vous vraiment annuler ? Les choix **non enregistrés** (rôles/salons pas encore sauvegardés avec 💾) seront perdus. Ce qui est déjà enregistré (rôles de niveau, logs, gestionnaires, sécurité) ne sera **pas** supprimé.', title='○ Annuler la configuration ?')), confirm), ephemere=True)
        await confirm.wait()
        if not confirm.value:
            return
        await self.bot.db.delete_setup_session(self.message_id)
        cog = self.bot.get_cog("Configuration")
        if cog:
            cog.active_setups.pop(self.message_id, None)
            cog.release_lock(self.guild_id, self.message_id)
        for child in self.children:
            child.disabled = True
        self.stop()
        try:
            channel = self.bot.get_channel(self.channel_id)
            if channel:
                message = await channel.fetch_message(self.message_id)
                await message.edit(embed=embeds.neutral("○ Configuration annulée", "Rien de ce qui était déjà enregistré n'a été supprimé.", color=SETUP_COLOR_DANGER), view=self)
        except discord.HTTPException:
            pass

    async def _restart(self, interaction: discord.Interaction):
        self.choices = {}
        self.dirty = False
        self.page = -1
        self.render_page()
        await self.persist_session()
        await interaction.response.edit_message(embed=await self.build_embed(), view=self)

    async def _finish(self, interaction: discord.Interaction):
        if self.choices:
            for field, value in self.choices.items():
                await self.bot.db.set_guild_config(self.guild_id, field, value)
            if "prefix" in self.choices:
                self.bot.prefix_cache[self.guild_id] = self.choices["prefix"]
        lines = [f"● {FIELD_LABELS.get(k, k)}" for k in self.choices]
        if self.level_role_additions:
            lines.append(f"● {len(self.level_role_additions)} rôle(s) de niveau")
        if self.logs_created:
            lines.append(f"● {len(self.logs_created)} salon(s) de logs créés")
        if self.managers:
            lines.append(f"● {len(self.managers)} gestionnaire(s) du bot")
        if self.security_touched:
            active_filters = sum(1 for v in self.security_choices.values() if v)
            lines.append(f"● Sécurité : {active_filters}/{len(AUTOMOD_TOGGLE_LABELS)} filtre(s) actif(s)")
        if not lines:
            lines.append("Aucun changement — la configuration existante a été conservée telle quelle.")

        # Vérifications finales demandées avant de clore l'assistant : permissions du bot,
        # rôle staff, salon de logs, sécurité, rôles automatiques. Purement informatif —
        # ça n'empêche jamais de terminer, ça prévient juste d'un oubli éventuel.
        conf = await self.bot.db.get_guild_config(self.guild_id)
        checks_lines = await self._run_final_checks(self._guild(), conf)

        await self.bot.db.log_setup_history(self.guild_id, self.author_id, "Configuration", "setup terminé", new_value=f"{len(lines)} changement(s)")

        self.dirty = False
        await self.bot.db.delete_setup_session(self.message_id)
        cog = self.bot.get_cog("Configuration")
        if cog:
            cog.active_setups.pop(self.message_id, None)
            cog.release_lock(self.guild_id, self.message_id)
        for child in self.children:
            child.disabled = True
        final_embed = embeds.neutral("● Configuration enregistrée !", "\n".join(lines), color=SETUP_COLOR_SUCCESS)
        final_embed.add_field(name="🔎 Vérifications finales", value="\n".join(checks_lines)[:1024], inline=False)
        await interaction.response.edit_message(embed=final_embed, view=self)
        self.stop()


async def setup(bot: commands.Bot):
    await bot.add_cog(Configuration(bot))
