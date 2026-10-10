#!/usr/bin/env python3
"""Économie sur le bot booté : la mémoire des ajouts du staff, l'unité, les erreurs lisibles.

    python3 tools/economy_memory_e2e.py
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
MEMBER = dict(author_id=h.SECOND_ID, author_roles=(h.MEMBER_ROLE_ID,))


async def main() -> int:
    bot = await h.boot(quiet=True)
    guild = await h.setup_world(bot)

    async def run(command: str, who: dict) -> str:
        since = len(h.CALLS)
        await asyncio.wait_for(h.run_prefix(bot, guild, command, **who), 15)
        await h.settle(idle=0.3, maximum=2)
        return h.visible_text([c for c in h.CALLS[since:] if c[1] == f"/channels/{h.CID}/messages"])

    shown = await run(f"+give-money <@{h.TARGET_ID}> 500", ADMIN)
    check("500 🪙 ajoutés" in shown, "l'unité 🪙 n'est plus effacée", shown[:160])
    check("solde 500 🪙" in shown and "1 ajout du staff en 30 j (500 🪙)" in shown and "Réf. SX-" in shown,
          "+give-money : solde et ajouts du staff rappelés avec la référence", shown[-160:])
    shown = await run(f"+give-money <@{h.TARGET_ID}> 300", ADMIN)
    check("solde 800 🪙" in shown and "2 ajouts du staff en 30 j (800 🪙)" in shown,
          "le second ajout cumule : 2 ajouts, 800 🪙", shown[-160:])
    shown = await run(f"+give-money <@{h.ADMIN_ID}> 50", ADMIN)
    check("à soi-même" in shown, "un membre du staff qui se crédite lui-même est signalé", shown[-160:])

    shown = await run("+balance", MEMBER)
    check("🪙" in shown, "+balance garde l'unité", shown[:160])
    shown = await run(f"+pay <@{h.TARGET_ID}> 10", MEMBER)
    check("pas assez d'argent" in shown, "+pay sans fonds : le message d'erreur est lisible (plus de carte vide)", shown[:160])

    # Symbole de monnaie = emoji personnalisé supprimé depuis du serveur : enregistré
    # entier (plus tronqué à 16 caractères), affiché comme la pièce par défaut.
    from cogs import setup_v2_core as core

    await core.set_currency(bot, h.GID, "Pièce", "Pièces", "<:piece:123456789012345678>")
    row = await bot.db.fetchone("SELECT currency_symbol FROM economy_settings_v2 WHERE guild_id = ?", (h.GID,))
    check(row["currency_symbol"] == "<:piece:123456789012345678>", "un emoji personnalisé est enregistré entier",
          str(row["currency_symbol"]))
    shown = await run("+balance", MEMBER)
    check("<:piece:" not in shown and "🪙" in shown, "emoji supprimé : +balance montre la pièce, jamais le marquage brut",
          shown[:200])

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
