#!/usr/bin/env python3
"""+fight sur le bot booté : un vrai combat au tour par tour entre deux membres.

    python3 tools/fight_e2e.py
"""
from __future__ import annotations

import asyncio
import os
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import discord  # noqa: E402

import sentrix_e2e_harness as h  # noqa: E402
from suggestions_e2e import RESULTS, _base, _buttons, check  # noqa: E402

P1 = dict(author_id=h.SECOND_ID, author_roles=(h.MEMBER_ROLE_ID,))
STRANGER = 100000000000009999


async def main() -> int:
    bot = await h.boot(quiet=True)
    games = sys.modules["cogs.games_economy"]
    games.FIGHT_WINDUP_SECONDS = 0.05
    guild = await h.setup_world(bot)

    async def click(custom_id: str, message_id: int, user_id: int) -> str:
        since = len(h.CALLS)
        data = _base(user_id, (h.MEMBER_ROLE_ID,), kind=3, data={"custom_id": custom_id, "component_type": 2},
                     message=h.message_payload(message_id, h.CID, ""))
        bot._connection._view_store.dispatch_view(2, custom_id, discord.Interaction(data=data, state=bot._connection))
        await h.settle(idle=0.25, maximum=3)
        return h.visible_text(h.CALLS[since:])

    def last_panel(since: int):
        for method, path, js in reversed(h.CALLS[since:]):
            if isinstance(js, dict) and js.get("components") and method in ("POST", "PATCH") and "/callback" not in path:
                return h.visible_text([(method, path, js)]), {b.get("label"): b for b in _buttons({"components": js["components"]})}
        return "", {}

    async def start_fight():
        since = len(h.CALLS)
        asyncio.create_task(h.run_prefix(bot, guild, f"+fight <@{h.TARGET_ID}>", **P1))
        for _ in range(80):  # la première commande d'un bot froid prend plus d'une seconde
            await asyncio.sleep(0.1)
            if "doit accepter" in h.visible_text(h.CALLS[since:]):
                break
        await h.settle(idle=0.2, maximum=2)
        return since, h.STATE["msg_seq"]

    since, msg = await start_fight()
    text, buttons = last_panel(since)
    accept = next((b for label, b in buttons.items() if "Accepter" in str(label)), None)
    check(accept is not None and "doit accepter" in text, "+fight envoie une invitation, rien ne commence", text[:160])
    shown = await click(accept["custom_id"], msg, h.SECOND_ID)
    check("Seul le membre défié" in shown, "le défieur ne peut pas accepter à la place de l'autre", shown[:120])
    shown = await click(accept["custom_id"], msg, STRANGER)
    check("Seul le membre défié" in shown, "un spectateur ne peut pas accepter", shown[:120])

    since = len(h.CALLS)
    await click(accept["custom_id"], msg, h.TARGET_ID)
    text, buttons = last_panel(since)
    check("Défi accepté" in text and "100 PV" in text and "Attaquer" in " ".join(map(str, buttons)),
          "accepté : les deux à 100 PV, boutons Attaquer / Bouclier / Pouvoir", text[:220])
    check(buttons.get("Pouvoir (0/3)", {}).get("disabled") is True, "le pouvoir est grisé tant qu'il n'est pas chargé",
          str(list(buttons)))

    who = re.search(r"À \*\*([^*]+)\*\* de jouer", text)
    names = {guild.get_member(h.SECOND_ID).display_name: h.SECOND_ID, guild.get_member(h.TARGET_ID).display_name: h.TARGET_ID}
    current = names.get(who.group(1)) if who else None
    other = h.TARGET_ID if current == h.SECOND_ID else h.SECOND_ID
    shown = await click(buttons["Attaquer"]["custom_id"], msg, other)
    check("pas votre tour" in shown, "celui dont ce n'est pas le tour est refusé", shown[:120])
    shown = await click(buttons["Attaquer"]["custom_id"], msg, STRANGER)
    check("deux autres membres" in shown, "un spectateur ne peut pas jouer", shown[:120])

    # Le combat jusqu'au bout : chacun attaque, puis lance son pouvoir dès qu'il peut.
    frames, rounds = [], 0
    while rounds < 80:
        rounds += 1
        since = len(h.CALLS)
        text, buttons = last_panel(since - 1) if False else (text, buttons)
        who = re.search(r"À \*\*([^*]+)\*\* de jouer", text)
        if not who:
            break
        current = names[who.group(1)]
        power = next((b for label, b in buttons.items() if str(label) == "Pouvoir" and not b.get("disabled")), None)
        target_button = power or buttons["Attaquer"]
        await click(target_button["custom_id"], msg, current)
        frames.append(h.visible_text(h.CALLS[since:]))
        text, buttons = last_panel(since)
    joined = "\n".join(frames)
    check("prend son élan" in joined and "frappe" in joined, "chaque coup s'anime : l'élan, puis l'impact", joined[:200])
    check("pouvoir" in joined.lower() and "déchaîne" in joined, "le pouvoir spécial est utilisé une fois chargé")
    check("remporte le combat" in text or "Égalité" in text, "le combat se termine par un vrai résultat", text[-200:])
    winner = re.search(r"\*\*([^*]+)\*\* remporte le combat", text)
    if winner:
        wid = names[winner.group(1)]
        rows = await bot.db.fetchall(
            "SELECT * FROM game_transactions WHERE guild_id = ? AND user_id = ? AND game_name = 'fight'", (h.GID, wid))
        check(len(rows) == 1, "le gagnant est payé une seule fois", str(len(rows)))
        check("0 PV" in text, "le perdant finit à 0 PV", text[-200:])

    # Abandon : un joueur qui ne joue pas perd la partie (délai entre parties effacé).
    await bot.db.execute("DELETE FROM game_cooldowns")
    games.FIGHT_TURN_SECONDS = 1
    since, msg = await start_fight()
    _text, buttons = last_panel(since)
    accept = next(b for label, b in buttons.items() if "Accepter" in str(label))
    await click(accept["custom_id"], msg, h.TARGET_ID)
    await asyncio.sleep(1.5)
    await h.settle(idle=0.3, maximum=3)
    text, _ = last_panel(since)
    check("abandon" in text and "remporte le combat" in text, "45 s sans jouer : abandon, l'autre gagne", text[-160:])

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
