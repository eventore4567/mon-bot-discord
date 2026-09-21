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
