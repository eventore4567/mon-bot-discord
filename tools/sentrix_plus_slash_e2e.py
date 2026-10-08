#!/usr/bin/env python3
"""Sticky, messages programmés, starboard et vocaux temporaires, en « / », sur le bot booté.

Ces fonctions (cogs/sentrix_plus.py) n'existaient qu'en « + », masquées de
l'aide faute de classement. Le catalogue les publie désormais ; ce scénario
vérifie leurs effets RÉELS en slash (lignes en base, republication, refus) et
que la décision de permission est la même qu'en préfixe.

    python3 tools/sentrix_plus_slash_e2e.py
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

ADMIN = dict(author_id=h.ADMIN_ID, author_roles=(h.ADMIN_ROLE_ID,))
MEMBER = dict(author_id=h.TARGET_ID, author_roles=(h.MEMBER_ROLE_ID,))


async def main() -> int:
    bot = await h.boot(quiet=True)
    guild = await h.setup_world(bot)
    db = bot.db

    async def slash(root: str, leaf: str, who: dict, **values) -> str:
        """Les options partent sous leur nom AFFICHÉ, comme Discord les envoie."""
        command = bot.tree.get_command(root).get_command(leaf)
        options = []
        for param in command.parameters:
            if param.display_name not in values:
                continue
            raw = values[param.display_name]
            options.append({"name": param.display_name, "type": param.type.value,
                            "value": int(raw) if param.type.value == 4 else str(raw)})
        since = len(h.CALLS)
        inter = h.build_interaction(bot, root, [{"name": leaf, "type": 1, "options": options}], **who)
        await asyncio.wait_for(bot.tree._call(inter), 15)
        await h.settle(idle=0.4, maximum=3)
        return h.visible_text(h.CALLS[since:]).replace("\n", " ")

    async def prefix(command: str, who: dict) -> str:
        since = len(h.CALLS)
        await asyncio.wait_for(h.run_prefix(bot, guild, command, **who), 15)
        await h.settle(idle=0.3, maximum=2)
        return h.visible_text(h.CALLS[since:]).replace("\n", " ")

    # 1 — Sticky : posé, fréquence, republication, retiré.
    await slash("sticky", "set", ADMIN, channel=h.CID, message="Lisez le règlement")
    row = await db.fetchone("SELECT content, every_messages FROM sentrix_sticky WHERE channel_id=?", (h.CID,))
    check(row is not None and row["content"] == "Lisez le règlement", "/sticky set enregistre le message")
    await slash("sticky", "frequency", ADMIN, channel=h.CID, every=3)
    row = await db.fetchone("SELECT every_messages FROM sentrix_sticky WHERE channel_id=?", (h.CID,))
    check(row is not None and int(row["every_messages"]) == 3, "/sticky frequency enregistre la fréquence")
    bot.get_cog("SentriXPlus")._no_sticky.clear()
    since = len(h.CALLS)
    for index in range(3):
        bot.dispatch("message", h.build_message(bot, guild, f"bavardage {index}", author_id=h.TARGET_ID,
                                                author_roles=(h.MEMBER_ROLE_ID,)))
        await h.settle(idle=0.2, maximum=1)
    reposted = any("Lisez le règlement" in str((js or {}).get("content")) for m, p, js in h.CALLS[since:]
                   if m == "POST" and p == f"/channels/{h.CID}/messages")
    check(reposted, "le sticky est republié après 3 messages")
    await slash("sticky", "off", ADMIN, channel=h.CID)
    check(await db.fetchone("SELECT 1 FROM sentrix_sticky WHERE channel_id=?", (h.CID,)) is None,
          "/sticky off retire le sticky")

    # 2 — Messages programmés : envoi, liste, annulation.
    await db.execute("DELETE FROM sentrix_scheduled_messages")
    await slash("schedule", "send", ADMIN, delay="10m", channel=h.CID, message="Réunion ce soir")
    row = await db.fetchone("SELECT id, status FROM sentrix_scheduled_messages WHERE content=?", ("Réunion ce soir",))
    check(row is not None and row["status"] == "pending", "/schedule send programme le message")
    shown = await slash("schedule", "list", ADMIN)
    check(row is not None and f"#{row['id']}" in shown and "Réunion ce soir" in shown, "/schedule list le montre", shown[:160])
    await slash("schedule", "cancel", ADMIN, id=row["id"] if row else 0)
    left = await db.fetchone("SELECT status FROM sentrix_scheduled_messages WHERE id=?", (row["id"] if row else 0,))
    check(left is None or left["status"] != "pending", "/schedule cancel l'annule", str(dict(left) if left else None))

    # 3 — Starboard : activé puis coupé.
    await slash("starboard", "setup", ADMIN, channel=h.LOGCID, threshold=4)
    row = await db.fetchone("SELECT channel_id, threshold FROM sentrix_starboard_config WHERE guild_id=?", (h.GID,))
    check(row is not None and int(row["channel_id"]) == h.LOGCID and int(row["threshold"]) == 4,
          "/starboard setup enregistre salon et seuil")
    await slash("starboard", "off", ADMIN)
    check(await db.fetchone("SELECT 1 FROM sentrix_starboard_config WHERE guild_id=?", (h.GID,)) is None,
          "/starboard off le coupe")

    # 4 — Même décision qu'en préfixe : un membre est refusé, avec le même motif.
    in_slash = await slash("schedule", "send", MEMBER, delay="10m", channel=h.CID, message="spam")
    in_prefix = await prefix(f"+schedule-send 10m <#{h.CID}> spam", MEMBER)
    check("Gérer les messages" in in_slash and "Gérer les messages" in in_prefix,
          "membre : /schedule send et +schedule-send refusés pour le même motif", f"{in_slash[:90]} | {in_prefix[:90]}")
    in_slash = await slash("starboard", "setup", MEMBER, channel=h.CID, threshold=2)
    check("Gérer le serveur" in in_slash, "membre : /starboard setup refusé (Gérer le serveur)", in_slash[:120])

    # 5 — Vocaux : un membre sans salon temporaire reçoit l'explication, pas un refus de permission.
    shown = await slash("voice", "rename", MEMBER, name="Mon salon")
    check("propriétaire" in shown and "Permission" not in shown,
          "membre : /voice rename explique qu'il faut posséder un vocal temporaire", shown[:140])

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
