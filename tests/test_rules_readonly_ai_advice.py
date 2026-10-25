"""Conseils d'IA optionnels : le modèle ne modifie jamais les accès Discord."""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from utils.verification_access_intelligence import AccessPlan, ai_access_review_context
from cogs import verify_setup_interactive_v78 as rules
from utils import ai_service


def test_ai_context_contains_only_bounded_channel_names_and_no_discord_identifiers():
    category = SimpleNamespace(name="SentriX — Logs")
    logs = SimpleNamespace(
        id=123456, category=category,
        name="logs <@&678901> @everyone https://private.example/path",
    )
    plan = AccessPlan(gate=[], staff_channels=[], secure_sensitive=[],
                      log_destinations=[logs])
    data = json.loads(ai_access_review_context(plan))
    serialized = json.dumps(data, ensure_ascii=False)
    assert "SentriX — Logs" in serialized
    assert "123456" not in serialized
    assert "678901" not in serialized
    assert "https://private" not in serialized
    assert "@everyone" not in serialized
    assert "[mention]" in serialized
    assert "[url]" in serialized


def test_ai_context_never_contains_overwrite_objects_or_members():
    plan = AccessPlan()
    plan.gate.append(SimpleNamespace(
        id=44, name="general", category=SimpleNamespace(name="Membres"),
        overwrites={"secret": "do not leak"},
    ))
    prompt = ai_access_review_context(plan)
    assert "general" in prompt
    assert "secret" not in prompt
    assert "do not leak" not in prompt
    assert '"verrouillage_membres": 1' in prompt


def _interaction():
    reply = SimpleNamespace(send_message=AsyncMock())
    followup = SimpleNamespace(send=AsyncMock())
    return SimpleNamespace(
        response=reply, followup=followup,
        guild_id=5, user=SimpleNamespace(id=11),
    )


@pytest.mark.asyncio
async def test_ia_disabled_does_not_call_provider_or_change_permissions(monkeypatch):
    monkeypatch.setattr(ai_service, "get_settings", AsyncMock(return_value={"enabled": False}))
    model = AsyncMock()
    monkeypatch.setattr(ai_service, "generate", model)
    monkeypatch.setattr(rules, "preview_published_channels", AsyncMock())
    bot = SimpleNamespace()
    guild = SimpleNamespace(id=5, owner_id=11)
    view = rules.RulesLockConfirmView(bot, guild, 11, ())
    button = next(x for x in view.children if getattr(x, "label", "") == "Avis IA (lecture seule)")
    inter = _interaction()
    await button.callback(inter)
    model.assert_not_awaited()
    inter.followup.send.assert_awaited_once()
    assert "désactivée" in inter.followup.send.await_args.args[0]


@pytest.mark.asyncio
async def test_explicit_ai_review_is_read_only_and_never_calls_lock(monkeypatch):
    monkeypatch.setattr(
        ai_service, "get_settings",
        AsyncMock(return_value={"enabled": True, "default_model": ai_service.MODEL_TERRA}),
    )
    model = AsyncMock(return_value=SimpleNamespace(ok=True, text="Ne touchez pas aux logs privés."))
    monkeypatch.setattr(ai_service, "generate", model)
    plan = AccessPlan()
    plan.gate.append(SimpleNamespace(name="general", category=None))
    monkeypatch.setattr(
        rules, "preview_published_channels",
        AsyncMock(return_value=(plan, SimpleNamespace(id=7), {"role_id": 7})),
    )
    lock = AsyncMock()
    monkeypatch.setattr(rules, "lock_published_channels", lock)
    bot = SimpleNamespace()
    guild = SimpleNamespace(id=5, owner_id=11)
    view = rules.RulesLockConfirmView(bot, guild, 11, ())
    button = next(x for x in view.children if getattr(x, "label", "") == "Avis IA (lecture seule)")
    inter = _interaction()
    await button.callback(inter)
    model.assert_awaited_once()
    lock.assert_not_awaited()
    assert "Aucune permission n'a été modifiée." in inter.followup.send.await_args.args[0]
    assert inter.followup.send.await_args.kwargs["ephemeral"] is True
