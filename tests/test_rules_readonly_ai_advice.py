"""Conseils d'IA optionnels : le modèle ne modifie jamais les accès Discord."""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from utils.verification_access_intelligence import AccessPlan, ai_access_review_context
from cogs import verify_setup_interactive_v78 as rules


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


def test_no_public_ai_advice_button_in_rules_preview():
    bot = SimpleNamespace()
    guild = SimpleNamespace(id=5, owner_id=11)
    view = rules.RulesLockConfirmView(bot, guild, 11, ())
    labels = [getattr(x, "label", "") for x in view.children]
    assert "Avis IA (lecture seule)" not in labels
    assert "Confirmer le verrouillage" in labels
    assert "Annuler" in labels


@pytest.mark.asyncio
async def test_no_member_channels_does_not_offer_dangerous_confirm(monkeypatch):
    bot = SimpleNamespace()
    guild = SimpleNamespace(id=5, owner_id=11, get_channel=lambda _id: None, get_role=lambda _id: None)
    view = rules.VerifySetupView(
        bot, guild, 11, channel_id=10, role_id=20,
        rules_text="Règlement déjà publié", image_url="",
        captcha_enabled=True, captcha_max_attempts=3, message_id=123,
    )
    plan = AccessPlan()
    plan.secure_sensitive.append(SimpleNamespace(id=33, name="staff"))
    monkeypatch.setattr(
        rules, "preview_published_channels",
        AsyncMock(return_value=(plan, SimpleNamespace(mention="@Vérifié"), {})),
    )
    apply_lock = AsyncMock()
    monkeypatch.setattr(rules, "lock_published_channels", apply_lock)
    response = SimpleNamespace(defer=AsyncMock())
    followup = SimpleNamespace(send=AsyncMock())
    interaction = SimpleNamespace(
        guild_id=5, user=SimpleNamespace(id=11),
        response=response, followup=followup,
    )
    button = next(x for x in view.children if getattr(x, "label", "").startswith("Verrouiller les salons"))
    await button.callback(interaction)
    from utils import sentrix_panels as panels
    result = followup.send.await_args.kwargs["view"]
    assert "Aucun salon membre" in panels.texte_complet(result)
    assert isinstance(result, panels.Panneau)
    assert result.avec_banniere
    assert result.fichiers()
    apply_lock.assert_not_awaited()


def test_short_preview_does_not_show_log_destinations_or_ai_advice():
    plan = AccessPlan(
        gate=[SimpleNamespace(name="general", id=11)],
        protected={99: "logs"},
        log_destinations=[SimpleNamespace(name="logs-confidentiels", id=32)],
    )
    summary = plan.preview()
    assert "Salons textuels à verrouiller : 1" in summary
    assert "Salons protégés ou inchangés : 1" in summary
    assert "logs-confidentiels" not in summary
    assert "IA" not in summary
    assert len(summary) < 350



@pytest.mark.asyncio
async def test_warning_feedback_has_neutral_banner_and_no_user_ping():
    from utils import sentrix_panels as panels
    followup = SimpleNamespace(send=AsyncMock())
    await rules._send_access_feedback(
        followup,
        "Discord protège un salon d'accueil : aucun changement demandé.",
        kind="warning",
    )
    kwargs = followup.send.await_args.kwargs
    assert kwargs["ephemeral"] is True
    assert isinstance(kwargs["view"], panels.Panneau)
    assert kwargs["view"].avec_banniere is True
    assert kwargs["files"]
    assert kwargs["allowed_mentions"].everyone is False
    assert kwargs["allowed_mentions"].users is False
