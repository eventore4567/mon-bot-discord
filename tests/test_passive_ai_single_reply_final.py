"""Contrats de l'autorité finale des réponses IA passives."""
from __future__ import annotations

from types import SimpleNamespace

from cogs import passive_ai_single_reply_final as guard


def _bot(*, user=None):
    return SimpleNamespace(user=user, prefix_cache={})


def _message(content="sentrix yo", *, guild=True, author_bot=False, mentions=None):
    author = SimpleNamespace(bot=author_bot)
    return SimpleNamespace(
        id=123456789012345678,
        content=content,
        guild=SimpleNamespace(id=42) if guild else None,
        author=author,
        mentions=list(mentions or []),
    )


def test_primary_service_identity(monkeypatch):
    monkeypatch.setenv("RAILWAY_SERVICE_ID", guard.PRIMARY_RAILWAY_SERVICE_ID)
    monkeypatch.setenv("RAILWAY_SERVICE_NAME", "mon-bot-discord")
    assert guard._is_primary_service() is True


def test_secondary_service_identity(monkeypatch):
    monkeypatch.setenv("RAILWAY_SERVICE_ID", "237537af-2be4-40fa-8527-301358d533a9")
    monkeypatch.setenv("RAILWAY_SERVICE_NAME", "[+] Bot'Odboug |")
    assert guard._is_primary_service() is False


def test_identity_detects_all_four_ai_responder_sources():
    expected = {
        "cogs.ai": ("on_message", "primary"),
        "cogs.ai_api_hotfix": ("fallback_on_message", "api_fallback"),
        "cogs.ai_reply_recovery": ("backup_on_message", "recovery"),
        "cogs.bot_experience_v5": ("natural_continuation", "experience"),
    }
    for module, (name, kind) in expected.items():
        async def callback(message):
            return message
        callback.__module__ = module
        callback.__name__ = name
        detected, _, original = guard._identity(callback)
        assert detected == kind
        assert original is callback


def test_unrelated_on_message_listener_is_never_targeted():
    async def callback(message):
        return message
    callback.__module__ = "cogs.logs"
    callback.__name__ = "on_message"
    detected, _, _ = guard._identity(callback)
    assert detected is None


def test_primary_coordinates_only_explicit_guild_trigger():
    bot = _bot()
    assert guard._should_coordinate(bot, "primary", _message("sentrix yo", guild=True)) is True
    assert guard._should_coordinate(bot, "primary", _message("bonjour", guild=True)) is False
    assert guard._should_coordinate(bot, "primary", _message("sentrix yo", guild=False)) is False


def test_fallbacks_coordinate_explicit_trigger_in_dm_too():
    bot = _bot()
    dm = _message("sentrix yo", guild=False)
    assert guard._should_coordinate(bot, "api_fallback", dm) is True
    assert guard._should_coordinate(bot, "recovery", dm) is True


def test_experience_coordinates_dm_but_not_guild_wake_word():
    bot = _bot()
    assert guard._should_coordinate(bot, "experience", _message("yo", guild=False)) is True
    assert guard._should_coordinate(bot, "experience", _message("sentrix yo", guild=True)) is False


def test_prefixed_commands_are_never_claimed_as_passive_ai(monkeypatch):
    monkeypatch.setattr(guard.config, "DEFAULT_PREFIX", "+")
    bot = _bot()
    command = _message("+help", guild=True)
    assert guard._should_coordinate(bot, "primary", command) is False
    assert guard._should_coordinate(bot, "recovery", command) is False
