"""Abonnements Premium officiels : pas de paiement ou verrouillage sans SKU."""
from types import SimpleNamespace

import pytest

from utils import premium


class FakeBot:
    def __init__(self, entitlements):
        self.values = entitlements
        self.reads = 0

    async def entitlements(self, **kwargs):
        self.reads += 1
        for item in self.values:
            yield item


@pytest.mark.asyncio
async def test_premium_off_without_a_discord_sku(monkeypatch):
    monkeypatch.delenv("SENTRIX_PREMIUM_SKU_ID", raising=False)
    premium.invalider()
    bot = FakeBot([])
    assert not await premium.est_premium(bot, 42)
    assert bot.reads == 0


@pytest.mark.asyncio
async def test_premium_requires_matching_guild_and_sku(monkeypatch):
    monkeypatch.setenv("SENTRIX_PREMIUM_SKU_ID", "1234567890")
    premium.invalider()
    entitlements = [
        SimpleNamespace(guild_id=99, sku_id=1234567890, deleted=False, starts_at=None, ends_at=None),
        SimpleNamespace(guild_id=42, sku_id=1234567890, deleted=False, starts_at=None, ends_at=None),
    ]
    bot = FakeBot(entitlements)
    assert await premium.est_premium(bot, 42)
    assert await premium.est_premium(bot, 42)
    assert bot.reads == 1


@pytest.mark.asyncio
async def test_premium_deleted_entitlement_is_not_active(monkeypatch):
    monkeypatch.setenv("SENTRIX_PREMIUM_SKU_ID", "1234567890")
    premium.invalider()
    bot = FakeBot([SimpleNamespace(guild_id=42, sku_id=1234567890, deleted=True, starts_at=None, ends_at=None)])
    assert not await premium.est_premium(bot, 42)
