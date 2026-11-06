"""Réglages persistants : vraies récompenses atomiques, modals et boutons privés."""

import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import discord
import pytest
import pytest_asyncio

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")
from cogs.economy import Economy
from cogs.economy_setup import (
    EconomyAdvancedView,
    EconomyPublicView,
    EconomySettingsModal,
    EconomySetupView,
)
from database.db import Database
from utils import game_rewards
from utils.economy_settings import (
    get_economy_settings,
    invalidate,
    save_economy_settings,
    validate,
)


@pytest_asyncio.fixture
async def bot(tmp_path):
    db = Database(str(tmp_path / "settings.db"))
    await db.connect()
    value = SimpleNamespace(db=db, get_guild=lambda _: None, add_view=lambda _: None)
    from utils.system_features import set_system_feature

    await set_system_feature(db, 1, "economy", True)
    yield value
    await db.close()


def context():
    return SimpleNamespace(
        guild=SimpleNamespace(id=1),
        author=SimpleNamespace(id=42, mention="<@42>"),
        send=AsyncMock(),
    )


@pytest.mark.asyncio
async def test_defaults_and_saved_daily_use_true_logic(bot):
    cog = Economy(bot)
    ctx = context()
    cog._panneau_gain = AsyncMock()
    with (
        patch(
            "cogs.economy.temporary_boosts.apply_money_boost",
            side_effect=lambda db, g, u, a: (a, None),
        ),
        patch(
            "cogs.community_v3.register_daily_claim",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        await cog.daily.callback(cog, ctx)
        assert (await bot.db.get_balance(1, 42))["cash"] == 200
        await save_economy_settings(bot, 1, {"daily_amount": 500}, 42)
        await bot.db.execute(
            "UPDATE economy SET last_daily=0,bank=10000 WHERE guild_id=1 AND user_id=42"
        )
        await cog.daily.callback(cog, ctx)
        assert (await bot.db.get_balance(1, 42))[
            "cash"
        ] == 800  # 200 + 500 + intérêts 100
    row = await bot.db.fetchone(
        "SELECT * FROM config_journal WHERE guild_id=1 AND field='economy.daily_amount'"
    )
    assert row["actor_id"] == 42


@pytest.mark.asyncio
async def test_work_cooldown_30_minutes_and_default_career(bot):
    cog = Economy(bot)
    ctx = context()
    cog._panneau_gain = AsyncMock()
    cog._panneau_attente = AsyncMock()
    await save_economy_settings(bot, 1, {"work_cooldown": 1800}, 42)
    with (
        patch(
            "cogs.economy.temporary_boosts.apply_money_boost",
            side_effect=lambda db, g, u, a: (a, None),
        ),
        patch("database.db.now", return_value=100000),
        patch(
            "cogs.economy.progression.tirer_salaire",
            return_value=(
                80,
                None,
                SimpleNamespace(
                    nom="Stagiaire", emoji="", salaire_min=40, salaire_max=120
                ),
                "travaille",
            ),
        ),
    ):
        await cog.work.callback(cog, ctx)
        await cog.work.callback(cog, ctx)
        assert cog._panneau_gain.await_count == 1
        assert cog._panneau_attente.call_args.kwargs["restant"] == 1800
    with (
        patch(
            "cogs.economy.temporary_boosts.apply_money_boost",
            side_effect=lambda db, g, u, a: (a, None),
        ),
        patch("database.db.now", return_value=101801),
    ):
        await cog.work.callback(cog, ctx)
    assert cog._panneau_gain.await_count == 2
    assert (
        40 <= cog._panneau_gain.call_args.kwargs["montant"] <= 240
    )  # événement inclus


@pytest.mark.asyncio
async def test_disabled_blocks_commands_and_game_money(bot):
    await save_economy_settings(bot, 1, {"enabled": 0}, 42)
    cog = Economy(bot)
    for name in ("daily", "work", "balance"):
        ctx = context()
        await getattr(cog, name).callback(cog, ctx)
        assert "désactivée" in ctx.send.call_args.args[0]
        assert ctx.send.call_args.kwargs["ephemeral"]
    await bot.db.set_game_settings(1, {"logs_enabled": 0})
    reward = await game_rewards.reward_game_winner(
        bot, 1, 42, "trivia", 100, "test-disabled"
    )
    assert reward.amount == 0
    assert reward.reason == "economy_disabled"


@pytest.mark.asyncio
async def test_settings_survive_new_bot_and_empty_cache(bot):
    await save_economy_settings(
        bot, 1, {"daily_amount": 500, "salary_multiplier": 2, "interest_rate": 0.02}, 42
    )
    invalidate(bot, 1)
    restarted = SimpleNamespace(db=bot.db)
    values = await get_economy_settings(restarted, 1)
    assert (
        values["daily_amount"] == 500
        and values["salary_multiplier"] == 2
        and values["interest_rate"] == 0.02
    )


@pytest.mark.asyncio
async def test_bad_modal_value_saves_nothing(bot):
    guild = SimpleNamespace(id=1)
    owner = EconomySetupView(bot, guild, 42)
    modal = EconomySettingsModal(owner, "rewards", await get_economy_settings(bot, 1))
    modal.inputs["daily_amount"]._value = "10"
    i = SimpleNamespace(
        guild_id=1,
        user=SimpleNamespace(
            id=42, guild_permissions=SimpleNamespace(administrator=True)
        ),
        response=SimpleNamespace(send_message=AsyncMock()),
    )
    await modal.on_submit(i)
    assert "refusée" in i.response.send_message.call_args.args[0]
    assert (await get_economy_settings(bot, 1))["daily_amount"] == 200
    assert (
        await bot.db.fetchone("SELECT * FROM sentrix_economy_settings WHERE guild_id=1")
        is None
    )


@pytest.mark.asyncio
async def test_persistent_public_buttons_call_real_commands_privately(bot):
    cog = Economy(bot)
    cog._panneau_gain = AsyncMock()
    bot.get_cog = lambda name: cog
    view = EconomyPublicView(bot)
    assert view.is_persistent()
    row = view.children[0].children[1]
    assert [x.custom_id for x in row.children] == [
        "sentrix:economy:public:" + n
        for n in ("daily", "work", "balance", "shop", "economyleaderboard")
    ]
    i = SimpleNamespace(
        guild=SimpleNamespace(id=1),
        user=SimpleNamespace(id=42, mention="<@42>"),
        channel=object(),
        message=None,
        response=SimpleNamespace(is_done=lambda: True, defer=AsyncMock()),
        followup=SimpleNamespace(send=AsyncMock()),
    )
    with (
        patch(
            "cogs.economy.temporary_boosts.apply_money_boost",
            side_effect=lambda db, g, u, a: (a, None),
        ),
        patch(
            "cogs.community_v3.register_daily_claim",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        await row.children[0].callback(i)
    assert (await bot.db.get_balance(1, 42))["cash"] == 200
    assert i.response.defer.call_args.kwargs["ephemeral"]


@pytest.mark.asyncio
async def test_games_multiplier_and_no_pay(bot):
    await save_economy_settings(bot, 1, {"enabled": 1, "games_multiplier": 2}, 42)
    await bot.db.set_game_settings(
        1,
        {
            "logs_enabled": 0,
            "min_reward_multiplier": 1.0,
            "max_reward_multiplier": 1.0,
            "event_multiplier": 1.0,
        },
    )
    reward = await game_rewards.reward_game_winner(bot, 1, 42, "trivia", 50, "game-1")
    assert reward.amount == 100
    await save_economy_settings(bot, 1, {"games_pay": 0}, 42)
    reward = await game_rewards.reward_game_winner(bot, 1, 42, "trivia", 50, "game-2")
    assert reward.amount == 0


@pytest.mark.parametrize(
    "update",
    [
        {"daily_amount": 49},
        {"weekly_amount": 1000001},
        {"work_min": 1000, "work_max": 10},
        {"salary_multiplier": 5.1},
        {"interest_rate": 0.1},
        {"games_multiplier": -1},
        {"rob_success": 99},
    ],
)
def test_all_numeric_bounds(update):
    from utils.economy_settings import DEFAULTS

    with pytest.raises(ValueError):
        validate(update, DEFAULTS)


@pytest.mark.asyncio
async def test_setup_component_admin_rejects_member(bot):
    from tools.permission_audit_sweep import _expected

    assert _expected("setup", "categorie:configuration", "membre", False, None) == (
        "autorise",
        "lecture-seule",
    )
    view = EconomySetupView(bot, SimpleNamespace(id=1), 42)
    interaction = SimpleNamespace(
        guild_id=1,
        user=SimpleNamespace(
            id=42, guild_permissions=SimpleNamespace(administrator=False)
        ),
        response=SimpleNamespace(send_message=AsyncMock()),
    )
    assert not await view.interaction_check(interaction)
    interaction.response.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_economy_page_is_complete_and_fits_discord_components(bot):
    view = await EconomyAdvancedView(bot, SimpleNamespace(id=1), 42).build()
    assert int(view.children[0].accent_colour) == 0xF1C40F
    labels = {
        item.label
        for row in view.children[0].children
        if isinstance(row, discord.ui.ActionRow)
        for item in row.children
    }
    assert {
        "Activer / Désactiver",
        "Monnaie",
        "Récompenses",
        "Métiers",
        "Banque",
        "Vol (rob)",
        "Boutique",
        "Jeux",
        "Panneau économie",
        "Réinitialiser l'économie",
    } <= labels
    assert view.total_children_count <= 40
    assert isinstance(view.children[0].children[0], discord.ui.MediaGallery)


@pytest.mark.asyncio
async def test_rob_parameters_preserve_atomic_service(bot):
    from services.economy import atomic_rob

    await bot.db.add_balance(1, 42, 100)
    await bot.db.add_balance(1, 43, 100)
    with patch("services.economy.secrets.randbelow", return_value=99):
        result, amount = await atomic_rob(bot.db, 1, 42, 43, success_chance=5, fine=35)
    assert (result, amount) == ("failed", 35)
    assert (await bot.db.get_balance(1, 42))["cash"] == 65


@pytest.mark.asyncio
async def test_currency_modal_shares_name_and_emoji_with_existing_engine(bot):
    owner = EconomySetupView(bot, SimpleNamespace(id=1), 42)
    values = {**await get_economy_settings(bot, 1), "economy_emoji": "🪙"}
    modal = EconomySettingsModal(owner, "currency", values)
    modal.inputs["currency_name"]._value = "jetons"
    modal.inputs["economy_emoji"]._value = "<:jeton:123456789012345678>"
    owner.refresh = AsyncMock()
    interaction = SimpleNamespace(
        guild_id=1,
        user=SimpleNamespace(
            id=42, guild_permissions=SimpleNamespace(administrator=True)
        ),
        response=SimpleNamespace(send_message=AsyncMock()),
    )
    await modal.on_submit(interaction)
    assert (await get_economy_settings(bot, 1))["currency_name"] == "jetons"
    assert (await bot.db.get_stats_settings(1))[
        "economy_emoji"
    ] == "<:jeton:123456789012345678>"
    assert (
        await bot.db.fetchone(
            "SELECT currency_plural FROM economy_settings_v2 WHERE guild_id=1"
        )
    )["currency_plural"] == "jetons"
    owner.refresh.assert_awaited_once()


@pytest.mark.asyncio
async def test_old_switch_stays_in_sync_with_public_buttons(bot):
    from cogs.setup_v2_core import set_module_enabled

    await save_economy_settings(bot, 1, {"daily_amount": 500}, 42)
    await set_module_enabled(bot, 1, "economy", False, actor_id=42)
    assert not (await get_economy_settings(bot, 1))["enabled"]
    assert not (
        await bot.db.fetchone(
            "SELECT enabled FROM sentrix_economy_settings WHERE guild_id=1"
        )
    )["enabled"]
    await set_module_enabled(bot, 1, "economy", True, actor_id=42)
    assert (await get_economy_settings(bot, 1))["enabled"]


@pytest.mark.asyncio
async def test_economy_keeps_existing_default_on_without_module_row(bot):
    # L'absence de ligne n'est pas OFF : economy appartient à DEFAULT_ON_MODULES.
    settings = await get_economy_settings(bot, 2)
    assert settings["enabled"] == 1 and settings["daily_amount"] == 200


@pytest.mark.asyncio
async def test_confirmed_reset_uses_existing_retention_context(bot):
    from cogs.economy_setup import ResetEconomyView
    from cogs.member_data_retention_v17 import (
        ProtectedProgressDeletionError,
        _install_db_guard,
    )

    cog = Economy(bot)
    bot.get_cog = lambda _: cog
    _install_db_guard(bot)
    await bot.db.add_balance(1, 42, 500)
    with pytest.raises(ProtectedProgressDeletionError):
        await bot.db.execute("DELETE FROM economy WHERE guild_id=?", (1,))
    view = ResetEconomyView(bot, SimpleNamespace(id=1), 42)
    interaction = SimpleNamespace(
        guild=SimpleNamespace(id=1),
        guild_id=1,
        user=SimpleNamespace(
            id=42, guild_permissions=SimpleNamespace(administrator=True)
        ),
        channel=object(),
        message=None,
        response=SimpleNamespace(send_message=AsyncMock(), defer=AsyncMock()),
    )
    assert await view.interaction_check(interaction)
    with (
        patch("cogs.economy.journaliser", new_callable=AsyncMock),
        patch("cogs.economy.sx_panels.envoyer", new_callable=AsyncMock),
    ):
        await next(
            item
            for item in view.walk_children()
            if isinstance(item, discord.ui.Button)
            and item.label == "Oui, tout remettre à zéro"
        ).callback(interaction)
    row = await bot.db.fetchone("SELECT * FROM economy WHERE guild_id=1 AND user_id=42")
    assert row is None
    # Le reset explicite ne laisse pas la garde désactivée après le clic.
    with pytest.raises(ProtectedProgressDeletionError):
        await bot.db.execute("DELETE FROM economy WHERE guild_id=?", (1,))
