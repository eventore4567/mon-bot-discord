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

#: Qui agit, et par quel canal, pendant l'écriture en cours : (identifiant, source).
#: Posé par les commandes (cogs/trace.py), les menus et formulaires (/setup) et le
#: dashboard ; lu par le journal des réglages (utils/config_journal.py).
ACTOR: contextvars.ContextVar[tuple[int | None, str] | None] = contextvars.ContextVar(
    "sentrix_actor", default=None,
)


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
            "SELECT COUNT(*) AS n FROM sanctions WHERE guild_id = ? AND user_id = ? AND created_at >= ? "
            "AND action NOT LIKE 'un%' AND action NOT LIKE 'clear%'",  # une levée n'est pas une sanction
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


async def ticket_memory(bot: Any, guild: Any, user_id: int, *, exclude_ticket: int | None = None,
                        now: float | None = None) -> str:
    """Ce qu'un membre du staff doit savoir en prenant un ticket : les tickets d'avant
    du membre, puis son contexte de modération (``member_context``)."""
    now = float(now if now is not None else time.time())
    try:
        from cogs import language_runtime

        english = await language_runtime.get_language(bot, guild.id) == language_runtime.LANG_EN
    except Exception:  # noqa: BLE001
        english = False
    parts: list[str] = []
    try:
        rows = await bot.db.fetchall(
            "SELECT id, status, created_at FROM tickets WHERE guild_id = ? AND user_id = ? AND id != ? "
            "ORDER BY created_at DESC",
            (int(guild.id), int(user_id), int(exclude_ticket or 0)),
        )
    except Exception:  # noqa: BLE001
        rows = []
    if rows:
        last = rows[0]
        age = _duree(now - int(last["created_at"] or now), english)
        state = str(last["status"] or "")
        if english:
            state = {"ouvert": "still open", "ferme": "closed", "supprime": "closed and deleted"}.get(state, state)
            parts.append(f"{len(rows)} earlier ticket{'s' if len(rows) > 1 else ''} (last {age} ago, {state})")
        else:
            state = {"ouvert": "encore ouvert", "ferme": "fermé", "supprime": "fermé et supprimé"}.get(state, state)
            parts.append(f"{len(rows)} ticket{'s' if len(rows) > 1 else ''} avant celui-ci (dernier il y a {age}, {state})")
    else:
        parts.append("first ticket" if english else "premier ticket")
    context = await member_context(bot, guild, int(user_id), now=now)
    if context:
        parts.append(context)
    return " · ".join(parts)


# Libellés des sanctions dans la mémoire d'arrivée : (singulier, pluriel) FR puis EN.
# Une levée (unban, unmute…) n'est pas une sanction : elle n'est jamais comptée.
_SANCTION_WORDS = {
    "warn": ("avertissement", "avertissements", "warning", "warnings"),
    "mute": ("mute", "mutes", "mute", "mutes"),
    "timeout": ("mute", "mutes", "mute", "mutes"),
    "kick": ("expulsion", "expulsions", "kick", "kicks"),
    "ban": ("ban", "bans", "ban", "bans"),
    "tempban": ("ban temporaire", "bans temporaires", "temporary ban", "temporary bans"),
}


def _is_reversal(action: str) -> bool:
    return action.startswith("un") or action.startswith("clear")


