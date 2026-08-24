"""Logs Discord silencieux + regroupement exact des rafales de rôles.

Garanties :
1. Les journaux SentriX n'envoient jamais de ping membre/rôle.
2. Les membres/rôles restent de vraies mentions Discord cliquables (`<@id>` / `<@&id>`).
3. Une rafale de >=3 rôles créée/supprimée/modifiée dans une fenêtre FIXE de 3 secondes
   devient UNE carte avec UNE liste, jamais une carte par rôle.
4. Une ou deux actions dans la fenêtre gardent leurs cartes individuelles détaillées.

Le regroupement travaille au point d'envoi central afin de couvrir +create-server,
+create sentrix, dashboard et actions manuelles Discord. La notification est neutralisée
uniquement au dernier envoi avec AllowedMentions.none(), ce qui conserve l'apparence
native des mentions sans réellement ping la personne ou le rôle.
"""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass

import discord

from utils import log_service


logger = logging.getLogger("bot.role-log-batcher")
_INSTALLED = False

ROLE_BATCH_DELAY = 3.0
ROLE_BATCH_THRESHOLD = 3
ROLE_BATCH_DESCRIPTION_LIMIT = 3500

# (instance bot, serveur, action) -> {role_id: événement le plus récent}
_ROLE_BATCHES: dict[tuple[int, int, str], dict[int, "RoleLogEvent"]] = {}
_ROLE_BATCH_ACTIVE: set[tuple[int, int, str]] = set()
_BACKGROUND_TASKS: set[asyncio.Task] = set()


@dataclass(slots=True)
class RoleLogEvent:
    role_id: int
    embed: discord.Embed
    role_name: str


ROLE_ACTIONS = {
    "Rôle créé": {
        "key": "create",
        "title": "Création de rôles",
        "audit": discord.AuditLogAction.role_create,
    },
    "Rôle supprimé": {
        "key": "delete",
        "title": "Suppression de rôles",
        "audit": discord.AuditLogAction.role_delete,
    },
    "Rôle modifié": {
        "key": "update",
        "title": "Modification de rôles",
        "audit": discord.AuditLogAction.role_update,
    },
}


def _spawn(coro) -> None:
    task = asyncio.create_task(coro)
    _BACKGROUND_TASKS.add(task)

    def done(completed: asyncio.Task) -> None:
        _BACKGROUND_TASKS.discard(completed)
        if completed.cancelled():
            return
        try:
            exc = completed.exception()
            if exc is not None:
                logger.error("Erreur dans une tâche de regroupement des logs rôles.", exc_info=exc)
        except Exception:
            logger.exception("Erreur pendant la récupération d'une tâche de logs rôles.")

    task.add_done_callback(done)


def _target_id(embed: discord.Embed) -> int | None:
    footer = getattr(embed.footer, "text", None) or ""
    match = re.search(r"(?<!\d)(\d{15,22})(?!\d)", footer)
    if not match:
        match = re.search(r"<@&?(\d{15,22})>", embed.description or "")
    return int(match.group(1)) if match else None


def _role_name_from_embed(embed: discord.Embed, role_id: int) -> str:
    description = (embed.description or "").strip()
    if not description:
        return f"Rôle {role_id}"
    first = description.splitlines()[0].strip()
    if re.fullmatch(r"<@&\d{15,22}>", first):
        return f"Rôle {role_id}"
    return first[:100]


def _safe_name(value: str) -> str:
    return discord.utils.escape_markdown(value.replace("`", "'").replace("@", "＠"))[:90]


def _actor_text(actor: discord.abc.User | None) -> str:
    """Vraie mention Discord, rendue sans notification au dernier envoi."""
    if actor is None:
        return "**Auteur inconnu**"
    return f"{actor.mention} (`{actor.id}`)"


def _update_summary(embed: discord.Embed) -> str:
    lines = (embed.description or "").splitlines()
    if lines and re.fullmatch(r"<@&\d{15,22}>", lines[0].strip()):
        lines = lines[1:]
    text = " · ".join(line.strip() for line in lines if line.strip())
    return text[:260]


async def _audit_actor_map(
    guild: discord.Guild,
    action: discord.AuditLogAction,
    target_ids: set[int],
) -> dict[int, discord.abc.User]:
    if not target_ids:
        return {}
    result: dict[int, discord.abc.User] = {}
    try:
        async for entry in guild.audit_logs(limit=min(100, max(25, len(target_ids) * 4)), action=action):
            target_id = getattr(entry.target, "id", None)
            if target_id in target_ids and target_id not in result and entry.user is not None:
                result[int(target_id)] = entry.user
                if len(result) == len(target_ids):
                    break
    except (discord.Forbidden, discord.HTTPException):
        pass
    except Exception:
        logger.exception("Lecture Audit Log impossible pendant un batch de rôles sur %s.", guild.id)
    return result


def _event_line(
    guild: discord.Guild,
    event: RoleLogEvent,
    action_key: str,
    actor: discord.abc.User | None,
) -> str:
    role = guild.get_role(event.role_id)
    # Même si le rôle vient d'être supprimé, on conserve le token de mention Discord.
    # Lorsqu'il existe encore, Discord rend la vraie pastille du rôle ; dans tous les cas
    # AllowedMentions.none() empêche la notification.
    role_label = f"<@&{event.role_id}> (`{event.role_id}`)"
    actor_label = _actor_text(actor)

    if action_key == "delete":
        return f"• {role_label} — supprimé par {actor_label}"
    if action_key == "create":
        extra = " • affiché séparément" if role is not None and role.hoist else ""
        return f"• {role_label} — créé par {actor_label}{extra}"

    summary = _update_summary(event.embed)
    suffix = f" — {summary}" if summary else ""
    return f"• {role_label} — modifié par {actor_label}{suffix}"


