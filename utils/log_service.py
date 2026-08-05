"""
Service centralisé des LOGS — refonte demandée par Jayden pour pouvoir activer/désactiver
chaque catégorie de log indépendamment, avec son propre salon.

Portée exacte de cette refonte (à lire avant de croire qu'un type précis est câblé) :
- Le bot n'émettait déjà, avant cette refonte, que 7 catégories de logs (voir l'ancien
  utils.helpers.LOG_KIND_COLUMNS) : messages, members, voice, roles, server (salons/
  catégories), automod (anti-spam/anti-raid/anti-nuke), moderation (sanctions). Ces 7
  catégories restent émises exactement aux mêmes endroits qu'avant (aucun listener/
  commande déplacé) — seule leur configuration devient indépendante (avant : un simple
  ID de salon par colonne, sans on/off séparé).
- 6 nouvelles catégories sont ajoutées à la configuration : tickets, security (alias
  visuel de la catégorie déjà existante "automod", regroupée ici sous le nom demandé
  "Sécurité"), economy, levels, ai, games, system. Parmi celles-ci, SEULES "tickets"
  (déjà partiellement câblée dans cogs/tickets.py) et "games" (câblée en Phase 4 avec
  les récompenses de mini-jeux) émettent réellement des logs à ce stade. economy,
  levels, ai et system sont pleinement CONFIGURABLES (on/off, salon, test) mais
  n'ont pas encore d'événement qui les déclenche automatiquement — ce sera la suite
  logique d'une prochaine phase si Jayden le souhaite. Ce fichier ne prétend jamais
  qu'un log "fonctionne" s'il n'est pas réellement émis quelque part.

Migration : au premier accès à un (guild_id, log_type) qui n'a pas encore de ligne dans
log_settings, on reprend l'état ACTUEL de guild_config (salon déjà configuré + activé
implicitement s'il y avait un salon, désactivé sinon) — jamais de renommage, jamais de
salon remplacé, jamais de "tout activer" ou "tout désactiver" d'un coup.
"""

import logging

import discord

logger = logging.getLogger("bot")


# ---------------------------------------------------------------------------
# CATALOGUE DES CATÉGORIES DE LOGS
# ---------------------------------------------------------------------------
# category : regroupement affiché dans le menu de /logsetup (Messages, Membres, Rôles,
#            Salons, Vocal, Modération, Tickets, Sécurité, Économie, Niveaux, IA, Jeux,
#            Système — les 13 catégories demandées).
# label    : nom affiché pour ce type de log.
# legacy_column : colonne guild_config correspondante pour la migration (None si nouvelle
#            catégorie sans équivalent avant cette refonte).
# emits    : True si au moins un endroit du bot envoie réellement ce log aujourd'hui —
#            affiché honnêtement dans /logsetup pour ne jamais laisser croire qu'un
#            réglage "actif" produit un résultat s'il n'y a rien pour l'émettre encore.
LOG_TYPES = {
    "messages": {
        "label": "Messages (suppression/modification)", "category": "Messages",
        "legacy_column": "log_messages", "emits": True,
    },
    "members": {
        "label": "Membres (arrivées/départs/pseudo/rôles)", "category": "Membres",
        "legacy_column": "log_members", "emits": True,
    },
    "roles": {
        "label": "Rôles (création/suppression/attribution)", "category": "Rôles",
        "legacy_column": "log_roles", "emits": True,
    },
    "server": {
        "label": "Salons (création/suppression/modification)", "category": "Salons",
        "legacy_column": "log_server", "emits": True,
    },
    "voice": {
        "label": "Vocal (connexion/déconnexion/changement de salon)", "category": "Vocal",
        "legacy_column": "log_voice", "emits": True,
    },
    "moderation": {
        "label": "Modération (avertissements, mutes, kicks, bans)", "category": "Modération",
        "legacy_column": "log_moderation", "emits": True,
    },
    "tickets": {
        "label": "Tickets (ouverture, fermeture, transcript)", "category": "Tickets",
        "legacy_column": "ticket_log_channel", "emits": True,
    },
    "automod": {
        "label": "Sécurité (anti-spam, anti-raid, anti-nuke, AutoMod)", "category": "Sécurité",
        "legacy_column": "log_automod", "emits": True,
    },
    "economy": {
        "label": "Économie (gains, transferts, achats)", "category": "Économie",
        "legacy_column": None, "emits": False,
    },
    "levels": {
        "label": "Niveaux (montée de niveau, XP ajoutée/retirée par un admin)", "category": "Niveaux",
        "legacy_column": None, "emits": False,
    },
    "ai": {
        "label": "Intelligence artificielle (commandes IA, erreurs OpenAI)", "category": "IA",
        "legacy_column": None, "emits": False,
    },
    "games": {
        "label": "Jeux (parties, victoires, récompenses, triche détectée)", "category": "Jeux",
        "legacy_column": None, "emits": False,
    },
    "system": {
        "label": "Système (démarrage, arrêt, erreurs techniques, migrations)", "category": "Système",
        "legacy_column": None, "emits": False,
    },
}

