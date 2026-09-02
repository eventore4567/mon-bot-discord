"""Bot Core V5 — améliorations Discord natives, sans dépendance au dashboard.

Cette couche améliore uniquement l'expérience du bot dans Discord :
- /sentrix et les messages naturels utilisent le pipeline IA moderne (mémoire persistante,
  quotas, cooldowns, restrictions de salon/rôle et journal d'usage) ;
- les réponses IA ne peuvent pas déclencher de mentions @everyone/@roles accidentelles ;
- une réponse à un message du bot continue naturellement la conversation sans répéter son nom ;
- les messages privés deviennent de vraies conversations avec le bot ;
- les utilisateurs blacklistés ne peuvent plus contourner la blacklist via le listener IA ;
- un simple appel du nom/une mention du bot répond localement sans consommer l'API ;
- les fautes dans les commandes préfixées reçoivent des suggestions utiles.

Aucune commande slash n'est ajoutée et aucun fichier du dashboard n'est modifié.
"""
from __future__ import annotations

import difflib
import logging
import re
import time
import types
from typing import Any

import discord
from discord.ext import commands

import config
from database.db import PRIMARY_CREATOR_ID
from utils import ai_service, embeds
from utils import sentrix_panels as panels
from utils.instance_identity import brand_label, wake_words

logger = logging.getLogger("bot.experience-v5")

# Commandes membres volontairement proposées lors d'une faute de frappe. On n'expose pas
# les commandes sensibles dans les suggestions automatiques ; leurs permissions restent de
# toute façon protégées par les checks centraux du bot.
_PUBLIC_HINT_COMMANDS = {
    "help", "ping", "avatar", "info", "userinfo", "channelinfo", "membercount",
    "emoji-list", "poll", "remind", "reminder-list", "reminder-cancel", "translate",
    "weather", "suggest", "report-bug", "afk", "roll", "choose", "sentrix", "ai",
    "summarize", "image", "explain", "rewrite", "fact-check", "improve", "correct",
    "ai-translate", "balance", "economy", "daily", "weekly", "work", "rob", "pay",
    "economyleaderboard", "shop", "buy", "inventory", "sell", "gamble", "deposit",
    "withdraw", "banque", "stats", "level", "leaderboard-levels", "profile", "set-bio",
    "rep", "reputation", "repleaderboard", "voice-time", "ticket", "giveaway-list",
    "event-join", "event-list", "tournament-join", "tournament-list", "invites",
    "invite-leaderboard", "invited-by", "bot-status", "server-growth", "command-stats",
    "changelog", "feedback", "botinfo", "rps", "guess-number", "trivia", "tictactoe",
    "hangman", "math-quiz", "blackjack", "slots", "coinflip", "dice", "luckyroll",
    "highlow", "memory", "reaction", "scramble", "wordgame", "emojiquiz", "colorquiz",
    "fasttype", "duel", "connect4", "numberduel", "reactionduel", "quizduel",
    "triviastart", "wordrace", "reactionevent", "guessrace", "mathrace", "lastmessage",
    "emoji-race", "adventure", "dungeon", "mining", "fishing", "treasure", "hunt",
    "explore", "gamehistory", "gameprofile", "gamestats", "gametop", "dailygames",
    "join", "leave", "play", "pause", "resume", "skip", "stop", "queue",
    "nowplaying", "volume", "loop", "shuffle", "remove-from-queue", "clear-queue",
    "playlist-save", "playlist-load", "drop",
}


def _prefix_for(bot: commands.Bot, message: discord.Message) -> str:
    if message.guild is not None and hasattr(bot, "prefix_cache"):
        return str(bot.prefix_cache.get(message.guild.id, config.DEFAULT_PREFIX))
    return str(config.DEFAULT_PREFIX)