def _split_lines(lines: list[str], limit: int = ROLE_BATCH_DESCRIPTION_LIMIT) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []
    current_size = 0
    for raw in lines:
        line = raw[:700]
        added = len(line) + (1 if current else 0)
        if current and current_size + added > limit:
            chunks.append("\n".join(current))
            current = []
            current_size = 0
        current.append(line)
        current_size += len(line) + 1
    if current:
        chunks.append("\n".join(current))
    return chunks


async def _flush_role_batch(
    original_send_log,
    bot,
    guild: discord.Guild,
    action_meta: dict,
    key: tuple[int, int, str],
) -> None:
    # Fenêtre FIXE : le timer démarre au premier rôle et n'est jamais repoussé.
    await asyncio.sleep(ROLE_BATCH_DELAY)
    events_by_id = _ROLE_BATCHES.pop(key, {})
    _ROLE_BATCH_ACTIVE.discard(key)
    events = list(events_by_id.values())
    if not events:
        return

    if len(events) < ROLE_BATCH_THRESHOLD:
        for event in events:
            await original_send_log(bot, guild, "roles", event.embed)
        return

    target_ids = {event.role_id for event in events}
    actors = await _audit_actor_map(guild, action_meta["audit"], target_ids)
    action_key = action_meta["key"]
    lines = [_event_line(guild, event, action_key, actors.get(event.role_id)) for event in events]
    chunks = _split_lines(lines)

    total = len(events)
    colour = events[0].embed.colour or discord.Colour.blurple()
    for index, description in enumerate(chunks, start=1):
        title = f"{action_meta['title']} ({total})"
        if len(chunks) > 1:
            title += f" • {index}/{len(chunks)}"
        grouped = discord.Embed(
            title=title,
            description=description,
            colour=colour,
            timestamp=discord.utils.utcnow(),
        )
        grouped.set_footer(text="SentriX • Actions regroupées automatiquement")
        await original_send_log(bot, guild, "roles", grouped)


async def _queue_role_log(
    original_send_log,
    bot,
    guild: discord.Guild,
    embed: discord.Embed,
    action_meta: dict,
) -> bool:
    role_id = _target_id(embed)
    if role_id is None:
        return await original_send_log(bot, guild, "roles", embed)

    key = (id(bot), guild.id, action_meta["key"])
    batch = _ROLE_BATCHES.setdefault(key, {})
    role = guild.get_role(role_id)
    role_name = role.name if role is not None else _role_name_from_embed(embed, role_id)
    batch[role_id] = RoleLogEvent(role_id=role_id, embed=embed.copy(), role_name=role_name)

    if key not in _ROLE_BATCH_ACTIVE:
        _ROLE_BATCH_ACTIVE.add(key)
        _spawn(_flush_role_batch(original_send_log, bot, guild, action_meta, key))
    return True


def _is_role_log_embed(embed: discord.Embed | None) -> bool:
    if embed is None:
        return False
    title = str(embed.title or "")
    return title in ROLE_ACTIONS or any(
        marker in title
        for marker in ("Création de rôles", "Suppression de rôles", "Modification de rôles")
    )


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    original_send_log = log_service.send_log
    if not getattr(original_send_log, "_sentrix_role_batcher", False):
        async def send_with_role_batching(
            bot,
            guild: discord.Guild,
            log_type: str,
            embed: discord.Embed,
            file: discord.File | None = None,
        ) -> bool:
            if file is None and log_type == "roles":
                action_meta = ROLE_ACTIONS.get(str(embed.title or ""))
                if action_meta is not None:
                    return await _queue_role_log(original_send_log, bot, guild, embed, action_meta)
            return await original_send_log(bot, guild, log_type, embed, file=file)

        send_with_role_batching._sentrix_role_batcher = True
        log_service.send_log = send_with_role_batching

    # Dernière sécurité : les mentions restent de vraies mentions Discord mais aucune
    # notification n'est envoyée, même pour un membre ou un rôle réellement mentionné.
    original_channel_send = discord.TextChannel.send
    if not getattr(original_channel_send, "_sentrix_logs_no_ping", False):
        async def send_without_log_mentions(self, *args, **kwargs):
            view = kwargs.get("view")
            embed = kwargs.get("embed")
            view_cls = view.__class__ if view is not None else None
            is_log_layout = bool(
                view_cls is not None
                and (
                    getattr(view_cls, "_sentrix_log_layout", False)
                    or view_cls.__name__ in {"PremiumLogLayout", "DetailedPremiumLogLayout"}
                    or view_cls.__module__.endswith("premium_logs_v2")
                    or view_cls.__module__.endswith("log_detail_layout_v24")
                )
            )
            if is_log_layout or _is_role_log_embed(embed):
                kwargs["allowed_mentions"] = discord.AllowedMentions.none()
            return await original_channel_send(self, *args, **kwargs)

        send_without_log_mentions._sentrix_logs_no_ping = True
        discord.TextChannel.send = send_without_log_mentions

    _INSTALLED = True
    logger.info(
        "Logs rôles : fenêtre fixe %.1fs, seuil=%s, vraies mentions sans ping.",
        ROLE_BATCH_DELAY,
        ROLE_BATCH_THRESHOLD,
    )
