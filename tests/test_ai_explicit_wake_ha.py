from __future__ import annotations

import asyncio
import inspect
from types import MethodType, SimpleNamespace


def test_ai_reliability_never_uses_fixed_railway_primary_for_passive_reply():
    """Le standby promu doit répondre s'il est le client réellement connecté à Discord."""
    from cogs import ai_reliability

    source = inspect.getsource(ai_reliability._install_single_passive_reply)
    assert "_is_primary_process" not in source
    assert "message_id" in source
    assert "_PASSIVE_REPLY_RECENT" in source


def test_sentrix_yo_reaches_ai_reply_exactly_once():
    from cogs.ai import Ai

    calls: list[tuple[str, object]] = []

    class Typing:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    channel = SimpleNamespace(id=20, typing=lambda: Typing())
    author = SimpleNamespace(id=42, bot=False)
    guild = SimpleNamespace(id=1)
    bot = SimpleNamespace(
        user=SimpleNamespace(id=999),
        prefix_cache={1: "+"},
    )
    message = SimpleNamespace(
        id=123456,
        content="sentrix yo",
        author=author,
        guild=guild,
        channel=channel,
        mentions=[],
        attachments=[],
    )

    # On teste le listener réel sans démarrer la tâche périodique du Cog.
    cog = object.__new__(Ai)
    cog.bot = bot
    cog.histories = {}
    cog._last_used = {}
    cog._minute_bucket = {}

    async def no_natural_command(self, incoming, question, prefix):
        assert incoming is message
        assert question == "yo"
        assert prefix == "+"
        return False

    async def capture_reply(self, destination, incoming_author, question, *, reply_to=None):
        assert destination is channel
        assert incoming_author is author
        calls.append((question, reply_to))

    cog._invoke_natural_command = MethodType(no_natural_command, cog)
    cog.send_sentrix_reply = MethodType(capture_reply, cog)

    asyncio.run(cog.on_message(message))

    assert calls == [("yo", message)]


def test_prefix_command_is_not_stolen_by_passive_ai_listener():
    from cogs.ai import Ai

    bot = SimpleNamespace(user=SimpleNamespace(id=999), prefix_cache={1: "+"})
    message = SimpleNamespace(
        id=123457,
        content="+sentrix yo",
        author=SimpleNamespace(id=42, bot=False),
        guild=SimpleNamespace(id=1),
        channel=SimpleNamespace(id=20),
        mentions=[],
        attachments=[],
    )
    cog = object.__new__(Ai)
    cog.bot = bot
    cog.histories = {}
    cog._last_used = {}
    cog._minute_bucket = {}

    async def forbidden(*args, **kwargs):
        raise AssertionError("Le listener passif ne doit pas consommer une commande +.")

    cog.send_sentrix_reply = forbidden
    asyncio.run(cog.on_message(message))
