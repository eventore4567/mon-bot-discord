#!/usr/bin/env python3
"""Coût du démarrage (on_ready) en fonction du nombre de serveurs, sur le bot booté.

Discord renvoie on_ready au démarrage et après chaque reconnexion complète. Tout
ce qu'un module y fait « pour chaque serveur » se paie N fois : à 100 000
serveurs, un appel Discord par serveur, c'est 100 000 appels qui consomment la
limite globale de l'API (≈ 50 requêtes/s) — celle dont l'AutoMod a besoin au même
moment pour supprimer le spam.

La sonde ajoute N serveurs ordinaires (non configurés, comme la grande majorité),
déclenche on_ready, et compte appels Discord et opérations base, par source.

    python3 tools/scale_ready_probe.py [--guilds 2000]
"""
from __future__ import annotations

import argparse
import asyncio
import contextvars
import os
import pathlib
import re
import sys
import time
import traceback
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import discord  # noqa: E402

import sentrix_e2e_harness as h  # noqa: E402

FIRST_GUILD = 300000000000000000


def add_guilds(bot, count: int) -> None:
    state = bot._connection
    for n in range(count):
        gid = FIRST_GUILD + n * 100
        data = {
            "id": str(gid), "name": f"Serveur {n}", "owner_id": str(gid + 1),
            "roles": [
                {"id": str(gid), "name": "@everyone", "permissions": str(h.MEMBER_PERMISSIONS.value),
                 "position": 0, "color": 0, "hoist": False, "managed": False, "mentionable": False},
                {"id": str(gid + 2), "name": "SentriX", "permissions": str(discord.Permissions.all().value),
                 "position": 1, "color": 0, "hoist": False, "managed": True, "mentionable": False},
            ],
            "channels": [
                {"id": str(gid + 3), "type": 0, "name": "general", "position": 0, "permission_overwrites": [],
                 "nsfw": False, "parent_id": None},
                {"id": str(gid + 4), "type": 2, "name": "vocal", "position": 1, "permission_overwrites": [],
                 "nsfw": False, "parent_id": None, "bitrate": 64000, "user_limit": 0},
            ],
            "members": [h.member_payload(h.BOT_ID, "SentriX", [gid + 2])],
            "emojis": [], "features": [], "afk_timeout": 300, "verification_level": 0,
            "default_message_notifications": 0, "explicit_content_filter": 0, "mfa_level": 0, "premium_tier": 0,
            "preferred_locale": "fr", "nsfw_level": 0, "stickers": [], "large": False, "member_count": 40,
            "system_channel_flags": 0, "premium_progress_bar_enabled": False, "voice_states": [],
        }
        state._add_guild(discord.Guild(data=data, state=state))


SOURCE = contextvars.ContextVar("source", default="?")


def caller() -> str:
    """Le module produit le plus proche (cogs/web d'abord, sinon utils) qui a déclenché l'appel."""
    frames = traceback.extract_stack()[:-2]
    for wanted in ("/cogs/", "/web/", "/utils/"):
        for frame in reversed(frames):
            path = frame.filename
            if wanted in path and "database" not in path and "sentrix_e2e_harness" not in path:
                return f"{pathlib.Path(path).parent.name}/{pathlib.Path(path).name}:{frame.name}"
    return "?"


async def main(count: int, rounds: int = 2) -> int:
    bot = await h.boot(quiet=True)
    await h.setup_world(bot)
    add_guilds(bot, count)
    db = bot.db
    db_ops: Counter = Counter()
    api: Counter = Counter()

    for name in ("execute", "fetchone", "fetchall"):
        original = getattr(db, name)

        async def counted(*args, _original=original, **kwargs):
            db_ops[caller()] += 1
            return await _original(*args, **kwargs)

        setattr(db, name, counted)

    since = len(h.CALLS)
    original_request = discord.http.HTTPClient.request

    async def request(self, route, **kwargs):
        api[caller()] += 1
        return await original_request(self, route, **kwargs)

    discord.http.HTTPClient.request = request

    # Le préchargement des invitations est volontairement lent (débit borné) : la
    # sonde compte les appels, elle n'attend pas leur étalement.
    invites_module = sys.modules.get("cogs.invites")
    if invites_module is not None:
        invites_module.INVITE_PREFETCH_INTERVAL = 0
    for round_ in range(1, rounds + 1):
        if round_ > 1:
            # Une reconnexion : les caches mémoire repartent de zéro, la base reste.
            invites = bot.get_cog("Invites")
            if invites is not None:
                invites.invite_cache.clear()
            api.clear()
            db_ops.clear()
            since = len(h.CALLS)
        await one_round(bot, round_, api, db_ops, since)
    sys.stdout.flush()
    os._exit(0)


async def one_round(bot, round_, api, db_ops, since) -> None:
    db = bot.db
    t0 = time.monotonic()
    bot.dispatch("ready")
    await h.settle(idle=2.0, maximum=600)
    elapsed = time.monotonic() - t0
    routes = Counter(f"{m} {re.sub(r'[0-9]{6,}', '#', p)}" for m, p, _ in h.CALLS[since:])

    total_guilds = len(bot.guilds)
    label = "démarrage (base vide)" if round_ == 1 else "reconnexion / redémarrage (base remplie)"
    print(f"\n=== on_ready n°{round_} — {label} — {total_guilds} serveurs, {elapsed:.1f} s")
    print(f"Appels Discord : {sum(api.values())} ({sum(api.values()) / total_guilds:.2f} par serveur)")
    for source, n in api.most_common(10):
        print(f"  {n:7d}  {source}")
    print("  routes :", routes.most_common(6))
    print(f"Opérations base : {sum(db_ops.values())} ({sum(db_ops.values()) / total_guilds:.2f} par serveur)")
    for source, n in db_ops.most_common(14):
        print(f"  {n:7d}  {source}")
    rows = await db.fetchall("SELECT name FROM sqlite_master WHERE type='table'")
    biggest = []
    for r in rows:
        try:
            c = await db.fetchone(f"SELECT COUNT(*) AS n FROM \"{r['name']}\"")
            biggest.append((c["n"], r["name"]))
        except Exception:
            pass
    print("Tables les plus remplies après on_ready :", sorted(biggest, reverse=True)[:6])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--guilds", type=int, default=2000)
    try:
        asyncio.run(main(parser.parse_args().guilds))
    except BaseException:
        traceback.print_exc()
        sys.stdout.flush()
        os._exit(1)
