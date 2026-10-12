#!/usr/bin/env python3
"""Auto Mode face à plusieurs spammeurs à la fois, sur le bot booté.

N membres spamment en même temps dans #general pendant qu'un membre ordinaire
discute normalement. Discord est simulé avec une latence réseau par requête et
une limite de suppressions par salon (modèle annoncé dans la sortie). On mesure :
messages de spam restés visibles, délai jusqu'au nettoyage, appels de
suppression, sanctions, avertissements publics, et le membre ordinaire intact.

    python3 tools/spam_burst_e2e.py [--spammers 20] [--messages 12]
"""
from __future__ import annotations

import argparse
import asyncio
import os
import pathlib
import re
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import discord  # noqa: E402

import sentrix_e2e_harness as h  # noqa: E402
from suggestions_e2e import RESULTS, check  # noqa: E402

LATENCY = 0.08          # aller-retour Discord typique
DELETE_PER_SECOND = 5   # suppressions par salon et par seconde avant 429 (modèle)
FIRST_SPAMMER = 100000000000005000
REGULAR_ID = h.SECOND_ID


def install_discord_model(bot) -> dict:
    """Latence sur chaque requête + file de suppressions par salon, comme le ferait
    discord.py en attendant le retry-after d'un 429."""
    stats = {"delete_calls": 0, "bulk_calls": 0, "rate_wait": 0.0, "in_flight": 0, "deleted_at": {}}
    original = discord.http.HTTPClient.request
    next_slot: dict[str, float] = {}

    async def request(self, route, **kwargs):
        method, path = route.method, route.url.replace(discord.http.Route.BASE, "")
        is_delete = (method == "DELETE" and re.fullmatch(r"/channels/\d+/messages/\d+", path)) or \
            path.endswith("/messages/bulk-delete")
        if is_delete:
            stats["in_flight"] += 1
            channel = path.split("/")[2]
            now = time.monotonic()
            slot = max(now, next_slot.get(channel, 0.0))
            next_slot[channel] = slot + 1.0 / DELETE_PER_SECOND
            if slot > now:
                stats["rate_wait"] += slot - now
                await asyncio.sleep(slot - now)
            stats["bulk_calls" if path.endswith("bulk-delete") else "delete_calls"] += 1
            done_at = time.monotonic() + LATENCY
            for mid in (kwargs.get("json") or {}).get("messages", []) or [path.rsplit("/", 1)[-1]]:
                stats["deleted_at"].setdefault(int(mid), done_at)
            stats["in_flight"] -= 1
        stats["in_flight"] += 1
        try:
            await asyncio.sleep(LATENCY)
            result = await original(self, route, **kwargs)
            # Comme Discord : la suppression revient par la passerelle.
            parts = path.split("/")
            if path.endswith("/messages/bulk-delete"):
                ids = [str(i) for i in (kwargs.get("json") or {}).get("messages", [])]
                bot.dispatch("raw_bulk_message_delete", discord.RawBulkMessageDeleteEvent(
                    {"ids": ids, "channel_id": parts[2], "guild_id": str(h.GID)}))
            elif method == "DELETE" and re.fullmatch(r"/channels/\d+/messages/\d+", path):
                bot.dispatch("raw_message_delete", discord.RawMessageDeleteEvent(
                    {"id": parts[4], "channel_id": parts[2], "guild_id": str(h.GID)}))
            return result
        finally:
            stats["in_flight"] -= 1

    discord.http.HTTPClient.request = request
    return stats


def deleted_ids(calls) -> dict[int, int]:
    """id de message -> index de l'appel qui l'a supprimé."""
    out: dict[int, int] = {}
    for index, (method, path, js) in enumerate(calls):
        m = re.fullmatch(rf"/channels/{h.CID}/messages/(\d+)", path)
        if method == "DELETE" and m:
            out.setdefault(int(m.group(1)), index)
        if path == f"/channels/{h.CID}/messages/bulk-delete":
            for mid in (js or {}).get("messages", []):
                out.setdefault(int(mid), index)
    return out


