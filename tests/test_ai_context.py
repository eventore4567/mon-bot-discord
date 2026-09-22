from types import SimpleNamespace

import pytest

from services.ai_context import build_system_instructions


class FakeDB:
    def __init__(self):
        self.calls = 0

    async def get_primary_bot_creator(self):
        self.calls += 1
        return {
            "display_name": "Jayden",
            "username": "jayden",
            "user_id": 42,
        }


@pytest.mark.asyncio
async def test_ai_system_context_mentions_creator_and_uses_cache():
    db = FakeDB()
    bot = SimpleNamespace(db=db)

    first, cache = await build_system_instructions(bot, user_id=42, author_name="Jay", creator_cache=None)
    second, same_cache = await build_system_instructions(bot, user_id=99, creator_cache=cache)

    assert "Jayden" in first
    assert "créateur authentifié" in first
    assert "Jay" in first
    assert "Jayden" in second
    assert "créateur authentifié" not in second
    assert same_cache is cache
    assert db.calls == 1
