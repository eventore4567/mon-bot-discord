#!/usr/bin/env python3
"""Réactivité de l'anti-spam par serveur, sur le bot booté.

Le niveau de sécurité règle les seuils (souple / normale / stricte), un
administrateur peut choisir les siens, un membre ne peut rien changer, et une
vague de spammeurs déclenche le renfort anti-raid pendant 10 minutes.

    python3 tools/spam_levels_e2e.py
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

import sentrix_e2e_harness as h  # noqa: E402
from suggestions_e2e import RESULTS, check  # noqa: E402

ADMIN = dict(author_id=h.ADMIN_ID, author_roles=(h.ADMIN_ROLE_ID,))
MEMBER = dict(author_id=h.SECOND_ID, author_roles=(h.MEMBER_ROLE_ID,))
BASE_ID = 100000000000007000


async def main() -> int:
    bot = await h.boot(quiet=True)
    sys.modules["cogs.automod"].INCIDENT_LOG_DELAY_SECONDS = 0.1
    guild = await h.setup_world(bot)
    db = bot.db
    automod = bot.get_cog("Automod")
    from utils import log_service

    await log_service.set_log_config(bot, h.GID, "spam", channel_id=h.LOGCID, enabled=True)
    counter = iter(range(10_000))

    async def enable_antispam() -> None:
        await db.execute("INSERT INTO automod_settings (guild_id) VALUES (?) ON CONFLICT(guild_id) DO NOTHING", (h.GID,))
        await db.execute("UPDATE automod_settings SET antispam=1 WHERE guild_id=?", (h.GID,))
        automod.automod_cache.clear()

    async def command(text: str, who: dict) -> str:
        since = len(h.CALLS)
        await asyncio.wait_for(h.run_prefix(bot, guild, text, **who), 15)
        await h.settle(idle=0.3, maximum=3)
        return h.visible_text([c for c in h.CALLS[since:] if c[1] == f"/channels/{h.CID}/messages"])

    def calm() -> None:
        """Oublie la vague en cours : chaque test de niveau est isolé (sinon trois
        tests consécutifs font trois spammeurs en 30 s, et le renfort s'active)."""
        automod._spammeurs_recents = None
        automod._renfort_jusqua = {}

    async def burst(count: int, *, author: int | None = None, isolated: bool = True) -> int:
        """Un nouveau membre envoie `count` messages rapprochés ; combien sont supprimés."""
        if isolated:
            calm()
        author = author or BASE_ID + next(counter)
        since = len(h.CALLS)
        ids = []
        for i in range(count):
            message = h.build_message(bot, guild, f"message rapide numéro {i}", author_id=author,
                                      author_name="m", author_roles=(h.MEMBER_ROLE_ID,))
            ids.append(message.id)
            bot.dispatch("message", message)
            await asyncio.sleep(0.05)
        await h.settle(idle=0.6, maximum=6)
        gone = set()
        for method, path, js in h.CALLS[since:]:
            m = re.fullmatch(rf"/channels/{h.CID}/messages/(\d+)", path)
            if method == "DELETE" and m:
                gone.add(int(m.group(1)))
            if path.endswith("/messages/bulk-delete"):
                gone.update(int(x) for x in (js or {}).get("messages", []))
        return sum(1 for mid in ids if mid in gone)

    await enable_antispam()

    # Normale (aucun niveau choisi) : 4 messages passent, 5 déclenchent.
    check(await burst(4) == 0, "réactivité normale : 4 messages rapprochés ne sont pas du spam")
    check(await burst(5) == 5, "réactivité normale : au 5e, toute la rafale est supprimée")

    # Un membre ne change rien.
    shown = await command("+security-level eleve", MEMBER)
    row = await db.get_guild_config(h.GID)
    check(row["security_level"] in (None, "", "moyen") and ("accès" in shown.lower() or "permission" in shown.lower()),
          "un simple membre ne peut pas changer le niveau", shown[:160])

    # Élevé : 4 messages en 5 s suffisent.
    shown = await command("+security-level eleve", ADMIN)
    check("4 messages en 5 s" in shown and "stricte" in shown, "Élevé annonce « 4 messages en 5 s (réactivité stricte) »",
          shown[:240])
    check(await burst(4) == 4, "réactivité stricte : 4 messages suffisent")

    # Faible coupe l'anti-spam (préréglage) ; le réactiver garde la réactivité souple.
    shown = await command("+security-level faible", ADMIN)
    check("7 messages en 6 s" in shown, "Faible annonce « 7 messages en 6 s »", shown[:240])
    await enable_antispam()
    check(await burst(6) == 0, "réactivité souple : 6 messages rapprochés passent")
    check(await burst(7) == 7, "réactivité souple : au 7e, la rafale est supprimée")

    # Personnalisé : seuils choisis, filtres inchangés, bornes respectées.
    before = dict(await db.fetchone("SELECT * FROM automod_settings WHERE guild_id=?", (h.GID,)))
    shown = await command("+security-level personnalise 3 10", ADMIN)
    after = dict(await db.fetchone("SELECT * FROM automod_settings WHERE guild_id=?", (h.GID,)))
    check("3 messages en 10 s" in shown and before == after,
          "Personnalisé 3/10 : annoncé, et aucun interrupteur de filtre ne bouge", shown[:240])
    check(await burst(3) == 3, "seuil personnalisé : 3 messages suffisent")
    shown = await command("+security-level personnalise 1 999", ADMIN)
    check("3 messages en 30 s" in shown, "des valeurs hors bornes sont ramenées à 3 messages / 30 s", shown[:240])
    shown = await command("+security-level personnalise", ADMIN)
    check("3 messages en 30 s" in shown and "personnalisée" in shown, "sans valeurs : le réglage actuel est affiché",
          shown[:240])
    shown = await command("+security-level moyen", ADMIN)
    check("5 messages en 6 s" in shown, "choisir un niveau efface les seuils personnalisés", shown[:240])

    await command("+security-level moyen", ADMIN)
    await enable_antispam()

    # Renfort anti-raid : trois spammeurs en même temps, puis un quatrième plus discret.
    since = len(h.CALLS)
    calm()
    for _ in range(3):
        await burst(5, isolated=False)
    cards = h.visible_text([c for c in h.CALLS[since:] if c[1] == f"/channels/{h.LOGCID}/messages"])
    check("Renfort anti-raid activé" in cards and "4 messages en 5 s" in cards and "10 min" in cards,
          "trois spammeurs simultanés : carte « Renfort anti-raid activé » (stricte, 10 min)", cards[-400:])
    check(cards.count("Renfort anti-raid activé") == 1, "une seule annonce de renfort pour la vague")
    check(await burst(4, isolated=False) == 4, "pendant le renfort, 4 messages suffisent même en réactivité normale")
    automod._renfort_jusqua[h.GID] = 0
    check(await burst(4) == 0, "à la fin du renfort, le serveur revient à son niveau (4 messages passent)")

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
