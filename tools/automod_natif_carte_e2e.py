#!/usr/bin/env python3
"""Carte de log d'un blocage par l'AutoMod natif de Discord (26/11/2026).

Avant : titre coupé (« Blocage du messa… »), aucune raison réelle, doublons
(Source, « autre sanction non confirmée »). Maintenant : titre court, règle
en clair, mot détecté et message bloqué.

    python3 tools/automod_natif_carte_e2e.py
"""
from __future__ import annotations

import asyncio
import os
import pathlib
import sys
from types import SimpleNamespace

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import discord  # noqa: E402
import sentrix_e2e_harness as h  # noqa: E402
from suggestions_e2e import RESULTS, check  # noqa: E402


async def main() -> int:
    from cogs import setup_v2_core as core
    from utils import log_service

    bot = await h.boot(quiet=True)
    guild = await h.setup_world(bot)
    await core.set_module_enabled(bot, guild.id, "logs", True, actor_id=h.ADMIN_ID)
    await log_service.set_log_channel(bot, guild.id, "automod", h.LOGCID)
    await log_service.set_log_enabled(bot, guild.id, "automod", True)
    cog = bot.get_cog("Automod")
    cog._native_rule_details[(guild.id, 555)] = ("Block Commonly Flagged Words", None)
    execution = SimpleNamespace(
        action=SimpleNamespace(type=discord.AutoModRuleActionType.block_message),
        guild_id=guild.id, rule_id=555, user_id=h.TARGET_ID, channel_id=h.CID,
        content="tu es un criminel va", matched_keyword="criminel", matched_content="criminel",
        alert_system_message_id=None, message_id=None,
    )
    debut = len(h.CALLS)
    await cog.on_automod_action(execution)
    await h.settle(idle=2.0, maximum=8)
    texte = h.visible_text(h.CALLS[debut:])

    titre = next((l for l in texte.splitlines() if l.startswith("### ")), "")
    check(len(titre) <= 50, "le titre est assez court pour ne pas être coupé", titre)
    check("`criminel`" in texte, "la carte montre le mot qui a déclenché le blocage", texte[-300:])
    check("tu es un criminel va" in texte, "la carte montre le message bloqué")
    check("Mots couramment signalés" in texte, "la règle de Discord est nommée en clair")
    check("autre sanction non confirmée" not in texte and "Source" not in texte,
          "plus de doublons (Source, « autre sanction non confirmée »)")

    # 27/11/2026 : règle à expression régulière — le mot écrit, pas le motif.
    cog._native_block_last_seen.clear()
    cog._native_rule_details[(guild.id, 556)] = ("Block Custom Words", None)
    regex = SimpleNamespace(**{**vars(execution), "rule_id": 556, "content": "T'es bien enfoire",
                                 "matched_keyword": r"(?i)\b(connard|connasse|enfoir[eé])", "matched_content": "enfoire"})
    debut = len(h.CALLS)
    await cog.on_automod_action(regex)
    await h.settle(idle=2.0, maximum=8)
    texte = h.visible_text(h.CALLS[debut:])
    check("`enfoire`" in texte and "(?i)" not in texte,
          "règle regex : la carte montre le mot écrit, pas l'expression", texte[-200:])

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
