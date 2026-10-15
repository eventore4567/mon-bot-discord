#!/usr/bin/env python3
"""Rôles automatiques (/setup › Rôles automatiques), sur le bot booté.

Règles du brief : un rôle n'est donné que s'il a été choisi ; la hiérarchie est
respectée ; à la levée d'une sanction, seul le rôle donné par SentriX est retiré,
jamais un rôle posé à la main.

    python3 tools/auto_roles_e2e.py
"""
from __future__ import annotations

import asyncio
import os
import pathlib
import re
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import discord  # noqa: E402
from discord import utils as dutils  # noqa: E402

import sentrix_e2e_harness as h  # noqa: E402
from setup_sweep import build, interaction, walk  # noqa: E402
from suggestions_e2e import RESULTS, check  # noqa: E402

ADMIN = dict(author_id=h.ADMIN_ID, author_roles=(h.ADMIN_ROLE_ID,))
WARN_ROLE_ID = 100000000000000201
MUTE_ROLE_ID = 100000000000000202


def role_calls(since: int, user_id: int) -> list[tuple[str, int]]:
    out = []
    for method, path, _js in h.CALLS[since:]:
        m = re.fullmatch(rf"/guilds/{h.GID}/members/{user_id}/roles/(\d+)", path)
        if m and method in ("PUT", "DELETE"):
            out.append((method, int(m.group(1))))
    return out


def gateway(member: discord.Member, since: int) -> None:
    """Comme Discord : les rôles ajoutés/retirés reviennent par la passerelle."""
    roles = {r for r in member._roles}
    for method, role_id in role_calls(since, member.id):
        (roles.add if method == "PUT" else roles.discard)(role_id)
    member._roles = dutils.SnowflakeList(sorted(roles))


