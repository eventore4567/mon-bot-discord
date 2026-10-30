#!/usr/bin/env python3
"""Commandes personnalisées à actions (cogs/custom_commands), sur le bot booté.

    python3 tools/custom_commands_e2e.py
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

RESULTS: list[tuple[bool, str]] = []
ADMIN = dict(author_id=h.ADMIN_ID, author_roles=(h.ADMIN_ROLE_ID,))


def check(ok: bool, label: str, detail: str = "") -> None:
    RESULTS.append((bool(ok), label))
    print(("OK   " if ok else "ÉCHEC ") + label + (f" — {detail}" if detail and not ok else ""))


async def main() -> int:
    bot = await h.boot(quiet=True)
    guild = await h.setup_world(bot)
    # Production : le « + » des commandes SentriX est coupé ; les personnalisées restent.
    os.environ["SENTRIX_PREFIXE_ACTIF"] = "0"

    # Décision du 30/10/2026 : l'administration /custom a été retirée ;
    # les commandes personnalisées se configurent désormais depuis /setup.
    # Le test conserve les mêmes garanties métier, dans les tables réellement
    # écrites par la nouvelle interface (sans contourner les sanctions/actions).
    from utils.slash_catalog import CATALOG
    check(not any(e.path.startswith("custom ") for e in CATALOG),
          "aucune commande de configuration /custom publiée")

    platform = bot.get_cog("PlatformV4")
    check(platform is not None, "moteur de commandes personnalisées chargé")
    if platform is None:
        return 1

    created = await platform.save_custom_command(guild, h.ADMIN_ID, {
        "name": "bonus", "response": "Bonus_pour_{user}",
    })
    check(created["name"] == "bonus", "/setup enregistre le message via PlatformV4")
    await bot.db.execute(
        "INSERT INTO custom_command_actions(guild_id,name,kind,value,duration_s) VALUES(?,?,?,?,?)",
        (h.GID, "bonus", "role_add", h.PING_ROLE_ID, 0),
    )
    await bot.db.execute(
        "INSERT INTO custom_command_actions(guild_id,name,kind,value,duration_s) VALUES(?,?,?,?,?)",
        (h.GID, "bonus", "money", 250, 0),
    )
    await bot.db.execute(
        "INSERT INTO custom_command_settings(guild_id,delete_trigger) VALUES(?,1) "
        "ON CONFLICT(guild_id) DO UPDATE SET delete_trigger=1",
        (h.GID,),
    )

    # Vérifier que la page publique de /setup sait reconstruire la vue C V2.
    from cogs.setup_experience_v74 import SentriXSetupV74
    view = SentriXSetupV74(bot, guild, h.ADMIN_ID)
    view.page = "custom_commands"
    await view.rebuild()
    check(bool(view.children), "page Commandes personnalisées de /setup construite")

    avant = await bot.db.fetchone("SELECT cash FROM economy WHERE guild_id=? AND user_id=?", (h.GID, h.TARGET_ID))
    avant = int(avant["cash"]) if avant else 0
    since = len(h.CALLS)
    message = h.build_message(bot, guild, "+bonus", author_id=h.TARGET_ID, author_roles=(h.MEMBER_ROLE_ID,))
    bot.dispatch("message", message)
    await h.settle(idle=0.8, maximum=5)
    appels = h.CALLS[since:]
    check(any("Bonus_pour_" in str((js or {}).get("content")) for _m, _p, js in appels if isinstance(js, dict)),
          "+bonus répond même avec le « + » des commandes SentriX coupé")
    check(any(m == "PUT" and f"/members/{h.TARGET_ID}/roles/{h.PING_ROLE_ID}" in p for m, p, _ in appels),
          "le rôle est donné à la personne")
    apres = await bot.db.fetchone("SELECT cash FROM economy WHERE guild_id=? AND user_id=?", (h.GID, h.TARGET_ID))
    check(apres is not None and int(apres["cash"]) == avant + 250, "250 ajoutés à son argent", str(dict(apres) if apres else None))
    check(any(m == "DELETE" and f"/messages/{message.id}" in p for m, p, _ in appels),
          "le message qui a lancé la commande est supprimé")

    failed = [r for r in RESULTS if not r[0]]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} étapes réussies.")
    sys.stdout.flush()
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        code = asyncio.run(main())
    except BaseException:
        import traceback
        traceback.print_exc()
        code = 1
    sys.stdout.flush()
    os._exit(code)
