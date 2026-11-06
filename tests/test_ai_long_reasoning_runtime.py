"""Régressions du parcours IA pour les questions longues."""

import inspect

from cogs import ai, ai_reliability, community_v34


def test_text_timeout_is_long_but_bounded():
    assert 30.0 <= ai_reliability.TEXT_TIMEOUT_SECONDS <= 180.0
    assert ai_reliability.TEXT_TIMEOUT_SECONDS >= 120.0


def test_fast_runtime_never_reduces_the_shared_timeout():
    source = inspect.getsource(community_v34._install_fast_ai)
    assert "REQUEST_TIMEOUT_SECONDS = 12.0" not in source
    assert "ai_service._TEXT_CLIENT = None" in source


def test_reliability_install_never_reduces_an_existing_timeout():
    source = inspect.getsource(ai_reliability.install)
    assert "max(" in source
    assert "TEXT_TIMEOUT_SECONDS" in source


def test_long_ai_command_updates_one_progress_message():
    source = inspect.getsource(ai.Ai._handle_ai_command)
    assert "progress_task = asyncio.create_task(update_progress())" in source
    assert "thinking_msg.edit(content=text)" in source
    assert "edit_original_response(content=text)" in source
    assert "progress_task.cancel()" in source


def test_sentrix_slash_command_defers_and_updates_the_same_response():
    source = inspect.getsource(ai.Ai.sentrix.callback)
    assert "await ctx.defer()" in source
    assert "edit_original_response(content=text)" in source
    assert "progress_task.cancel()" in source
