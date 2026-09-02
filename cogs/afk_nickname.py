"""Mode AFK avec renommage temporaire et restauration sûre du pseudo."""

from __future__ import annotations

import logging
import time
from types import MethodType

import discord
from discord.ext import commands

from utils import embeds
from utils import sentrix_panels as panels

logger = logging.getLogger("bot.afk")
_INSTALLED = False
AFK_PREFIX = "(AFK) "
MAX_NICKNAME_LENGTH = 32


def _state_key(guild_id: int | None, user_id: int) -> tuple[int, int]:
    return (int(guild_id or 0), int(user_id))


def _clean_base_name(value: str) -> str:
    value = str(value or "Membre").strip()
    while value.casefold().startswith(AFK_PREFIX.casefold()):
        value = value[len(AFK_PREFIX):].lstrip()
    available = MAX_NICKNAME_LENGTH - len(AFK_PREFIX)
    return (value or "Membre")[:available]


def _can_edit_nickname(member: discord.Member) -> bool:
    guild = member.guild
    me = guild.me
    if me is None or guild.owner_id == member.id:
        return False
    return bool(me.guild_permissions.manage_nicknames and me.top_role > member.top_role)


async def _save_state(bot: commands.Bot, guild_id: int, user_id: int, state: dict) -> None:
    await bot.db.execute(
        "INSERT INTO afk_status (guild_id, user_id, reason, original_nick, afk_nick, renamed, started_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(guild_id, user_id) DO UPDATE SET "
        "reason=excluded.reason, original_nick=excluded.original_nick, afk_nick=excluded.afk_nick, "
        "renamed=excluded.renamed, started_at=excluded.started_at",
        (
            guild_id,
            user_id,
            state["reason"],
            state.get("original_nick"),
            state.get("afk_nick"),
            1 if state.get("renamed") else 0,
            state["started_at"],
        ),
    )


async def _delete_state(bot: commands.Bot, guild_id: int, user_id: int) -> None:
    await bot.db.execute(
        "DELETE FROM afk_status WHERE guild_id = ? AND user_id = ?",
        (guild_id, user_id),
    )


async def _afk_callback(self, ctx: commands.Context, *, raison: str = "Absent"):
    raison = (raison or "Absent").strip()[:300] or "Absent"
    guild = ctx.guild
    guild_id = guild.id if guild else 0
    key = _state_key(guild_id, ctx.author.id)
    existing = self.afk_states.get(key)

    original_nick = existing.get("original_nick") if existing else getattr(ctx.author, "nick", None)
    base_name = original_nick or getattr(ctx.author, "display_name", None) or getattr(ctx.author, "name", "Membre")
    afk_nick = AFK_PREFIX + _clean_base_name(base_name)
    renamed = False
    rename_note = ""

    if guild and isinstance(ctx.author, discord.Member):
        if _can_edit_nickname(ctx.author):
            try:
                if ctx.author.nick != afk_nick:
                    await ctx.author.edit(nick=afk_nick, reason="Mode AFK activé avec SentriX")
                renamed = True
            except discord.HTTPException:
                rename_note = "\n\n⚠️ Le mode AFK est actif, mais Discord a refusé le changement de pseudo."
        else:
            rename_note = (
                "\n\n⚠️ Le mode AFK est actif, mais SentriX ne peut pas modifier ce pseudo "
                "à cause de la hiérarchie des rôles ou des permissions."
            )

    state = {
        "reason": raison,
        "original_nick": original_nick,
        "afk_nick": afk_nick,
        "renamed": renamed,
        "started_at": int(time.time()),
    }
    self.afk_states[key] = state
    if guild:
        try:
            await _save_state(self.bot, guild.id, ctx.author.id, state)
        except Exception:
            logger.exception("Impossible d'enregistrer le statut AFK de %s.", ctx.author.id)

    description = (
        f"{ctx.author.mention} est maintenant absent.\n\n"
        f"**Raison :** {raison}"
        + (f"\n**Pseudo temporaire :** `{afk_nick}`" if renamed else "")
        + rename_note
    )
    await panels.envoyer(ctx, panels.depuis_embed(embeds.info(description, title='Mode AFK activé')))


async def _restore_member(self, member: discord.Member, state: dict) -> bool:
    if not state.get("renamed") or not _can_edit_nickname(member):
        return False
    # Ne remplace pas un pseudo que le membre ou un administrateur aurait modifié pendant
    # son absence. On restaure uniquement le pseudo temporaire posé par SentriX.
    if member.nick != state.get("afk_nick"):
        return False
    try:
        await member.edit(nick=state.get("original_nick"), reason="Retour du mode AFK SentriX")
        return True
    except discord.HTTPException:
        logger.warning("Restauration du pseudo AFK impossible pour %s.", member.id)
        return False


