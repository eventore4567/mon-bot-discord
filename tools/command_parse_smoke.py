#!/usr/bin/env python3
"""Parse real SentriX command arguments with discord.py without connecting to Discord.

This catches a class of regressions that signature-only audits cannot see: a command can
print `+gamble <montant>` while its internal ``params`` still asks the parser for a bogus
``ctx`` argument. We exercise Command._parse_arguments() on selected scalar commands.
"""
from __future__ import annotations

import asyncio
import inspect
import os
import pathlib
import sys
import tempfile
from types import SimpleNamespace

from discord.ext.commands.view import StringView

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class ParseContext(SimpleNamespace):
    pass


async def _parse(command, bot, raw: str):
    ctx = ParseContext(
        bot=bot,
        view=StringView(raw),
        interaction=None,
        message=SimpleNamespace(attachments=[]),
        guild=None,
        author=None,
        current_parameter=None,
        args=[],
        kwargs={},
    )
    await command._parse_arguments(ctx)
    return ctx


async def run() -> int:
    errors: list[str] = []
    with tempfile.TemporaryDirectory(prefix="sentrix-parse-") as temp_dir:
        os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")
        os.environ["DATABASE_PATH"] = str(pathlib.Path(temp_dir) / "sentrix-ci.db")

        import main

        bot = main.BotAllInOne()
        await bot.db.connect()
        for extension in main.EXTENSIONS:
            try:
                await bot.load_extension(extension)
            except Exception as exc:
                errors.append(f"load {extension}: {type(exc).__name__}: {exc}")

        # command name -> (raw user input after command name, expected parsed value)
        cases = {
            "gamble": ("10", 10),
            "deposit": ("100", "100"),
            "withdraw": ("50", "50"),
            "roll": ("6", 6),
        }
        for name, (raw, expected) in cases.items():
            command = bot.get_command(name)
            if command is None:
                errors.append(f"missing command: {name}")
                continue
            exposed = [
                param_name
                for param_name in command.params
                if param_name.casefold() not in {"self", "cog", "ctx", "context", "interaction"}
            ]
            if not exposed:
                errors.append(f"{name}: no user parameter in command.params")
                continue
            try:
                ctx = await _parse(command, bot, raw)
            except Exception as exc:
                errors.append(f"{name} {raw!r}: {type(exc).__name__}: {exc}")
                continue
            parsed_values = list(ctx.args[2:] if getattr(command, "cog", None) is not None else ctx.args[1:])
            parsed_values.extend(ctx.kwargs.values())
            if expected not in parsed_values:
                errors.append(f"{name}: expected parsed {expected!r}, got {parsed_values!r}")

        # Explicitly forbid the historical regression regardless of display sanitizers.
        gamble = bot.get_command("gamble")
        if gamble is not None:
            internal = [name.casefold() for name in gamble.params]
            if internal.count("ctx") > 1 or internal.count("context") or internal.count("interaction"):
                errors.append(f"gamble internal parser polluted: {internal}")

        current = asyncio.current_task()
        pending = [task for task in asyncio.all_tasks() if task is not current and not task.done()]
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        close_db = getattr(bot.db, "close", None)
        if close_db:
            result = close_db()
            if inspect.isawaitable(result):
                await result

    for error in errors:
        print(f"[ERROR] {error}")
    if errors:
        print(f"FAILED: {len(errors)} parser regression(s)")
        return 1
    print("OK: real discord.py parsing smoke tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
