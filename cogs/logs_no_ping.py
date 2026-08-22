"""Logs Discord silencieux + regroupement des rafales de rôles.

Deux garanties sont centralisées ici, après l'installation des cartes PremiumLogLayout :

1. Les mentions visibles dans les logs ne pinguent jamais les membres/rôles.
2. Une création/suppression/modification massive de rôles n'envoie plus un message par
   événement. Les événements rapprochés sont regroupés dans une carte du type
   ``Création de rôles (16)`` avec acteur Audit Log, ID et état d'affichage du rôle.

Les petits changements (1 ou 2 rôles) gardent le log individuel historique. Aucun
listener métier n'est remplacé : on regroupe uniquement au point d'envoi central afin
que +create-server, le dashboard et les actions Discord profitent tous du même système.
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

# Une rafale est considérée terminée après quelques secondes sans nouvel événement.
ROLE_BATCH_DELAY = 3.0
ROLE_BATCH_THRESHOLD = 3
ROLE_BATCH_DESCRIPTION_LIMIT = 3500

# (instance bot, serveur, action) -> {role_id: événement le plus récent}
_ROLE_BATCHES: dict[tuple[int, int, str], dict[int, "RoleLogEvent"]] = {}
_ROLE_BATCH_VERSIONS: dict[tuple[int, int, str], int] = {}
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
        "verb": "a été créé par",
    },
    "Rôle supprimé": {
        "key": "delete",
        "title": "Suppression de rôles",
        "audit": discord.AuditLogAction.role_delete,
        "verb": "a été supprimé par",
    },
    "Rôle modifié": {
        "key": "update",
        "title": "Modification de rôles",
        "audit": discord.AuditLogAction.role_update,
        "verb": "a été modifié par",
    },
}


def _spawn(coro) -> None:
    """Lance une tâche courte sans laisser d'exception asyncio non récupérée."""
    task = asyncio.create_task(coro)
    _BACKGROUND_TASKS.add(task)

    def done(completed: asyncio.Task) -> None:
        _BACKGROUND_TASKS.discard(completed)
        if completed.cancelled():
            return
        try:
            completed.exception()
        except Exception:
            logger.exception("Erreur dans une tâche de regroupement des logs rôles.")

    task.add_done_callback(done)


def _target_id(embed: discord.Embed) -> int | None:
    footer = getattr(embed.footer, "text", None) or ""
    match = re.search(r"(?<!\d)(\d{15,22})(?!\d)", footer)
    if not match:
        # Repli utile si une future couche déplace l'ID dans la description.
        match = re.search(r"<@&?(\d{15,22})>", embed.description or "")
    return int(match.group(1)) if match else None


def _role_name_from_embed(embed: discord.Embed, role_id: int) -> str:
    description = (embed.description or "").strip()
    if not description:
        return f"Rôle {role_id}"
    first = description.splitlines()[0].strip()
    # Une mention <@&id> n'apporte pas le nom si le rôle a déjà été supprimé.
    if re.fullmatch(r"<@&\d{15,22}>", first):
        return f"Rôle {role_id}"
    return first[:100]


def _actor_text(actor: discord.abc.User | None) -> str:
    if actor is None:
        return "`Auteur inconnu`"
    return f"{actor.mention} (`{actor.id}`)"


def _safe_role_name(name: str) -> str:
    return discord.utils.escape_markdown(name.replace("`", "'"))[:90]


