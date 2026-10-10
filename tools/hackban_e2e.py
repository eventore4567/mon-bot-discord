#!/usr/bin/env python3
"""+hackban sur le bot booté : bannir par identifiant un compte absent du serveur,
avec la même permission que +ban, sans jamais contourner +ban pour un présent.

    python3 tools/hackban_e2e.py
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

MEMBER = dict(author_id=h.SECOND_ID, author_roles=(h.MEMBER_ROLE_ID,))
MOD = dict(author_id=h.MOD_ID, author_roles=(h.MOD_ROLE_ID,))
ABSENT = 100000000000009999


async def main() -> int:
    bot = await h.boot(quiet=True)
    guild = await h.setup_world(bot)
    bot.get_cog("Moderation").SANCTION_DUPLICATE_TTL = 0

    async def run(command: str, who: dict) -> tuple[str, list]:
        since = len(h.CALLS)
        await asyncio.wait_for(h.run_prefix(bot, guild, command, **who), 15)
        await h.settle(idle=0.4, maximum=3)
        calls = h.CALLS[since:]
        bans = [p for m, p, _ in calls if m == "PUT" and p.startswith(f"/guilds/{h.GID}/bans/")]
        return h.visible_text([c for c in calls if c[1] == f"/channels/{h.CID}/messages"]), bans

    async def sanctions(uid: int) -> list:
        return [dict(r) for r in await bot.db.fetchall(
            "SELECT action, moderator_id, reason FROM sanctions WHERE guild_id = ? AND user_id = ?", (h.GID, uid))]

    shown, bans = await run(f"+hackban {ABSENT} raid connu", MEMBER)
    check(not bans and "accès" in shown, "un simple membre est refusé (même décision que +ban)", shown[:160])

    shown, bans = await run(f"+hackban {h.TARGET_ID} spam", MOD)
    check(not bans and "+ban" in shown, "une personne présente est renvoyée vers +ban (hiérarchie)", shown[:160])
    shown, bans = await run("+hackban abc raid", MOD)
    check(not bans and "invalide" in shown, "un identifiant invalide est refusé", shown[:160])
    shown, bans = await run(f"+hackban {h.MOD_ID} test", MOD)
    check(not bans and "vous-même" in shown, "impossible de se bannir soi-même", shown[:160])

    since = len(h.CALLS)
    shown, bans = await run(f"+hackban {ABSENT} raid connu", MOD)
    check(bans == [f"/guilds/{h.GID}/bans/{ABSENT}"], "le modérateur bannit le compte absent par identifiant", str(bans))
    rows = await sanctions(ABSENT)
    check(len(rows) == 1 and rows[0]["action"] == "ban" and rows[0]["moderator_id"] == h.MOD_ID,
          "le dossier de sanction est enregistré au nom du modérateur", str(rows))
    logs = [c for c in h.CALLS[since:] if c[1] == f"/channels/{h.LOGCID}/messages"]
    check(len(logs) == 1 and "Réf. SX-" in shown, "une carte de log, et la réponse porte sa référence",
          f"{len(logs)} carte(s) | {shown[-120:]}")

    from discord.ext import commands
    from utils import error_texts

    hint = error_texts.argument_error_text(commands.MemberNotFound(str(ABSENT)), usage="+ban <membre> [raison]")
    check(f"+hackban {ABSENT}" in (hint or ""), "+ban sur l'identifiant d'un absent propose +hackban", str(hint))
    other = error_texts.argument_error_text(commands.MemberNotFound(str(ABSENT)), usage="+tempban <membre> <duree>")
    check("hackban" not in (other or ""), "+tempban ne propose pas +hackban", str(other))

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
