#!/usr/bin/env python3
"""Coût d'un message ordinaire sur le bot booté : appels base de données et temps,
par écouteur on_message. Un message de membre traverse ~20 écouteurs ; chaque
aller-retour base se paie à chaque message du serveur.

    python3 tools/message_cost_probe.py
"""
from __future__ import annotations

import asyncio
import contextvars
import os
import pathlib
import sys
import time
from collections import defaultdict

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import sentrix_e2e_harness as h  # noqa: E402

CURRENT = contextvars.ContextVar("listener", default="(hors écouteur)")
CALLS: dict[str, int] = defaultdict(int)
SECONDS: dict[str, float] = defaultdict(float)
MESSAGES = 40


async def main() -> int:
    bot = await h.boot(quiet=True)
    guild = await h.setup_world(bot)
    db = bot.db
    for name in ("execute", "fetchone", "fetchall", "executemany"):
        original = getattr(db, name, None)
        if original is None:
            continue

        async def counted(*args, _original=original, **kwargs):
            CALLS[CURRENT.get()] += 1
            return await _original(*args, **kwargs)

        setattr(db, name, counted)
    listeners = bot.extra_events.get("on_message", [])
    wrapped = []
    for listener in listeners:
        owner = getattr(listener, "__self__", None)
        label = f"{getattr(listener, '__module__', '?').replace('cogs.', '')}." + (
            type(owner).__name__ if owner else getattr(listener, "__qualname__", "?").split(".")[0])

        async def run(*args, _listener=listener, _label=label, **kwargs):
            token = CURRENT.set(_label)
            start = time.perf_counter()
            try:
                return await _listener(*args, **kwargs)
            finally:
                SECONDS[_label] += time.perf_counter() - start
                CURRENT.reset(token)

        run.__name__ = "on_message"
        wrapped.append(run)
    bot.extra_events["on_message"] = wrapped
    # Échauffement (caches), puis mesure.
    for _ in range(3):
        bot.dispatch("message", h.build_message(bot, guild, "salut", author_id=h.SECOND_ID, author_roles=(h.MEMBER_ROLE_ID,)))
    await h.settle(idle=0.5, maximum=4)
    CALLS.clear(); SECONDS.clear()
    for i in range(MESSAGES):
        bot.dispatch("message", h.build_message(bot, guild, f"message ordinaire numéro {i}", author_id=h.SECOND_ID,
                                                author_roles=(h.MEMBER_ROLE_ID,)))
        await asyncio.sleep(0.05)
    await h.settle(idle=1.0, maximum=8)
    total = sum(CALLS.values())
    print(f"{MESSAGES} messages ordinaires — {total / MESSAGES:.1f} appels base par message\n")
    for label in sorted(set(CALLS) | set(SECONDS), key=lambda k: -CALLS.get(k, 0)):
        print(f"{CALLS.get(label, 0) / MESSAGES:6.2f} appels/msg  {SECONDS.get(label, 0) / MESSAGES * 1000:7.2f} ms/msg  {label}")
    sys.stdout.flush()
    os._exit(0)


if __name__ == "__main__":
    asyncio.run(main())