CATEGORY_ORDER = [
    "Messages", "Membres", "Rôles", "Salons", "Vocal", "Modération", "Tickets",
    "Sécurité", "Économie", "Niveaux", "IA", "Jeux", "Système",
]


def categories_with_types() -> dict[str, list[str]]:
    """{catégorie affichée: [log_type, ...]} dans l'ordre du menu."""
    result: dict[str, list[str]] = {c: [] for c in CATEGORY_ORDER}
    for log_type, meta in LOG_TYPES.items():
        result.setdefault(meta["category"], []).append(log_type)
    return {c: types for c, types in result.items() if types}


DEFAULT_LOG_SETTING = {
    "enabled": False, "channel_id": None, "include_content": True,
    "include_attachments": True, "include_actor": True, "include_reason": True,
}


async def _migrate_from_legacy(bot, guild_id: int, log_type: str) -> dict:
    """Reprend l'état actuel de guild_config pour ce log_type (aucune donnée perdue, aucun
    salon remplacé) et l'écrit dans log_settings pour que ce soit désormais la source de
    vérité. Retourne le réglage obtenu (jamais un dict vide)."""
    meta = LOG_TYPES.get(log_type, {})
    legacy_column = meta.get("legacy_column")
    channel_id = None

    if legacy_column:
        conf = await bot.db.get_guild_config(guild_id)
        if conf:
            try:
                channel_id = conf[legacy_column]
            except (KeyError, IndexError):
                channel_id = None
            # Repli sur le salon général UNIQUEMENT pour les catégories qui s'appuyaient
            # déjà sur ce repli avant la refonte (les 7 catégories historiques) — jamais
            # pour les nouvelles catégories, qui n'avaient aucun comportement à reprendre.
            if not channel_id and legacy_column != "ticket_log_channel":
                try:
                    channel_id = conf["log_channel"]
                except (KeyError, IndexError):
                    channel_id = None

    enabled = 1 if channel_id else 0
    now_ts = _now()
    await bot.db.execute(
        "INSERT INTO log_settings (guild_id, log_type, enabled, channel_id, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(guild_id, log_type) DO NOTHING",
        (guild_id, log_type, enabled, channel_id, now_ts, now_ts),
    )
    return {
        "enabled": bool(enabled), "channel_id": channel_id, "include_content": True,
        "include_attachments": True, "include_actor": True, "include_reason": True,
    }


def _now() -> int:
    import time
    return int(time.time())


async def get_log_setting(bot, guild_id: int, log_type: str) -> dict:
    """Renvoie le réglage courant pour ce type de log — migre depuis guild_config au tout
    premier accès si aucune ligne n'existe encore (voir _migrate_from_legacy), sans jamais
    écraser une ligne déjà migrée."""
    row = await bot.db.fetchone(
        "SELECT * FROM log_settings WHERE guild_id = ? AND log_type = ?", (guild_id, log_type)
    )
    if row is None:
        return await _migrate_from_legacy(bot, guild_id, log_type)
    return {
        "enabled": bool(row["enabled"]), "channel_id": row["channel_id"],
        "include_content": bool(row["include_content"]), "include_attachments": bool(row["include_attachments"]),
        "include_actor": bool(row["include_actor"]), "include_reason": bool(row["include_reason"]),
    }


async def get_all_log_settings(bot, guild_id: int) -> dict[str, dict]:
    """Comme get_log_setting() mais pour TOUS les types connus d'un coup (utilisé par le
    panneau /logsetup et par +logs status) — migre également chaque type manquant."""
    return {log_type: await get_log_setting(bot, guild_id, log_type) for log_type in LOG_TYPES}


async def set_log_enabled(bot, guild_id: int, log_type: str, enabled: bool) -> dict:
    current = await get_log_setting(bot, guild_id, log_type)  # garantit que la ligne existe (migration)
    if enabled and not current["channel_id"]:
        raise ValueError("channel_required")
    await bot.db.execute(
        "UPDATE log_settings SET enabled = ?, updated_at = ? WHERE guild_id = ? AND log_type = ?",
        (1 if enabled else 0, _now(), guild_id, log_type),
    )
    current["enabled"] = enabled
    return current