def _explicit_trigger_pattern() -> re.Pattern[str]:
    words = list(wake_words())
    # Le listener historique du cog IA comprend encore ces variantes SentriX. On les garde
    # ici pour détecter qu'un autre listener va déjà prendre le message et éviter un doublon.
    words.extend(("SentriX", "SSentriX", "Sentri", "Snetri", "SnentriX"))
    unique: list[str] = []
    seen: set[str] = set()
    for word in sorted(words, key=len, reverse=True):
        key = word.casefold()
        if key in seen:
            continue
        seen.add(key)
        unique.append(re.escape(word).replace(r"\ ", r"\s+"))
    return re.compile(rf"^(?:{'|'.join(unique)})\b", re.IGNORECASE)


def _is_bare_trigger(bot: commands.Bot, message: discord.Message | None) -> bool:
    """Vrai si le message contient seulement la mention/le nom du bot et rien d'autre."""
    if message is None:
        return False
    content = (message.content or "").strip()
    if not content:
        return False
    user = bot.user
    if user is not None:
        stripped = re.sub(rf"<@!?{user.id}>", "", content).strip(" \t,;:!?.-")
        if stripped == "" and re.search(rf"<@!?{user.id}>", content):
            return True
    match = _explicit_trigger_pattern().match(content)
    if match and not content[match.end():].strip(" \t,;:!?.-"):
        return True
    return False


async def _is_blacklisted(bot: commands.Bot, user_id: int) -> bool:
    if int(user_id) == int(PRIMARY_CREATOR_ID) or int(user_id) in set(getattr(config, "OWNER_IDS", [])):
        return False
    try:
        if await bot.db.is_bot_creator(int(user_id)):
            return False
    except Exception:
        # Le cache reste un filet de sécurité même si SQLite est momentanément occupée.
        pass
    cache = getattr(bot, "blacklist_cache", {})
    return int(user_id) in cache


async def _safe_reply_target(message: discord.Message) -> discord.Message | None:
    reference = message.reference
    if reference is None or not reference.message_id:
        return None
    resolved = reference.resolved
    if isinstance(resolved, discord.Message):
        return resolved
    try:
        return await message.channel.fetch_message(reference.message_id)
    except (discord.NotFound, discord.Forbidden, discord.HTTPException, AttributeError):
        return None


async def _ai_access_error(ai_cog: Any, author: discord.abc.User, guild_id: int | None, channel_id: int | None) -> str | None:
    if guild_id is None:
        return None
    settings = await ai_service.get_settings(ai_cog.bot, guild_id)
    if not settings["enabled"]:
        return "L'IA est désactivée sur ce serveur."
    if channel_id is not None and not ai_service.is_channel_allowed(settings, channel_id):
        return "L'IA n'est pas autorisée dans ce salon."
    role_ids = [role.id for role in getattr(author, "roles", [])]
    if not ai_service.is_role_allowed(settings, role_ids):
        return "Tu n'as pas le rôle nécessaire pour utiliser l'IA dans ce serveur."
    return None