async def join_memory(bot: Any, guild: Any, member: Any, *, now: float | None = None) -> str:
    """À l'arrivée d'un membre : ce que le serveur sait déjà de cette personne.

    Les départs viennent du journal de conservation (``member_data_retention_events``,
    écrit à chaque départ), les sanctions du journal unifié — tous deux liés à
    l'identifiant, donc conservés après le départ. Une source illisible ne produit
    aucune affirmation : jamais « première venue » sans journal des départs.
    """
    now = float(now if now is not None else time.time())
    try:
        from cogs import language_runtime

        english = await language_runtime.get_language(bot, guild.id) == language_runtime.LANG_EN
    except Exception:  # noqa: BLE001
        english = False
    guild_id, user_id = int(guild.id), int(member.id)
    parts: list[str] = []
    try:
        row = await bot.db.fetchone(
            "SELECT COUNT(*) AS n, MAX(created_at) AS last FROM member_data_retention_events "
            "WHERE guild_id = ? AND user_id = ? AND event_type = 'member_remove'",
            (guild_id, user_id),
        )
        left = int(row["n"] or 0) if row else 0
        if left:
            age = _duree(now - int(row["last"] or now), english)
            parts.append(
                f"returning: left {left} time{'s' if left > 1 else ''}, last {age} ago" if english
                else f"revient : parti {left} fois, dernier départ il y a {age}"
            )
        else:
            parts.append("first known visit" if english else "première venue connue")
    except Exception:  # noqa: BLE001 — journal absent : on n'affirme rien
        pass
    try:
        rows = await bot.db.fetchall(
            "SELECT action, created_at FROM sanctions WHERE guild_id = ? AND user_id = ? ORDER BY created_at DESC",
            (guild_id, user_id),
        )
    except Exception:  # noqa: BLE001
        rows = []
    counts: dict[str, int] = {}
    last_at = None
    for sanction in rows:
        action = str(sanction["action"] or "").lower()
        if not action or _is_reversal(action):
            continue
        counts[action] = counts.get(action, 0) + 1
        last_at = last_at or int(sanction["created_at"] or now)
    if counts:
        total = sum(counts.values())
        detail = []
        for action, n in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
            words = _SANCTION_WORDS.get(action, (action, action, action, action))
            word = words[2:] if english else words[:2]
            detail.append(f"{n} {word[1] if n > 1 else word[0]}")
        age = _duree(now - last_at, english)
        plural = "s" if total > 1 else ""
        parts.append(
            f"{total} past sanction{plural} here ({', '.join(detail)}), last {age} ago" if english
            else f"{total} sanction{plural} passée{plural} ici ({', '.join(detail)}), la dernière il y a {age}"
        )
    created = getattr(member, "created_at", None)
    if created is not None and now - created.timestamp() < 30 * 86400:
        age = _duree(now - created.timestamp(), english)
        parts.append(f"account {age} old" if english else f"compte créé il y a {age}")
    return " · ".join(parts)


# Familles de filtres AutoMod, pour résumer l'historique d'un membre en mots.
_AUTOMOD_FAMILIES = {
    "antilink": "link", "blacklist_link": "link", "blacklist_word_link": "link",
    "antiinvite": "invite", "antiscam": "scam",
    "blacklist_word": "word", "antiinsult": "word",
    "antimention": "mention",
    "antispam": "spam", "antispam_duplicate": "spam", "antiemoji": "spam",
}
_AUTOMOD_WORDS = {
    "link": ("lien", "liens", "link", "links"),
    "invite": ("invitation", "invitations", "invite", "invites"),
    "scam": ("arnaque", "arnaques", "scam", "scams"),
    "word": ("mot interdit", "mots interdits", "blocked word", "blocked words"),
    "mention": ("mentions en masse", "mentions en masse", "mass mention", "mass mentions"),
    "spam": ("spam", "spams", "spam", "spam"),
    "other": ("autre", "autres", "other", "other"),
}


def _ordinal(n: int, english: bool) -> str:
    if not english:
        return "1er" if n == 1 else f"{n}e"
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


