"""Sonde exécutée dans un SOUS-PROCESSUS dédié par test_setup_roles_rules_subpage.py.

Booter le vrai bot (~300 extensions, tout finalize_runtime()) pollue le processus :
la plupart des cogs installent leurs monkeypatches avec une garde d'idempotence
(if getattr(current, "_marker", False): return) pensée pour un SEUL vrai bot par
processus, pas pour cohabiter avec les autres fichiers de tests/ dans le même
interpréteur pytest partagé -- la première tentative de ce test (dans le même
processus que le reste de la suite) a fait échouer cinq tests sans rapport dans
tests/test_visual_brand_v2.py en court-circuitant leur propre install(). D'où ce
script séparé : un seul vrai boot, jetable, dont l'interpréteur est détruit à la fin
(os._exit, pas de nettoyage asyncio qui pourrait traîner sur des tâches de fond
posées par d'autres cogs).

Imprime un objet JSON unique sur stdout ; n'importe quelle exception y apparaît
sous la clé "error" plutôt que de faire planter le sous-processus silencieusement.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DISCORD_TOKEN", "x")
os.environ["DATABASE_PATH"] = ":memory:"

import discord  # noqa: E402
from unittest.mock import AsyncMock, Mock  # noqa: E402

import railway_boot as boot  # noqa: E402


class _FakeRole:
    def __init__(self, rid=1, position=1, name="Role"):
        self.id, self.position, self.name = rid, position, name

    def is_default(self):
        return False


class _FakeMe:
    def __init__(self):
        self.guild_permissions = discord.Permissions(manage_roles=True)
        self.top_role = _FakeRole(position=99, name="SentriX")


class _FakeGuild:
    def __init__(self, gid):
        self.id = gid
        self.name = "Test"
        self.default_role = _FakeRole(rid=gid, position=0, name="@everyone")
        self.roles = []
        self.channels = []
        self.owner_id = 1
        self.me = _FakeMe()

    def get_member(self, uid):
        return None

    def get_role(self, rid):
        return None

    def get_channel(self, cid):
        return None


async def _run() -> dict:
    bot_instance = boot.bot_main.BotAllInOne()
    await bot_instance.db.connect()
    for ext in boot.bot_main.EXTENSIONS:
        await bot_instance.load_extension(ext)

    from cogs.setup_control_center import SetupView
    from cogs.setup_polish_v70 import V70PageSelect

    result: dict = {}

    for subpage, guild_id in (("rules", 1001), ("panel", 1002)):
        guild = _FakeGuild(guild_id)
        view = SetupView(bot_instance, guild, author_id=1)
        view.category = "roles"
        view._v3_subpage = subpage
        embed = await view.build_embed()
        result[f"{subpage}_title"] = embed.title
        result[f"{subpage}_fields"] = sorted(field.name.casefold() for field in embed.fields)

    select_guild = _FakeGuild(1003)
    select_view = SetupView(bot_instance, select_guild, author_id=1)
    select_view.category = None
    select_view.refresh = AsyncMock()
    select = V70PageSelect(select_view)
    result["select_options"] = [option.value for option in select.options]

    select._values = ["roles_rules"]
    interaction = Mock(spec=discord.Interaction)
    interaction.user = Mock(id=1)
    await select.callback(interaction)
    result["select_refresh_called"] = select_view.refresh.await_count == 1
    result["after_click_category"] = select_view.category
    result["after_click_subpage"] = getattr(select_view, "_v3_subpage", None)

    return result


def main() -> None:
    try:
        output = asyncio.run(_run())
    except BaseException as exc:  # noqa: BLE001 - remonte tout à l'appelant via JSON
        import traceback

        output = {"error": f"{exc!r}", "traceback": traceback.format_exc()}
    print(json.dumps(output))
    sys.stdout.flush()
    os._exit(0)


if __name__ == "__main__":
    main()