def _install_ai_pipeline_upgrade(bot: commands.Bot) -> None:
    ai_cog = bot.get_cog("Ai")
    if ai_cog is None or getattr(ai_cog, "_sentrix_experience_v5_pipeline", False):
        return

    async def upgraded_send_sentrix_reply(
        self,
        destination,
        author,
        question: str,
        *,
        reply_to: discord.Message | None = None,
    ):
        async def _send(**kwargs):
            # Le texte produit par un modèle ne doit jamais pouvoir ping @everyone, un rôle
            # ou un utilisateur arbitraire. Le seul ping autorisé est celui de la réponse
            # Discord vers l'auteur du message auquel le bot répond.
            kwargs.setdefault(
                "allowed_mentions",
                discord.AllowedMentions(
                    everyone=False,
                    roles=False,
                    users=False,
                    replied_user=reply_to is not None,
                ),
            )
            if reply_to is not None:
                kwargs["reference"] = discord.MessageReference(
                    message_id=reply_to.id,
                    channel_id=reply_to.channel.id,
                    guild_id=reply_to.guild.id if reply_to.guild else None,
                    fail_if_not_exists=False,
                )
                kwargs.setdefault("mention_author", True)
            try:
                return await destination.send(**kwargs)
            except discord.HTTPException:
                kwargs.pop("reference", None)
                kwargs.pop("mention_author", None)
                return await destination.send(**kwargs)

        if await _is_blacklisted(self.bot, author.id):
            return await _send(embed=embeds.error("Vous n'êtes pas autorisé à utiliser ce bot."))

        guild = getattr(destination, "guild", None)
        if guild is None:
            guild = getattr(getattr(destination, "channel", None), "guild", None)
        guild_id = getattr(guild, "id", None)
        channel = getattr(destination, "channel", destination)
        channel_id = getattr(channel, "id", None)

        access_error = await _ai_access_error(self, author, guild_id, channel_id)
        if access_error:
            return await _send(embed=embeds.error(access_error))

        if _is_bare_trigger(self.bot, reply_to):
            prefix = _prefix_for(self.bot, reply_to)
            brand = brand_label()
            return await _send(
                content=(
                    f'Je suis là. Écrivez **{brand}** suivi de votre question, réponds directement à un de mes messages, ou utilisez `{prefix}help`.'
                )
            )

        command_name = "ai-dm" if guild_id is None else ("ai-reply" if reply_to is not None else "sentrix")
        result = await self._prepare_and_generate(
            guild_id=guild_id,
            channel_id=channel_id or 0,
            user_id=author.id,
            author_name=getattr(author, "display_name", None) or str(author),
            question=(question or "").strip() or "Salut",
            command=command_name,
        )
        if not result["ok"]:
            return await _send(embed=embeds.error(result["error"]))

        content = (result["text"] or "…").strip()
        for chunk in ai_service.split_for_discord(content):
            await _send(content=chunk)

    ai_cog.send_sentrix_reply = types.MethodType(upgraded_send_sentrix_reply, ai_cog)
    # L'ancien historique author_id-only n'est plus utilisé par /sentrix naturel. On le
    # vide ici pour éviter qu'une conversation précédemment mélangée reste en mémoire RAM.
    try:
        ai_cog.histories.clear()
    except Exception:
        pass
    ai_cog._sentrix_experience_v5_pipeline = True
    logger.info("Bot Core V5 : pipeline IA naturel modernisé pour %s.", brand_label())


