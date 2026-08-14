"""Final safety net for SentriX Discord replies.

The OpenAI path can be healthy while a Discord-side helper raises before the answer is
actually sent. This module keeps the normal Ai cog as the primary path, but recovers from
those failures with a minimal direct generation/send path. No user prompt content or
credentials are written to diagnostics.
"""
from __future__ import annotations

import asyncio
import re
import time

import discord
from discord.ext import commands

from utils import ai_service

_NATURAL_TRIGGER = re.compile(r"^(?:sentrix|ssentrix|sentri|snetri|snentrix)\b", re.IGNORECASE)
_UNSET = object()


def _path(bot: commands.Bot) -> dict:
    state = getattr(bot, "ai_api_hotfix_state", None)
    if not isinstance(state, dict):
        return {}
    path = state.get("discord_path")
    if not isinstance(path, dict):
        path = {}
        state["discord_path"] = path
    return path


def _mark(bot: commands.Bot, key: str, value=_UNSET) -> None:
    path = _path(bot)
    if isinstance(path, dict):
        path[key] = int(time.time()) if value is _UNSET else value


def _record_error(bot: commands.Bot, stage: str, exc: Exception) -> None:
    _mark(bot, "last_error", type(exc).__name__)
    _mark(bot, "last_error_stage", stage)
    key = None
    if isinstance(exc, KeyError) and getattr(exc, "args", None):
        key = str(exc.args[0])[:80]
    _mark(bot, "last_error_key", key)


def _chunks(text: str, limit: int = 1900) -> list[str]:
    text = (text or "…").strip() or "…"
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    remaining = text
    while remaining:
        if len(remaining) <= limit:
            chunks.append(remaining)
            break
        cut = remaining.rfind("\n", 0, limit)
        if cut < limit // 2:
            cut = remaining.rfind(" ", 0, limit)
        if cut < limit // 2:
            cut = limit
        chunks.append(remaining[:cut].rstrip())
        remaining = remaining[cut:].lstrip()
    return [chunk for chunk in chunks if chunk]


async def _safe_instructions(ai_cog, bot: commands.Bot, user_id: int | None, author_name: str | None) -> str:
    builder = getattr(ai_cog, "_sentrix_reply_recovery_original_builder", None)
    if builder is None:
        builder = getattr(ai_cog, "_build_system_instructions", None)
    if callable(builder):
        try:
            return await builder(user_id, author_name)
        except KeyError as exc:
            _record_error(bot, "creator_context", exc)
        except Exception as exc:
            _record_error(bot, "system_instructions", exc)

    instructions = ai_service.SYSTEM_PROMPT
    if author_name:
        instructions += f"\n\nLa personne qui te parle s'appelle « {author_name} »."
    return instructions


async def _send_text(destination, text: str, *, reply_to: discord.Message | None = None) -> None:
    first = True
    for chunk in _chunks(text):
        kwargs = {"content": chunk}
        if first and reply_to is not None:
            kwargs["reference"] = discord.MessageReference(
                message_id=reply_to.id,
                channel_id=reply_to.channel.id,
                guild_id=reply_to.guild.id if reply_to.guild else None,
                fail_if_not_exists=False,
            )
            kwargs["mention_author"] = True
        try:
            await destination.send(**kwargs)
        except (discord.HTTPException, TypeError):
            kwargs.pop("reference", None)
            kwargs.pop("mention_author", None)
            await destination.send(**kwargs)
        first = False


async def _direct_reply(
    bot: commands.Bot,
    destination,
    author,
    question: str,
    *,
    reply_to: discord.Message | None = None,
) -> None:
    """Generate and send without depending on the legacy reply/context helpers."""
    _mark(bot, "recovery_used_at")
    guild = getattr(destination, "guild", None)
    channel = getattr(destination, "channel", destination)
    author_name = getattr(author, "display_name", None) or str(author)

    model_key = ai_service.MODEL_LUNA
    try:
        model_key = ai_service.pick_model(question)
    except Exception:
        pass
    try:
        effort = ai_service.pick_reasoning_effort(model_key, "medium")
    except Exception:
        effort = "none"

    ai_cog = bot.get_cog("Ai")
    instructions = await _safe_instructions(
        ai_cog,
        bot,
        getattr(author, "id", None),
        author_name,
    ) if ai_cog is not None else ai_service.SYSTEM_PROMPT

    result = await ai_service.generate(
        question,
        model_key=model_key,
        reasoning_effort=effort,
        instructions=instructions,
        guild_id=getattr(guild, "id", None),
        channel_id=getattr(channel, "id", None),
        user_id=getattr(author, "id", None),
        command="sentrix-reply-recovery",
        web_search=ai_service.needs_web_search(question),
    )

    if result.ok and (result.text or "").strip():
        text = (result.text or "").strip()
    elif result.ok:
        text = "Je n'ai pas reçu de texte de l'IA. Réessaie ta question."
    else:
        try:
            text = ai_service.error_message(result.error)
        except Exception:
            text = "L'IA a rencontré une erreur temporaire. Réessaie dans quelques secondes."

    await _send_text(destination, text, reply_to=reply_to)
    _mark(bot, "recovery_completed_at")
    _mark(bot, "reply_completed_at")
    _mark(bot, "last_error", None)
    _mark(bot, "last_error_stage", None)
    _mark(bot, "last_error_key", None)


