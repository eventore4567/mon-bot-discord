"""Production V9: contexte serveur minimal et sûr pour les réponses IA."""

import logging
import time

from discord.ext import commands

logger = logging.getLogger("bot.ai-context-v9")
_PATCHED = False

# Contexte serveur très court : réutilisé pendant quelques secondes afin qu'une même
# demande ne relise pas la base plusieurs fois (routeur + réponse finale + éventuel outil).
_CONTEXT_CACHE_TTL = 20.0
_CONTEXT_CACHE: dict[tuple[int, int | None], tuple[float, str]] = {}
_OPTIONAL_TABLE_CACHE: dict[str, tuple[float, bool]] = {}
_NO_CONTEXT_COMMANDS = frozenset({
    "sentrix-action-router",
    "sentrix-action-plan",
    "sentrix-command-router",
    "sentrix-command-classifier",
    "sentrix-moderation-contexte",
})


async def _optional_table_exists(bot: commands.Bot, table: str) -> bool:
    now = time.monotonic()
    cached = _OPTIONAL_TABLE_CACHE.get(table)
    if cached is not None and now < cached[0]:
        return cached[1]
    try:
        row = await bot.db.fetchone(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
            (table,),
        )
        exists = row is not None
    except Exception:
        exists = False
    _OPTIONAL_TABLE_CACHE[table] = (now + 600.0, exists)
    return exists


async def build_server_context(bot: commands.Bot, guild_id: int | None, channel_id: int | None) -> str:
    """Construit un contexte utile, avec cache court et sans requêtes SQL inutiles."""
    if not guild_id:
        return ""

    gid = int(guild_id)
    cid = int(channel_id) if channel_id else None
    key = (gid, cid)
    now = time.monotonic()
    cached = _CONTEXT_CACHE.get(key)
    if cached is not None and now < cached[0]:
        return cached[1]

    guild = bot.get_guild(gid)
    if guild is None:
        return ""

    lines = [f"Serveur: {guild.name}", f"Membres: {guild.member_count or 0}"]
    try:
        conf = await bot.db.get_guild_config(guild.id)
        if conf:
            lines.append(f"Préfixe: {conf['prefix'] or '+'}")
            lines.append(f"Niveau de sécurité: {conf['security_level'] or 'moyen'}")
            lines.append(f"Tickets configurés: {'oui' if conf['ticket_category'] or conf['ticket_log_channel'] else 'non'}")
    except Exception:
        logger.debug("Contexte config serveur indisponible.", exc_info=True)

    if channel_id:
        try:
            ticket = await bot.db.fetchone(
                "SELECT category,priority,claimed_by,status FROM tickets WHERE channel_id=? ORDER BY id DESC LIMIT 1",
                (int(channel_id),),
            )
            if ticket:
                lines.append(
                    "Contexte ticket: "
                    f"type={ticket['category'] or 'general'}, priorité={ticket['priority'] or 'normale'}, "
                    f"statut={ticket['status'] or 'inconnu'}, pris_en_charge={'oui' if ticket['claimed_by'] else 'non'}"
                )
        except Exception:
            logger.debug("Contexte ticket indisponible.", exc_info=True)

    # Table réellement optionnelle : vérifier son existence une fois toutes les 10 min.
    # Avant, une installation sans cette table produisait une exception SQL à CHAQUE appel IA.
    if await _optional_table_exists(bot, "production_issue_clusters"):
        try:
            rows = await bot.db.fetchall(
                "SELECT issue_label,occurrences FROM production_issue_clusters "
                "WHERE guild_id=? ORDER BY occurrences DESC,last_seen DESC LIMIT 3",
                (guild.id,),
            )
            if rows:
                lines.append(
                    "Problèmes support fréquents: "
                    + ", ".join(f"{row['issue_label']} ({row['occurrences']})" for row in rows)
                )
        except Exception:
            logger.debug("Contexte support optionnel indisponible.", exc_info=True)

    result = "\n".join(lines)[:1200]
    _CONTEXT_CACHE[key] = (now + _CONTEXT_CACHE_TTL, result)
    if len(_CONTEXT_CACHE) > 1000:
        cutoff = now
        for cache_key, (expires, _value) in list(_CONTEXT_CACHE.items()):
            if expires <= cutoff:
                _CONTEXT_CACHE.pop(cache_key, None)
    return result