def _install_reply_and_dm_conversations(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_experience_v5_conversations", False):
        return

    explicit_pattern = _explicit_trigger_pattern()

    async def natural_continuation(message: discord.Message):
        if message.author.bot:
            return
        content = (message.content or "").strip()
        if not content:
            return
        if await _is_blacklisted(bot, message.author.id):
            return

        prefix = _prefix_for(bot, message)
        if content.startswith(prefix):
            return

        # En message privé, le bot devient conversationnel par défaut. Une vraie commande
        # préfixée reste gérée par le moteur commands.Bot et n'est jamais doublée ici.
        if message.guild is None:
            try:
                ctx = await bot.get_context(message)
                if ctx.valid:
                    return
            except Exception:
                pass
            ai_cog = bot.get_cog("Ai")
            if ai_cog is None:
                return
            try:
                async with message.channel.typing():
                    await ai_cog.send_sentrix_reply(message.channel, message.author, content, reply_to=message)
            except Exception:
                logger.exception("Bot Core V5 : conversation privée impossible.")
            return

        # Les mentions et mots de réveil sont déjà pris en charge par les listeners
        # historiques SentriX/Odboug. Ici on ne traite QUE la continuation par réponse.
        if bot.user is not None and bot.user in message.mentions:
            return
        if explicit_pattern.match(content):
            return
        if message.reference is None:
            return

        referenced = await _safe_reply_target(message)
        if referenced is None or bot.user is None or referenced.author.id != bot.user.id:
            return

        ai_cog = bot.get_cog("Ai")
        if ai_cog is None:
            return

        # Une phrase naturelle de type « ouvre help » continue de profiter du moteur
        # d'actions existant au lieu d'être envoyée inutilement au modèle.
        invoke_natural = getattr(ai_cog, "_invoke_natural_command", None)
        if callable(invoke_natural):
            try:
                if await invoke_natural(message, content, prefix):
                    return
            except Exception:
                logger.exception("Bot Core V5 : invocation naturelle depuis une réponse impossible.")

        try:
            async with message.channel.typing():
                await ai_cog.send_sentrix_reply(message.channel, message.author, content, reply_to=message)
        except Exception:
            logger.exception("Bot Core V5 : continuation de conversation impossible.")

    bot.add_listener(natural_continuation, "on_message")
    bot._sentrix_experience_v5_conversations = True
    logger.info("Bot Core V5 : réponses conversationnelles et DM activés.")


def _install_unknown_command_hints(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_experience_v5_command_hints", False):
        return

    cooldowns: dict[tuple[int, int], float] = {}

    async def command_hint(ctx: commands.Context, error: commands.CommandError):
        original = getattr(error, "original", error)
        if not isinstance(original, commands.CommandNotFound):
            return

        requested = (getattr(ctx, "invoked_with", None) or "").strip().casefold()
        if not requested:
            return

        guild_id = ctx.guild.id if ctx.guild else 0
        key = (guild_id, ctx.author.id)
        current = time.monotonic()
        if current - cooldowns.get(key, 0.0) < 2.5:
            return
        cooldowns[key] = current

        prefix = getattr(ctx, "clean_prefix", None) or config.DEFAULT_PREFIX
        custom_names: list[str] = []
        if ctx.guild is not None:
            try:
                # Si la commande existe dans Platform V4, son propre listener va répondre :
                # on ne doit surtout pas afficher simultanément « commande inconnue ».
                exact = await bot.db.fetchone(
                    "SELECT 1 FROM platform_custom_commands WHERE guild_id=? AND name=? AND enabled=1",
                    (ctx.guild.id, requested),
                )
                if exact:
                    return
                rows = await bot.db.fetchall(
                    "SELECT name FROM platform_custom_commands WHERE guild_id=? AND enabled=1 ORDER BY name LIMIT 100",
                    (ctx.guild.id,),
                )
                custom_names = [str(row["name"]).casefold() for row in rows]
            except Exception:
                custom_names = []

        candidates = {
            name for name in _PUBLIC_HINT_COMMANDS
            if bot.get_command(name) is not None
        }
        candidates.update(custom_names)
        matches = difflib.get_close_matches(requested, sorted(candidates), n=3, cutoff=0.48)

        if matches:
            suggestions = " • ".join(f"`{prefix}{name}`" for name in matches)
            text = (
                f"Commande `{prefix}{requested}` inconnue.\n"
                f"Tu voulais peut-être : {suggestions}\n"
                f"Sinon, ouvre `{prefix}help`."
            )
        else:
            text = f"Commande `{prefix}{requested}` inconnue. Utilise `{prefix}help` pour voir les commandes disponibles."
        try:
            await panels.envoyer(ctx, panels.depuis_embed(embeds.warning(text)))
        except discord.HTTPException:
            pass

    bot.add_listener(command_hint, "on_command_error")
    bot._sentrix_experience_v5_command_hints = True
    logger.info("Bot Core V5 : suggestions de commandes inconnues activées.")


def install(bot: commands.Bot) -> None:
    """Installation idempotente ; appelée après chaque extension chargée.

    Le patch IA est retenté tant que le cog Ai n'est pas encore chargé, tandis que les
    listeners globaux ne sont enregistrés qu'une fois.
    """
    _install_unknown_command_hints(bot)
    _install_reply_and_dm_conversations(bot)
    _install_ai_pipeline_upgrade(bot)
