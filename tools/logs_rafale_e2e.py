#!/usr/bin/env python3
"""Logs : une suppression multiple devient UNE carte (26/11/2026).

Avant : un ban avec effacement de l'historique, ou la purge d'un autre bot,
produisait une carte « Message supprimé » par message dans le salon de logs.

    python3 tools/logs_rafale_e2e.py
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


async def main() -> int:
    from utils import log_service

    bot = await h.boot(quiet=True)
    guild = await h.setup_world(bot)
    await log_service.set_log_channel(bot, guild.id, "messages", h.LOGCID)
    await log_service.set_log_enabled(bot, guild.id, "messages", True)
    from cogs import setup_v2_core as core
    await core.set_module_enabled(bot, guild.id, "logs", True, actor_id=h.ADMIN_ID)

    async def poster(n):
        ids = []
        for i in range(n):
            message = h.build_message(bot, guild, f"message de test numéro {i} un peu long pour l'aperçu",
                                      author_id=h.TARGET_ID if i % 2 else h.SECOND_ID, author_name="membre")
            ids.append(message.id)
            bot.dispatch("message", message)
        await h.settle(idle=0.5, maximum=4)
        return ids

    def cartes_de_logs(appels):
        return [js for m, p, js in appels if m == "POST" and p == f"/channels/{h.LOGCID}/messages"]

    async def supprimer(ids):
        debut = len(h.CALLS)
        bot.dispatch("raw_bulk_message_delete", discord.RawBulkMessageDeleteEvent(
            {"ids": [str(i) for i in ids], "channel_id": str(h.CID), "guild_id": str(h.GID)}))
        await h.settle(idle=3.5, maximum=12)
        return cartes_de_logs(h.CALLS[debut:])

    ids = await poster(12)
    # Deux messages avec une image (pièce jointe en cache).
    for mid in ids[:2]:
        await bot.db.execute(
            "UPDATE message_log_cache SET attachments=? WHERE message_id=?",
            ('["https://cdn.discordapp.com/attachments/1/2/photo-souvenir.png"]', mid),
        )
    cartes = await supprimer(ids)
    check(len(cartes) == 1, "12 messages supprimés d'un coup donnent UNE carte", f"{len(cartes)} carte(s)")
    texte = str(cartes[0]) if cartes else ""
    check("Suppression multiple" in texte or "supprimé" in texte, "la carte est une suppression multiple", texte[:200])
    check("12 message" in texte, "la carte affiche le nombre exact de messages (revue Codex #729)", texte[:300])
    check(f"<@{h.TARGET_ID}>" in texte and f"<@{h.SECOND_ID}>" in texte, "la carte liste les auteurs")
    check("attachment://suppression-" in texte, "le transcript complet est visible dans la carte (revue Codex #729)")
    check("photo-souvenir" in texte, "les pièces jointes du lot restent dans le log (revue Codex #729)")

    # 27/11/2026 : « quand on fait un clear, ça dit l'auteur lui-même ». Un lot
    # supprimé par un AUTRE bot est tracé sous message_bulk_delete (cible : le
    # salon) ; la carte doit nommer ce bot.
    from types import SimpleNamespace
    AUTRE_BOT_ID = 100000000000000999
    autre_bot = await bot.fetch_user(AUTRE_BOT_ID)
    original_audit = discord.Guild.audit_logs

    def audit_lot(self, *, limit=100, action=None, **kwargs):
        async def generateur():
            if action == discord.AuditLogAction.message_bulk_delete:
                yield SimpleNamespace(_target_id=h.CID, created_at=discord.utils.utcnow(),
                                      extra=SimpleNamespace(count=6), user=autre_bot)
        return generateur()

    discord.Guild.audit_logs = audit_lot
    try:
        cartes = await supprimer(await poster(6))
    finally:
        discord.Guild.audit_logs = original_audit
    rendu = h.visible_text([("POST", "x", c) for c in cartes])
    check(f"par <@{AUTRE_BOT_ID}>" in rendu, "un lot supprimé par un autre bot est attribué à ce bot", rendu[:400])

    def audit_vide(self, *, limit=100, action=None, **kwargs):
        async def generateur():
            if False:
                yield None
        return generateur()

    discord.Guild.audit_logs = audit_vide
    try:
        cartes = await supprimer(await poster(6))
    finally:
        discord.Guild.audit_logs = original_audit
    rendu = h.visible_text([("POST", "x", c) for c in cartes])
    check("auteur lui" not in rendu and "par un bot ou un modérateur" in rendu,
          "sans trace d'audit : « un bot ou un modérateur », jamais « l'auteur lui-même »", rendu[:400])

    cartes = await supprimer(await poster(2))
    check(len(cartes) == 2, "2 messages gardent leur carte chacun (pas de regroupement inutile)",
          f"{len(cartes)} carte(s)")

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
