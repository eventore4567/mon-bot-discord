#!/usr/bin/env python3
"""Stock et promotions de la boutique, réglés dans /setup → Économie (25/11/2026).

+shopstock / +shoppromo (cogs/v17_ai_economy_games) n'étaient plus chargés en
production depuis août. Réglage relogé dans /setup, appliqué à l'achat.

    python3 tools/boutique_stock_promo_e2e.py
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
    from cogs import economy_setup

    bot = await h.boot(quiet=True)
    guild = await h.setup_world(bot)
    cur = await bot.db.execute(
        "INSERT INTO shop_items (guild_id, name, price, description, role_id) VALUES (?, ?, ?, ?, NULL)",
        (h.GID, "Badge doré", 100, ""),
    )
    article = int(cur.lastrowid)
    await bot.db.execute("INSERT OR IGNORE INTO economy (guild_id, user_id) VALUES (?, ?)", (h.GID, h.TARGET_ID))
    await bot.db.execute("UPDATE economy SET cash = 1000 WHERE guild_id = ? AND user_id = ?", (h.GID, h.TARGET_ID))

    vue = economy_setup.ShopRulesView(bot, guild, h.ADMIN_ID)
    await vue.build()

    async def cliquer(item, valeur):
        item._values = [valeur]
        try:
            await item.callback(admin_interaction(bot))
        except Exception:  # noqa: BLE001 — le rafraîchissement du message n'est pas testé ici
            pass

    def menu(texte):
        return next((i for i in vue.walk_children() if isinstance(i, discord.ui.Select) and i.placeholder == texte), None)

    check(menu("Article à régler") is not None, "/setup → Économie propose de choisir un article")
    await cliquer(menu("Article à régler"), str(article))
    await vue.build()
    check(menu("Stock") is not None and menu("Promotion") is not None, "stock et promotion se règlent pour l'article")
    await cliquer(menu("Stock"), "1")
    await vue.build()
    await cliquer(menu("Promotion"), "50-24")
    regle = await bot.db.regle_boutique(h.GID, article)
    check(regle and regle["stock"] == 1 and regle["prix_promo"] == 50, "stock 1 et promo −50 % enregistrés", str(regle))

    async def commande(texte):
        debut = len(h.CALLS)
        await asyncio.wait_for(h.run_prefix(bot, guild, texte, author_id=h.TARGET_ID), 20)
        await h.settle(idle=0.4, maximum=4)
        return h.visible_text(h.CALLS[debut:])

    texte = await commande("+shop")
    check("promo" in texte and "1 en stock" in texte, "+shop affiche la promo et le stock", texte[-300:])
    texte = await commande(f"+buy {article}")
    solde = await bot.db.fetchone("SELECT cash FROM economy WHERE guild_id = ? AND user_id = ?", (h.GID, h.TARGET_ID))
    check(int(solde["cash"]) == 950, "l'achat se fait au prix promo (50 au lieu de 100)", f"solde {solde['cash']} — {texte[-160:]}")
    texte = await commande(f"+buy {article}")
    solde2 = await bot.db.fetchone("SELECT cash FROM economy WHERE guild_id = ? AND user_id = ?", (h.GID, h.TARGET_ID))
    check("rupture" in texte and int(solde2["cash"]) == 950, "le stock épuisé bloque l'achat suivant sans débit",
          f"solde {solde2['cash']} — {texte[-160:]}")

    # Revue Codex (PR #728) : un achat remboursé (rôle refusé par Discord,
    # inventaire en échec) rend l'exemplaire au stock.
    await bot.db.regler_boutique(h.GID, article, stock=1)
    statut, achete = await bot.db.purchase_shop_item(h.GID, h.TARGET_ID, article)
    apres_achat = (await bot.db.regle_boutique(h.GID, article))["stock"]
    await bot.db.refund_shop_item(h.GID, h.TARGET_ID, achete, "test remboursement")
    apres_remboursement = (await bot.db.regle_boutique(h.GID, article))["stock"]
    check(statut == "ok" and apres_achat == 0 and apres_remboursement == 1,
          "un achat remboursé rend l'exemplaire au stock", f"{statut} {apres_achat} -> {apres_remboursement}")

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
