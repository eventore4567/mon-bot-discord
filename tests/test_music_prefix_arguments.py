"""+music volume/seek/loop en préfixe : app_commands.Range / app_commands.Choice n'ont
pas de convertisseur préfixe (« Argument invalide » systématique, trouvé par
tools/command_sweep.py). Les annotations doivent rester convertibles des deux côtés."""
from __future__ import annotations

import asyncio

from discord.ext import commands

from cogs.music import Music


def _param(name: str, param: str):
    command = getattr(Music, name)
    return command.clean_params[param]


def test_volume_and_seek_use_prefix_convertible_ranges():
    for name, param, upper in (("music_volume", "niveau", 100), ("music_seek", "secondes", 36000)):
        converter = _param(name, param).converter
        assert isinstance(converter, commands.Range), f"{name}.{param} doit être commands.Range"
        assert converter.annotation is int and converter.min == 0 and converter.max == upper


def test_loop_mode_is_plain_string_with_slash_choices():
    param = _param("music_loop", "mode")
    assert param.converter is str
    app_param = {p.name: p for p in Music.music_loop.app_command.parameters}["mode"]
    assert [c.value for c in app_param.choices] == ["off", "track", "queue"]


def test_loop_aliases_cover_french_and_slash_values():
    aliases = Music._LOOP_ALIASES
    assert aliases["piste"] == "track" and aliases["file"] == "queue" and aliases["off"] == "off"
    assert aliases["track"] == "track" and aliases["queue"] == "queue"
