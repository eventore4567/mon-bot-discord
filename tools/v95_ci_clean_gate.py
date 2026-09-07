#!/usr/bin/env python3
"""Lance le gate V95 hors-ligne avec un journal strictement actionnable.

Le gate charge le runtime produit complet mais ne se connecte volontairement ni à Discord
ni à OpenAI. Deux messages historiques sont donc du bruit dans CE contexte uniquement :
la clé OpenAI absente et l'état transitoire V18 avant l'audit final du registre. Toute autre
erreur ou tout autre warning garde son niveau et reste visible.
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
        return True


def _install_filter() -> None:
    noise_filter = _ExpectedOfflineNoise()
    logging.getLogger("bot.ai-api-hotfix").addFilter(noise_filter)
    logging.getLogger("bot.command-runtime-hardening-v18").addFilter(noise_filter)


def main() -> int:
    _install_filter()
    from tools.v95_slash_invites_gate import run

    return asyncio.run(run())


if __name__ == "__main__":
    raise SystemExit(main())
