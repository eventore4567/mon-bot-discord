"""Le verrouillage doit rester un acte explicite avec aperçu revalidé."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from cogs import verify_setup_interactive_v78 as rules
from utils.verification_access_intelligence import AccessPlan


def plan(*ids):
    return SimpleNamespace(
        gate=[SimpleNamespace(id=i) for i in ids],
        secure_sensitive=[],
        category_gates=[],
        log_destinations=[],
        staff_channels=[],
        protected={888: "staff"},
        untouched={999: "inconnu"},
        preview=lambda: "Aperçu sûr et catégories protégées",
        audit_lines=lambda: ["✅ salon général — public pour @everyone"],
    )


def test_signature_changes_if_public_channel_is_added():
    assert rules.plan_signature(plan(1, 2)) != rules.plan_signature(plan(1, 2, 3))


def test_manual_selection_can_only_reduce_the_safe_plan():
    category = SimpleNamespace(id=10, name="Membres")
    first = SimpleNamespace(id=1, category=category, permissions_synced=True)
    second = SimpleNamespace(id=2, category=category, permissions_synced=True)
    access = AccessPlan(gate=[first, second], category_gates=[category])
    filtered = rules._selected_plan(access, {1})
    assert [channel.id for channel in filtered.gate] == [1]
    assert filtered.category_gates == []


def test_setup_home_routes_lock_button_to_read_only_preview():
    from pathlib import Path
    source = Path("cogs/setup_experience_v74.py").read_text(encoding="utf-8")
    callback = source[source.index("async def ouvrir_verrou"):source.index("verrou.callback = ouvrir_verrou")]
    assert "open_lock_preview" in callback
    assert "send_modal" not in callback


def test_startup_does_not_replace_the_canonical_access_engine():
    from pathlib import Path
    source = Path("sitecustomize.py").read_text(encoding="utf-8")
    assert "VerificationConfigV96._apply_auto_access =" not in source


@pytest.mark.asyncio
async def test_lock_button_only_opens_preview_not_discord_permission_writes(monkeypatch):
    guild = SimpleNamespace(id=55, owner_id=7, get_role=lambda _id: None, get_channel=lambda _id: None)
    bot = SimpleNamespace()
    view = rules.VerifySetupView(
        bot, guild, 7, channel_id=10, role_id=20,
        rules_text="Règlement déjà publié", image_url="",
        captcha_enabled=True, captcha_max_attempts=3, message_id=1234,
    )
    monkeypatch.setattr(
        rules, "preview_published_channels",
        AsyncMock(return_value=(plan(1, 2), SimpleNamespace(mention="@Vérifié"), {})),
    )
    lockdown = AsyncMock()
    monkeypatch.setattr(rules, "lock_published_channels", lockdown)
    interaction = SimpleNamespace(
        user=SimpleNamespace(id=7),
        guild=guild,
        guild_id=55,
        response=SimpleNamespace(defer=AsyncMock()),
        followup=SimpleNamespace(send=AsyncMock()),
    )
    button = next(child for child in view.children if getattr(child, "label", "").startswith("Verrouiller les salons"))
    await button.callback(interaction)
    interaction.response.defer.assert_awaited_once()
    assert interaction.followup.send.await_count == 2
    assert "Aperçu sûr" in interaction.followup.send.await_args_list[-1].args[0]
    confirm_view = interaction.followup.send.await_args_list[-1].kwargs["view"]
    assert isinstance(confirm_view, rules.RulesLockConfirmView)
    lockdown.assert_not_awaited()


@pytest.mark.asyncio
async def test_admin_other_than_owner_cannot_confirm_someone_elses_preview():
    guild = SimpleNamespace(id=55, owner_id=7)
    view = rules.RulesLockConfirmView(SimpleNamespace(), guild, 7, ())
    response = SimpleNamespace(send_message=AsyncMock())
    interaction = SimpleNamespace(
        user=SimpleNamespace(id=8, guild_permissions=SimpleNamespace(administrator=True)),
        guild_id=55,
        response=response,
    )
    assert await view.interaction_check(interaction) is False
    response.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_modified_plan_requires_new_preview_without_writes(monkeypatch):
    guild = SimpleNamespace(id=55, owner_id=7)
    bot = SimpleNamespace()
    old = plan(1)
    view = rules.RulesLockConfirmView(bot, guild, 7, rules.plan_signature(old))
    monkeypatch.setattr(
        rules, "preview_published_channels",
        AsyncMock(return_value=(plan(1, 2), object(), {})),
    )
    lockdown = AsyncMock()
    monkeypatch.setattr(rules, "lock_published_channels", lockdown)
    interaction = SimpleNamespace(
        user=SimpleNamespace(id=7),
        guild_id=55,
        response=SimpleNamespace(defer=AsyncMock()),
        followup=SimpleNamespace(send=AsyncMock()),
    )
    confirm_button = next(child for child in view.children if getattr(child, "label", "") == "Confirmer le verrouillage")
    await confirm_button.callback(interaction)
    from utils import sentrix_panels as panels
    assert "changé" in panels.texte_complet(interaction.followup.send.await_args.kwargs["view"])
    lockdown.assert_not_awaited()
