"""Fast command-candidate index for SentriX natural-language actions.

Kept outside cogs.ai so the command routing logic can evolve/test independently from the
conversation UI, memory and Discord listeners. This module does not execute commands and
never decides permissions: the normal SentriX/Discord permission pipeline remains the
single source of truth.
"""

from __future__ import annotations

import difflib
import re
import unicodedata
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

def normalize_request(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(text or ""))
    return "".join(
        char for char in normalized if not unicodedata.combining(char)
    ).lower().strip()


def natural_command_line(
    bot: commands.Bot,
    question: str,
    prefix: str,
    *,
    has_attachment: bool,
) -> str | None:
    """Map explicit natural requests to already-loaded commands without an LLM call."""
    normalized = normalize_request(question)
    action_intent = bool(re.search(
        r"\b(ouvre|affiche|lance|execute|fais|fait|utilise|ajoute|cree|genere|dessine|importe|"
        r"supprime|enleve|retire|mets|configure)\b",
        normalized,
    ))

    image_intent = bool(
        re.search(r"\b(image|photo|illustration|dessin)\b", normalized)
        and re.search(r"\b(fais|fait|cree|genere|dessine)\b", normalized)
    )
    if image_intent:
        tail = re.split(
            r"\b(?:image|photo|illustration|dessin)\b",
            question,
            maxsplit=1,
            flags=re.IGNORECASE,
        )[-1]
        tail = re.sub(
            r"^\s*(?:de|du|d['’]|avec|sur|representant|qui represente)\s*",
            "",
            tail,
            flags=re.IGNORECASE,
        ).strip(" :,-")
        return f"{prefix}image" + (f" {tail}" if tail else "")

    if action_intent and re.search(r"\b(setup|configuration)\b", normalized):
        return f"{prefix}setup"
    if action_intent and re.search(r"\b(help|aide|commandes)\b", normalized):
        return f"{prefix}help"

    emoji_action = any(word in normalized for word in ("emoji", "emogi", "amogi"))
    pasted_emoji = re.search(r"<a?:[A-Za-z0-9_]{2,32}:[0-9]+>", question)
    named_emoji = re.search(r"[:;]([A-Za-z0-9_]{2,32}):", question)
    direct_url = re.search(r"https://\S+", question)

    if emoji_action and re.search(r"\b(ajoute|cree|importe)\b", normalized):
        if pasted_emoji:
            return f"{prefix}addemoji {pasted_emoji.group(0)}"
        if named_emoji:
            command = f"{prefix}addemoji {named_emoji.group(1)}"
            if direct_url:
                command += f" {direct_url.group(0)}"
            return command
        tail = re.split(
            r"\b(?:emoji|emogi|amogi)\b", question, maxsplit=1, flags=re.IGNORECASE
        )[-1]
        tail = re.sub(
            r"^\s*(?:nomme|appele|appelé|avec|de|moi)\s+",
            "", tail, flags=re.IGNORECASE
        ).strip()
        if tail:
            return f"{prefix}addemoji {tail}"
        if has_attachment:
            return f"{prefix}addemoji emoji"

    if emoji_action and re.search(r"\b(supprime|enleve|retire)\b", normalized):
        if pasted_emoji:
            return f"{prefix}deleteemoji {pasted_emoji.group(0)}"
        if named_emoji:
            return f"{prefix}deleteemoji {named_emoji.group(1)}"
        tail = re.split(
            r"\b(?:emoji|emogi|amogi)\b", question, maxsplit=1, flags=re.IGNORECASE
        )[-1]
        target = tail.strip(" :;,")
        if target:
            return f"{prefix}deleteemoji {target}"

    candidates: list[tuple[int, re.Match, commands.Command]] = []
    excluded = {"ai", "sentrix", "chat", "ask"}
    for command in bot.walk_commands():
        if command.qualified_name in excluded:
            continue
        triggers = [command.qualified_name]
        parent = (
            command.qualified_name.rsplit(" ", 1)[0]
            if " " in command.qualified_name
            else ""
        )
        triggers.extend(f"{parent} {alias}".strip() for alias in command.aliases)
        for trigger in triggers:
            trigger_normalized = normalize_request(trigger)
            match = re.search(
                rf"(?<![\w-]){re.escape(trigger_normalized)}(?![\w-])",
                normalized,
            )
            if match:
                candidates.append((len(trigger_normalized), match, command))

    for _, match, command in sorted(candidates, key=lambda item: item[0], reverse=True):
        direct_request = match.start() == 0 or normalized.startswith("commande ")
        if not action_intent and not direct_request:
            continue
        trailing = question[match.end():].strip()
        while trailing:
            cleaned = re.sub(
                r"^(?:avec|sur|pour|de|du|la|le|les|moi)\s+",
                "",
                trailing,
                count=1,
                flags=re.IGNORECASE,
            )
            if cleaned == trailing:
                break
            trailing = cleaned.strip()
        if not command.clean_params:
            trailing = ""
        command_line = f"{prefix}{command.qualified_name}"
        if trailing:
            command_line += f" {trailing}"
        return command_line
    return None
