from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from cogs.poll_ui import PollBuilderView, _answers_error, _clean_answers, _poll_error


class PollValidationTests(unittest.TestCase):
    def test_clean_answers_removes_empty_values(self):
        self.assertEqual(_clean_answers([" Oui ", "", "   ", "Non"]), ["Oui", "Non"])

    def test_answers_require_unique_two_to_ten_choices(self):
        self.assertIsNotNone(_answers_error(["Oui"]))
        self.assertIsNotNone(_answers_error(["Oui", "oui"]))
        self.assertIsNone(_answers_error(["Oui", "Non"]))
        self.assertIsNone(_answers_error([str(i) for i in range(10)]))
        self.assertIsNotNone(_answers_error([str(i) for i in range(11)]))

    def test_poll_validation_covers_question_duration_and_answers(self):
        self.assertIn("question", _poll_error("", ["Oui", "Non"], 24).lower())
        self.assertIn("300", _poll_error("x" * 301, ["Oui", "Non"], 24))
        self.assertIn("7 jours", _poll_error("Question", ["Oui", "Non"], 169))
        self.assertIsNone(_poll_error("Question", ["Oui", "Non"], 24))


class PollPublishTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def _interaction(channel, guild):
        return SimpleNamespace(
            channel=channel,
            guild=guild,
            user=SimpleNamespace(id=42),
            response=SimpleNamespace(send_message=AsyncMock()),
        )

    async def test_publish_is_single_flight(self):
        entered = asyncio.Event()
        release = asyncio.Event()

        async def send_poll(**kwargs):
            self.assertIn("poll", kwargs)
            entered.set()
            await release.wait()
            return SimpleNamespace(jump_url="https://discord.com/channels/1/2/3")

        channel = SimpleNamespace(
            mention="#sondages",
            permissions_for=lambda _member: SimpleNamespace(send_messages=True, create_polls=True),
            send=AsyncMock(side_effect=send_poll),
        )
        guild = SimpleNamespace(me=object())
        first = self._interaction(channel, guild)
        second = self._interaction(channel, guild)
        view = PollBuilderView(object(), author_id=42, question="On joue ?", answers=["Oui", "Non"])

        with patch("cogs.poll_ui.panels.editer", new=AsyncMock()):
            first_task = asyncio.create_task(view.publish.callback(first))
            await asyncio.wait_for(entered.wait(), timeout=1)
            await view.publish.callback(second)
            second.response.send_message.assert_awaited_once()
            self.assertIn("déjà en cours", second.response.send_message.await_args.args[0])
            release.set()
            await asyncio.wait_for(first_task, timeout=1)

        self.assertEqual(channel.send.await_count, 1)
        self.assertTrue(view.is_finished())

    async def test_failed_publish_releases_single_flight_guard(self):
        channel = SimpleNamespace(
            mention="#sondages",
            permissions_for=lambda _member: SimpleNamespace(send_messages=True, create_polls=True),
            send=AsyncMock(side_effect=ValueError("Discord rejected poll")),
        )
        guild = SimpleNamespace(me=object())
        interaction = self._interaction(channel, guild)
        view = PollBuilderView(object(), author_id=42, question="On joue ?", answers=["Oui", "Non"])

        await view.publish.callback(interaction)

        interaction.response.send_message.assert_awaited_once()
        self.assertFalse(view._publish_lock.locked())
        self.assertFalse(view.is_finished())


if __name__ == "__main__":
    unittest.main()