def _update_summary(embed: discord.Embed) -> str:
    """Transforme les lignes détaillées d'un update en résumé compact pour un batch."""
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
    """Résout les acteurs en UNE lecture Audit Log par rafale, pas une requête par rôle."""
    if not target_ids:
        return {}
    result: dict[int, discord.abc.User] = {}
    try:
        # Les événements du batch viennent de se produire : 100 entrées récentes suffisent
        # largement, même sur un gros create-server.
        async for entry in guild.audit_logs(limit=min(100, max(25, len(target_ids) * 4)), action=action):
            target_id = getattr(entry.target, "id", None)
            if target_id in target_ids and target_id not in result and entry.user is not None:
                result[int(target_id)] = entry.user
                if len(result) == len(target_ids):
                    break
    except (discord.Forbidden, discord.HTTPException):
        # Sans permission Voir le journal d'audit, le log reste utile et affiche
        # simplement « Auteur inconnu » au lieu de disparaître.
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
    actor_label = _actor_text(actor)

    if action_key == "delete":
        role_label = f"**@{_safe_role_name(event.role_name)}** (`{event.role_id}`)"
        return f"• Le rôle {role_label} a été supprimé par {actor_label}"

    role_label = role.mention if role is not None else f"<@&{event.role_id}>"
    role_label += f" (`{event.role_id}`)"

    if action_key == "create":
        extra = " *(Affiché séparément)*" if role is not None and role.hoist else ""
        return f"• Le rôle {role_label} a été créé par {actor_label}{extra}"

    summary = _update_summary(event.embed)
    suffix = f" — {summary}" if summary else ""
    return f"• Le rôle {role_label} a été modifié par {actor_label}{suffix}"


def _split_lines(lines: list[str], limit: int = ROLE_BATCH_DESCRIPTION_LIMIT) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []
    current_size = 0
    for line in lines:
        # Empêche un changement de permissions anormalement verbeux de casser l'embed.
        line = line[:700]
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
    version: int,
) -> None:
    await asyncio.sleep(ROLE_BATCH_DELAY)

    # Un nouvel événement est arrivé pendant le délai : seule la dernière tâche vide le
    # batch. Cette stratégie évite d'annuler une tâche qui serait déjà en train d'envoyer.
    if _ROLE_BATCH_VERSIONS.get(key) != version:
        return

    events_by_id = _ROLE_BATCHES.pop(key, {})
    _ROLE_BATCH_VERSIONS.pop(key, None)
    events = list(events_by_id.values())
    if not events:
        return

    # 1-2 événements : conserver exactement les cartes individuelles existantes.
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

    action_key = action_meta["key"]
    key = (id(bot), guild.id, action_key)
    batch = _ROLE_BATCHES.setdefault(key, {})

    role = guild.get_role(role_id)
    role_name = role.name if role is not None else _role_name_from_embed(embed, role_id)
    batch[role_id] = RoleLogEvent(
        role_id=role_id,
        embed=embed.copy(),
        role_name=role_name,
    )

    version = _ROLE_BATCH_VERSIONS.get(key, 0) + 1
    _ROLE_BATCH_VERSIONS[key] = version
    _spawn(_flush_role_batch(original_send_log, bot, guild, action_meta, key, version))
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

    # ------------------------------------------------------------------
    # 1) Regroupement au point d'envoi central.
    # premium_logs_v2 est déjà installé à cet instant : original_send_log conserve donc
    # tout le design Components V2 actuel, on ne change que le nombre de cartes envoyées.
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

    # ------------------------------------------------------------------
    # 2) Mentions visibles mais silencieuses dans les cartes de logs.
    original_channel_send = discord.TextChannel.send
    if not getattr(original_channel_send, "_sentrix_logs_no_ping", False):

        async def send_without_log_mentions(self, *args, **kwargs):
            view = kwargs.get("view")
            embed = kwargs.get("embed")
            is_premium_log = (
                view is not None
                and view.__class__.__name__ == "PremiumLogLayout"
                and view.__class__.__module__.endswith("premium_logs_v2")
            )
            # Le second test protège aussi le rare fallback embed si Components V2 est
            # indisponible : les @rôles/@utilisateurs du batch ne notifieront personne.
            if is_premium_log or _is_role_log_embed(embed):
                kwargs["allowed_mentions"] = discord.AllowedMentions.none()
            return await original_channel_send(self, *args, **kwargs)

        send_without_log_mentions._sentrix_logs_no_ping = True
        discord.TextChannel.send = send_without_log_mentions

    _INSTALLED = True
    logger.info(
        "Logs rôles : regroupement des rafales actif (seuil=%s, délai=%.1fs) et mentions silencieuses.",
        ROLE_BATCH_THRESHOLD,
        ROLE_BATCH_DELAY,
    )
