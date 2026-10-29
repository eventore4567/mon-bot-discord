#!/usr/bin/env python3
"""Giveaway V6 de bout en bout, sur le bot booté (brief V6, partie 2).

Configuration par les vrais formulaires (lot, durée, gagnants, conditions dont
le niveau XP minimum), aperçu privé, publication avec lien de confirmation,
puis participations réelles : membre éligible, rôle interdit, rôle obligatoire
manquant, niveau trop bas ; tirage, reroll, et reprise après redémarrage
(un giveaway échu en base est clôturé par la boucle).

    python3 tools/giveaway_v6_e2e.py
"""
from __future__ import annotations

import asyncio
import json
import os
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import discord  # noqa: E402
import sentrix_e2e_harness as h  # noqa: E402
from suggestions_e2e import _base  # noqa: E402

RESULTS: list[tuple[bool, str]] = []
ELIGIBLE, ELIGIBLE_2, INTERDIT, SANS_ROLE, NIVEAU_BAS = (
    100000000000000501, 100000000000000502, 100000000000000503, 100000000000000504, 100000000000000505)


def check(ok: bool, label: str, detail: str = "") -> None:
    RESULTS.append((bool(ok), label))
    print(("OK   " if ok else "ÉCHEC ") + label + (f" — {detail}" if detail and not ok else ""))


def inter(bot, uid, roles, *, message_id=None, custom_id="x"):
    data = _base(uid, roles, kind=3, data={"custom_id": custom_id, "component_type": 2},
                 message=h.message_payload(message_id or h.next_id(), h.CID, ""))
    return discord.Interaction(data=data, state=bot._connection)


def reponses(calls) -> str:
    return " ".join(h.visible_text([c]) + " " + str((c[2] or {}).get("content") or "") for c in calls
                    if isinstance(c[2], dict) and ("/webhooks/" in c[1] or c[1].endswith("/callback")))