async def setup(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_reply_recovery_installed", False):
        return

    # Remove the previous fallback listener. The normal Ai listener remains untouched;
    # this module replaces only the emergency layer that previously stopped on KeyError.
    previous_listener = getattr(bot, "_sentrix_natural_fallback_listener", None)
    if previous_listener is not None:
        try:
            bot.remove_listener(previous_listener, "on_message")
        except Exception:
            pass

    ai_cog = bot.get_cog("Ai")
    in_progress: set[int] = set()
    completed: set[int] = set()

    if ai_cog is not None:
        # The creator-context helper used direct dict indexing. If an older persisted row is
        # missing one optional field, keep the system prompt instead of losing the reply.
        builder = getattr(ai_cog, "_build_system_instructions", None)
        if callable(builder) and not getattr(builder, "_sentrix_reply_recovery_safe", False):
            ai_cog._sentrix_reply_recovery_original_builder = builder

            async def safe_builder(user_id: int | None, author_name: str | None = None):
                try:
                    return await builder(user_id, author_name)
                except KeyError as exc:
                    _record_error(bot, "creator_context", exc)
                    instructions = ai_service.SYSTEM_PROMPT
                    if author_name:
                        instructions += f"\n\nLa personne qui te parle s'appelle « {author_name} »."
                    return instructions

            safe_builder._sentrix_reply_recovery_safe = True
            ai_cog._build_system_instructions = safe_builder

        current_send = getattr(ai_cog, "send_sentrix_reply", None)
        if callable(current_send) and not getattr(current_send, "_sentrix_reply_recovery_safe", False):
            async def safe_send(destination, author, question: str, *, reply_to=None):
                message_id = getattr(reply_to, "id", None)
                if message_id is not None:
                    in_progress.add(int(message_id))
                    _mark(bot, "recovery_primary_entered_at")
                    _mark(bot, "last_message_id", str(message_id))
                try:
                    result = await current_send(
                        destination,
                        author,
                        question,
                        reply_to=reply_to,
                    )
                    if message_id is not None:
                        completed.add(int(message_id))
                    return result
                except Exception as exc:
                    _record_error(bot, "primary_reply", exc)
                    try:
                        await _direct_reply(
                            bot,
                            destination,
                            author,
                            question,
                            reply_to=reply_to,
                        )
                        if message_id is not None:
                            completed.add(int(message_id))
                        return None
                    except Exception as recovery_exc:
                        _record_error(bot, "direct_recovery", recovery_exc)
                        raise
                finally:
                    if message_id is not None:
                        in_progress.discard(int(message_id))
                        async def cleanup(mid: int):
                            await asyncio.sleep(90)
                            completed.discard(mid)
                        asyncio.create_task(cleanup(int(message_id)))

            safe_send._sentrix_reply_recovery_safe = True
            safe_send._sentrix_reply_recovery_original = current_send
            ai_cog.send_sentrix_reply = safe_send

    async def backup_on_message(message: discord.Message):
        if getattr(message.author, "bot", False):
            return
        content = (message.content or "").strip()
        if not content:
            return

        bot_user = bot.user
        mentioned = bool(bot_user is not None and bot_user in getattr(message, "mentions", []))
        name_match = _NATURAL_TRIGGER.match(content)
        if not mentioned and name_match is None:
            return

        message_id = int(message.id)
        _mark(bot, "recovery_trigger_seen_at")
        _mark(bot, "last_message_id", str(message_id))

        question = content
        if mentioned:
            question = re.sub(r"<@!?\d+>", "", question, count=1).strip()
        elif name_match is not None:
            question = content[name_match.end():].lstrip(" ,:-").strip()
        if not question:
            question = "Salut, comment tu vas ?"

        # Give the normal Ai listener priority. If it entered safe_send it owns the request;
        # safe_send itself recovers on failure. This avoids duplicate answers for slow prompts.
        await asyncio.sleep(1.25)
        if message_id in completed or message_id in in_progress:
            return

        try:
            async with message.channel.typing():
                await _direct_reply(
                    bot,
                    message.channel,
                    message.author,
                    question,
                    reply_to=message,
                )
            completed.add(message_id)
        except Exception as exc:
            _record_error(bot, "backup_listener", exc)

    bot.add_listener(backup_on_message, "on_message")
    bot._sentrix_reply_recovery_listener = backup_on_message
    bot._sentrix_reply_recovery_installed = True
    _mark(bot, "reply_recovery_registered", True)
