import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from test_automod_cross_channel_spam_v125 import _cog, _member, _message
from cogs import automod
from utils import sentrix_panels as panels


@pytest.mark.asyncio
async def test_everyone_is_detected_before_content_filters():
    cog = _cog(conf={"antimention": 1})
    message = _message(_member(), 1, "@everyone")
    message.mention_everyone = True
    cog._delete_and_warn = AsyncMock()
    await cog.on_message(message)
    cog._delete_and_warn.assert_awaited_once_with(message, "Mention massive détectée.", "antimention")


@pytest.mark.asyncio
async def test_literal_everyone_without_ping_and_disabled_filter_are_not_punished():
    for enabled, actual in ((1, False), (0, True)):
        cog = _cog(conf={"antimention": enabled})
        message = _message(_member(), 1, "@everyone")
        message.mention_everyone = actual
        cog._delete_and_warn = AsyncMock()
        await cog.on_message(message)
        cog._delete_and_warn.assert_not_awaited()


@pytest.mark.asyncio
async def test_mention_timeout_starts_before_slow_deletion_and_only_once():
    cog = _cog(conf={"antimention": 1})
    member = _member()
    first = _message(member, 1, "@everyone")
    first.mention_everyone = True
    deleting = asyncio.Event()
    release = asyncio.Event()
    async def slow_delete():
        deleting.set()
        await release.wait()
    first.delete = AsyncMock(side_effect=slow_delete)
    with patch.object(panels, "texte_court", AsyncMock()), patch.object(automod, "INCIDENT_LOG_DELAY_SECONDS", 0.01):
        task = asyncio.create_task(cog.on_message(first))
        try:
            await asyncio.wait_for(deleting.wait(), 2)
            member.timeout.assert_awaited_once()
            release.set()
            await task
            second = _message(member, 2, "@everyone")
            second.mention_everyone = True
            await cog.on_message(second)
            member.timeout.assert_awaited_once()
        finally:
            release.set()
            await task
        await asyncio.sleep(0.05)