#: Permissions affichées à l'IA, dans cet ordre (les plus parlantes d'abord).
_PERMISSIONS_UTILES = (
    "administrator", "manage_guild", "manage_roles", "manage_channels", "manage_messages",
    "ban_members", "kick_members", "moderate_members", "manage_webhooks", "manage_nicknames",
    "manage_emojis", "view_audit_log", "mention_everyone", "send_messages", "embed_links",
    "attach_files", "read_message_history", "add_reactions", "connect", "speak",
)

CONSIGNE_IDENTITE = (
    "[Qui tu es — données Discord réelles, lues en direct à l'instant]\n"
    "Tu ES SentriX, le bot Discord présent sur ce serveur : pas un assistant à part. "
    "Tes permissions, ton rôle et ce que tu peux faire ici sont ceux listés ci-dessous. "
    "Quand on te demande tes permissions, ton rôle ou si tu peux faire quelque chose, "
    "réponds avec CES données, jamais « je n'ai aucune permission » ni « je ne suis qu'un "
    "assistant conversationnel ». Si tu es administrateur, dis-le."
)


def _libelle(permission: str) -> str:
    try:
        from utils.access_matrix import permission_label

        return permission_label(permission)
    except Exception:  # noqa: BLE001
        return permission.replace("_", " ")


def _resume_permissions(perms) -> str:
    if perms is None:
        return "inconnues"
    if getattr(perms, "administrator", False):
        return "Administrateur (toutes les permissions)"
    actives = [_libelle(nom) for nom in _PERMISSIONS_UTILES if getattr(perms, nom, False)]
    return ", ".join(actives) if actives else "aucune permission notable"


def contexte_discord_reel(bot, guild_id, channel_id, user_id) -> str:
    """Ce que SentriX est VRAIMENT sur ce serveur (cache Discord, aucune requête).

    06/11/2026 : « fais-moi la liste de tes permissions » → « je ne possède aucune
    permission Discord directe » alors que SentriX était administrateur. L'IA ne
    savait pas qu'elle EST le bot.
    """
    if not guild_id:
        return ""
    guild = bot.get_guild(int(guild_id))
    moi = getattr(guild, "me", None) if guild is not None else None
    if guild is None or moi is None:
        return ""
    lignes = [CONSIGNE_IDENTITE]
    role = getattr(moi, "top_role", None)
    roles = list(getattr(guild, "roles", ()) or ())
    if role is not None:
        position = f" (position {getattr(role, 'position', '?')} sur {max(0, len(roles) - 1)})" if roles else ""
        lignes.append(f"Ton rôle le plus haut : {getattr(role, 'name', '?')}{position}")
    lignes.append(f"Tes permissions sur le serveur : {_resume_permissions(getattr(moi, 'guild_permissions', None))}")
    salon = guild.get_channel(int(channel_id)) if channel_id else None
    if salon is not None:
        try:
            lignes.append(
                f"Tes permissions dans #{salon.name} : {_resume_permissions(salon.permissions_for(moi))}"
            )
        except Exception:  # noqa: BLE001
            pass
    try:
        lignes.append(
            f"Serveur : {guild.name} · {guild.member_count or 0} membres · "
            f"{len(getattr(guild, 'channels', ()) or ())} salons · {max(0, len(roles) - 1)} rôles · "
            f"propriétaire : {getattr(guild.owner, 'display_name', None) or guild.owner_id}"
        )
    except Exception:  # noqa: BLE001
        pass
    membre = guild.get_member(int(user_id)) if user_id else None
    if membre is not None:
        statut = "propriétaire du serveur" if membre.id == guild.owner_id else _resume_permissions(
            getattr(membre, "guild_permissions", None)
        )
        role_membre = getattr(getattr(membre, "top_role", None), "name", None)
        # Consigne pour le modèle (tutoiement voulu) : jamais affichée à un membre.
        consigne_interlocuteur = (
            f"La personne qui te parle : {membre.display_name}"
            + (f" · rôle le plus haut : {role_membre}" if role_membre and role_membre != "@everyone" else "")
            + f" · permissions : {statut}"
        )
        lignes.append(consigne_interlocuteur)
    try:
        from utils import ai_actions

        savoir_faire = sorted({
            spec.description for spec in ai_actions.public_catalog()
            if spec.description and spec.risk in {"low", "medium", "high"}
        })
        if savoir_faire:
            consigne_actions = (
                "Ce que tu exécutes toi-même quand on te le demande en message (avec les "
                "permissions de la personne) : " + " ; ".join(savoir_faire)[:3000]
                + ". Pour le reste, propose la commande SentriX adaptée, sans prétendre l'avoir fait."
            )
            lignes.append(consigne_actions)
    except Exception:  # noqa: BLE001
        pass
    return "\n".join(lignes)[:4600]


