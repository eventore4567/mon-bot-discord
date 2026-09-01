"""Porte de detection des modules morts.

Charge reellement le bot, puis signale les fichiers de cogs/ qui ne sont JAMAIS
importes et qu'aucun module vivant ne reference.

Pourquoi cette porte existe : le depot a accumule des generations de correctifs
(fix_v24 -> style_v29 -> layout_v26 -> polish_v53 -> dedupe_v54 -> ...) qui
s'importaient entre elles sans que plus rien de vivant n'y entre. 23 modules et
6609 lignes ont ete retires ainsi. Cette porte empeche que ca recommence sans
qu'on le voie.

Elle ne casse PAS le build par defaut : elle rapporte. Passez --strict pour la
rendre bloquante en CI une fois le depot assaini.
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

# Modules non importes au boot mais dont une dependance vivante a ete VERIFIEE.
# Chacun est retenu par un appel reel, pas par une reference defensive.
RETENUS: dict[str, str] = {
    "command_clarity": "language_runtime appelle friendly_summary()",
    "moderation_logs_fix": "premium_logs et premium_logs_v2 appellent _repair_log_target()",
    "command_no_emoji_runtime": "plain_response_policy appelle _clean_send_args()",
    "final_runtime_polish": "help_v8_final_guard appelle install()",
    "verification_polish_v51": "security_verification_v71 l'importe",
    "live_command_gate_v19": "railway_boot l'installe au demarrage (hors harnais)",
}


async def main() -> int:
    strict = "--strict" in sys.argv
    config.DATABASE_PATH = str(pathlib.Path(tempfile.mkdtemp()) / "dead.db")
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

    importes = {n.split(".", 1)[1] for n in sys.modules if n.startswith("cogs.")}
    tous = {p.stem for p in (ROOT / "cogs").glob("*.py") if p.stem != "__init__"}
    jamais = tous - importes

    # Une reference TEXTUELLE depuis un module vivant suffit a retenir un fichier :
    # elle attrape aussi les imports differes dans une fonction rarement appelee.
    vivants = [
        p for p in list((ROOT / "cogs").glob("*.py")) + list((ROOT / "utils").glob("*.py"))
        + [ROOT / "main.py", ROOT / "railway_boot.py"]
        if p.stem not in jamais
    ]
    retenus_par: dict[str, list[str]] = {}
    for fichier in vivants:
        texte = fichier.read_text(encoding="utf-8", errors="ignore")
        for module in jamais:
            if re.search(rf"\b{re.escape(module)}\b", texte):
                retenus_par.setdefault(module, []).append(fichier.name)

    orphelins = sorted(m for m in jamais if m not in retenus_par and m not in RETENUS)
    lignes = sum(
        len((ROOT / "cogs" / f"{m}.py").read_text(encoding="utf-8", errors="ignore").splitlines())
        for m in orphelins
    )

    print(f"fichiers cogs/*.py       : {len(tous)}")
    print(f"importes au boot         : {len(tous & importes)}")
    print(f"jamais importes          : {len(jamais)}")
    print(f"  retenus par un vivant  : {len(retenus_par)}")
    print(f"  dependance verifiee    : {len(RETENUS)}")
    print(f"  ORPHELINS              : {len(orphelins)} ({lignes} lignes)")

    if orphelins:
        print("\nModules que plus rien n'atteint :")
        for module in orphelins:
            print("   ", module)
        print("\nVerifiez avant de supprimer : un chemin d'import non couvert par le")
        print("harnais (comme railway_boot) peut encore les atteindre en production.")
        if strict:
            return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