async def _afk_on_message(self, message: discord.Message):
    if message.author.bot:
        return

    guild = message.guild
    guild_id = guild.id if guild else 0
    key = _state_key(guild_id, message.author.id)
    state = self.afk_states.get(key)

    # Réutiliser +afk permet de modifier la raison sans quitter puis reprendre le mode AFK.
    prefix = getattr(self.bot, "prefix_cache", {}).get(guild_id, "+") if guild else "+"
    content = message.content.strip().casefold()
    trigger = f"{prefix}afk".casefold()
    is_afk_command = content == trigger or content.startswith(trigger + " ")

    if state and not is_afk_command:
        self.afk_states.pop(key, None)
        restored = False
        if guild and isinstance(message.author, discord.Member):
            restored = await _restore_member(self, message.author, state)
            try:
                await _delete_state(self.bot, guild.id, message.author.id)
            except Exception:
                logger.exception("Impossible de supprimer le statut AFK de %s.", message.author.id)

        text = f"Bon retour {message.author.mention}, ton mode AFK a été retiré."
        if state.get("renamed") and not restored:
            text += "\n⚠️ Le pseudo n'a pas pu être restauré automatiquement."
        try:
            await panels.envoyer(message.channel, panels.depuis_embed(embeds.success(text, title='Retour détecté')))
        except discord.HTTPException:
            pass

    # Filet de sécurité après une perte de base ou un redémarrage incomplet : un membre ne
    # reste pas bloqué éternellement avec le préfixe AFK lorsqu'il recommence à parler.
    elif guild and isinstance(message.author, discord.Member) and message.author.nick:
        if message.author.nick.casefold().startswith(AFK_PREFIX.casefold()) and not is_afk_command:
            if _can_edit_nickname(message.author):
                fallback_name = message.author.nick[len(AFK_PREFIX):].strip() or None
                try:
                    await message.author.edit(nick=fallback_name, reason="Nettoyage d'un ancien pseudo AFK SentriX")
                except discord.HTTPException:
                    pass

    if not guild:
        return
    for mention in message.mentions:
        mentioned_state = self.afk_states.get(_state_key(guild.id, mention.id))
        if not mentioned_state:
            continue
        reason = mentioned_state.get("reason") or "Absent"
        try:
            await panels.envoyer(message.channel, panels.depuis_embed(embeds.info(f'{mention.mention} est actuellement absent.\n**Raison :** {reason}', title='Membre AFK')))
        except discord.HTTPException:
            pass


async def install(bot: commands.Bot) -> None:
    """Remplace uniquement le comportement AFK de Utility, sans recréer la commande."""
    global _INSTALLED
    if _INSTALLED:
        return

    utility = bot.get_cog("Utility")
    command = bot.get_command("afk")
    if utility is None or command is None:
        logger.warning("Correctif AFK non installé : cog Utility ou commande afk introuvable.")
        return

    states: dict[tuple[int, int], dict] = {}
    try:
        await bot.db.execute(
            "CREATE TABLE IF NOT EXISTS afk_status ("
            "guild_id INTEGER NOT NULL, user_id INTEGER NOT NULL, reason TEXT NOT NULL, "
            "original_nick TEXT, afk_nick TEXT, renamed INTEGER NOT NULL DEFAULT 0, "
            "started_at INTEGER NOT NULL, PRIMARY KEY (guild_id, user_id))"
        )
        rows = await bot.db.fetchall("SELECT * FROM afk_status")
        for row in rows:
            states[_state_key(row["guild_id"], row["user_id"])] = {
                "reason": row["reason"],
                "original_nick": row["original_nick"],
                "afk_nick": row["afk_nick"],
                "renamed": bool(row["renamed"]),
                "started_at": row["started_at"],
            }
    except Exception:
        # Le mode AFK reste utilisable en mémoire même si SQLite est momentanément
        # indisponible ; une fonction de confort ne doit jamais bloquer tout Utility.
        logger.exception("Persistance AFK indisponible : fonctionnement temporaire en mémoire.")

    utility.afk_states = states
    utility.afk_users.clear()

    old_listener = getattr(utility, "on_message", None)
    if old_listener is not None:
        bot.remove_listener(old_listener, "on_message")
    new_listener = MethodType(_afk_on_message, utility)
    utility.on_message = new_listener
    bot.add_listener(new_listener, "on_message")

    command.callback = _afk_callback
    app_command = getattr(command, "app_command", None)
    if app_command is not None and hasattr(app_command, "_callback"):
        app_command._callback = _afk_callback

    _INSTALLED = True
    logger.info("Mode AFK amélioré installé : renommage, restauration et persistance actifs.")
