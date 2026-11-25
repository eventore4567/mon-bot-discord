#!/usr/bin/env python3
"""Recours de bannissement et modmail sur le bot booté (25/11/2026).

L'Enterprise Suite dormait depuis août (jamais chargée en production) : elle
est rechargée, désactivée par défaut, réglée dans /setup → Modération.

    python3 tools/support_recours_e2e.py
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

DM_ID = 100000000000009911


def message_prive(bot, texte: str) -> discord.Message:
    canal = discord.DMChannel(me=bot.user, state=bot._connection,
                              data={"id": str(DM_ID), "type": 1, "recipients": [h.user(h.TARGET_ID, "cible")]})
    data = h.message_payload(h.next_id(), DM_ID, texte, h.TARGET_ID, "cible")
    return discord.Message(state=bot._connection, channel=canal, data=data)


async def main() -> int:
    from utils import enterprise_infra

    connexions = []
    original_connect = enterprise_infra.EnterpriseInfra.connect

    async def connect_espion(self):
        connexions.append(self)
        return await original_connect(self)

    enterprise_infra.EnterpriseInfra.connect = connect_espion
    bot = await h.boot(quiet=True)
    guild = await h.setup_world(bot)
    support = bot.get_cog("EnterpriseSuite")
    check(support is not None, "le module recours/modmail est chargé au démarrage")
    if support is None:
        os._exit(1)

    # Pas de seconde réserve de connexions PostgreSQL, ni de boucles qui
    # écrivent toutes les minutes (métriques, analyses, sauvegardes).
    check(not connexions and getattr(support.infra, "pg_pool", None) is None,
          "le module n'ouvre aucune connexion PostgreSQL à part")
    check(not support.metrics_loop.is_running() and not support.analytics_loop.is_running()
          and not support.backup_loop.is_running(),
          "les boucles de métriques, d'analyses et de sauvegarde ne tournent pas")

    reglages = await support.get_settings(h.GID)
    check(not int(reglages["appeals_enabled"]) and not int(reglages["modmail_enabled"]),
          "recours et modmail sont désactivés par défaut", str(reglages))

    async def mp(texte):
        debut = len(h.CALLS)
        await support.on_message(message_prive(bot, texte))
        await h.settle(idle=0.3, maximum=3)
        return h.CALLS[debut:]

    appels = await mp("bonjour le staff")
    check(not any("/threads" in p for _m, p, _ in appels), "modmail désactivé : un MP n'ouvre aucun fil")

    # /setup → Modération : les deux réglages sont là.
    from cogs import setup_experience_v74 as v74
    async def page_moderation():
        view = v74.SentriXSetupV74(bot, guild, h.ADMIN_ID)
        await view.prepare()
        view.page = "section:moderation"
        view.clear_items()
        await view._build_page(view.page)
        return view
    view = await page_moderation()
    textes = " ".join(i.content for i in view.walk_children() if isinstance(i, discord.ui.TextDisplay))
    check("Recours de bannissement" in textes and "Modmail" in textes,
          "/setup → Modération propose recours et modmail")
    salons = [i for i in view.walk_children() if isinstance(i, discord.ui.ChannelSelect)]
    check(bool(salons), "un menu choisit le salon du modmail")

    # Activation par /setup.
    select = salons[0]
    select._values = [guild.get_channel(h.LOGCID)]
    try:
        await select.callback(admin_interaction(bot))
    except Exception:  # noqa: BLE001 — le rafraîchissement de la vue n'est pas testé ici
        pass
    reglages = await support.get_settings(h.GID)
    check(int(reglages["modmail_enabled"]) == 1 and int(reglages["modmail_channel_id"] or 0) == h.LOGCID,
          "choisir un salon active le modmail", str(reglages))

    appels = await mp("bonjour le staff")
    check(any(m == "POST" and "/threads" in p for m, p, _ in appels), "modmail actif : le MP ouvre un fil staff")
    ligne = await bot.db.fetchone("SELECT COUNT(*) AS n FROM modmail_messages", ())
    check(int(ligne["n"]) >= 1, "le message du membre est enregistré")

    # Une conversation IA ouverte (« mp moi ») garde la priorité.
    from utils import mp_ouvertes
    await mp_ouvertes.ouvrir(bot, h.TARGET_ID, h.GID)
    avant = await bot.db.fetchone("SELECT COUNT(*) AS n FROM modmail_messages", ())
    await mp("salut sentrix")
    apres = await bot.db.fetchone("SELECT COUNT(*) AS n FROM modmail_messages", ())
    check(int(apres["n"]) == int(avant["n"]), "une conversation IA ouverte n'est pas détournée en modmail")

    # Recours : désactivé, un ban n'en crée pas ; activé, oui.
    cible = await bot.fetch_user(h.SECOND_ID) if guild.get_member(h.SECOND_ID) is None else guild.get_member(h.SECOND_ID)
    check(await support.create_appeal_for_ban(guild, cible) is None, "recours désactivé : aucun lien envoyé")
    await support.update_settings(h.GID, appeals_enabled=1)
    recours = await support.create_appeal_for_ban(guild, cible)
    check(bool(recours) and recours.get("token") and recours.get("appeal_id"),
          "recours actif : un recours et son lien sont créés", str(recours)[:200])

    # Base PostgreSQL : la sauvegarde toutes les 6 h ne lève plus d'erreur.
    erreurs = []
    original = support._record_error
    async def espion(*a):
        erreurs.append(a)
    support._record_error = espion
    from unittest import mock
    try:
        with mock.patch.object(type(bot.db), "backend", new=property(lambda self: "postgres")):
            await support.backup_loop.coro(support)
    finally:
        support._record_error = original
    check(not erreurs, "sur PostgreSQL, la boucle de sauvegarde ne remonte aucune erreur")

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