async def main() -> int:
    bot = await h.boot(quiet=True)
    guild = await h.setup_world(bot)
    from cogs import giveaway_v2 as gv

    cog = bot.get_cog("GiveawayV2")
    await cog.ensure_schema()
    ctx = await bot.get_context(h.build_message(bot, guild, "+giveaway create", author_id=h.ADMIN_ID,
                                                author_roles=(h.ADMIN_ROLE_ID,)))
    vue = gv.GiveawayBuilderView(cog, ctx)
    admin = lambda: inter(bot, h.ADMIN_ID, (h.ADMIN_ROLE_ID,))  # noqa: E731

    # 1. Formulaire obligatoire (le vrai on_submit, avec validation).
    modal = gv.BaseModal(vue)
    modal.prize._value, modal.duration._value, modal.winners._value, modal.description._value = "Nitro", "2h", "1", "Bonne chance"
    await modal.on_submit(admin())
    check(vue.state.prize == "Nitro" and vue.state.duration_seconds == 7200 and vue.state.winners == 1,
          "formulaire obligatoire : lot, durée et gagnants enregistrés")
    mauvais = gv.BaseModal(vue)
    mauvais.prize._value, mauvais.duration._value, mauvais.winners._value, mauvais.description._value = "X", "bientôt", "1", ""
    since = len(h.CALLS)
    await mauvais.on_submit(admin())
    check("Durée invalide" in reponses(h.CALLS[since:]) and vue.state.prize == "Nitro",
          "durée invalide refusée sans écraser la configuration")

    # 2. Conditions : niveau XP minimum 5, rôles obligatoire / interdit / bonus.
    cond = gv.ConditionsModal(vue)
    cond.min_invites._value, cond.account_age._value, cond.server_age._value, cond.min_level._value = "0", "0", "0", "5"
    if hasattr(cond, "custom_condition"):
        cond.custom_condition._value = ""
    await cond.on_submit(admin())
    check(vue.state.min_level == 5, "niveau XP minimum enregistré (5)")
    vue.state.channel_id = h.CID
    vue.state.required_roles = [h.MEMBER_ROLE_ID]
    vue.state.excluded_roles = [h.PING_ROLE_ID]
    vue.state.bonus_roles = [h.MEMBER_ROLE_ID]
    vue.state.bonus_multipliers = {h.MEMBER_ROLE_ID: 3}
    resume = "\n".join(it.content for it in _textes(vue.setup_panel()))
    check("Nitro" in resume and "5" in resume, "le résumé reflète les réglages", resume[:200])

    # 3. Aperçu privé, puis publication avec lien.
    since = len(h.CALLS)
    await vue.preview.callback(admin())
    apercu = [c for c in h.CALLS[since:] if isinstance(c[2], dict)]
    check(apercu and all(c[1].endswith("/callback") for c in apercu)
          and int(((apercu[0][2].get("data") or {}).get("flags") or 0)) & 64,
          "aperçu envoyé en privé, rien dans le salon")
    since = len(h.CALLS)
    await vue.publish.callback(admin())
    await h.settle(idle=0.4, maximum=4)
    publies = [c for c in h.CALLS[since:] if c[0] == "POST" and c[1] == f"/channels/{h.CID}/messages"]
    check(len(publies) == 1, "un seul message public publié", str([c[1] for c in h.CALLS[since:]]))
    check("discord.com/channels/" in reponses(h.CALLS[since:]), "confirmation privée avec le lien du giveaway")
    row = await bot.db.fetchone("SELECT * FROM giveaways_v2 WHERE guild_id=? ORDER BY id DESC LIMIT 1", (h.GID,))
    check(row is not None and int(row["min_level"]) == 5 and json.loads(row["bonus_roles_json"]),
          "giveaway enregistré avec niveau minimum et bonus")
    since = len(h.CALLS)
    await vue.publish.callback(admin())
    check(not any(c[0] == "POST" and c[1] == f"/channels/{h.CID}/messages" for c in h.CALLS[since:]),
          "second clic sur Publier : aucun doublon")

    # 4. Participations réelles.
    for uid, niveau in ((ELIGIBLE, 6), (ELIGIBLE_2, 9), (INTERDIT, 9), (NIVEAU_BAS, 2)):
        await bot.db.execute("INSERT INTO levels (guild_id,user_id,xp,level) VALUES (?,?,0,?) "
                             "ON CONFLICT(guild_id,user_id) DO UPDATE SET level=excluded.level", (h.GID, uid, niveau))
    mid = int(row["message_id"])

    async def entrer(uid, roles):
        since = len(h.CALLS)
        await cog.toggle_entry(inter(bot, uid, roles, message_id=mid, custom_id="sentrix:giveaway:v2:enter"))
        await h.settle(idle=0.2, maximum=2)
        return reponses(h.CALLS[since:])

    r = await entrer(ELIGIBLE, (h.MEMBER_ROLE_ID,))
    check("Participation enregistrée" in r and "x3" in r, "membre éligible : inscrit, chances x3 annoncées", r[:160])
    r = await entrer(ELIGIBLE_2, (h.MEMBER_ROLE_ID,))
    r = await entrer(INTERDIT, (h.MEMBER_ROLE_ID, h.PING_ROLE_ID))
    check("rôle interdit" in r, "rôle interdit : refusé avec la raison", r[:160])
    r = await entrer(SANS_ROLE, ())
    check("rôle obligatoire" in r, "rôle obligatoire manquant : refusé", r[:160])
    r = await entrer(NIVEAU_BAS, (h.MEMBER_ROLE_ID,))
    check("niveau" in r.lower() and "5" in r, "niveau XP trop bas : refusé (vérification automatique réelle)", r[:160])
    n = await bot.db.fetchone("SELECT COUNT(*) AS n FROM giveaway_entries_v2 WHERE giveaway_id=?", (row["id"],))
    check(int(n["n"]) == 2, f"deux participations valides seulement ({n['n']})")

    # 5. Reprise après redémarrage : un giveaway échu est clôturé par la boucle.
    await bot.db.execute("UPDATE giveaways_v2 SET end_at=? WHERE id=?", (int(time.time()) - 5, row["id"]))
    await cog.check_ends.coro(cog)
    await h.settle(idle=0.4, maximum=4)
    fin = await bot.db.fetchone("SELECT status, winners_json FROM giveaways_v2 WHERE id=?", (row["id"],))
    gagnants = json.loads(fin["winners_json"] or "[]")
    check(fin["status"] != "actif" and len(gagnants) == 1 and gagnants[0] in (ELIGIBLE, ELIGIBLE_2),
          "échéance passée : clôturé par la boucle, gagnant parmi les éligibles", f"{fin['status']} {gagnants}")
    premier = gagnants[0]
    fin_row = await bot.db.fetchone("SELECT * FROM giveaways_v2 WHERE id=?", (row["id"],))
    nouveaux = await cog.finish(fin_row, reroll=True)
    check(nouveaux and nouveaux[0] != premier and nouveaux[0] in (ELIGIBLE, ELIGIBLE_2),
          "reroll : un autre gagnant éligible", f"{premier} → {nouveaux}")

    failed = [r for r in RESULTS if not r[0]]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} étapes réussies.")
    sys.stdout.flush()
    return 1 if failed else 0


def _textes(vue):
    def walk(item):
        yield item
        for enfant in list(getattr(item, "children", []) or []):
            yield from walk(enfant)
        acc = getattr(item, "accessory", None)
        if acc is not None:
            yield acc
    return [it for top in getattr(vue, "children", []) for it in walk(top) if isinstance(it, discord.ui.TextDisplay)]


if __name__ == "__main__":
    try:
        code = asyncio.run(main())
    except BaseException:
        import traceback
        traceback.print_exc()
        code = 1
    sys.stdout.flush()
    os._exit(code)