async def coordinated_wave(bot, guild, stats) -> None:
    """Raid coordonné : 15 comptes postent chacun UNE fois le même message, sous le
    seuil individuel de chacun ; et une fête où 6 membres écrivent la même courte
    phrase, qui ne doit pas être prise pour un raid."""
    since = len(h.CALLS)
    raid, party = [], []
    for n in range(15):
        message = h.build_message(bot, guild, "Rejoignez vite le meilleur serveur : discord.gg/promo123 nitro offert",
                                  author_id=FIRST_SPAMMER + 500 + n, author_name=f"raid{n}",
                                  author_roles=(h.MEMBER_ROLE_ID,))
        raid.append(message.id)
        bot.dispatch("message", message)
        await asyncio.sleep(0.05)
    for n in range(6):
        message = h.build_message(bot, guild, "joyeux anniversaire Paul !!", author_id=FIRST_SPAMMER + 800 + n,
                                  author_name=f"ami{n}", author_roles=(h.MEMBER_ROLE_ID,))
        party.append(message.id)
        bot.dispatch("message", message)
        await asyncio.sleep(0.05)
    while True:
        await h.settle(idle=1.0, maximum=120)
        if not stats["in_flight"]:
            break
    gone = deleted_ids(h.CALLS[since:])
    print(f"Raid coordonné : {sum(1 for m in raid if m in gone)}/{len(raid)} messages supprimés ; "
          f"fête : {sum(1 for m in party if m in gone)}/{len(party)} supprimés.")
    check(all(m in gone for m in raid), "raid coordonné (15 comptes, 1 message identique chacun) : tout est supprimé")
    check(not any(m in gone for m in party), "6 membres qui souhaitent un anniversaire ne sont pas pris pour un raid")


