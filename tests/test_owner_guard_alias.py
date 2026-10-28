"""Le verrou « propriétaire seulement » ne doit jamais tomber sur une autre commande.

28/10/2026 : ``bot.get_command("security whitelist user-add")`` rend la racine
quand elle n'est pas un groupe. « security » étant devenu un alias de
+security-check, le verrou des whitelists refusait la vérification de sécurité à
tous les administrateurs non propriétaires.
"""
from __future__ import annotations

import os

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import discord
from discord.ext import commands

from cogs import security_owner_immunity_final as guard


def _bot() -> commands.Bot:
    bot = commands.Bot(command_prefix="+", intents=discord.Intents.none())

    @bot.command(name="security-check", aliases=["security"])
    async def security_check(ctx):
        pass

    @bot.command(name="whitelist-domain")
    async def whitelist_domain(ctx):
        pass

    return bot


def test_owner_lock_skips_a_root_returned_for_a_missing_subcommand():
    bot = _bot()
    guard._guard_whitelists(bot)
    assert guard._server_owner_only not in bot.get_command("security-check").checks


def test_owner_lock_still_applies_to_the_real_whitelist_command():
    bot = _bot()
    guard._guard_whitelists(bot)
    assert guard._server_owner_only in bot.get_command("whitelist-domain").checks