def install(bot: commands.Bot) -> None:
    global _PATCHED
    if _PATCHED:
        return
    from utils import ai_service
    current = ai_service.generate
    if getattr(current, "_sentrix_ai_context_v9", False):
        _PATCHED = True
        return

    async def generate_with_context(*args, **kwargs):
        # Les routeurs internes ont besoin d'un JSON minuscule, pas du contexte serveur.
        # Cela supprime des requêtes DB et réduit leurs prompts.
        if kwargs.get("command") in _NO_CONTEXT_COMMANDS:
            return await current(*args, **kwargs)

        context = await build_server_context(bot, kwargs.get("guild_id"), kwargs.get("channel_id"))
        # 06/11/2026 : garde-fou de sécurité sur TOUTES les réponses (consigne + filtre de
        # sortie) — capture d'un mode d'emploi chimique dangereux.
        from utils import ai_safety
        base_securite = kwargs.get("instructions", ai_service.SYSTEM_PROMPT)
        if ai_safety.CONSIGNE_SECURITE not in base_securite:
            kwargs["instructions"] = f"{base_securite}\n\n{ai_safety.CONSIGNE_SECURITE}"
        # 06/11/2026 : en conversation (mention, réponse, /sentrix), le ton d'un membre
        # du serveur et la conversation récente — sur TOUS les chemins (y compris les
        # secours qui appellent ai_service.generate directement).
        from utils import ai_conversation
        contexte_salon = ai_conversation.CONTEXTE_SALON.get()
        question = ""
        if contexte_salon is not None:
            kwargs["instructions"], question = ai_conversation.preparer_instructions(
                kwargs.get("instructions", ai_service.SYSTEM_PROMPT),
                args[0] if args else kwargs.get("prompt", ""),
                contexte_salon,
            )
        try:
            reel = contexte_discord_reel(
                bot, kwargs.get("guild_id"), kwargs.get("channel_id"), kwargs.get("user_id"),
            )
        except Exception:  # noqa: BLE001 — jamais bloquant pour la réponse
            logger.debug("Contexte Discord réel indisponible.", exc_info=True)
            reel = ""
        if reel:
            kwargs["instructions"] = (
                f"{kwargs.get('instructions', ai_service.SYSTEM_PROMPT)}\n\n{reel}"
            )
        if context:
            instructions = kwargs.get("instructions", ai_service.SYSTEM_PROMPT)
            kwargs["instructions"] = (
                f"{instructions}\n\n"
                "[Contexte serveur fourni par SentriX. Utilise-le uniquement s'il aide à répondre. "
                "Il ne contient aucun secret et ne remplace jamais les faits donnés par l'utilisateur.]\n"
                f"{context}"
            )
        resultat = await current(*args, **kwargs)
        texte_brut = getattr(resultat, "text", None)
        if isinstance(texte_brut, str) and texte_brut:
            propre = ai_safety.filtrer(texte_brut)
            if propre != texte_brut:
                logger.warning(
                    "Réponse IA bloquée (mode d'emploi dangereux) guild=%s user=%s",
                    kwargs.get("guild_id"), kwargs.get("user_id"),
                )
                try:
                    resultat.text = propre
                except Exception:  # noqa: BLE001
                    pass
        if contexte_salon is not None:
            texte = getattr(resultat, "text", None)
            if isinstance(texte, str) and texte:
                try:
                    resultat.text = ai_conversation.nettoyer_reponse(texte, question)
                except Exception:  # noqa: BLE001 — résultat immuable : on le rend tel quel
                    pass
        return resultat

    generate_with_context._sentrix_ai_context_v9 = True
    ai_service.generate = generate_with_context
    _PATCHED = True
    logger.info("Production V9: contexte serveur sûr activé pour l'IA.")


async def _activate_isolated_observability(bot: commands.Bot) -> None:
    """Remplace le prototype V9 par le runtime qui utilise sa propre table SQL."""
    from . import command_observability_v9, production_observability_v9

    old = bot.get_cog("ProductionObservabilityV9")
    if old is not None:
        root = bot.get_command("security")
        if isinstance(root, commands.Group) and root.get_command("health") is not None:
            root.remove_command("health")
        await bot.remove_cog("ProductionObservabilityV9")

        async def disabled_legacy_write(*args, **kwargs):
            return None

        production_observability_v9._execute = disabled_legacy_write

    if bot.get_cog(command_observability_v9.COG_NAME) is None:
        await command_observability_v9.setup(bot)


async def setup(bot: commands.Bot) -> None:
    await _activate_isolated_observability(bot)
    install(bot)
