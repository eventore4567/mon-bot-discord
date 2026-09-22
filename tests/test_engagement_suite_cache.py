from types import SimpleNamespace

import pytest

from cogs.engagement_suite import EngagementSuite


class FakeDB:
    def __init__(self):
        self.queries = []

    async def execute(self, query: str, params: tuple = ()):
        self.queries.append((" ".join(query.split()), params))


@pytest.mark.asyncio
async def test_engagement_settings_insert_is_cached_per_guild():
    db = FakeDB()
    suite = EngagementSuite(SimpleNamespace(db=db))

    await suite.ensure_settings(123)
    await suite.ensure_settings("123")

    assert len(db.queries) == 1
    assert db.queries[0][1][0] == 123


@pytest.mark.asyncio
async def test_engagement_member_insert_is_cached_per_member():
    db = FakeDB()
    suite = EngagementSuite(SimpleNamespace(db=db))

    await suite._ensure_member(123, 456, joined_at=111)
    await suite._ensure_member("123", "456", joined_at=222)
    await suite._ensure_member(123, 789, joined_at=333)

    assert len(db.queries) == 2
    assert db.queries[0][1][:3] == (123, 456, 111)
    assert db.queries[1][1][:3] == (123, 789, 333)
