"""Le fil SentriX : chaque action du staff porte une référence vérifiable.

La même référence (« SX-7K4QF2M ») apparaît dans la réponse, dans la carte de
log et en base ; ``/logs trace`` la reconstitue : qui, quoi, où, quand, avec
quel résultat. Elle naît UNE fois par invocation, dans ``Command.invoke`` — le
point de passage commun du préfixe et du slash du catalogue — et se propage par
ContextVar à tout ce que la commande produit, cartes de log comprises.

Seules les commandes non publiques sont tracées et affichent leur référence :
un ``+ping`` n'a rien à prouver, un ``+ban`` si.
"""
from __future__ import annotations

import contextvars
import hashlib
import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("bot.trace")

#: Crockford : ni I, L, O, U — une référence se lit et se dicte sans ambiguïté.
_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
RETENTION_SECONDS = 90 * 86400

SCHEMA = (
    "CREATE TABLE IF NOT EXISTS sentrix_traces ("
    "guild_id INTEGER NOT NULL, ref TEXT NOT NULL, command TEXT NOT NULL, transport TEXT NOT NULL, "
    "actor_id INTEGER, channel_id INTEGER, target_id INTEGER, outcome TEXT NOT NULL, detail TEXT, "
    "created_at INTEGER NOT NULL, PRIMARY KEY (guild_id, ref))"
)


@dataclass
class Trace:
    ref: str
    guild_id: int
    command: str
    transport: str
    actor_id: int
    channel_id: int | None
    created_at: int = field(default_factory=lambda: int(time.time()))
    target_id: int | None = None
    outcome: str = "ok"
    detail: str = ""
    #: La commande en cours : son nom définitif n'est connu qu'une fois la
    #: sous-commande résolue (Group.invoke met ctx.command à jour).
    ctx: Any = field(default=None, repr=False, compare=False)


CURRENT: contextvars.ContextVar[Trace | None] = contextvars.ContextVar("sentrix_trace", default=None)


def make_ref(guild_id: int, invocation_id: int) -> str:
    """7 caractères (35 bits) dérivés de l'invocation : stable et sans collision pratique."""
    digest = int.from_bytes(hashlib.sha1(f"{guild_id}:{invocation_id}".encode()).digest()[:8], "big")
    chars = []
    for _ in range(7):
        digest, index = divmod(digest, 32)
        chars.append(_ALPHABET[index])
    return "SX-" + "".join(chars)


def normalise_ref(value: str) -> str:
    """« sx-7k4qf2m », « 7K4QF2M », « SX 7K4QF2M » : la même référence."""
    text = "".join(ch for ch in str(value or "").upper() if ch.isalnum())
    if text.startswith("SX"):
        text = text[2:]
    text = text.replace("O", "0").replace("I", "1").replace("L", "1")
    return f"SX-{text}" if text else ""


def is_traced(command_name: str) -> bool:
    """Une commande est tracée si elle n'est pas publique."""
    try:
        from utils import access_matrix

        return access_matrix.access_tier(command_name) != "public"
    except Exception:  # noqa: BLE001 — sans matrice, on ne trace pas plutôt que de casser
        return False


def visible_ref() -> str | None:
    """La référence à afficher, seulement si la commande en cours est tracée."""
    trace = CURRENT.get()
    if trace is None:
        return None
    name = getattr(getattr(trace.ctx, "command", None), "qualified_name", None) or trace.command
    return trace.ref if is_traced(name) else None


def classify(error: BaseException | None) -> tuple[str, str]:
    """(résultat, détail) d'une invocation à partir de l'erreur levée."""
    if error is None:
        return "ok", ""
    from discord.ext import commands

    name = type(error).__name__
    if isinstance(error, commands.CheckFailure):
        return "refusé", name
    if isinstance(error, commands.UserInputError):
        return "saisie invalide", name
    original = getattr(error, "original", None)
    return "erreur", type(original).__name__ if original is not None else name


async def ensure_schema(db: Any) -> None:
    await db.execute(SCHEMA)


async def record(db: Any, trace: Trace) -> None:
    await ensure_schema(db)
    await db.execute(
        "INSERT OR REPLACE INTO sentrix_traces "
        "(guild_id, ref, command, transport, actor_id, channel_id, target_id, outcome, detail, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (trace.guild_id, trace.ref, trace.command, trace.transport, trace.actor_id, trace.channel_id,
         trace.target_id, trace.outcome, trace.detail[:300], trace.created_at),
    )


async def lookup(db: Any, guild_id: int, ref: str) -> Any:
    await ensure_schema(db)
    return await db.fetchone(
        "SELECT * FROM sentrix_traces WHERE guild_id = ? AND ref = ?", (int(guild_id), normalise_ref(ref)),
    )


async def purge(db: Any, now: int | None = None) -> None:
    await ensure_schema(db)
    await db.execute(
        "DELETE FROM sentrix_traces WHERE created_at < ?", (int(now or time.time()) - RETENTION_SECONDS,),
    )


def _duree(seconds: float, english: bool) -> str:
    seconds = max(0, int(seconds))
    if seconds >= 86400:
        return f"{seconds // 86400} {'d' if english else 'j'}"
    if seconds >= 3600:
        return f"{seconds // 3600} h"
    return f"{max(1, seconds // 60)} min"