async def automod_memory(bot: Any, guild: Any, member_id: int, *, now: float | None = None) -> str:
    """Sur une carte AutoMod : le rang de cet incident sur 30 jours, par type, puis
    ``member_context`` (sanctions du staff, ancienneté, compte récent).

    Un incident = une ligne ``suppression`` dans ``automod_logs`` (une par incident,
    pas par message supprimé) ; celui de la carte y est déjà écrit.
    """
    now = float(now if now is not None else time.time())
    try:
        from cogs import language_runtime

        english = await language_runtime.get_language(bot, guild.id) == language_runtime.LANG_EN
    except Exception:  # noqa: BLE001
        english = False
    parts: list[str] = []
    try:
        rows = await bot.db.fetchall(
            "SELECT filter_name FROM automod_logs WHERE guild_id = ? AND user_id = ? "
            "AND action = 'suppression' AND timestamp >= ?",
            (int(guild.id), int(member_id), int(now) - 30 * 86400),
        )
    except Exception:  # noqa: BLE001
        rows = []
    if rows:
        families: dict[str, int] = {}
        for row in rows:
            family = _AUTOMOD_FAMILIES.get(str(row["filter_name"] or ""), "other")
            families[family] = families.get(family, 0) + 1
        text = (f"{_ordinal(len(rows), True)} AutoMod incident in 30 d" if english
                else f"{_ordinal(len(rows), False)} incident AutoMod en 30 j")
        if len(rows) > 1:
            detail = []
            for family, n in sorted(families.items(), key=lambda item: (-item[1], item[0])):
                words = _AUTOMOD_WORDS[family]
                word = words[2:] if english else words[:2]
                detail.append(f"{n} {word[1] if n > 1 else word[0]}")
            text += f" ({', '.join(detail)})"
        parts.append(text)
    context = await member_context(bot, guild, int(member_id), now=now)
    if context:
        parts.append(context)
    return " · ".join(parts)


async def economy_context(bot: Any, guild: Any, target_id: int, actor_id: int | None = None,
                          *, now: float | None = None) -> str:
    """Avant qu'un membre du staff crée de l'argent : le solde du membre et les ajouts
    du staff des 30 derniers jours — et s'il se crédite lui-même."""
    now = float(now if now is not None else time.time())
    try:
        from cogs import language_runtime

        english = await language_runtime.get_language(bot, guild.id) == language_runtime.LANG_EN
    except Exception:  # noqa: BLE001
        english = False
    try:
        from cogs.setup_v2_core import economy_settings

        symbol = (await economy_settings(bot, guild.id))["currency_symbol"]
    except Exception:  # noqa: BLE001
        symbol = "🪙"

    def nombre(value: int) -> str:
        return f"{int(value):,}".replace(",", " ")

    parts: list[str] = []
    try:
        row = await bot.db.fetchone(
            "SELECT cash, bank FROM economy WHERE guild_id = ? AND user_id = ?", (int(guild.id), int(target_id)),
        )
        if row is not None:
            total = int(row["cash"] or 0) + int(row["bank"] or 0)
            parts.append(f"balance {nombre(total)} {symbol}" if english else f"solde {nombre(total)} {symbol}")
        grants = await bot.db.fetchone(
            "SELECT COUNT(*) AS n, COALESCE(SUM(amount), 0) AS total FROM economy_transactions "
            "WHERE guild_id = ? AND receiver_id = ? AND transaction_type = 'admin_grant' AND created_at >= ?",
            (int(guild.id), int(target_id), int(now) - 30 * 86400),
        )
        count = int(grants["n"] or 0) if grants else 0
        if count:
            amount = nombre(int(grants["total"] or 0))
            parts.append(
                f"{count} staff grant{'s' if count > 1 else ''} in 30 d ({amount} {symbol})" if english
                else f"{count} ajout{'s' if count > 1 else ''} du staff en 30 j ({amount} {symbol})"
            )
    except Exception:  # noqa: BLE001
        pass
    if actor_id is not None and int(actor_id) == int(target_id):
        parts.append("to yourself" if english else "à soi-même")
    return " · ".join(parts)


#: Les commandes par lesquelles le staff crée de l'XP (nom legacy et slash du catalogue).
XP_COMMANDS = ("add-xp", "set-xp", "levels xp-add", "levels xp-set")


