import asyncio
from types import SimpleNamespace

from cogs.generated_logs_sync import _explicitly_disabled
from cogs.setup_v2_completion import PaginatedNotificationSelect


def test_notification_selector_paginates_more_than_discord_limit():
    owner = SimpleNamespace(notification_page=0, selected_notification=None)
    rows = [
        {"id": index, "platform": "TikTok", "source_url": f"https://tiktok.com/@source{index}"}
        for index in range(1, 51)
    ]
    select = PaginatedNotificationSelect(owner, rows)
    values = [option.value for option in select.options]
    assert len(select.options) == 25
    assert "__prev__" in values
    assert "__next__" in values
    assert values[0] == "1"
    assert values[22] == "23"


def test_notification_selector_second_page_is_independent():
    owner = SimpleNamespace(notification_page=1, selected_notification=None)
    rows = [
        {"id": index, "platform": "YouTube", "source_url": f"https://youtube.com/@source{index}"}
        for index in range(1, 51)
    ]
    select = PaginatedNotificationSelect(owner, rows)
    values = [option.value for option in select.options]
    assert values[0] == "24"
    assert values[22] == "46"


def test_generated_log_sync_preserves_configured_disabled_route():
    class Db:
        async def fetchone(self, _query, _params):
            return {"enabled": 0, "channel_id": 123456789}

    bot = SimpleNamespace(db=Db())
    assert asyncio.run(_explicitly_disabled(bot, 1, "messages")) is True


def test_generated_log_sync_can_recover_never_configured_route():
    class Db:
        async def fetchone(self, _query, _params):
            return {"enabled": 0, "channel_id": None}

    bot = SimpleNamespace(db=Db())
    assert asyncio.run(_explicitly_disabled(bot, 1, "messages")) is False
