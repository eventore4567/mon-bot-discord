from __future__ import annotations

import inspect
from types import SimpleNamespace

import discord

from cogs import final_interaction_policy
from cogs import giveaway_v2


def test_giveaway_media_is_native_file_upload_not_url_field():
    conditions = inspect.getsource(giveaway_v2.ConditionsModal)
    media = inspect.getsource(giveaway_v2.MediaModal)

    assert "URL image / GIF" not in conditions
    assert "FileUpload" in media
    assert "Choisissez directement un fichier" in media


def test_giveaway_bonus_multiplier_is_per_role():
    state = giveaway_v2.BuilderState(
        author_id=1,
        guild_id=2,
        prize="Nitro",
        duration_text="30m",
        duration_seconds=1800,
        winners=1,
        channel_id=3,
        bonus_roles=[10, 20],
        bonus_multiplier=2,
        bonus_multipliers={10: 3, 20: 5},
    )
    cog = object.__new__(giveaway_v2.GiveawayV2)
    embed = giveaway_v2.GiveawayV2.build_public_embed(
        cog,
        SimpleNamespace(),
        state,
        2_000_000_000,
        SimpleNamespace(mention="<@1>"),
    )

    bonus = next(field.value for field in embed.fields if field.name == "Chances bonus")
    assert "<@&10> — **x3**" in bonus
    assert "<@&20> — **x5**" in bonus

    source = inspect.getsource(giveaway_v2.GiveawayV2.publish)
    assert "state.bonus_multipliers.get(role_id, state.bonus_multiplier)" in source


def test_role_setup_updates_existing_panel_instead_of_spamming_success_cards():
    source = inspect.getsource(giveaway_v2.RoleSetupView.refresh)
    assert "edit_message" in source
    assert "sync_main_message" in source


def test_success_text_with_interdit_is_not_classified_as_error():
    assert final_interaction_policy._title_for_text(
        "Rôles interdits mis à jour."
    ) == "Action effectuée"

    token = final_interaction_policy._COMMAND_ROOT.set("giveaway")
    try:
        assert final_interaction_policy._text_is_simple_error(
            "Rôles interdits mis à jour."
        ) is False
        assert final_interaction_policy._text_is_simple_error(
            "Un de vos rôles est interdit pour ce giveaway."
        ) is True
    finally:
        final_interaction_policy._COMMAND_ROOT.reset(token)


def test_excluded_role_error_identifies_the_blocking_role():
    source = inspect.getsource(giveaway_v2.GiveawayV2._eligibility)
    assert "Vous avez un rôle interdit pour ce giveaway" in source
    assert "<@&{role_id}>" in source
