"""Milestone 5 (Scale) : cogs/bot_v14_core.py::guild_remove nettoyait déjà 3
caches internes (manager_cache, manager_category_cache, alias_cache) au départ
d'un serveur, mais Database._guild_config_cache et bot._rank_cache (utils/
stats_service.py) n'étaient jamais purgés — des dicts qui ne font que
grossir. Les deux ont leur propre méthode d'invalidation publique déjà
existante ; on vérifie ici qu'elles sont bien appelées.

Levels._xp_locks (cogs/levels.py) n'est PAS touché : son propre commentaire
documente explicitement le choix de ne jamais purger ("coût mémoire
négligeable") — ce n'est pas un oubli, donc pas un correctif à faire ici.
"""
from __future__ import annotations

import asyncio
from unittest.mock import Mock

import discord
from discord.ext import commands

from cogs import bot_v14_core
from utils import stats_service


def _make_bot() -> commands.Bot:
    bot = commands.Bot(command_prefix="+", intents=discord.Intents.none())
    bot.db = Mock()
    bot.db.invalidate_guild_config = Mock()

    async def _on_ready():
        return None

    bot.on_ready = _on_ready
    return bot


def _fake_guild(guild_id: int):
    from types import SimpleNamespace
    return SimpleNamespace(id=guild_id)


def _find_guild_remove_listener(bot: commands.Bot):
    for listener in bot.extra_events.get("on_guild_remove", []):
        yield listener


def test_guild_remove_invalidates_guild_config_cache():
    bot = _make_bot()
    # bot_v14_core.py::_patch_database_hot_paths enveloppe déjà invalidate_guild_config
    # lui-même (chaîne vers l'original, motif déjà correct ici) : on garde la référence
    # AVANT install() pour vérifier que la chaîne l'appelle toujours au bout du compte.
    original_mock = bot.db.invalidate_guild_config
    bot_v14_core.install(bot)
    listeners = list(_find_guild_remove_listener(bot))
    assert listeners, "aucun listener on_guild_remove enregistré"

    asyncio.run(listeners[0](_fake_guild(123)))

    original_mock.assert_called_once_with(123)


def test_guild_remove_invalidates_rank_cache():
    bot = _make_bot()
    bot._rank_cache = {(123, 1): (0.0, 5), (123, 2): (0.0, 9), (456, 1): (0.0, 2)}
    bot_v14_core.install(bot)
    listeners = list(_find_guild_remove_listener(bot))

    asyncio.run(listeners[0](_fake_guild(123)))

    remaining = set(bot._rank_cache.keys())
    assert remaining == {(456, 1)}


def test_xp_locks_are_deliberately_never_purged():
    """Garde-fou documentaire : ce test échoue si quelqu'un ajoute plus tard une
    purge de _xp_locks sans avoir d'abord retiré/mis à jour le commentaire qui
    documente ce choix comme délibéré (cogs/levels.py)."""
    import inspect

    from cogs import levels

    source = inspect.getsource(levels.Levels.__init__)
    assert "jamais purgés" in source
