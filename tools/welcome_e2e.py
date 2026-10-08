#!/usr/bin/env python3
"""Bienvenue et départ sur le bot booté comme en production.

Chaque étape passe par le vrai chemin : l'événement Discord d'arrivée ou de
départ, les vrais contrôles du /setup servi (V74 → V73 → V3), et les appels
HTTP réellement émis.

    python3 tools/welcome_e2e.py
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
from suggestions_e2e import RESULTS, _base, callbacks, check  # noqa: E402

DM_CHANNEL = "100000000000009001"  # salon privé renvoyé par le harnais


def posts(since: int, channel_id) -> list[dict]:
    return [c[2] if isinstance(c[2], dict) else {} for c in h.CALLS[since:]
            if c[0] == "POST" and c[1] == f"/channels/{channel_id}/messages"]


def role_puts(since: int, user_id: int) -> list[int]:
    found = []
    for method, path, _ in h.CALLS[since:]:
        m = re.fullmatch(rf"/guilds/{h.GID}/members/{user_id}/roles/(\d+)", path)
        if method == "PUT" and m:
            found.append(int(m.group(1)))
    return found


def body_of(payload: dict) -> str:
    parts = [str(payload.get("content") or "")]
    for embed in payload.get("embeds") or ():
        parts += [str(embed.get("title") or ""), str(embed.get("description") or "")]
    return "\n".join(parts)


async def join(bot, name: str) -> tuple[int, int]:
    uid = h.next_id()
    data = h.member_payload(uid, name, [])
    data["guild_id"] = str(h.GID)
    since = len(h.CALLS)
    bot._connection.parse_guild_member_add(data)
    await h.settle(idle=0.8, maximum=6)
    return uid, since


async def leave(bot, uid: int, name: str) -> int:
    since = len(h.CALLS)
    bot._connection.parse_guild_member_remove({"guild_id": str(h.GID), "user": h.user(uid, name)})
    await h.settle(idle=0.8, maximum=6)
    return since


def find(item, wanted):
    if wanted(item):
        return item
    children = list(getattr(item, "children", []) or [])
    if getattr(item, "accessory", None) is not None:
        children.append(item.accessory)
    for child in children:
        found = find(child, wanted)
        if found is not None:
            return found
    return None


async def setup_page(bot, guild, page: str):
    from cogs import setup_experience_v74 as v74

    view = v74.SentriXSetupV74(bot, guild, h.ADMIN_ID)
    await view.prepare()
    view.page = page
    view.backend = view._new_backend(page)
    view.clear_items()
    await view._build_page(page)
    return view


def control(view, wanted):
    for child in view.children:
        found = find(child, wanted)
        if found is not None:
            return found
    return None


def admin_interaction(bot):
    data = _base(h.ADMIN_ID, (h.ADMIN_ROLE_ID,), kind=3, data={"custom_id": "x", "component_type": 2},
                 message=h.message_payload(h.next_id(), h.CID, ""))
    return discord.Interaction(data=data, state=bot._connection)


async def main() -> int:
    from cogs import setup_v2_completion as completion
    from utils import welcome_autoroles

    bot = await h.boot(quiet=True)
    guild = await h.setup_world(bot)
    await bot.db.set_guild_config(
        h.GID, "welcome_message",
        "U={user} N={username} D={display_name} S={server} C={member_count} A={created_at} J={joined_at}",
    )
    await bot.db.set_guild_config(h.GID, "goodbye_message", "Bye {user} {username} {server} {member_count}")

    # 1 — Une arrivée : un message, les variables remplacées, le membre notifié.
    uid, since = await join(bot, "arrivant")
    sent = posts(since, h.CID)
    check(len(sent) == 1, "une arrivée = un seul message de bienvenue", f"{len(sent)} message(s)")
    text = body_of(sent[0]) if sent else ""
    # Le vrai @ est posé UNE fois au-dessus du panneau ; dans le corps, {user} devient le nom.
    check(text.count(f"<@{uid}>") == 1 and "U=arrivant" in text and "N=arrivant" in text and "S=Serveur test" in text,
          "{user} {username} {server} remplacés, le @ une seule fois", text[:200])
    check(re.search(r"A=<t:\d+:D>", text) and re.search(r"J=<t:\d+:D>", text) and "{" not in text,
          "{created_at} et {joined_at} deviennent des dates Discord", text[:300])
    allowed = (sent[0].get("allowed_mentions") or {}) if sent else {}
    check(str(uid) in [str(u) for u in allowed.get("users", [])], "le membre accueilli est notifié", str(allowed))
    check(role_puts(since, uid) == [h.MEMBER_ROLE_ID], "le rôle d'arrivée historique est toujours donné",
          str(role_puts(since, uid)))
    check(not posts(since, DM_CHANNEL), "pas de message privé tant que l'option est coupée")

    # 2 — Plusieurs rôles d'arrivée, réglés par le vrai sélecteur du /setup.
    view = await setup_page(bot, guild, "welcome")
    select = control(view, lambda i: type(i).__name__ == "WelcomeAutoRolesSelect")
    check(select is not None and select.max_values == welcome_autoroles.MAX_ROLES,
          "la page Bienvenue propose un sélecteur multi-rôles (5 max.)")
    select._values = [guild.get_role(h.MEMBER_ROLE_ID), guild.get_role(h.PING_ROLE_ID)]
    await select.callback(admin_interaction(bot))
    await h.settle(idle=0.3, maximum=2)
    ids = await welcome_autoroles.configured_ids(bot, h.GID)
    check(ids == [h.MEMBER_ROLE_ID, h.PING_ROLE_ID], "deux rôles enregistrés, dans l'ordre", str(ids))
    conf = await bot.db.get_guild_config(h.GID)
    check(conf["autorole"] == h.MEMBER_ROLE_ID, "le premier reste dans guild_config.autorole (dashboard, +setautorole)")

    uid, since = await join(bot, "duo")
    check(sorted(role_puts(since, uid)) == sorted([h.MEMBER_ROLE_ID, h.PING_ROLE_ID]),
          "les deux rôles sont donnés à l'arrivée", str(role_puts(since, uid)))

    # 3 — Rôles refusés au réglage : modération, géré par un bot, au-dessus de SentriX.
    for role_id, why in ((h.MOD_ROLE_ID, "Bannir"), (h.BOT_ROLE_ID, "géré"), (h.ADMIN_ROLE_ID, "Administrateur")):
        select._values = [guild.get_role(h.MEMBER_ROLE_ID), guild.get_role(role_id)]
        since = len(h.CALLS)
        await select.callback(admin_interaction(bot))
        await h.settle(idle=0.3, maximum=2)
        shown = h.visible_text(h.CALLS[since:])
        after = await welcome_autoroles.configured_ids(bot, h.GID)
        check(why in shown and after == [h.MEMBER_ROLE_ID, h.PING_ROLE_ID],
              f"rôle {guild.get_role(role_id).name} refusé avec la raison, rien n'est écrasé", shown[:160])

    # 4 — Un rôle devenu dangereux APRÈS le réglage n'est plus donné ; les autres si.
    await welcome_autoroles.save(bot, h.GID, [h.MEMBER_ROLE_ID, h.MOD_ROLE_ID])
    uid, since = await join(bot, "apres-coup")
    check(role_puts(since, uid) == [h.MEMBER_ROLE_ID], "le rôle de modération est écarté à l'arrivée, le rôle Membre est donné",
          str(role_puts(since, uid)))
    await welcome_autoroles.save(bot, h.GID, [h.MEMBER_ROLE_ID])

    # 5 — Option « mp » par la vraie modale : copie privée de la bienvenue.
    presentation = await completion._welcome_presentation(bot, h.GID)
    modal = completion.WelcomeSettingsModal(view.backend, conf=await bot.db.get_guild_config(h.GID), presentation=presentation)
    check("mp=off" in modal.options_input.default, "la modale affiche l'option mp", modal.options_input.default)
    modal.options_input._value = modal.options_input.default.replace("mp=off", "mp=on")
    for field in (modal.title_input, modal.welcome_input, modal.goodbye_input):
        field._value = field.default
    await modal.on_submit(admin_interaction(bot))
    check((await completion._welcome_presentation(bot, h.GID))["dm"] is True, "mp=on est enregistré")
    check((await completion._welcome_presentation(bot, h.GID))["ping"] is True, "le ping n'est pas écrasé au passage")

    uid, since = await join(bot, "prive")
    check(len(posts(since, h.CID)) == 1 and len(posts(since, DM_CHANNEL)) == 1,
          "mp=on : le salon ET le message privé", f"salon={len(posts(since, h.CID))} mp={len(posts(since, DM_CHANNEL))}")
    dm = posts(since, DM_CHANNEL)
    check(dm and (dm[0].get("allowed_mentions") or {}).get("parse") == [], "le message privé ne notifie aucune mention",
          str(dm[0].get("allowed_mentions") if dm else None))

    # 6 — MP fermés : la bienvenue part quand même, sans erreur.
    original_send = discord.abc.Messageable.send

    async def closed_dm(self, *args, **kwargs):
        if isinstance(self, (discord.Member, discord.User)):
            raise discord.Forbidden(type("R", (), {"status": 403, "reason": "Forbidden"})(), "Cannot send messages to this user")
        return await original_send(self, *args, **kwargs)

    discord.abc.Messageable.send = closed_dm
    try:
        uid, since = await join(bot, "ferme")
    finally:
        discord.abc.Messageable.send = original_send
    check(len(posts(since, h.CID)) == 1, "MP fermés : la bienvenue du salon part quand même")

    # 7 — Aperçu depuis les pages Bienvenue et Départs : vrai message, aucune notification.
    for page, label in (("welcome", "Bienvenue"), ("goodbye", "Départs")):
        view = await setup_page(bot, guild, page)
        button = control(view, lambda i: getattr(i, "label", None) == "Aperçu")
        check(button is not None, f"page {label} : bouton Aperçu présent")
        if button is None:
            continue
        since = len(h.CALLS)
        await button.callback(admin_interaction(bot))
        await h.settle(idle=0.4, maximum=3)
        sent = posts(since, h.CID)
        check(len(sent) == 1 and (sent[0].get("allowed_mentions") or {}).get("parse") == []
              and not (sent[0].get("allowed_mentions") or {}).get("users"),
              f"page {label} : l'aperçu envoie le message sans notifier", str(sent[0].get("allowed_mentions") if sent else None))
        check("Test envoyé" in h.visible_text(h.CALLS[since:]), f"page {label} : l'aperçu confirme où il a été envoyé")
    goodbye_view = await setup_page(bot, guild, "goodbye")
    check(control(goodbye_view, lambda i: getattr(i, "label", None) == "Texte de départ") is not None,
          "page Départs : le texte de départ se modifie depuis sa propre page")

    # 8 — Départ : un message, les variables remplacées, personne n'est notifié.
    uid, _ = await join(bot, "partant")
    since = await leave(bot, uid, "partant")
    sent = posts(since, h.CID)
    check(len(sent) == 1, "un départ = un seul message", f"{len(sent)} message(s)")
    text = body_of(sent[0]) if sent else ""
    check(text.count(f"<@{uid}>") == 1 and "Bye partant partant Serveur test" in text and "{" not in text,
          "variables du départ remplacées, le @ une seule fois", text[:200])
    check(sent and not (sent[0].get("allowed_mentions") or {}).get("users"), "le départ ne notifie personne par défaut")

    failed = [r for r in RESULTS if not r[0]]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} étapes réussies.")
    sys.stdout.flush()
    os._exit(1 if failed else 0)


if __name__ == "__main__":
    asyncio.run(main())
