"""Anti-lien SentriX : vrai retrait du message et avis court sans repost.

Les exceptions staff sont protégées dans test_security_message_bypass_regression.py ;
ici on vérifie le parcours d'enforcement visible pour le membre.
"""
import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from cogs import automod
from utils.automod_message_claims import AutomodMessageClaims


def _scenario():
    cog = object.__new__(automod.AutoMod)
    cog.bot = SimpleNamespace(db=SimpleNamespace(log_automod_action=AsyncMock()))
    cog.incidents = {}
    cog._local_block_last_seen = {}
    cog._sanctioned_messages = AutomodMessageClaims(ttl_seconds=120, max_entries=256)
    cog._mark_xp_skip = Mock()
    cog._record_incident_trace = AsyncMock()
    cog._flush_incident_log = AsyncMock()
    cog._repost_censored = AsyncMock(return_value=True)
    channel = SimpleNamespace(id=33, send=AsyncMock())
    author = SimpleNamespace(id=22, mention="<@22>")
    message = SimpleNamespace(
        id=123, guild=SimpleNamespace(id=11),
        channel=channel, author=author,
        content="https://exemple.fr/un-lien",
        attachments=[], delete=AsyncMock(),
    )
    return cog, message


def test_link_filters_delete_then_send_short_notice_without_reposting():
    async def run():
        for filter_name in sorted(automod.LINK_NOTICE_FILTERS):
            cog, message = _scenario()
            await cog._delete_and_warn(
                message, "Lien interdit", filter_name,
                censored_content="[lien supprimé]",
                allow_escalation=False,
            )
            message.delete.assert_awaited_once()
            cog._repost_censored.assert_not_awaited()
            message.channel.send.assert_awaited_once()
            args, kwargs = message.channel.send.await_args
            assert "Les liens sont interdits dans ce salon." in args[0]
            assert "<@22>" in args[0]
            assert "https://" not in args[0]
            assert kwargs["delete_after"] == 8
            assert kwargs["allowed_mentions"].everyone is False
            assert kwargs["allowed_mentions"].users is False
            assert "view" not in kwargs
            await asyncio.sleep(0)

    asyncio.run(run())


def test_scam_does_not_repost_a_blocked_url():
    async def run():
        cog, message = _scenario()
        cog._content_notice_view = Mock(return_value=object())
        await cog._delete_and_warn(
            message, "Hameçonnage", "antiscam",
            censored_content="https://[censuré]",
            allow_escalation=False,
        )
        message.delete.assert_awaited_once()
        cog._repost_censored.assert_not_awaited()
        await asyncio.sleep(0)

    asyncio.run(run())


def test_duplicate_detection_does_not_send_repeated_warnings():
    async def run():
        cog, message = _scenario()
        for _ in range(2):
            await cog._delete_and_warn(
                message, "Lien interdit", "antilink", allow_escalation=False,
            )
        message.delete.assert_awaited_once()
        message.channel.send.assert_awaited_once()
        await asyncio.sleep(0)

    asyncio.run(run())


def test_admin_guard_prevents_link_deletion(monkeypatch):
    async def run():
        cog, message = _scenario()
        monkeypatch.setattr(automod, "_is_discord_administrator", lambda member: True)
        await cog._delete_and_warn(
            message, "Lien interdit", "antilink", allow_escalation=False,
        )
        message.delete.assert_not_awaited()
        message.channel.send.assert_not_awaited()

    asyncio.run(run())
