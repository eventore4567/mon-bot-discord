"""Le V17 ne doit pas planter quand le listener de mention obsolete est supprimé."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from cogs import common_command_names
from cogs import v17_user_facing_hotfix as v17


def test_install_v17_supporte_absence_du_listener(monkeypatch):
    monkeypatch.setattr(v17, "_MENTION_PATCHED", False)
    monkeypatch.delattr(common_command_names, "_mention_help", raising=False)
    v17._patch_duplicate_mention()
    assert v17._MENTION_PATCHED


def test_ancien_listener_reste_bloque_si_ia_active(monkeypatch):
    calls = []

    async def original(bot, message):
        calls.append(message)
        return "ancienne aide"

    monkeypatch.setattr(v17, "_MENTION_PATCHED", False)
    monkeypatch.setattr(common_command_names, "_mention_help", original, raising=False)
    v17._patch_duplicate_mention()
    patched = common_command_names._mention_help
    assert asyncio.run(patched(SimpleNamespace(get_cog=lambda _: object()), object())) is None
    assert calls == []
    assert asyncio.run(patched(SimpleNamespace(get_cog=lambda _: None), "message")) == "ancienne aide"
    assert calls == ["message"]
