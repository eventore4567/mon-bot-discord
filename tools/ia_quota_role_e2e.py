#!/usr/bin/env python3
"""Limites d'IA par rôle dans /setup → IA (25/11/2026).

+airolequota (cogs/v17_ai_economy_games) n'était plus chargé en production
depuis août : réglage relogé dans /setup → IA, appliqué par ai_service.

    python3 tools/ia_quota_role_e2e.py
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

import discord  # noqa: E402
import sentrix_e2e_harness as h  # noqa: E402
from suggestions_e2e import RESULTS, check  # noqa: E402
from welcome_e2e import admin_interaction  # noqa: E402


async def main() -> int:
    from cogs import setup_experience_v74 as v74
    from utils import ai_service

    bot = await h.boot(quiet=True)
    guild = await h.setup_world(bot)
    reglages = await ai_service.get_settings(bot, guild.id)
    base = int(reglages["daily_limit"])

    view = v74.SentriXSetupV74(bot, guild, h.ADMIN_ID)
    await view.prepare()

    async def page():
        view.page = "ai"
        view.clear_items()
        await view._build_page("ai")
        return [i for i in view.walk_children()]

    items = await page()
    roles = [i for i in items if isinstance(i, discord.ui.RoleSelect)]
    check(bool(roles), "/setup → IA propose de choisir un rôle à limiter")
    if not roles:
        os._exit(1)
    roles[0]._values = [guild.get_role(h.MEMBER_ROLE_ID)]
    try:
        await roles[0].callback(admin_interaction(bot))
    except Exception:  # noqa: BLE001 — rafraîchissement non testé ici
        pass
    items = await page()
    limites = [i for i in items if isinstance(i, discord.ui.Select) and any("200" in o.label for o in i.options)]
    check(bool(limites), "après le rôle, une limite par jour se choisit")
    limites[0]._values = ["200"]
    try:
        await limites[0].callback(admin_interaction(bot))
    except Exception:  # noqa: BLE001
        pass
    quotas = await ai_service.quotas_par_role(bot, guild.id)
    check(quotas.get(h.MEMBER_ROLE_ID) == 200, "la limite du rôle est enregistrée", str(quotas))

    limite = await ai_service.limite_quotidienne(bot, guild.id, h.TARGET_ID, reglages)
    check(limite == 200, "un membre de ce rôle a 200 demandes par jour", f"{limite} (base {base})")
    limite_admin = await ai_service.limite_quotidienne(bot, guild.id, h.ADMIN_ID, reglages)
    check(limite_admin == base, "un membre sans ce rôle garde la limite du serveur", str(limite_admin))

    texte = " ".join(i.content for i in (await page()) if isinstance(i, discord.ui.TextDisplay))
    check(f"<@&{h.MEMBER_ROLE_ID}>" in texte and "200" in texte, "la page liste les limites par rôle")

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
