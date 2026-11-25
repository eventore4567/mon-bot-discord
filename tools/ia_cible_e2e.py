#!/usr/bin/env python3
"""Actions de l'IA sur une cible, sur le bot booté (25/11/2026, PR #725).

- « ban pp » : le membre « pp fortnite » est trouvé AVANT la confirmation ;
- un nom introuvable est cité, sans carte ;
- revue Codex : une suppression « de @absent » (cible qui n'est pas un
  membre visé) garde sa confirmation ;
- revue Codex : une réponse texte à SentriX dont Discord n'a pas joint le
  message cité va le chercher (GET), au lieu d'être ignorée.

    python3 tools/ia_cible_e2e.py
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

import discord  # noqa: E402
import sentrix_e2e_harness as h  # noqa: E402
from suggestions_e2e import RESULTS, check  # noqa: E402

PP = 100000000000009001
ABSENT = 100000000000009999


async def main() -> int:
    from utils import ai_actions

    bot = await h.boot(quiet=True)
    guild = await h.setup_world(bot)
    p = h.member_payload(PP, "pp fortnite", [h.MEMBER_ROLE_ID])
    p["user"]["bot"] = True
    guild._add_member(discord.Member(data=p, guild=guild, state=guild._state))
    ai = next(c for c in bot.cogs.values() if hasattr(c, "_handle_parsed_action"))

    async def agir(action, texte="x"):
        message = h.build_message(bot, guild, texte, author_id=h.AUTHOR_ID, author_roles=(h.ADMIN_ROLE_ID,))
        since = len(h.CALLS)
        await ai._handle_parsed_action(message, action, "+")
        await h.settle(idle=0.6, maximum=6)
        return h.CALLS[since:]

    def textes(appels):
        sortie = []
        for c in appels:
            sortie.append(h.describe_call(*c))
            for e in ((c[2] or {}).get("embeds") or []):
                sortie.append(str(e.get("description")))
        return "\n".join(sortie)

    appels = await agir(ai_actions.ParsedAction(intent="moderation.ban", slots={"target": "pp"}))
    t = textes(appels)
    check("Confirmation requise" in t and f"<@{PP}>" in t and "target=" not in t,
          "« ban pp » : la confirmation nomme le membre trouvé (pp fortnite)", t[-200:])
    check(not any(c[0] == "PUT" and "/bans/" in c[1] for c in appels), "rien n'est banni avant le clic")

    appels = await agir(ai_actions.ParsedAction(intent="moderation.ban", slots={"target": "zorglub"}))
    t = textes(appels)
    check("zorglub" in t and "Confirmation requise" not in t,
          "un nom introuvable est cité, sans carte de confirmation", t[-200:])

    appels = await agir(ai_actions.ParsedAction(
        intent="moderation.purge", slots={"count": 100, "target": f"<@{ABSENT}>"}))
    t = textes(appels)
    check("Confirmation requise" in t and not any("bulk-delete" in c[1] for c in appels),
          "suppression « de @absent » : la confirmation reste, rien n'est supprimé", t[-200:])

    # Réponse texte à SentriX, message cité non joint par Discord.
    cite = h.next_id()
    message = h.build_message(bot, guild, "et pourquoi ?", author_id=h.AUTHOR_ID, author_roles=(h.ADMIN_ROLE_ID,))
    message.reference = discord.MessageReference(message_id=cite, channel_id=h.CID, guild_id=h.GID)
    since = len(h.CALLS)
    bot.dispatch("message", message)
    await h.settle(idle=0.6, maximum=6)
    check(any(c[0] == "GET" and c[1].endswith(f"/messages/{cite}") for c in h.CALLS[since:]),
          "réponse texte sans message cité joint : SentriX va le chercher",
          str([h.describe_call(*c)[:80] for c in h.CALLS[since:]][:4]))

    # Revue Codex (PR #725) : répondre (sans ping) à une CARTE de réponse de l'IA
    # continue la conversation ; un panneau ordinaire, lui, ne la déclenche pas.
    from utils import reponses_ia

    async def repondre_a(carte_ia: bool) -> list:
        data = h.message_payload(h.next_id(), h.CID, "", author_id=h.BOT_ID, name="SentriX")
        data["components"] = [{"type": 17, "components": [{"type": 10, "content": "longue réponse"}]}]
        cite_msg = discord.Message(state=bot._connection, channel=guild.get_channel(h.CID), data=data)
        if carte_ia:
            reponses_ia.noter(cite_msg)
        suite = h.build_message(bot, guild, "et ensuite ?", author_id=h.AUTHOR_ID, author_roles=(h.ADMIN_ROLE_ID,))
        suite.reference = discord.MessageReference.from_message(cite_msg)
        suite.reference.resolved = cite_msg
        debut = len(h.CALLS)
        bot.dispatch("message", suite)
        await h.settle(idle=0.8, maximum=8)
        return [c for c in h.CALLS[debut:] if c[0] == "POST" and c[1].startswith(f"/channels/{h.CID}/")]

    check(bool(await repondre_a(True)), "réponse à une carte de l'IA : la conversation continue")
    check(not await repondre_a(False), "réponse à un panneau ordinaire : rien ne se déclenche")

    # 25/11/2026 : « oui vzi fait » après un prompt proposé par SentriX → image.
    generees = []

    async def generation_espion(_message, demande):
        generees.append(demande)
        return True

    ai._send_generated_image_natural = generation_espion
    data = h.message_payload(h.next_id(), h.CID,
                             "Utilise ce prompt : **SentriX, robot Discord futuriste noir et bleu**.",
                             author_id=h.BOT_ID, name="SentriX")
    propose_msg = discord.Message(state=bot._connection, channel=guild.get_channel(h.CID), data=data)
    oui = h.build_message(bot, guild, "oui vzi fait", author_id=h.AUTHOR_ID, author_roles=(h.ADMIN_ROLE_ID,))
    oui.reference = discord.MessageReference.from_message(propose_msg)
    oui.reference.resolved = propose_msg
    bot.dispatch("message", oui)
    await h.settle(idle=0.8, maximum=8)
    check(any("robot Discord futuriste" in g for g in generees),
          "« oui vzi fait » après un prompt proposé : l'image est générée avec ce prompt", str(generees)[:160])

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
