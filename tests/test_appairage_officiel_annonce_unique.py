"""Le repli par marqueurs tourne toutes les trois minutes : une seule annonce INFO."""
import asyncio
import logging
import os
from types import SimpleNamespace

os.environ.setdefault("DISCORD_TOKEN", "test-token")

from cogs import official_server_binding_fix as module


class _Runtime:
    def __init__(self, guild):
        self.bot = SimpleNamespace(get_guild=lambda _id: guild)

    async def _set_setting(self, *_args):
        return None


def test_appairage_annonce_une_seule_fois(monkeypatch, caplog):
    guild = SimpleNamespace(id=1540892096448438322, name="Sentrix bot +suport")
    runtime = _Runtime(guild)

    async def pas_dinvitation(_runtime):
        return None

    async def persister(_runtime, _guild):
        return None

    monkeypatch.setattr(module, "_resolve_invite_guild_id", pas_dinvitation)
    monkeypatch.setattr(module, "_unique_marker_guild", lambda _runtime: guild)
    monkeypatch.setattr(module, "_persist_binding", persister)
    monkeypatch.setattr(module, "_DERNIER_APPAIRAGE_ANNONCE", None)

    with caplog.at_level(logging.DEBUG, logger=module.logger.name):
        for _ in range(3):
            assert asyncio.run(module.official_guild_id_fixed(runtime)) == guild.id

    niveaux = [r.levelno for r in caplog.records if "appairé via marqueurs" in r.getMessage()]
    assert niveaux == [logging.INFO, logging.DEBUG, logging.DEBUG]