async def levels_context(bot: Any, guild: Any, target_id: int, actor_id: int | None = None,
                         *, now: float | None = None) -> str:
    """Quand le staff crée de l'XP : le niveau et le rang du membre APRÈS le
    changement, et les ajouts d'XP du staff sur 30 jours — lus dans le fil des
    commandes (``sentrix_traces``), où chaque +add-xp / +set-xp réussi est écrit."""
    now = float(now if now is not None else time.time())
    try:
        from cogs import language_runtime

        english = await language_runtime.get_language(bot, guild.id) == language_runtime.LANG_EN
    except Exception:  # noqa: BLE001
        english = False
    guild_id = int(guild.id)
    parts: list[str] = []
    try:
        row = await bot.db.fetchone(
            "SELECT level, xp FROM levels WHERE guild_id = ? AND user_id = ?", (guild_id, int(target_id)),
        )
        if row is not None:
            level, xp = int(row["level"] or 0), int(row["xp"] or 0)
            # Même classement que /rank (utils/stats_service.get_rank), sans son cache.
            above = await bot.db.fetchone(
                "SELECT COUNT(*) AS n FROM levels WHERE guild_id = ? AND (level > ? OR (level = ? AND xp > ?))",
                (guild_id, level, level, xp),
            )
            rank = int(above["n"] or 0) + 1 if above else 1
            parts.append(f"level {level} · #{rank} on the server" if english
                         else f"niveau {level} · {_ordinal(rank, False)} du serveur")
    except Exception:  # noqa: BLE001
        pass
    try:
        await ensure_schema(bot.db)
        marks = ",".join("?" for _ in XP_COMMANDS)
        row = await bot.db.fetchone(
            f"SELECT COUNT(*) AS n FROM sentrix_traces WHERE guild_id = ? AND target_id = ? AND outcome = 'ok' "
            f"AND command IN ({marks}) AND created_at >= ?",
            (guild_id, int(target_id), *XP_COMMANDS, int(now) - 30 * 86400),
        )
        count = int(row["n"] or 0) if row else 0
    except Exception:  # noqa: BLE001
        count = 0
    # La commande en cours n'est écrite dans le fil qu'à sa fin : la compter ici.
    if (current_command() or "") in XP_COMMANDS:
        count += 1
    if count:
        parts.append(f"{count} staff XP grant{'s' if count > 1 else ''} in 30 d" if english
                     else f"{count} ajout{'s' if count > 1 else ''} d'XP du staff en 30 j")
    if actor_id is not None and int(actor_id) == int(target_id):
        parts.append("to yourself" if english else "à soi-même")
    return " · ".join(parts)


async def memory_line(bot: Any, guild: Any) -> str:
    """La mémoire de la commande en cours, selon sa famille (sanctions, économie)."""
    target = current_target()
    if not target or guild is None or bot is None:
        return ""
    name = current_command() or ""
    try:
        from utils import access_matrix

        module = access_matrix.module_for_command(name)
    except Exception:  # noqa: BLE001
        module = None
    trace = CURRENT.get()
    if module == "moderation":
        return await member_context(bot, guild, target)
    if module == "economy":
        return await economy_context(bot, guild, target, getattr(trace, "actor_id", None))
    if name in XP_COMMANDS:
        return await levels_context(bot, guild, target, getattr(trace, "actor_id", None))
    return ""


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
    "ACTOR", "CURRENT", "RETENTION_SECONDS", "Trace", "classify", "ensure_schema", "is_traced", "lookup",
    "SUITES", "SUITE_PREFIX", "current_command", "current_is_moderation", "current_target", "make_ref", "member_context", "normalise_ref", "purge",
    "economy_context", "memory_line", "parse_suite", "record", "ticket_memory", "suite_command", "suites_view", "target_of", "visible_ref",
    "automod_memory", "join_memory", "levels_context", "XP_COMMANDS",
]
