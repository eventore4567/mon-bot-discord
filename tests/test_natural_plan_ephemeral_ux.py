"""Actions naturelles : aucun panneau expiré, doublon ni bouton fantôme."""
from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import discord
import pytest

from cogs.ai import Ai, _NaturalActionConfirmView, _NaturalPlanConfirmView
from cogs.moderation import Moderation, _hierarchy_refusal_panel
from utils import sentrix_panels as panels


def _source():
    return SimpleNamespace(
        author=SimpleNamespace(id=123456),
        reply=AsyncMock(),
    )


def _interaction():
    return SimpleNamespace(
        user=SimpleNamespace(id=123456),
        response=SimpleNamespace(
            edit_message=AsyncMock(),
            send_message=AsyncMock(),
        ),
    )


def _button(view, label):
    return next(button for button in view.children if getattr(button, "label", None) == label)


def _plan_view(*, steps=1):
    cog = SimpleNamespace(_execute_action_plan=AsyncMock())
    view = _NaturalPlanConfirmView(
        cog,
        message=_source(),
        actions=tuple(f"action-{idx}" for idx in range(steps)),
        prefix="+",
        author_id=123456,
    )
    view.message = SimpleNamespace(delete=AsyncMock(), edit=AsyncMock())
    return view, cog


@pytest.mark.asyncio
async def test_cancel_plan_edits_existing_message_then_deletes_it():
    view, cog = _plan_view()
    interaction = _interaction()

    await _button(view, "Annuler").callback(interaction)

    interaction.response.edit_message.assert_awaited_once()
    kwargs = interaction.response.edit_message.await_args.kwargs
    assert kwargs["content"] is None
    assert kwargs["view"] is None
    assert kwargs["embed"].title == "Plan annulé"
    view.message.delete.assert_awaited_once_with(delay=5)
    view.message.edit.assert_not_awaited()
    cog._execute_action_plan.assert_not_awaited()


@pytest.mark.asyncio
async def test_confirm_plan_uses_single_progress_message_then_deletes_it():
    view, cog = _plan_view(steps=2)
    interaction = _interaction()

    await _button(view, "Exécuter le plan").callback(interaction)

    kwargs = interaction.response.edit_message.await_args.kwargs
    assert kwargs["content"] is None
    assert kwargs["view"] is None
    assert kwargs["embed"].title == "Plan en cours"
    cog._execute_action_plan.assert_awaited_once_with(
        view.source_message,
        view.actions,
        "+",
        status_message=view.message,
    )
    view.message.delete.assert_awaited_once_with(delay=4)
    view.message.edit.assert_not_awaited()


@pytest.mark.asyncio
async def test_confirm_plan_even_if_motor_fails_cleanup_is_guaranteed():
    view, cog = _plan_view()
    cog._execute_action_plan.side_effect = RuntimeError("moteur indisponible")
    with pytest.raises(RuntimeError):
        await _button(view, "Exécuter le plan").callback(_interaction())
    view.message.delete.assert_awaited_once_with(delay=4)


@pytest.mark.asyncio
async def test_plan_timeout_removes_obsolete_buttons_and_card():
    view, cog = _plan_view()

    await view.on_timeout()

    view.message.delete.assert_awaited_once_with(delay=0)
    view.message.edit.assert_not_awaited()
    cog._execute_action_plan.assert_not_awaited()


@pytest.mark.asyncio
async def test_plan_executor_never_writes_unhelpful_plan_traite_summary():
    message = _source()
    status = SimpleNamespace(edit=AsyncMock(), delete=AsyncMock())
    cog = SimpleNamespace(_handle_parsed_action=AsyncMock(return_value=True))
    actions = (SimpleNamespace(intent="moderation.ban"),)
    await Ai._execute_action_plan(cog, message, actions, "+", status_message=status)

    cog._handle_parsed_action.assert_awaited_once()
    status.edit.assert_not_awaited()
    message.reply.assert_not_awaited()


@pytest.mark.asyncio
async def test_plan_executor_keeps_real_failure_reason_not_a_false_success():
    message = _source()
    cog = SimpleNamespace(_handle_parsed_action=AsyncMock(return_value=False))
    actions = (SimpleNamespace(intent="moderation.ban"),)
    await Ai._execute_action_plan(cog, message, actions, "+")

    message.reply.assert_awaited_once()
    assert "Plan interrompu" in message.reply.await_args.args[0]


@pytest.mark.asyncio
async def test_natural_action_cancel_deletes_prompt_without_running_anything():
    cog = SimpleNamespace(_invoke_command_line=AsyncMock())
    view = _NaturalActionConfirmView(
        cog,
        message=_source(),
        command_line="+clear 100",
        author_id=123456,
    )
    view.message = SimpleNamespace(delete=AsyncMock(), edit=AsyncMock())

    await _button(view, "Annuler").callback(_interaction())

    view.message.delete.assert_awaited_once_with(delay=5)
    cog._invoke_command_line.assert_not_awaited()


@pytest.mark.asyncio
async def test_natural_action_confirm_deletes_prompt_and_uses_real_command_path():
    cog = SimpleNamespace(_invoke_command_line=AsyncMock(return_value=True))
    view = _NaturalActionConfirmView(
        cog,
        message=_source(),
        command_line="+clear 100",
        author_id=123456,
    )
    view.message = SimpleNamespace(delete=AsyncMock(), edit=AsyncMock())

    await _button(view, "Confirmer").callback(_interaction())

    cog._invoke_command_line.assert_awaited_once_with(view.source_message, "+clear 100")
    view.message.delete.assert_awaited_once_with(delay=4)


def test_actor_hierarchy_refusal_is_explained_in_structured_panel():
    content = (
        "Vous ne pouvez pas sanctionner un membre ayant un rôle "
        "supérieur ou égal au vôtre."
    )
    panel = _hierarchy_refusal_panel(content)
    assert isinstance(panel, panels.Panneau)
    rendered = panels.texte_complet(panel)
    assert "Action impossible" in rendered
    assert "Comment corriger" in rendered
    assert "responsable" in rendered.casefold()
    assert "placez le rôle SentriX" not in rendered


@pytest.mark.asyncio
async def test_actor_hierarchy_refusal_uses_panel_not_bare_text():
    content = (
        "Vous ne pouvez pas sanctionner un membre ayant un rôle "
        "supérieur ou égal au vôtre."
    )
    ctx = SimpleNamespace()
    with patch.object(panels, "envoyer", AsyncMock()) as send, patch.object(
        panels, "texte_court", AsyncMock()
    ) as bare:
        await Moderation._reply(object(), ctx, content, ephemere=True)

    send.assert_awaited_once()
    assert send.await_args.kwargs["ephemere"] is True
    bare.assert_not_awaited()
