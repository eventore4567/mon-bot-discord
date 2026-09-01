"""Porte de couverture des permissions.

Charge REELLEMENT toutes les extensions, enumere chaque commande enregistree et refuse
qu'une racine ne soit pas classee dans utils/access_matrix.py.

Sans cette porte, une commande ajoutee (ou renommee) sans mise a jour de la matrice
tombe silencieusement en fail-closed : elle devient administrateur alors qu'elle etait
peut-etre destinee aux membres. C'est exactement ce qui etait arrive a "gameseason".
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
from utils import access_matrix as matrix  # noqa: E402

# Racines volontairement non classees : elles sont couvertes par un check local
# explicite et n'ont pas vocation a passer par la matrice.
ALLOWED_UNCOVERED: frozenset[str] = frozenset()


def covered_names() -> set[str]:
    names = set(matrix.PUBLIC_COMMANDS)
    names |= set(matrix.OWNER_ONLY_COMMANDS)
    names |= set(matrix.GUILD_OWNER_COMMANDS)
    names |= set(matrix.DISCORD_PERMISSION_COMMANDS)
    names |= set(matrix.CUSTOM_PERMISSION_COMMANDS)
    for group in matrix.CATEGORY_COMMANDS.values():
        names |= set(group)
    return {matrix.normalise(n) for n in names}


async def main() -> int:
    config.DATABASE_PATH = str(pathlib.Path(tempfile.mkdtemp()) / "gate.db")
    import main as bot_main

    bot = bot_main.BotAllInOne()
    bot.db = Database(config.DATABASE_PATH)
    await bot.db.connect()

    extensions = list(bot_main.EXTENSIONS)
    boot = (ROOT / "railway_boot.py").read_text(encoding="utf-8")
    for name in re.findall(r'bot_main\.EXTENSIONS\.append\("(cogs\.[a-z0-9_]+)"\)', boot):
        if name not in extensions:
            extensions.append(name)

    failures: list[str] = []
    for extension in extensions:
        try:
            await asyncio.wait_for(bot.load_extension(extension), timeout=30)
        except Exception as exc:  # pragma: no cover - diagnostic
            failures.append(f"{extension}: {type(exc).__name__}: {exc}")

    if failures:
        print("EXTENSIONS EN ECHEC :")
        for line in failures:
            print("  ", line)
        return 1

    covered = covered_names()
    roots = {
        matrix.normalise(command.name)
        for command in bot.walk_commands()
        if command.full_parent_name == ""
    }
    uncovered = sorted(roots - covered - ALLOWED_UNCOVERED)

    print(f"racines chargees : {len(roots)}")
    print(f"noms classes     : {len(covered)}")

    if uncovered:
        print(f"\n{len(uncovered)} COMMANDE(S) NON CLASSEE(S) — elles tomberaient en fail-closed :")
        for name in uncovered:
            print("  ", name)
        print("\nClassez-les dans utils/access_matrix.py (niveau 1 a 5).")
        return 1

    # Les 5 niveaux doivent rester disjoints.
    tiers = {
        "public": set(matrix.PUBLIC_COMMANDS),
        "guild-owner": set(matrix.GUILD_OWNER_COMMANDS),
        "owner-sentrix": set(matrix.OWNER_ONLY_COMMANDS),
        "discord-permission": set(matrix.DISCORD_PERMISSION_COMMANDS),
    }
    for left in tiers:
        for right in tiers:
            if left >= right:
                continue
            shared = tiers[left] & tiers[right]
            if shared:
                print(f"\nCHEVAUCHEMENT {left} / {right} : {sorted(shared)}")
                return 1

    print("\nCouverture des permissions : OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
