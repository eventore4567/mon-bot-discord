#!/usr/bin/env python3
"""Exemptions de sécurité sur le bot booté : rôles exemptés, salons ignorés, salons stricts.

Le brief demande UN système commun (rôles bypass, salons exclus, salons stricts,
immunité) plutôt qu'une logique par module. Il existe :
cogs/automod.py::security_filter_applies_to, appelé par les huit filtres de
messages. Ce scénario prouve qu'il tient sur de vrais messages — un lien posté
par un membre, supprimé ou non selon la configuration.

    python3 tools/security_policy_e2e.py
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

import sentrix_e2e_harness as h  # noqa: E402
from suggestions_e2e import RESULTS, check  # noqa: E402

LINK = "regarde ça https://exemple-douteux.example/offre"
INVITE = "rejoins discord.gg/abcdefg"
BYPASS_ROLE = h.PING_ROLE_ID  # rôle sans permission, utilisé comme rôle exempté


async def main() -> int:
    bot = await h.boot(quiet=True)
    guild = await h.setup_world(bot)
    automod = bot.get_cog("Automod")
    db = bot.db
    await db.execute("INSERT INTO automod_settings (guild_id) VALUES (?) ON CONFLICT(guild_id) DO NOTHING", (h.GID,))
    await db.execute("UPDATE automod_settings SET antilink=1, antiinvite=1 WHERE guild_id=?", (h.GID,))

    def forget() -> None:
        for cache in (automod.automod_cache, automod.exempt_roles_cache, automod.ignored_channels_cache,
                      automod.security_filter_policy_cache, automod.antispam_policy_cache,
                      automod.immunity_overrides_cache):
            cache.clear()

    async def deleted(content: str, roles=(h.MEMBER_ROLE_ID,)) -> bool:
        forget()
        message = h.build_message(bot, guild, content, author_id=h.TARGET_ID, author_name="cible", author_roles=roles)
        since = len(h.CALLS)
        bot.dispatch("message", message)
        await h.settle(idle=0.6, maximum=4)
        return any(m == "DELETE" and p == f"/channels/{h.CID}/messages/{message.id}" for m, p, _ in h.CALLS[since:])

    async def policy(filter_name: str, *, roles=(), strict=()) -> None:
        await db.set_security_filter_policy(h.GID, filter_name, role_ids=list(roles), strict_channel_ids=list(strict))

    with_bypass = (h.MEMBER_ROLE_ID, BYPASS_ROLE)

    # 1 — Référence : un lien d'un membre est supprimé.
    check(await deleted(LINK), "un lien posté par un membre est supprimé")

    # 2 — Rôle exempté POUR l'anti-liens : le lien passe.
    await policy("antilink", roles=[BYPASS_ROLE])
    check(not await deleted(LINK, with_bypass), "rôle exempté de l'anti-liens : le lien passe")

    # 3 — L'exemption est limitée à SON filtre : l'invitation reste supprimée.
    check(await deleted(INVITE, with_bypass), "le même rôle n'exempte pas de l'anti-invitations")

    # 4 — Salon strict : même le rôle exempté est soumis à la règle.
    await policy("antilink", roles=[BYPASS_ROLE], strict=[h.CID])
    check(await deleted(LINK, with_bypass), "salon strict : le rôle exempté est quand même filtré")
    await policy("antilink")

    # 5 — Salon ignoré : aucun filtre, pour tout le monde.
    await db.execute("INSERT INTO ignored_channels (guild_id, channel_id) VALUES (?, ?)", (h.GID, h.CID))
    check(not await deleted(LINK), "salon ignoré : le lien d'un membre passe")
    await policy("antilink", strict=[h.CID])
    check(await deleted(LINK), "salon ignoré MAIS strict pour l'anti-liens : le strict l'emporte")
    await policy("antilink")
    await db.execute("DELETE FROM ignored_channels WHERE guild_id=?", (h.GID,))

    # 6 — Rôle exempté de TOUT l'AutoMod (historique) : exempté, sauf en salon strict.
    await db.execute("INSERT INTO automod_exempt_roles (guild_id, role_id) VALUES (?, ?)", (h.GID, BYPASS_ROLE))
    check(not await deleted(LINK, with_bypass), "rôle exempté de tout l'AutoMod : le lien passe")
    await policy("antilink", strict=[h.CID])
    check(await deleted(LINK, with_bypass), "rôle exempté global en salon strict : filtré")
    await policy("antilink")
    await db.execute("DELETE FROM automod_exempt_roles WHERE guild_id=?", (h.GID,))

    # 7 — Immunité personnelle explicite : elle passe partout, salon strict compris.
    await db.execute(
        "INSERT INTO user_immunity_settings (guild_id, user_id, enabled, updated_at) VALUES (?, ?, 1, 0)",
        (h.GID, h.TARGET_ID),
    )
    await policy("antilink", strict=[h.CID])
    check(not await deleted(LINK), "immunité personnelle : le lien passe, même en salon strict")
    await db.execute("DELETE FROM user_immunity_settings WHERE guild_id=?", (h.GID,))
    await policy("antilink")

    # 8 — Retour à l'état de départ : filtré de nouveau.
    check(await deleted(LINK), "sans exemption, le lien est de nouveau supprimé")

    failed = [r for r in RESULTS if not r[0]]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} étapes réussies.")
    sys.stdout.flush()
    os._exit(1 if failed else 0)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except BaseException:
        # aiosqlite garde des threads vivants : sans sortie franche, une exception
        # laisserait le processus suspendu au lieu d'échouer.
        import traceback

        traceback.print_exc()
        sys.stdout.flush()
        os._exit(1)
