"""Porte de budget des listeners Discord.

Charge reellement le bot et refuse qu'un evenement gagne des handlers en silence.

Pourquoi : on_message est le chemin le plus chaud d'un bot Discord. Chaque handler
ajoute s'execute pour CHAQUE message de CHAQUE serveur. Passer de 20 a 25 handlers
sans s'en rendre compte, c'est +25 % de travail sur l'evenement le plus frequent.

Cette porte ne juge pas : elle constate. Si un ajout est legitime, on releve le
budget dans BUDGETS en connaissance de cause.
"""
from __future__ import annotations

import asyncio
import logging
import os
import pathlib
import re
import sys
import tempfile

os.environ.setdefault("DISCORD_TOKEN", "gate")
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
logging.disable(logging.CRITICAL)

import config  # noqa: E402
from database.db import Database  # noqa: E402

# Budgets constates le 2026-09-01. Un depassement doit etre un choix, pas une derive.
BUDGETS: dict[str, int] = {
    "on_message": 20,
    "on_ready": 28,
    "on_member_join": 16,
    "on_command_completion": 13,
    "on_member_remove": 7,
    "on_member_ban": 6,
    "on_guild_join": 9,
    "on_guild_role_update": 6,
    "on_guild_channel_create": 6,
    "on_message_delete": 2,
    "on_raw_message_delete": 2,
}


async def main() -> int:
    config.DATABASE_PATH = str(pathlib.Path(tempfile.mkdtemp()) / "listeners.db")
    import main as bot_main

    bot = bot_main.BotAllInOne()
    bot.db = Database(config.DATABASE_PATH)
    await bot.db.connect()

    extensions = list(bot_main.EXTENSIONS)
    boot = (ROOT / "railway_boot.py").read_text(encoding="utf-8")
    for name in re.findall(r'bot_main\.EXTENSIONS\.append\("(cogs\.[a-z0-9_]+)"\)', boot):
        if name not in extensions:
            extensions.append(name)
    for extension in extensions:
        try:
            await asyncio.wait_for(bot.load_extension(extension), timeout=30)
        except Exception:  # pragma: no cover - diagnostic
            pass

    # bot.extra_events contient DEJA les listeners de cogs : ne pas reparcourir les
    # cogs, cela compterait chaque handler deux fois.
    compte = {name: len(callbacks) for name, callbacks in bot.extra_events.items()}

    depassements: list[str] = []
    for evenement, budget in sorted(BUDGETS.items()):
        actuel = compte.get(evenement, 0)
        marque = "  " if actuel <= budget else "!!"
        print(f"{marque} {evenement:<32} {actuel:>3} / {budget}")
        if actuel > budget:
            depassements.append(f"{evenement} : {actuel} handlers pour un budget de {budget}")

    inconnus = {
        nom: n for nom, n in compte.items()
        if n >= 10 and nom not in BUDGETS
    }
    if inconnus:
        print("\nEvenements a fort trafic hors budget :")
        for nom, n in sorted(inconnus.items(), key=lambda x: -x[1]):
            print(f"   {nom:<32} {n}")

    total = sum(compte.values())
    print(f"\nlisteners totaux : {total}")

    if depassements:
        print("\nBUDGET DEPASSE :")
        for ligne in depassements:
            print("  ", ligne)
        print("\nSi l'ajout est voulu, relevez le budget dans tools/listener_budget_gate.py")
        print("en sachant ce que cela coute sur l'evenement concerne.")
        return 1

    print("\nBudget des listeners : OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
