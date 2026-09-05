from __future__ import annotations

import asyncio
import inspect
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from cogs.poll_ui import (
    AddAnswersModal,
    PollBuilderView,
    PollSetupModal,
    _answers_error,
    _clean_answers,
    _interaction_notice,
    _poll_error,
)


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

    def test_builder_exposes_question_edit_button(self):
        view = PollBuilderView(object(), author_id=42, question="On joue ?", answers=["Oui", "Non"])
        self.assertEqual(view.edit_question.label, "Modifier question")
        self.assertFalse(view.edit_question.disabled)

    def test_modal_transitions_never_switch_components_v2_back_to_embed(self):
        setup_source = inspect.getsource(PollSetupModal.on_submit)
        add_source = inspect.getsource(AddAnswersModal.on_submit)

        self.assertIn("panels.editer", setup_source)
        self.assertIn("panels.editer", add_source)
        self.assertNotIn("edit_message(embed=", setup_source)
        self.assertNotIn("edit_message(embed=", add_source)


class PollPublishTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def _interaction(channel, guild):
        state = {"done": False}

        async def send_message(*args, **kwargs):
            state["done"] = True
            return None

        async def defer(*args, **kwargs):
            state["done"] = True
            return None

        response = SimpleNamespace(
            is_done=lambda: state["done"],
            send_message=AsyncMock(side_effect=send_message),
            defer=AsyncMock(side_effect=defer),
        )
        return SimpleNamespace(
            channel=channel,
            guild=guild,
            user=SimpleNamespace(id=42),
            response=response,
            followup=SimpleNamespace(send=AsyncMock()),
            edit_original_response=AsyncMock(),
        )

    async def test_publish_is_single_flight_and_acknowledged_before_network_wait(self):
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

        edit_mock = AsyncMock()
        with patch("cogs.poll_ui.panels.editer", new=edit_mock):
            first_task = asyncio.create_task(view.publish.callback(first))
            await asyncio.wait_for(entered.wait(), timeout=1)

            # Le clic est acquitté avant que channel.send ne termine : Discord ne doit
            # plus afficher « Action interrompue » pendant un pic réseau.
            first.response.defer.assert_awaited_once()

            await view.publish.callback(second)
            second.response.send_message.assert_awaited_once()
            self.assertIn("déjà en cours", second.response.send_message.await_args.args[0])

            release.set()
            await asyncio.wait_for(first_task, timeout=1)

        self.assertEqual(channel.send.await_count, 1)
        edit_mock.assert_awaited_once()
        self.assertIs(edit_mock.await_args.args[0], first)
        self.assertTrue(view.is_finished())

    async def test_failed_publish_uses_followup_after_defer_and_releases_guard(self):
        channel = SimpleNamespace(
            mention="#sondages",
            permissions_for=lambda _member: SimpleNamespace(send_messages=True, create_polls=True),
            send=AsyncMock(side_effect=ValueError("Discord rejected poll")),
        )
        guild = SimpleNamespace(me=object())
        interaction = self._interaction(channel, guild)
        view = PollBuilderView(object(), author_id=42, question="On joue ?", answers=["Oui", "Non"])

        await view.publish.callback(interaction)

        interaction.response.defer.assert_awaited_once()
        interaction.response.send_message.assert_not_awaited()
        interaction.followup.send.assert_awaited_once()
        self.assertIn("Vérifiez", interaction.followup.send.await_args.args[0])
        self.assertFalse(view._publish_lock.locked())
        self.assertFalse(view.is_finished())

    async def test_notice_uses_initial_response_before_ack(self):
        channel = SimpleNamespace()
        guild = SimpleNamespace()
        interaction = self._interaction(channel, guild)

        await _interaction_notice(interaction, "Test")

        interaction.response.send_message.assert_awaited_once_with("Test", ephemeral=True)
        interaction.followup.send.assert_not_awaited()

    async def test_notice_uses_followup_after_ack(self):
        channel = SimpleNamespace()
        guild = SimpleNamespace()
        interaction = self._interaction(channel, guild)
        await interaction.response.defer()

        await _interaction_notice(interaction, "Après ACK")

        interaction.response.send_message.assert_not_awaited()
        interaction.followup.send.assert_awaited_once_with("Après ACK", ephemeral=True)


if __name__ == "__main__":
    unittest.main()