async def set_log_channel(bot, guild_id: int, log_type: str, channel_id: int | None) -> dict:
    await get_log_setting(bot, guild_id, log_type)  # garantit que la ligne existe (migration)
    await bot.db.execute(
        "UPDATE log_settings SET channel_id = ?, updated_at = ? WHERE guild_id = ? AND log_type = ?",
        (channel_id, _now(), guild_id, log_type),
    )
    setting = await get_log_setting(bot, guild_id, log_type)
    setting["channel_id"] = channel_id
    return setting


def validate_channel(guild: discord.Guild, channel_id: int | None, *, needs_file: bool = False):
    """Vérifie qu'un salon peut réellement recevoir un log. Retourne (ok, raison_courte)."""
    if not channel_id:
        return False, "aucun salon configuré"
    channel = guild.get_channel(channel_id)
    if not channel:
        return False, "salon introuvable (probablement supprimé)"
    perms = channel.permissions_for(guild.me)
    if not perms.view_channel:
        return False, "le bot ne peut pas voir ce salon"
    if not perms.send_messages:
        return False, "le bot ne peut pas envoyer de messages dans ce salon"
    if not perms.embed_links:
        return False, "le bot ne peut pas intégrer de liens/embeds dans ce salon"
    if needs_file and not perms.attach_files:
        return False, "le bot ne peut pas joindre de fichiers dans ce salon"
    return True, "ok"


async def send_log(bot, guild: discord.Guild, log_type: str, embed: discord.Embed,
                    file: discord.File | None = None) -> bool:
    """Point d'entrée central : envoie `embed` dans le salon dédié à `log_type` SI ce type
    est activé pour ce serveur. Ne lève jamais d'exception vers l'appelant — une sanction,
    un ticket ou une autre action principale ne doit jamais échouer à cause d'un log qui
    ne part pas. Retourne True si le message a bien été envoyé."""
    try:
        setting = await get_log_setting(bot, guild.id, log_type)
    except Exception:
        logger.warning("log_service.send_log: impossible de lire la configuration pour '%s' sur %s (%s).",
                        log_type, guild.name, guild.id, exc_info=True)
        return False

    if not setting["enabled"]:
        return False

    ok, reason = validate_channel(guild, setting["channel_id"], needs_file=file is not None)
    if not ok:
        logger.warning("log_service.send_log: log '%s' activé mais non envoyé sur %s (%s) — %s.",
                        log_type, guild.name, guild.id, reason)
        return False

    channel = guild.get_channel(setting["channel_id"])
    try:
        if file is not None:
            await channel.send(embed=embed, file=file)
        else:
            await channel.send(embed=embed)
        return True
    except discord.Forbidden:
        logger.warning("log_service.send_log: Forbidden en envoyant le log '%s' dans #%s sur %s (%s).",
                        log_type, channel.name, guild.name, guild.id)
    except discord.HTTPException as exc:
        logger.warning("log_service.send_log: échec HTTP en envoyant le log '%s' dans #%s sur %s (%s) : %s.",
                        log_type, channel.name, guild.name, guild.id, exc)
    return False


async def send_test_log(bot, guild: discord.Guild, log_type: str, author: discord.abc.User) -> tuple[bool, str]:
    """Envoie un embed de TEST clairement marqué comme tel — ne modifie jamais aucune
    donnée réelle. Retourne (succès, message explicatif) pour affichage direct dans
    l'interaction qui a déclenché le test (indépendant de l'état enabled — un test doit
    pouvoir vérifier un salon avant même d'activer le log)."""
    setting = await get_log_setting(bot, guild.id, log_type)
    ok, reason = validate_channel(guild, setting["channel_id"])
    if not ok:
        return False, f"❌ Impossible d'envoyer un test : {reason}."

    meta = LOG_TYPES.get(log_type, {})
    from utils import embeds as embeds_mod
    test_embed = embeds_mod.neutral(
        "🧪 Test de log",
        f"Ceci est un message de test pour la catégorie **{meta.get('label', log_type)}**.\n"
        "Le système fonctionne correctement.\n\n"
        "*Ce message est un test — aucun véritable événement ne s'est produit.*",
    )
    test_embed.add_field(name="Déclenché par", value=str(author), inline=False)
    channel = guild.get_channel(setting["channel_id"])
    try:
        await channel.send(embed=test_embed)
        return True, f"✅ Test envoyé dans {channel.mention}."
    except discord.HTTPException as exc:
        return False, f"❌ Échec de l'envoi du test : {exc}."
