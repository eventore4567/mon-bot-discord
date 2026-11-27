#!/usr/bin/env python3
"""« Supprime les liens qui sont dans ce serveur » (27/11/2026).

L'IA répondait qu'elle ne pouvait pas. +clear <n> liens [serveur] supprime les
messages déjà envoyés qui contiennent un lien ; l'IA s'en sert.

    python3 tools/clear_liens_e2e.py
"""
from __future__ import annotations

import asyncio
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import sentrix_e2e_harness as h  # noqa: E402
from suggestions_e2e import RESULTS, check  # noqa: E402


async def main() -> int:
    from utils import ai_actions

    bot = await h.boot(quiet=True)
    guild = await h.setup_world(bot)

    import discord

    historique, avec, sans = [], [], []
    for i in range(3):
        m = h.build_message(bot, guild, f"regarde https://exemple{i}.example/page", author_id=h.TARGET_ID, author_name="m")
        avec.append(m.id)
        historique.append(m)
        m = h.build_message(bot, guild, f"message normal numéro {i}", author_id=h.TARGET_ID, author_name="m")
        sans.append(m.id)
        historique.append(m)

    # Le banc d'essai invente un historique « msg N » sans lien : on fournit le vrai.
    original_history = discord.abc.Messageable.history

    def history(self, *, limit=100, **kwargs):
        async def gen():
            for message in reversed(historique[-limit:]):
                yield message
        return gen()

    discord.abc.Messageable.history = history
    debut = len(h.CALLS)
    try:
        await asyncio.wait_for(h.run_prefix(bot, guild, "+clear 20 liens", author_id=h.ADMIN_ID,
                                            author_roles=(h.ADMIN_ROLE_ID,)), 20)
    finally:
        discord.abc.Messageable.history = original_history
    await h.settle(idle=1.0, maximum=6)
    supprimes = set()
    for m, p, js in h.CALLS[debut:]:
        if p.endswith("bulk-delete"):
            supprimes |= {int(x) for x in (js or {}).get("messages", [])}
        elif m == "DELETE" and "/messages/" in p:
            try:
                supprimes.add(int(p.rsplit("/", 1)[-1]))
            except ValueError:
                pass
    check(set(avec) <= supprimes, "+clear 20 liens supprime les messages avec un lien", f"{len(set(avec) & supprimes)}/3")
    check(not (set(sans) & supprimes), "les messages sans lien restent")
    texte = h.visible_text(h.CALLS[debut:])
    check("avec un lien supprimé" in texte, "la réponse dit combien de messages avec un lien", texte[-150:])

    action = await ai_actions.parse_action("sup les lien qui son dans se serv", guild_id=guild.id,
                                           channel_id=h.CID, user_id=h.ADMIN_ID)
    check(action is not None and action.intent == "moderation.purge_links", "l'IA comprend « sup les lien qui son dans se serv »",
          str(getattr(action, "intent", None)))

    failed = [r for r in RESULTS if not r[0]]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} étapes réussies.")
    sys.stdout.flush()
    os._exit(1 if failed else 0)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except BaseException:
        import traceback

        traceback.print_exc()
        sys.stdout.flush()
        os._exit(1)
