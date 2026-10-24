#!/usr/bin/env python3
"""Trace d'exécution des installateurs SentriX sur le boot E2E SANS réseau.

Le rapport distingue installateurs observés pendant le boot et installateurs
non observés. "Non observé" NE signifie PAS "mort" : un chemin peut être
conditionnel, différé jusqu'à on_ready ou déclenché par une interaction.
N'applique aucune modification, ne supprime aucun fichier et n'utilise
pas le token de production.
"""
from __future__ import annotations

import asyncio
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import installer_inventory
from tools import sentrix_e2e_harness as harness

COGS = (ROOT / "cogs").resolve()


def make_profiler(seen: set[str]):
    def record(frame, event, _arg):
        if event != "call" or frame.f_code.co_name not in {"install", "setup"}:
            return
        try:
            path = pathlib.Path(frame.f_code.co_filename).resolve().relative_to(COGS)
        except (OSError, ValueError):
            return
        if len(path.parts) != 1 or path.suffix != ".py":
            return
        seen.add("cogs." + path.stem)
    return record


async def trace() -> dict:
    inventory = installer_inventory.inventory(ROOT)
    observed: set[str] = set()
    profiler = make_profiler(observed)
    bot = None
    previous_profiler = sys.getprofile()
    sys.setprofile(profiler)
    try:
        bot = await harness.boot(quiet=False)
    finally:
        sys.setprofile(previous_profiler)

    try:
        manual = set(inventory["install_without_setup"])
        status = dict(getattr(bot, "_sentrix_v17_install_report", {}) or {})
        failures = {
            key: value
            for key, value in status.items()
            if isinstance(value, dict) and value.get("status") == "failed"
        }
        return {
            "scope": "offline e2e startup (no Discord gateway or on_ready)",
            "installer_modules_observed": sorted(manual & observed),
            "installer_modules_not_observed": sorted(manual - observed),
            "v17_install_report": status,
            "v17_failure_count": len(failures),
            "v17_failure_labels": sorted(failures),
            "manual_installer_count": len(manual),
        }
    finally:
        if bot is not None:
            await bot.close()


def main() -> int:
    report = asyncio.run(trace())
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(
        "\nAttention : l'absence dans cette trace hors ligne n'est pas une "
        "preuve d'inutilité ni une autorisation de supprimer un cog."
    )
    return 1 if report["v17_failure_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
