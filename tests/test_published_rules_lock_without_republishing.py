"""Le règlement publié est un état durable, pas une étape locale de /setup."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import sentrix_verification_v96 as v96


def make_bot(*, v96_panel=None, v78_panel=None, conf=None):
    db = SimpleNamespace(
        fetchone=AsyncMock(side_effect=lambda query, _params: (
            v96_panel if "verification_panels_v96" in query
            else v78_panel
        )),
        get_guild_config=AsyncMock(return_value=conf or {}),
        set_guild_config=AsyncMock(),
    )
    return SimpleNamespace(db=db, get_cog=lambda _name: None)


@pytest.mark.asyncio
async def test_configured_roles_do_not_count_as_published_rules():
    bot = make_bot(conf={"verify_role": 3, "verification_channel": 8})
    assert await v96.published_rules_state(bot, SimpleNamespace(id=55)) is None


@pytest.mark.asyncio
async def test_v96_published_panel_is_recognized_after_new_setup_session():
    bot = make_bot(v96_panel={
        "channel_id": 8, "role_id": 3, "message_id": 999,
        "rules_text": "Respect et courtoisie", "updated_at": 11,
    })
    state = await v96.published_rules_state(bot, SimpleNamespace(id=55))
    assert state["source"] == "v96"
    assert state["message_id"] == 999
    assert state["role_id"] == 3


@pytest.mark.asyncio
async def test_v78_published_panel_uses_persisted_guild_config():
    bot = make_bot(
        v78_panel={"message_id": 555, "rules_text": "Règles", "updated_at": 16},
        conf={"verify_role": 3, "verification_channel": 8},
    )
    state = await v96.published_rules_state(bot, SimpleNamespace(id=55))
    assert state["source"] == "v78"
    assert (state["channel_id"], state["role_id"]) == (8, 3)


@pytest.mark.asyncio
async def test_latest_real_publication_wins_over_old_panel():
    bot = make_bot(
        v96_panel={"channel_id": 9, "role_id": 5, "message_id": 1, "rules_text": "A", "updated_at": 5},
        v78_panel={"message_id": 4, "rules_text": "B", "updated_at": 15},
        conf={"verify_role": 3, "verification_channel": 8},
    )
    state = await v96.published_rules_state(bot, SimpleNamespace(id=55))
    assert (state["source"], state["channel_id"]) == ("v78", 8)


@pytest.mark.asyncio
async def test_published_record_without_message_is_not_valid():
    bot = make_bot(v96_panel={
        "channel_id": 8, "role_id": 3, "message_id": None,
        "rules_text": "Règles", "updated_at": 50,
    })
    assert await v96.published_rules_state(bot, SimpleNamespace(id=55)) is None


@pytest.mark.asyncio
async def test_lock_refuses_unpublished_without_touching_permissions():
    bot = make_bot()
    with pytest.raises(ValueError, match="Publiez d'abord"):
        await v96.lock_channels_after_published_rules(
            bot, SimpleNamespace(id=55), SimpleNamespace(id=123),
        )
    bot.db.set_guild_config.assert_not_awaited()


@pytest.mark.asyncio
async def test_lock_reuses_published_panel_without_republishing(monkeypatch):
    class FakeChannel:
        def __init__(self):
            self.fetch_message = AsyncMock(return_value=SimpleNamespace(id=999))
    class FakeRole:
        pass

    monkeypatch.setattr(v96.discord, "TextChannel", FakeChannel)
    monkeypatch.setattr(v96.discord, "Role", FakeRole)
    channel, role = FakeChannel(), FakeRole()
    guild = SimpleNamespace(
        id=55,
        get_channel=lambda channel_id: channel if channel_id == 8 else None,
        get_role=lambda role_id: role if role_id == 3 else None,
    )
    manager = SimpleNamespace(
        _preflight=AsyncMock(return_value=[]),
        _ensure_table=AsyncMock(),
        _apply_auto_access=AsyncMock(return_value=(8, 6)),
    )
    bot = make_bot(v96_panel={
        "channel_id": 8, "role_id": 3, "message_id": 999,
        "rules_text": "Respectez les membres", "updated_at": 11,
    })
    bot.get_cog = lambda _name: manager
    actor = SimpleNamespace(id=123)
    assert await v96.lock_channels_after_published_rules(bot, guild, actor) == (8, 6)
    channel.fetch_message.assert_awaited_once_with(999)
    manager._preflight.assert_awaited_once_with(
        guild, channel=channel, role=role, auto_access=True,
    )
    manager._apply_auto_access.assert_awaited_once_with(
        guild, verification_channel=channel, verified_role=role, actor=actor,
    )
    bot.db.set_guild_config.assert_awaited_once_with(55, "verification_auto_access", 1)


@pytest.mark.asyncio
async def test_missing_permissions_prevent_any_overwrite(monkeypatch):
    class FakeChannel:
        fetch_message = AsyncMock(return_value=SimpleNamespace(id=999))
    class FakeRole:
        pass

    monkeypatch.setattr(v96.discord, "TextChannel", FakeChannel)
    monkeypatch.setattr(v96.discord, "Role", FakeRole)
    channel, role = FakeChannel(), FakeRole()
    manager = SimpleNamespace(
        _preflight=AsyncMock(return_value=["Gérer les salons manquant"]),
        _ensure_table=AsyncMock(),
        _apply_auto_access=AsyncMock(),
    )
    bot = make_bot(v96_panel={
        "channel_id": 8, "role_id": 3, "message_id": 999,
        "rules_text": "Règles", "updated_at": 11,
    })
    bot.get_cog = lambda _name: manager
    guild = SimpleNamespace(
        id=55, get_channel=lambda _id: channel, get_role=lambda _id: role,
    )
    with pytest.raises(ValueError, match="Verrouillage impossible"):
        await v96.lock_channels_after_published_rules(bot, guild, SimpleNamespace(id=123))
    manager._apply_auto_access.assert_not_awaited()
    bot.db.set_guild_config.assert_not_awaited()
