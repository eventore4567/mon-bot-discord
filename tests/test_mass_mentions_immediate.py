import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from test_automod_cross_channel_spam_v125 import _cog, _member, _message
from cogs import automod
from utils import sentrix_panels as panels


@pytest.mark.asyncio
async def test_everyone_is_detected_before_content_filters():
    # 07/11/2026 : @everyone d'un membre suit avertissement, avertissement, mute 1 h
    # (si la règle Discord n'a pas pu le bloquer avant l'envoi).
    cog = _cog(conf={"antimention": 1})
    message = _message(_member(), 1, "@everyone")
    message.mention_everyone = True
    cog._delete_and_warn = AsyncMock()
    cog._sanction_everyone = AsyncMock(return_value="warn")
    await cog.on_message(message)
    cog._delete_and_warn.assert_not_awaited()
    message.delete.assert_awaited()
    cog._sanction_everyone.assert_awaited_once_with(message.guild, message.author, message.channel)


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
async def test_everyone_two_warnings_then_one_hour_mute():
    # 07/11/2026 : « un mute de 5 min c'est trop peu ; d'abord 2 avertissements ».
    cog = _cog(conf={"antimention": 1})
    member = _member()
    with patch.object(automod.moderation_service, "warn", AsyncMock()) as warn, \
         patch.object(panels, "texte_court", AsyncMock()), \
         patch.object(cog, "_mp_sanction_automod", AsyncMock()):
        resultats = [await cog._sanction_everyone(member.guild, member, None) for _ in range(3)]
    assert resultats == ["warn", "warn", "mute"]
    assert warn.await_count == 2
    member.timeout.assert_awaited_once()
