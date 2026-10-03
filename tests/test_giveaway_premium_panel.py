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
    panel = giveaway_v2.GiveawayV2.build_public_panel(
        cog,
        SimpleNamespace(),
        state,
        2_000_000_000,
        SimpleNamespace(mention="<@1>"),
        count=12,
        interactive=False,
    )

    from utils import sentrix_panels
    text = sentrix_panels.texte_complet(panel)
    assert "<@&10> · **x3**" in text
    assert "<@&20> · **x5**" in text
    assert "Participants** · 12" in text

    source = inspect.getsource(giveaway_v2.GiveawayV2.publish)
    assert "state.bonus_multipliers.get(role_id, state.bonus_multiplier)" in source
    assert "embed=" not in source
    assert "panels.envoyer(channel, panel)" in source


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


def test_public_giveaway_is_components_v2_without_coloured_embed_bar():
    source = inspect.getsource(giveaway_v2.GiveawayV2.publish)
    assert "discord.Embed" not in source
    assert "embed=" not in source
    assert "build_public_panel" in source

    finish = inspect.getsource(giveaway_v2.GiveawayV2.finish)
    assert "channel.send(embed=" not in finish
    assert "panels.editer" in finish


def test_giveaway_media_is_rendered_as_panel_content_image():
    state = giveaway_v2.BuilderState(
        author_id=1,
        guild_id=2,
        prize="Nitro",
        duration_seconds=1800,
        winners=1,
        channel_id=3,
        image_url="https://cdn.example.test/giveaway.gif",
    )
    cog = object.__new__(giveaway_v2.GiveawayV2)
    panel = giveaway_v2.GiveawayV2.build_public_panel(
        cog,
        SimpleNamespace(),
        state,
        2_000_000_000,
        SimpleNamespace(mention="<@1>"),
        interactive=False,
    )
    assert "https://cdn.example.test/giveaway.gif" in repr(panel.to_components())


def test_giveaway_result_announcement_matches_simple_winner_style():
    source = inspect.getsource(giveaway_v2.GiveawayResultView)
    assert "Félicitations ! 🎉" in source
    assert "a gagné" in source
    assert "ont gagné" in source
    assert 'label="Aller au giveaway"' in source
    assert 'label="Relancer le tirage"' in source
    assert "discord.Embed" not in source
    assert "accent_color" not in source
    assert "accent_colour" not in source


def test_reroll_updates_the_same_result_message_and_persists_its_id():
    helper = inspect.getsource(giveaway_v2.GiveawayV2._upsert_result_announcement)
    assert "result_message_id" in helper
    assert "await message.edit(view=view)" in helper
    assert "UPDATE giveaways_v2 SET result_message_id=?" in helper

    finish = inspect.getsource(giveaway_v2.GiveawayV2.finish)
    assert "_upsert_result_announcement" in finish


def test_reroll_can_target_latest_finished_v2_without_message_id():
    source = inspect.getsource(giveaway_v2.GiveawayV2.handle_reroll)
    assert "message_id: int | None = None" in source
    assert "status='termine'" in source
    assert "ORDER BY end_at DESC, id DESC LIMIT 1" in source