async def main(spammers: int, per_member: int) -> int:
    bot = await h.boot(quiet=True)
    sys.modules["cogs.automod"].INCIDENT_LOG_DELAY_SECONDS = 0.2
    guild = await h.setup_world(bot)
    db = bot.db
    await db.execute("INSERT INTO automod_settings (guild_id) VALUES (?) ON CONFLICT(guild_id) DO NOTHING", (h.GID,))
    await db.execute("UPDATE automod_settings SET antispam=1, escalation=1 WHERE guild_id=?", (h.GID,))
    bot.get_cog("Automod").automod_cache.clear()
    # Les incidents de spam ont leur propre catégorie de logs (« Anti-Spam »).
    from utils import log_service
    await log_service.set_log_config(bot, h.GID, "spam", channel_id=h.LOGCID, enabled=True)
    stats = install_discord_model(bot)
    automod = bot.get_cog("Automod")
    log_calls: list[str] = []
    original_log_action = automod.log_action

    async def counted_log_action(guild_, embed, log_type="automod", **kw):
        log_calls.append(log_type)
        return await original_log_action(guild_, embed, log_type, **kw)

    automod.log_action = counted_log_action

    ids = [FIRST_SPAMMER + i for i in range(spammers)]
    spam: dict[int, list[int]] = {uid: [] for uid in ids}
    sent_at: dict[int, float] = {}
    regular: list[int] = []
    admin: list[int] = []
    start_calls = len(h.CALLS)
    t0 = time.monotonic()

    async def send(uid: int, content: str, bucket: list[int]) -> None:
        message = h.build_message(bot, guild, content, author_id=uid, author_name=f"m{uid % 1000}",
                                  author_roles=(h.MEMBER_ROLE_ID,))
        bucket.append(message.id)
        sent_at[message.id] = time.monotonic()
        bot.dispatch("message", message)

    # Chaque spammeur envoie un message toutes les 150 ms ; ils démarrent ensemble.
    for round_ in range(per_member):
        for n, uid in enumerate(ids):
            await send(uid, f"ACHETEZ MAINTENANT promo {n} vague {round_}", spam[uid])
        if round_ < 8:  # l'administrateur écrit aussi vite que les spammeurs
            message = h.build_message(bot, guild, f"annonce rapide {round_}", author_id=h.ADMIN_ID,
                                      author_name="admin", author_roles=(h.ADMIN_ROLE_ID,))
            admin.append(message.id)
            bot.dispatch("message", message)
        if round_ % 4 == 0:
            await send(REGULAR_ID, f"salut tout le monde, quelqu'un a vu le match ? ({round_})", regular)
        await asyncio.sleep(0.15)
    while True:
        await h.settle(idle=1.0, maximum=120)
        if not stats["in_flight"]:
            break
    elapsed = time.monotonic() - t0

    calls = h.CALLS[start_calls:]
    gone = deleted_ids(calls)
    all_spam = [mid for mids in spam.values() for mid in mids]
    left = [mid for mid in all_spam if mid not in gone]
    left_per_member = {uid: sum(1 for mid in mids if mid not in gone) for uid, mids in spam.items()}
    timeouts = {int(m.group(1)) for meth, p, js in calls
                if (m := re.fullmatch(rf"/guilds/{h.GID}/members/(\d+)", p)) and meth == "PATCH"
                and (js or {}).get("communication_disabled_until")}
    notices = [js for meth, p, js in calls if meth == "POST" and p == f"/channels/{h.CID}/messages"]
    log_cards = [js for meth, p, js in calls if meth == "POST" and p == f"/channels/{h.LOGCID}/messages"]
    warns = await db.fetchone("SELECT COUNT(*) AS n FROM sanctions WHERE guild_id=? AND action='warn'", (h.GID,))

    print(f"\nModèle Discord : {int(LATENCY * 1000)} ms par requête, {DELETE_PER_SECOND} suppressions/s par salon.")
    print(f"{spammers} spammeurs × {per_member} messages = {len(all_spam)} messages de spam, "
          f"traités en {elapsed:.1f} s.")
    print(f"Restés visibles : {len(left)} ({len(left) * 100 // max(1, len(all_spam))} %) — "
          f"par membre : min {min(left_per_member.values())}, max {max(left_per_member.values())}.")
    delays = sorted(stats["deleted_at"][m] - sent_at[m] for m in all_spam if m in stats["deleted_at"])
    if delays:
        print(f"Délai envoi → suppression : médian {delays[len(delays) // 2] * 1000:.0f} ms, "
              f"95e centile {delays[int(len(delays) * 0.95)] * 1000:.0f} ms, max {delays[-1] * 1000:.0f} ms.")
    others = sorted({p for meth, p, js in calls if meth == "POST" and p.endswith("/messages")
                     and p not in (f"/channels/{h.CID}/messages",)})
    print(f"Autres salons écrits : {others}")
    from collections import Counter
    print("Appels par route :", Counter(f"{meth} {re.sub(r'[0-9]{6,}', '#', p)}" for meth, p, js in calls).most_common(12))
    print(f"Appels de suppression : {stats['delete_calls']} unitaires + {stats['bulk_calls']} groupés ; "
          f"attente 429 cumulée {stats['rate_wait']:.1f} s.")
    print(f"Membres exclus temporairement : {len(timeouts & set(ids))}/{spammers} ; avertissements : {warns['n']} ; "
          f"messages publics dans #general : {len(notices)} ; cartes de log : {len(log_cards)} "
          f"(demandées : {len(log_calls)}).")
    deleted_cards = sum(1 for js in log_cards if "Message supprimé" in h.visible_text([("POST", "x", js)]))
    print(f"Cartes « Message supprimé » dans les logs : {deleted_cards}.")
    print(f"Membre ordinaire : {len(regular)} messages, {sum(1 for m in regular if m in gone)} supprimés, "
          f"{'exclu' if REGULAR_ID in timeouts else 'jamais sanctionné'}.")

    notice_text = "\n".join(h.visible_text([("POST", f"/channels/{h.CID}/messages", js)]) for js in notices)
    print("Avertissements publics :\n" + notice_text)
    check(not any(m in gone for m in regular) and REGULAR_ID not in timeouts,
          "le membre qui discute normalement n'est jamais touché")
    check(not any(m in gone for m in admin), "l'administrateur qui écrit vite n'est jamais touché")
    check(not left, f"aucun message de spam ne reste affiché ({len(left)} restants)")
    check(bool(delays) and delays[int(len(delays) * 0.95)] < 1.5, "95 % du spam disparaît en moins de 1,5 s")
    check(stats["delete_calls"] + stats["bulk_calls"] <= max(10, len(all_spam) // 10),
          "les suppressions sont regroupées (au plus un appel pour 10 messages)")
    unnamed = [uid for uid in ids if f"<@{uid}>" not in notice_text]
    check(not unnamed or len(notices) >= 1 and "autre" in notice_text,
          "chaque spammeur est nommé dans un avertissement (ou compté dans « et N autres »)", str(unnamed[:3]))
    check(deleted_cards <= spammers, f"pas une carte « Message supprimé » par message de spam ({deleted_cards})")
    await coordinated_wave(bot, guild, stats)
    check(len(notices) <= 3, f"un avertissement regroupé, pas un par spammeur ({len(notices)} messages)")
    check(all(left_per_member[uid] < per_member for uid in ids), "chaque spammeur est traité (aucun n'est oublié)",
          str(left_per_member))
    failed = [r for r in RESULTS if not r[0]]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} étapes réussies.")
    sys.stdout.flush()
    os._exit(1 if failed else 0)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--spammers", type=int, default=20)
    parser.add_argument("--messages", type=int, default=12)
    args = parser.parse_args()
    try:
        asyncio.run(main(args.spammers, args.messages))
    except BaseException:
        import traceback

        traceback.print_exc()
        sys.stdout.flush()
        os._exit(1)
