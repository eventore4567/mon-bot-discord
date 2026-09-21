"""Fast command-candidate index for SentriX natural-language actions.

Kept outside cogs.ai so the command routing logic can evolve/test independently from the
conversation UI, memory and Discord listeners. This module does not execute commands and
never decides permissions: the normal SentriX/Discord permission pipeline remains the
single source of truth.
"""

from __future__ import annotations

import difflib
import re
from typing import Iterable

from discord.ext import commands

from utils import access_matrix, ai_actions


CommandIndex = list[tuple[commands.Command, str, set[str]]]


def build_command_index(bot: commands.Bot) -> CommandIndex:
    """Build a stable in-memory index from the commands currently loaded in the bot."""
    index: CommandIndex = []
    for command in bot.walk_commands():
        if getattr(command, "hidden", False) or not getattr(command, "enabled", True):
            continue

        qualified = str(getattr(command, "qualified_name", "") or "").strip()
        if not qualified:
            continue

        root = qualified.split(" ", 1)[0].casefold()
        # Avoid routing back into the AI command family itself.
        if access_matrix.module_for_command(root) == "ai":
            continue

        aliases = " ".join(str(a) for a in getattr(command, "aliases", ()) or ())
        description = str(
            getattr(command, "description", "") or getattr(command, "help", "") or ""
        )
        signature = str(getattr(command, "signature", "") or "")

        qualified_norm = ai_actions.normalize_text(qualified)
        haystack = ai_actions.normalize_text(
            f"{qualified} {aliases} {description} {signature}"
        )
        command_tokens = set(re.findall(r"[a-z0-9_-]{2,}", haystack))
        index.append((command, qualified_norm, command_tokens))

    return index


def rank_command_candidates(
    index: CommandIndex,
    question: str,
    *,
    limit: int = 20,
    minimum_score: float = 1.2,
) -> list[commands.Command]:
    """Return the most relevant loaded commands for a natural-language request.

    Ranking is intentionally cheap: token overlap + fuzzy qualified-name ratio + a strong
    exact-name-in-request boost. Permissions are checked later by normal command execution.
    """
    normalized = ai_actions.normalize_text(question)
    tokens = set(re.findall(r"[a-z0-9_-]{2,}", normalized))

    rows: list[tuple[float, commands.Command]] = []
    for command, qualified_norm, command_tokens in index:
        overlap = len(tokens & command_tokens)
        ratio = (
            difflib.SequenceMatcher(a=normalized, b=qualified_norm).ratio()
            if normalized
            else 0.0
        )
        direct = 4.0 if qualified_norm and qualified_norm in normalized else 0.0
        score = overlap * 2.0 + ratio * 3.0 + direct
        if score >= minimum_score:
            rows.append((score, command))

    rows.sort(key=lambda item: item[0], reverse=True)
    return [command for _score, command in rows[: max(1, int(limit))]]


def arguments_grounded_in_question(question: str, arguments: str) -> bool:
    """Reject classifier arguments that are not grounded in the user's request.

    The classifier may reorder/normalize values, but it must not invent IDs, mentions,
    targets, reasons or arbitrary free-text parameters.
    """
    raw_question = str(question or "")
    raw_arguments = str(arguments or "")
    if not raw_arguments:
        return True
    if any(ch in raw_arguments for ch in ("\n", "\r", "`" * 3)):
        return False

    question_ids = set(re.findall(r"\d{15,22}", raw_question))
    argument_ids = set(re.findall(r"\d{15,22}", raw_arguments))
    if not argument_ids.issubset(question_ids):
        return False

    qnorm = ai_actions.normalize_text(raw_question)
    anorm = ai_actions.normalize_text(raw_arguments)
    qtokens = set(re.findall(r"[a-z0-9_-]+", qnorm))
    harmless = {"on", "off", "oui", "non", "true", "false"}

    for token in re.findall(r"[a-z0-9_-]+", anorm):
        if token in harmless or token.isdigit() or len(token) < 3:
            continue
        if re.fullmatch(r"\d{1,4}[smhjd]", token):
            digits = re.match(r"\d+", token).group(0)
            if digits not in qnorm:
                return False
            continue
        if token not in qtokens and token not in qnorm:
            return False
    return True


def command_needs_confirmation(command_line: str, prefix: str) -> bool:
    """Return whether a routed existing command requires explicit confirmation."""
    raw = str(command_line or "")
    if raw.startswith(prefix):
        raw = raw[len(prefix):]
    parts = raw.strip().split()
    if not parts:
        return False

    root = parts[0].casefold()
    dangerous = set(access_matrix.GUILD_OWNER_COMMANDS) | {
        "delete-channel", "deleteemoji", "massrole", "roleall",
        "blacklist-user", "blacklist-users", "lockdown-server", "panic",
        "pay", "give-money", "bot-leave", "reset-logs-all",
    }
    if root in dangerous or root.startswith((
        "wipe", "reset", "restore", "delete-", "mass"
    )):
        return True
    if root == "clear" and len(parts) > 1:
        try:
            return int(parts[1]) >= 50
        except ValueError:
            return False
    return False
