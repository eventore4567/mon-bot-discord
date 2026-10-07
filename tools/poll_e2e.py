#!/usr/bin/env python3
"""Parcours complet des sondages sur le bot booté comme en production.

Le sondage publié est un sondage NATIF Discord : c'est Discord qui gère le vote,
le double vote, la clôture à l'heure et les résultats. Ce scénario vérifie donc
ce que SentriX contrôle — le formulaire, l'éditeur, les permissions et la charge
exacte envoyée à Discord.

    python3 tools/poll_e2e.py
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
from suggestions_e2e import (  # noqa: E402
    RESULTS, _base, callbacks, check, persona, submit_modal, text_field,
)


def _find_item(bot, view_cls_name: str, label: str):
    """(entity_id, item) du bouton `label` actuellement enregistré.

    L'éditeur est relogé dans un panneau Components V2 (panels.avec_composants) :
    ses boutons appartiennent au Panneau et leurs rappels enveloppés n'ont pas de
    nom exploitable. Le libellé, unique dans le registre, suffit à les retrouver.
    """
    del view_cls_name
    for entity_id, items in bot._connection._view_store._views.items():
        for item in items.values():
            if getattr(item, "label", None) == label:
                return entity_id, item
    return None, None


async def press(bot, entity_id, item, who: str) -> int:
    since = len(h.CALLS)
    p = persona(who)
    message = h.message_payload(int(entity_id) if entity_id else h.next_id(), h.CID, "")
    data = _base(p["author_id"], p["author_roles"], kind=3,
                 data={"custom_id": item.custom_id, "component_type": 2}, message=message)
    inter = discord.Interaction(data=data, state=bot._connection)
    bot._connection._view_store.dispatch_view(2, item.custom_id, inter)
    await h.settle(idle=0.4, maximum=3.0)
    return since


async def main() -> int:
    bot = await h.boot(quiet=True)
    guild = await h.setup_world(bot)
    # 1 — Le bon système est chargé, et lui seul.
    check(bot.get_cog("PollUI") is not None, "le créateur de sondages natifs est chargé")
    command = bot.get_command("poll")
    check(command is not None and type(command.cog).__name__ == "PollUI", "+poll appartient au créateur natif",
          str(type(command.cog).__name__ if command and command.cog else None))
    check(bot.get_cog("Utility") is not None, "le cog Utility est toujours chargé (aucune collision de nom)")
    leaf = bot.tree.get_command("poll")
    check(leaf is not None and leaf.callback.__module__ == "cogs.poll_ui", "/poll est la commande native du créateur")

    # 2 — /poll ouvre le formulaire.
    since = len(h.CALLS)
    inter = h.build_interaction(bot, "poll", [], **persona("membre"))
    await asyncio.wait_for(bot.tree._call(inter), 15)
    await h.settle(idle=0.3, maximum=1.5)
    modals = [c for c in callbacks(since) if c.get("type") == 9]
    check(len(modals) == 1, "/poll ouvre le formulaire de création")
    modal_id = modals[0]["data"]["custom_id"] if modals else ""

    # 3 — Le formulaire mène à l'éditeur.
    def field(item_name: str, value: str) -> dict:
        return {"type": 1, "components": [{"type": 4, "custom_id": item_name, "value": value}]}

    # Les identifiants des champs, lus dans le formulaire RÉELLEMENT envoyé.
    def _ids(node) -> list[str]:
        out = []
        if isinstance(node, dict):
            if node.get("type") == 4 and node.get("custom_id"):
                out.append(node["custom_id"])
            for key in ("components", "component"):
                child = node.get(key)
                for item in (child if isinstance(child, list) else [child] if child else []):
                    out.extend(_ids(item))
        return out

    ids = _ids({"components": modals[0]["data"].get("components", [])}) if modals else []
    check(len(ids) >= 5, "le formulaire contient la question et quatre réponses", str(ids))
    ids += [""] * (5 - len(ids))
    since = await submit_modal(bot, modal_id, [
        field(ids[0], "Soirée jeux vendredi ?"),
        field(ids[1], "Oui"),
        field(ids[2], "Non"),
        field(ids[3], "Peut-être"),
        field(ids[4], ""),
    ], "membre")
    shown = h.visible_text(h.CALLS[since:])
    check("Soirée jeux vendredi" in shown and "Peut-être" in shown, "l'éditeur montre la question et les réponses", shown[:200])

    # 4 — Publier envoie un sondage NATIF.
    entity, publish = _find_item(bot, "PollBuilderView", "Publier")
    check(publish is not None, "l'éditeur propose « Publier »")
    if publish is not None:
        since = await press(bot, entity, publish, "membre")
        sent = [c for c in h.CALLS[since:] if c[0] == "POST" and c[1] == f"/channels/{h.CID}/messages"]
        poll = (sent[0][2] or {}).get("poll") if sent else None
        check(bool(poll), "Discord reçoit un sondage natif", str([c[:2] for c in h.CALLS[since:]])[:240])
        if poll:
            answers = [a["poll_media"]["text"] for a in poll.get("answers", [])]
            check(poll["question"]["text"] == "Soirée jeux vendredi ?" and answers == ["Oui", "Non", "Peut-être"],
                  "question et réponses exactes", str(poll)[:200])
            check(poll.get("duration") == 24 and poll.get("allow_multiselect") is False,
                  "durée 24 h et choix unique par défaut", str({k: poll.get(k) for k in ("duration", "allow_multiselect")}))

    # 5 — En préfixe, la forme rapide « question | réponse | réponse ».
    since = len(h.CALLS)
    await asyncio.wait_for(h.run_prefix(bot, guild, "+poll [48h] Quel jeu ? | Valorant | Minecraft", **persona("membre")), 15)
    await h.settle(idle=0.3, maximum=2)
    sent = [c for c in h.CALLS[since:] if c[0] == "POST" and "/messages" in c[1] and (c[2] or {}).get("poll")]
    poll = sent[0][2]["poll"] if sent else {}
    check(bool(sent) and poll.get("duration") == 48 and len(poll.get("answers", [])) == 2,
          "+poll en une ligne publie un sondage natif de 48 h", str(poll)[:200])

    failed = [r for r in RESULTS if not r[0]]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} étapes réussies.")
    sys.stdout.flush()
    os._exit(1 if failed else 0)


if __name__ == "__main__":
    asyncio.run(main())
