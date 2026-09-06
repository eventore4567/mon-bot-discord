from __future__ import annotations

import inspect

import sentrix_v98_ticket_reopen as reopen


def test_reopen_alias_delegates_to_canonical_ticket_reopen():
    source = inspect.getsource(reopen.install)
    assert 'bot.get_command("reopenticket")' in source
    assert 'bot.get_command("ticket-reopen")' in source
    assert "canonical.callback(canonical.cog, ctx)" in source
    assert "reopen_minutes" not in source


def test_reopen_patch_is_installed_after_v98_prepare():
    source = inspect.getsource(reopen.install_global)
    assert "mapping = await current(bot)" in source
    assert "install(bot)" in source
    assert "v95.prepare_bot = prepare_with_reopen" in source