async def member_context(bot: Any, guild: Any, target_id: int, *, now: float | None = None) -> str:
    """La mémoire SentriX : ce que le serveur sait déjà du membre visé, en une ligne.

    Calculée à partir des vraies données — le journal unifié des sanctions et le
    membre Discord —, jamais inventée : une donnée absente n'apparaît pas.
    """
    now = float(now if now is not None else time.time())
    try:
        from cogs import language_runtime

        english = await language_runtime.get_language(bot, guild.id) == language_runtime.LANG_EN
    except Exception:  # noqa: BLE001 — la langue ne doit jamais bloquer une réponse
        english = False
    parts: list[str] = []
    try:
        row = await bot.db.fetchone(
            "SELECT COUNT(*) AS n FROM sanctions WHERE guild_id = ? AND user_id = ? AND created_at >= ?",
            (int(guild.id), int(target_id), int(now) - 30 * 86400),
        )
        count = int(row["n"] if row else 0)
    except Exception:  # noqa: BLE001
        count = 0
    if count:
        plural = "s" if count > 1 else ""
        parts.append(f"{count} sanction{plural} in 30 d" if english else f"{count} sanction{plural} en 30 j")
    member = guild.get_member(int(target_id)) if hasattr(guild, "get_member") else None
    joined = getattr(member, "joined_at", None)
    if joined is not None:
        age = _duree(now - joined.timestamp(), english)
        parts.append(f"member for {age}" if english else f"sur le serveur depuis {age}")
    created = getattr(member, "created_at", None)
    if created is not None and now - created.timestamp() < 30 * 86400:
        # Un compte récent est un signal ; un compte de six ans n'apprend rien.
        age = _duree(now - created.timestamp(), english)
        parts.append(f"account {age} old" if english else f"compte créé il y a {age}")
    return " · ".join(parts)


def current_target() -> int | None:
    trace = CURRENT.get()
    return target_of(trace.ctx) if trace is not None and trace.ctx is not None else None


def current_is_moderation() -> bool:
    trace = CURRENT.get()
    if trace is None:
        return False
    name = getattr(getattr(trace.ctx, "command", None), "qualified_name", None) or trace.command
    try:
        from utils import access_matrix

        return access_matrix.module_for_command(name) == "moderation"
    except Exception:  # noqa: BLE001
        return False


#: Les suites d'une sanction : (action, commande exécutée, arguments). Un bouton
#: n'est qu'une commande pré-remplie — même permission, même hiérarchie, même
#: log que si la personne qui clique l'avait tapée.
SUITE_PREFIX = "sx:suite:"
SUITES: dict[str, tuple[tuple[str, str, str], ...]] = {
    "warn": (("history", "modhistory", "{target}"), ("timeout", "mute", "{target} 10m Suite de {ref}")),
    "mute": (("history", "modhistory", "{target}"), ("untimeout", "unmute", "{target} Levée après {ref}")),
    "tempban": (("history", "modhistory", "{target}"), ("unban", "unban", "{target_id} Levée après {ref}")),
    "ban": (("history", "modhistory", "{target}"), ("unban", "unban", "{target_id} Levée après {ref}")),
    "kick": (("history", "modhistory", "{target}"),),
    "unmute": (("history", "modhistory", "{target}"),),
    "unban": (("history", "modhistory", "{target}"),),
}
SUITE_LABELS = {
    "fr": {"history": "Historique", "timeout": "Exclure 10 min", "untimeout": "Lever l'exclusion", "unban": "Débannir"},
    "en": {"history": "History", "timeout": "Time out 10 min", "untimeout": "Remove timeout", "unban": "Unban"},
}


def suite_command(command_name: str, action: str, target_id: int, ref: str) -> tuple[str, str] | None:
    """(commande, arguments) qu'exécute le bouton ``action`` d'une sanction ``command_name``."""
    for key, command, template in SUITES.get(command_name, ()):
        if key == action:
            return command, template.format(target=f"<@{int(target_id)}>", target_id=int(target_id), ref=ref)
    return None


def suites_view(command_name: str, target_id: int, ref: str, *, english: bool = False):
    """Les boutons des gestes logiques suivants, ou None s'il n'y en a pas."""
    import discord

    actions = SUITES.get(command_name)
    if not actions:
        return None
    labels = SUITE_LABELS["en" if english else "fr"]
    view = discord.ui.View(timeout=None)
    for key, _command, _template in actions:
        view.add_item(discord.ui.Button(
            label=labels[key],
            custom_id=f"{SUITE_PREFIX}{command_name}:{key}:{int(target_id)}:{ref}",
            style=discord.ButtonStyle.secondary if key == "history" else discord.ButtonStyle.danger
            if key == "timeout" else discord.ButtonStyle.success,
        ))
    return view


def parse_suite(custom_id: str) -> tuple[str, str, int, str] | None:
    """« sx:suite:warn:timeout:123:SX-ABC » -> (warn, timeout, 123, SX-ABC)."""
    if not str(custom_id).startswith(SUITE_PREFIX):
        return None
    parts = str(custom_id)[len(SUITE_PREFIX):].split(":")
    if len(parts) != 4 or not parts[2].isdigit():
        return None
    return parts[0], parts[1], int(parts[2]), parts[3]


def current_command() -> str | None:
    trace = CURRENT.get()
    if trace is None:
        return None
    return getattr(getattr(trace.ctx, "command", None), "qualified_name", None) or trace.command


def target_of(ctx: Any) -> int | None:
    """Le membre visé par la commande, s'il y en a un : le premier argument Membre/Utilisateur."""
    import discord

    for value in [*getattr(ctx, "args", ()), *getattr(ctx, "kwargs", {}).values()]:
        if isinstance(value, (discord.Member, discord.User)):
            return int(value.id)
    return None


__all__ = [
    "CURRENT", "RETENTION_SECONDS", "Trace", "classify", "ensure_schema", "is_traced", "lookup",
    "SUITES", "SUITE_PREFIX", "current_command", "current_is_moderation", "current_target", "make_ref", "member_context", "normalise_ref", "purge",
    "parse_suite", "record", "suite_command", "suites_view", "target_of", "visible_ref",
]
