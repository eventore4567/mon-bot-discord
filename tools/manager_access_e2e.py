#!/usr/bin/env python3
"""Un gestionnaire de serveur (« Gérer le serveur », pas Administrateur) sur le bot booté.

Mesuré le 08/10/2026 en lançant chaque commande « configuration » sans argument :
une erreur d'argument prouve que la permission est passée, un refus montre le
message réellement affiché. Ce passage a révélé trois défauts :

- la vérification était refusée par SON code (Administrateur) après avoir été
  accordée par la décision centrale (Gérer le serveur) : deux décisions, deux
  messages ;
- +diagnostic et +healthcheck plantaient sur une table jamais créée ;
- +setup-auto répondait « se charge encore » à chaque appel.

    python3 tools/manager_access_e2e.py
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

MANAGER_ROLE = 100000000000000105
MANAGER_ID = 100000000000000081
TECHNICAL_ERROR = "Une erreur technique a interrompu la commande"


async def main() -> int:
    from utils import access_matrix as matrix

    bot = await h.boot(quiet=True)
    guild = await h.setup_world(bot)
    perms = discord.Permissions(h.MEMBER_PERMISSIONS.value)
    perms.update(manage_guild=True)
    guild._add_role(discord.Role(guild=guild, state=bot._connection, data={
        "id": str(MANAGER_ROLE), "name": "Gestion", "permissions": str(perms.value), "position": 3,
        "color": 0, "hoist": False, "managed": False, "mentionable": False}))
    guild._add_member(discord.Member(data=h.member_payload(MANAGER_ID, "gestion", [MANAGER_ROLE]),
                                     guild=guild, state=bot._connection))
    who = {
        "membre": dict(author_id=h.TARGET_ID, author_roles=(h.MEMBER_ROLE_ID,)),
        "gestionnaire": dict(author_id=MANAGER_ID, author_name="gestion", author_roles=(MANAGER_ROLE,)),
        "admin": dict(author_id=h.ADMIN_ID, author_roles=(h.ADMIN_ROLE_ID,)),
    }

    async def run(command: str, persona: str) -> str:
        since = len(h.CALLS)
        await asyncio.wait_for(h.run_prefix(bot, guild, command, **who[persona]), 15)
        await h.settle(idle=0.3, maximum=2)
        return h.visible_text(h.CALLS[since:]).replace("\n", " ")

    # 1 — Toute la catégorie « configuration » : le gestionnaire passe, rien ne plante.
    refused, crashed = [], []
    for name in sorted(matrix.CATEGORY_COMMANDS["configuration"]):
        if bot.get_command(name) is None:
            continue
        text = await run(f"+{name}", "gestionnaire")
        if "Vous n'avez pas accès" in text and "propriétaire" not in text and "proprietaire" not in text:
            refused.append(name)
        if TECHNICAL_ERROR in text:
            crashed.append(name)
    check(not refused, "configuration : le gestionnaire passe la décision centrale partout", ", ".join(refused))
    check(not crashed, "configuration : aucune commande ne plante sans argument", ", ".join(crashed))

    # 2 — Vérification : une seule décision, un seul message, Administrateur.
    for command in ("+verification", "+verify-setup", "+verify-panel"):
        member, manager, admin = [await run(command, p) for p in ("membre", "gestionnaire", "admin")]
        check("Administrateur" in member and member == manager,
              f"{command} : membre et gestionnaire reçoivent le même refus (Administrateur)", manager[:120])
        check("Configuration de la vérification" in admin, f"{command} : l'administrateur ouvre la configuration", admin[:120])

    # 3 — Diagnostic : un rapport, pas une erreur technique.
    for command in ("+diagnostic", "+healthcheck"):
        text = await run(command, "admin")
        check("Diagnostic" in text and TECHNICAL_ERROR not in text, f"{command} rend son rapport", text[:120])

    # 4 — L'auto-setup (création de salons et rôles) n'existe plus.
    check(bot.get_command("setup-auto") is None and bot.get_command("autosetup") is None,
          "+setup-auto et +autosetup sont retirés")

    failed = [r for r in RESULTS if not r[0]]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} étapes réussies.")
    sys.stdout.flush()
    os._exit(1 if failed else 0)


if __name__ == "__main__":
    asyncio.run(main())