async def main() -> int:
    bot = await h.boot(quiet=True)
    sys.modules["cogs.moderation"].Moderation.SANCTION_DUPLICATE_TTL = 0
    bot.get_cog("Moderation").SANCTION_DUPLICATE_TTL = 0
    guild = await h.setup_world(bot)
    state = bot._connection
    for rid, name in ((WARN_ROLE_ID, "Averti"), (MUTE_ROLE_ID, "Muet")):
        guild._add_role(discord.Role(guild=guild, state=state, data={
            "id": str(rid), "name": name, "permissions": "0", "position": 1, "color": 0,
            "hoist": False, "managed": False, "mentionable": False}))
    target = guild.get_member(h.TARGET_ID)
    second = guild.get_member(h.SECOND_ID)

    async def command(text: str) -> str:
        since = len(h.CALLS)
        await asyncio.wait_for(h.run_prefix(bot, guild, text, **ADMIN), 15)
        await h.settle(idle=0.3, maximum=3)
        return h.visible_text(h.CALLS[since:])

    async def choose(placeholder_start: str, role_id: int | None) -> str:
        view = await build(bot, guild, "roles")
        select = next(i for top in view.children for i in walk(top)
                      if isinstance(i, discord.ui.RoleSelect) and str(i.placeholder).startswith(placeholder_start))
        select._values = [guild.get_role(role_id)] if role_id else []
        since = len(h.CALLS)
        await select.callback(interaction(bot))
        await h.settle(idle=0.2, maximum=2)
        return h.visible_text(h.CALLS[since:])

    # La page : toutes les règles au même endroit, réglage en cours visible.
    view = await build(bot, guild, "roles")
    text = "\n".join(str(getattr(i, "content", "")) for top in view.children for i in walk(top)
                     if isinstance(i, discord.ui.TextDisplay))
    for label in ("Arrivée", "Vérification", "Avertissement", "Mute", "Exclusion des giveaways", "Récompenses de niveau"):
        check(f"**{label}**" in text, f"la page montre la règle « {label} »")

    shown = await choose("Avertissement", h.ADMIN_ROLE_ID)
    conf = await bot.db.get_guild_config(h.GID)
    check(not conf["warn_role"] and "au-dessus" in shown, "un rôle au-dessus de SentriX est refusé avec la raison",
          shown[:160])
    await choose("Avertissement", WARN_ROLE_ID)
    await choose("Mute", MUTE_ROLE_ID)
    conf = await bot.db.get_guild_config(h.GID)
    check(int(conf["warn_role"] or 0) == WARN_ROLE_ID and int(conf["mute_role"] or 0) == MUTE_ROLE_ID,
          "les rôles choisis sont enregistrés")
    view = await build(bot, guild, "roles")
    defaults = {str(i.placeholder).split(" :")[0]: [d.id for d in i.default_values]
                for top in view.children for i in walk(top) if isinstance(i, discord.ui.RoleSelect)}
    check(defaults.get("Avertissement") == [WARN_ROLE_ID], "le sélecteur affiche le rôle en cours", str(defaults))

    # Avertissement : donné, puis retiré quand il n'y a plus d'avertissement.
    since = len(h.CALLS)
    await command(f"+warn <@{h.TARGET_ID}> spam")
    check(("PUT", WARN_ROLE_ID) in role_calls(since, h.TARGET_ID), "+warn donne le rôle d'avertissement")
    gateway(target, since)
    since = len(h.CALLS)
    shown = await command(f"+clearwarnings <@{h.TARGET_ID}>")
    check(("DELETE", WARN_ROLE_ID) in role_calls(since, h.TARGET_ID) and "retiré" in shown,
          "effacer ses avertissements retire le rôle donné par SentriX", shown[:200])
    gateway(target, since)

    # Le même rôle posé À LA MAIN : jamais retiré par SentriX.
    second._roles = dutils.SnowflakeList(sorted(set(second._roles) | {WARN_ROLE_ID, MUTE_ROLE_ID}))
    since = len(h.CALLS)
    await command(f"+warn <@{h.SECOND_ID}> test")
    await command(f"+clearwarnings <@{h.SECOND_ID}>")
    check(not role_calls(since, h.SECOND_ID), "un rôle d'avertissement posé à la main n'est jamais retiré",
          str(role_calls(since, h.SECOND_ID)))
    since = len(h.CALLS)
    await command(f"+mute <@{h.SECOND_ID}> 10m test")
    await command(f"+unmute <@{h.SECOND_ID}>")
    check(("DELETE", MUTE_ROLE_ID) not in role_calls(since, h.SECOND_ID),
          "l'unmute ne retire pas un rôle de mute posé à la main (avant : retiré)", str(role_calls(since, h.SECOND_ID)))

    # Mute : rôle donné, puis retiré à la FIN NATURELLE du mute (avant : jamais).
    since = len(h.CALLS)
    await command(f"+mute <@{h.TARGET_ID}> 10m flood")
    check(("PUT", MUTE_ROLE_ID) in role_calls(since, h.TARGET_ID), "+mute donne le rôle de mute")
    gateway(target, since)
    row = await bot.db.fetchone("SELECT id FROM tempactions WHERE user_id = ? AND action = 'mute_role'", (h.TARGET_ID,))
    check(row is not None, "la fin du mute est programmée")
    await bot.db.execute("UPDATE tempactions SET expires_at = ? WHERE id = ?", (int(time.time()) - 5, row["id"]))
    target.timed_out_until = None
    moderation = bot.get_cog("Moderation")
    since = len(h.CALLS)
    await type(moderation).check_tempactions.coro(moderation)
    await h.settle(idle=0.2, maximum=2)
    check(("DELETE", MUTE_ROLE_ID) in role_calls(since, h.TARGET_ID), "à la fin du mute, le rôle de mute est retiré")
    left = await bot.db.fetchone("SELECT COUNT(*) AS n FROM tempactions WHERE user_id = ? AND action = 'mute_role'",
                                 (h.TARGET_ID,))
    check(int(left["n"]) == 0, "la tâche de fin de mute est soldée")

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
