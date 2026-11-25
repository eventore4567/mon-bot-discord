#!/usr/bin/env python3
"""« Annuler la sanction » sous /case <numéro>, sur le bot booté (25/11/2026).

Reprend +modundo (cogs/v17_moderation_security, jamais chargé en production
depuis août) sans nouvelle commande : un bouton sous la fiche du dossier.

    python3 tools/annulation_dossier_e2e.py
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

ADMIN = dict(author_id=h.ADMIN_ID, author_roles=(h.ADMIN_ROLE_ID,))


async def main() -> int:
    from cogs import moderation as mod

    bot = await h.boot(quiet=True)
    guild = await h.setup_world(bot)
    cog = bot.get_cog("Moderation")

    async def commande(texte):
        debut = len(h.CALLS)
        await asyncio.wait_for(h.run_prefix(bot, guild, texte, **ADMIN), 20)
        await h.settle(idle=0.4, maximum=4)
        return h.CALLS[debut:]

    await commande(f"+warn <@{h.TARGET_ID}> test annulation")
    dossier = await bot.db.fetchone(
        "SELECT case_number FROM sanctions WHERE guild_id=? AND user_id=? AND action='warn' ORDER BY id DESC LIMIT 1",
        (h.GID, h.TARGET_ID),
    )
    numero = int(dossier["case_number"])
    avant = await bot.db.fetchone("SELECT COUNT(*) AS n FROM warnings WHERE guild_id=? AND user_id=?", (h.GID, h.TARGET_ID))

    appels = await commande(f"+case {numero}")
    boutons = str([js for _m, _p, js in appels])
    check("Annuler la sanction" in boutons, "/case <numéro> d'un warn propose « Annuler la sanction »", boutons[-200:])

    vue = mod.AnnulerDossierView(cog, h.GID, numero)
    inter = admin_interaction(bot)
    await vue.annuler.callback(inter)
    await h.settle(idle=0.4, maximum=4)
    apres = await bot.db.fetchone("SELECT COUNT(*) AS n FROM warnings WHERE guild_id=? AND user_id=?", (h.GID, h.TARGET_ID))
    check(int(apres["n"]) == int(avant["n"]) - 1, "le clic supprime l'avertissement du dossier",
          f"{avant['n']} -> {apres['n']}")

    appels = await commande(f"+case {numero}")
    texte = str([js for _m, _p, js in appels])
    check("Annulé" in texte and "Annuler la sanction" not in texte,
          "la fiche affiche l'annulation et n'a plus de bouton", texte[-200:])
    ok, message = await cog.annuler_dossier(guild, numero, guild.get_member(h.ADMIN_ID))
    check(not ok and "déjà été annulé" in message, "une seconde annulation est refusée", message)

    # Mute : l'exclusion est retirée.
    await commande(f"+mute <@{h.TARGET_ID}> 10m test")
    dossier = await bot.db.fetchone(
        "SELECT case_number FROM sanctions WHERE guild_id=? AND user_id=? AND action='mute' ORDER BY id DESC LIMIT 1",
        (h.GID, h.TARGET_ID),
    )
    debut = len(h.CALLS)
    ok, message = await cog.annuler_dossier(guild, int(dossier["case_number"]), guild.get_member(h.ADMIN_ID))
    leve = [js for m, p, js in h.CALLS[debut:] if m == "PATCH" and p.endswith(f"/members/{h.TARGET_ID}")
            and (js or {}).get("communication_disabled_until", "x") is None]
    check(ok and bool(leve), "annuler un mute retire l'exclusion temporaire", message)

    # Une expulsion ne s'annule pas automatiquement.
    await commande(f"+kick <@{h.SECOND_ID}> test")
    dossier = await bot.db.fetchone(
        "SELECT case_number FROM sanctions WHERE guild_id=? AND user_id=? AND action='kick' ORDER BY id DESC LIMIT 1",
        (h.GID, h.SECOND_ID),
    )
    if dossier:
        ok, message = await cog.annuler_dossier(guild, int(dossier["case_number"]), guild.get_member(h.ADMIN_ID))
        check(not ok and "expulsion" in message, "une expulsion ne s'annule pas automatiquement", message)

    # Paliers (venaient de +sanctionpolicy) : mute 1 h puis expulsion, au palier exact.
    await bot.db.execute("DELETE FROM warnings WHERE guild_id=? AND user_id=?", (h.GID, h.TARGET_ID))
    await bot.db.set_guild_config(h.GID, "warn_ban_threshold", 0)
    await mod.regler_paliers(bot, h.GID, 2, 3)
    cog.SANCTION_DUPLICATE_TTL = 0  # l'anti-doublon (même membre, quelques s) n'est pas testé ici
    await commande(f"+warn <@{h.TARGET_ID}> palier 1")
    appels = await commande(f"+warn <@{h.TARGET_ID}> palier 2")
    mute = [js for m, p, js in appels if m == "PATCH" and p.endswith(f"/members/{h.TARGET_ID}")
            and (js or {}).get("communication_disabled_until")]
    check(bool(mute), "2e avertissement : mute d'1 h automatique (palier)")
    appels = await commande(f"+warn <@{h.TARGET_ID}> palier 3")
    check(any(m == "DELETE" and p.endswith(f"/members/{h.TARGET_ID}") for m, p, _ in appels),
          "3e avertissement : expulsion automatique (palier)")
    dossier = await bot.db.fetchone(
        "SELECT reason FROM sanctions WHERE guild_id=? AND user_id=? AND action='kick' ORDER BY id DESC LIMIT 1",
        (h.GID, h.TARGET_ID),
    )
    check(dossier is not None and "Palier" in str(dossier["reason"]), "l'expulsion a son dossier « Palier »")

    from cogs import setup_experience_v74 as v74
    view = v74.SentriXSetupV74(bot, guild, h.ADMIN_ID)
    await view.prepare()
    view.page = "section:moderation"
    view.clear_items()
    await view._build_page(view.page)
    menus = [i for i in view.walk_children() if isinstance(i, discord.ui.Select)]
    check(any("Paliers" in str(o.label) for m in menus for o in m.options),
          "/setup → Modération propose les paliers")

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
