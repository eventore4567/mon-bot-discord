#!/usr/bin/env python3
"""Lance le gate V95 hors-ligne avec un journal strictement actionnable.

Le gate charge le runtime produit complet mais ne se connecte volontairement ni à Discord
ni à OpenAI. Trois messages historiques sont donc du bruit dans CE contexte uniquement :
la clé OpenAI absente, l'état transitoire V18 avant l'audit final du registre, et l'échec
attendu de restauration d'une vue persistante avant login Discord. Toute autre erreur ou
tout autre warning garde son niveau et reste visible.
"""
from __future__ import annotations

import asyncio
import logging
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("SENTRIX_CI_OFFLINE", "1")


class _ExpectedOfflineNoise(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        if (
            record.name == "bot.ai-api-hotfix"
            and "OPENAI_API_KEY is missing" in message
        ):
            return False
        if (
            record.name == "bot.command-runtime-hardening-v18"
            and "paramètres internes encore exposés" in message
        ):
            return False
        if (
            record.name == "bot.sentrix-regression-runtime"
            and "Role panel persistent view restore failed" in message
        ):
            return False
        return True


def _install_filter() -> None:
    noise_filter = _ExpectedOfflineNoise()
    for logger_name in (
        "bot.ai-api-hotfix",
        "bot.command-runtime-hardening-v18",
        "bot.sentrix-regression-runtime",
    ):
        logging.getLogger(logger_name).addFilter(noise_filter)


def main() -> int:
    _install_filter()
    from tools.v95_slash_invites_gate import run

    return asyncio.run(run())


if __name__ == "__main__":
    raise SystemExit(main())
