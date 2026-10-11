from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import discord
import pytest

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from cogs import automod as automod_module
from cogs.automod import AutoMod


def _base_conf(**updates):
    conf = {
        key: 0
        for key in (
            "antispam",
            "antilink",
            "antilink_strict",
            "antiinvite",
            "antimention",
            "anticaps",
            "antiemoji",
            "antiscam",
            "antiraid",
            "antibot",
            "antiaccount",
            "antinuke",
            "antiinsult",
            "security_vanity",
            "security_prune",
            "security_permissions",
            "join_gate",
            "risk_engine",
            "escalation",
        )
    }
    conf.update(updates)
    return conf


def _cog(conf):
    bot = SimpleNamespace(
        db=SimpleNamespace(
            fetchone=AsyncMock(return_value=None),
            fetchall=AsyncMock(return_value=[]),
            get_automod=AsyncMock(return_value=conf),
            log_automod_action=AsyncMock(),
        )
    )
    cog = AutoMod(bot)
    cog.automod_cache[1] = conf
    cog.ignored_channels_cache[1] = set()
    cog.blacklist_words_cache[1] = []
    cog.blacklist_links_cache[1] = []
    cog.blacklist_users_cache[1] = set()
    cog.exempt_roles_cache[1] = set()
    cog.whitelist_domains_cache[1] = []
    cog.moderation_dataset = SimpleNamespace(match=lambda _content: None)
    cog._delete_and_warn = AsyncMock()
    cog._delete_and_timeout = AsyncMock()
    return cog


def _member(*, user_id=7, owner_id=999, manage_guild=False):
    guild = Mock(spec=discord.Guild)
    guild.id = 1
    guild.owner_id = owner_id
    me = Mock()
    me.top_role = 100
    me.guild_permissions = Mock(manage_guild=True, moderate_members=True)
    guild.me = me

    member = Mock(spec=discord.Member)
    member.id = user_id
    member.bot = False
    member.guild = guild
    member.roles = []
    member.top_role = 10
    member.guild_permissions = Mock(
        administrator=False,
        manage_guild=manage_guild,
    )
    return member


def _message(member, content):
    message = Mock(spec=discord.Message)
    message.id = 12345
    message.author = member
    message.guild = member.guild
    message.channel = Mock(id=55)
    message.content = content
    message.mentions = []
    message.role_mentions = []
    message.mention_everyone = False
    message.attachments = []
    message.delete = AsyncMock()
    return message


@pytest.mark.asyncio
async def test_normal_member_is_blocked_by_strict_antilink():
    cog = _cog(_base_conf(antilink=1, antilink_strict=1))
    message = _message(_member(), "https://example.com")

    await cog.on_message(message)

    cog._delete_and_warn.assert_awaited_once()


@pytest.mark.asyncio
async def test_risk_signal_decays_and_logs_threshold():
    conf = _base_conf(risk_engine=1)
    cog = _cog(conf)
    cog.log_action = AsyncMock()
    guild = SimpleNamespace(id=1)

    score = await cog.add_risk_signal(guild, 42, "join_gate", 75, reason="compte récent")

    assert score == 75
    cog.bot.db.log_automod_action.assert_awaited_once()
    cog.log_action.assert_awaited_once()


@pytest.mark.asyncio
async def test_bot_allowlist_prevents_antibot_kick():
    conf = _base_conf(antibot=1, risk_engine=1)
    cog = _cog(conf)
    cog._bot_is_allowlisted = AsyncMock(return_value=True)
    cog.add_risk_signal = AsyncMock()
    guild = SimpleNamespace(id=1)
    member = SimpleNamespace(id=42, bot=True, guild=guild, kick=AsyncMock())

    await cog.on_member_join(member)

    member.kick.assert_not_awaited()
    cog.add_risk_signal.assert_awaited_once()


@pytest.mark.asyncio
async def test_permission_guard_restores_role_escalation():
    conf = _base_conf(antinuke=1, security_permissions=1, risk_engine=1)
    cog = _cog(conf)
    cog.get_audit_actor = AsyncMock(return_value=SimpleNamespace(id=77))
    cog.is_antinuke_exempt = AsyncMock(return_value=False)
    cog.record_nuke_action = AsyncMock(return_value=False)
    cog.add_risk_signal = AsyncMock()
    cog.log_action = AsyncMock()
    guild = SimpleNamespace(id=1, owner_id=999)
    before = SimpleNamespace(id=5, guild=guild, name="mod", mention="<@&5>", permissions=discord.Permissions.none())
    after_perms = discord.Permissions.none()
    after_perms.manage_roles = True
    after = SimpleNamespace(
        id=5,
        guild=guild,
        name="mod",
        mention="<@&5>",
        permissions=after_perms,
        edit=AsyncMock(),
    )

    await cog.on_guild_role_update(before, after)

    after.edit.assert_awaited_once()
    cog.add_risk_signal.assert_awaited_once()
    cog.record_nuke_action.assert_awaited_once()


@pytest.mark.asyncio
async def test_manage_server_staff_is_not_blocked_by_strict_antilink():
    # « Gérer le serveur » est désormais harmonisé avec les règles de salons.
    cog = _cog(_base_conf(antilink=1, antilink_strict=1, antiscam=1))
    message = _message(_member(manage_guild=True), "https://example.com")

    await cog.on_message(message)

    cog._delete_and_warn.assert_not_awaited()


@pytest.mark.asyncio
async def test_server_owner_default_immunity_skips_strict_filter():
    cog = _cog(_base_conf(antilink=1, antilink_strict=1))
    owner = _member(user_id=999, owner_id=999)
    message = _message(owner, "https://example.com")

    with patch.object(automod_module.config, "OWNER_IDS", set()):
        await cog.on_message(message)

    cog._delete_and_warn.assert_not_awaited()


@pytest.mark.asyncio
async def test_server_owner_immunity_off_is_filtered_like_normal_member():
    cog = _cog(_base_conf(antilink=1, antilink_strict=1))
    owner = _member(user_id=999, owner_id=999)
    cog.immunity_overrides_cache[(1, 999)] = False
    message = _message(owner, "https://example.com")

    await cog.on_message(message)

    cog._delete_and_warn.assert_awaited_once()


@pytest.mark.asyncio
async def test_targeted_word_and_link_are_combined_in_one_action():
    cog = _cog(_base_conf())
    cog.blacklist_words_cache[1] = ["interdit"]
    cog.blacklist_links_cache[1] = ["example.com"]
    message = _message(_member(), "interdit https://example.com")

    await cog.on_message(message)

    cog._delete_and_warn.assert_awaited_once()
    args = cog._delete_and_warn.await_args
    assert args.args[2] == "blacklist_word_link"
    assert args.kwargs["censored_content"] is not None
    assert "example.com" not in args.kwargs["censored_content"]


def test_obfuscated_and_concatenated_links_are_normalized():
    raw = (
        "https:/ /discord.gg/Test"
        "https://example.com"
        " hxxps://evil[.]example"
    )
    normalized = automod_module._normalize_link_text(raw)

    assert "https://discord.gg/test" in normalized
    assert " https://example.com" in normalized
    assert "hxxps://evil.example" in normalized


@pytest.mark.asyncio
async def test_native_link_rule_is_never_recreated():
    # La règle native ne peut pas appliquer les bypass membres/administrateurs.
    bot = SimpleNamespace(user=SimpleNamespace(id=123))
    cog = AutoMod(bot)
    guild = SimpleNamespace(
        id=1,
        me=SimpleNamespace(id=123, guild_permissions=SimpleNamespace(manage_guild=True)),
        fetch_automod_rules=AsyncMock(return_value=[]),
        create_automod_rule=AsyncMock(),
    )
    assert await cog._sync_native_antilink_rule(guild) is True
    guild.create_automod_rule.assert_not_awaited()


@pytest.mark.asyncio
async def test_owned_native_rules_removed_without_touching_other_creators():
    bot = SimpleNamespace(user=SimpleNamespace(id=123))
    cog = AutoMod(bot)
    owned = SimpleNamespace(
        id=10, name=automod_module.NATIVE_ANTILINK_RULE_NAME,
        creator_id=123, delete=AsyncMock(),
    )
    foreign = SimpleNamespace(
        id=11, name=automod_module.NATIVE_ANTILINK_RULE_NAME,
        creator_id=987, delete=AsyncMock(),
    )
    unknown = SimpleNamespace(
        id=12, name=automod_module.NATIVE_ANTILINK_RULE_NAME,
        creator_id=None, delete=AsyncMock(),
    )
    unrelated = SimpleNamespace(
        id=13, name="Discord Moderation Manual",
        creator_id=123, delete=AsyncMock(),
    )
    guild = SimpleNamespace(
        id=1,
        me=SimpleNamespace(id=123, guild_permissions=SimpleNamespace(manage_guild=True)),
        fetch_automod_rules=AsyncMock(return_value=[owned, foreign, unknown, unrelated]),
        create_automod_rule=AsyncMock(),
    )
    assert await cog._sync_native_antilink_rule(guild) is True
    owned.delete.assert_awaited_once()
    foreign.delete.assert_not_awaited()
    unknown.delete.assert_not_awaited()
    unrelated.delete.assert_not_awaited()
    guild.create_automod_rule.assert_not_awaited()


@pytest.mark.asyncio
async def test_all_old_sentrix_content_rules_are_retired_on_bootstrap_sync():
    bot = SimpleNamespace(user=SimpleNamespace(id=123))
    cog = AutoMod(bot)
    names = [
        automod_module.NATIVE_ANTILINK_RULE_NAME,
        automod_module.NATIVE_TARGET_LINKS_RULE_NAME,
        automod_module.NATIVE_ANTIINVITE_RULE_NAME,
        automod_module.NATIVE_ANTISCAM_RULE_NAME,
        automod_module.NATIVE_ANTIMENTION_RULE_NAME,
        automod_module.NATIVE_BLACKLIST_RULE_NAME,
        automod_module.NATIVE_HARMFUL_RULE_NAME,
    ]
    rules = [SimpleNamespace(id=i, name=name, creator_id=123, delete=AsyncMock()) for i, name in enumerate(names, 1)]
    guild = SimpleNamespace(
        id=1,
        me=SimpleNamespace(id=123, guild_permissions=SimpleNamespace(manage_guild=True)),
        fetch_automod_rules=AsyncMock(return_value=rules),
        create_automod_rule=AsyncMock(),
    )
    bot.db = SimpleNamespace(fetchall=AsyncMock(return_value=[]), get_automod=AsyncMock(return_value=_base_conf(antilink=1, antiscam=1)))
    await cog._sync_native_suite(guild)
    for rule in rules:
        rule.delete.assert_awaited_once()
    guild.create_automod_rule.assert_not_awaited()


@pytest.mark.asyncio
async def test_native_permission_failure_keeps_local_filter_available_disabled_cleanup():
    conf = _base_conf(antilink=1)
    cog = _cog(conf)
    guild = SimpleNamespace(
        id=1,
        me=SimpleNamespace(id=123, guild_permissions=SimpleNamespace(manage_guild=False)),
        fetch_automod_rules=AsyncMock(),
    )
    assert await cog._sync_native_antilink_rule(guild) is False
    guild.fetch_automod_rules.assert_not_awaited()
    msg = _message(_member(), "https://example.com")
    await cog.on_message(msg)
    cog._delete_and_warn.assert_awaited_once()


@pytest.mark.asyncio
async def test_native_permission_failure_keeps_local_filter_available():
    conf = _base_conf(antilink=1, antilink_strict=1)
    bot = SimpleNamespace(
        db=SimpleNamespace(get_automod=AsyncMock(return_value=conf))
    )
    cog = AutoMod(bot)
    guild = SimpleNamespace(
        id=1,
        me=SimpleNamespace(
            guild_permissions=SimpleNamespace(manage_guild=False)
        ),
    )

    native_ok = await cog._sync_native_antilink_rule(guild)
    assert native_ok is False

    # The local listener is independent from native Discord AutoMod.
    cog.automod_cache[1] = conf
    cog.ignored_channels_cache[1] = set()
    cog.blacklist_words_cache[1] = []
    cog.blacklist_links_cache[1] = []
    cog.blacklist_users_cache[1] = set()
    cog.exempt_roles_cache[1] = set()
    cog.whitelist_domains_cache[1] = []
    cog.immunity_overrides_cache[(1, 7)] = False
    cog._delete_and_warn = AsyncMock()
    member = _member()
    member.guild = guild
    guild.owner_id = 999
    message = _message(member, "https://example.com")
    message.guild = guild

    await cog.on_message(message)

    cog._delete_and_warn.assert_awaited_once()



def test_invite_censor_keeps_link_shape_but_never_the_real_code():
    value = automod_module._censor_invites("https://discord.gg/SecretInvite")
    assert value == (
        "https://discord.gg/æ@#/%E2%82%AC%C3%9F!%& "
        "(invitation censurée)"
    )
    assert "SecretInvite" not in value


def test_invite_censor_supports_discord_com_invite_links():
    value = automod_module._censor_invites(
        "regarde https://discord.com/invite/abcDEF123 maintenant"
    )
    assert (
        "https://discord.com/invite/æ@#/%E2%82%AC%C3%9F!%& "
        "(invitation censurée)"
    ) in value
    assert "abcDEF123" not in value


def test_composed_invite_censor_uses_safe_visible_placeholder():
    value = automod_module._compose_censored_content(
        "https://discord.gg/real-code",
        invites=True,
    )
    assert value.startswith("https://discord.gg/æ@#/")
    assert value.endswith("(invitation censurée)")
    assert "real-code" not in value


@pytest.mark.asyncio
async def test_native_suite_reads_rules_once_per_guild_and_skips_required_community_rule():
    """Un 403 200006 sur anti-mentions ne doit pas empêcher l'anti-liens."""
    response = SimpleNamespace(status=403, reason="Forbidden")
    protected_error = discord.Forbidden(
        response,
        {"code": 200006, "message": "Mention Spam AutoMod rule cannot be deleted"},
    )
    protected = SimpleNamespace(
        id=11, name=automod_module.NATIVE_ANTIMENTION_RULE_NAME,
        creator_id=123, delete=AsyncMock(side_effect=protected_error),
    )
    antilink = SimpleNamespace(
        id=12, name=automod_module.NATIVE_ANTILINK_RULE_NAME,
        creator_id=123, delete=AsyncMock(),
    )
    external = SimpleNamespace(
        id=13, name=automod_module.NATIVE_ANTISCAM_RULE_NAME,
        creator_id=987, delete=AsyncMock(),
    )
    bot = SimpleNamespace(user=SimpleNamespace(id=123))
    cog = AutoMod(bot)
    guild = SimpleNamespace(
        id=1,
        me=SimpleNamespace(id=123, guild_permissions=SimpleNamespace(manage_guild=True)),
        fetch_automod_rules=AsyncMock(return_value=[protected, antilink, external]),
        create_automod_rule=AsyncMock(),
    )

    result = await cog._sync_native_suite(guild)
    assert result == {"removed": 1, "protected": 1, "external": 1, "failed": 0}
    guild.fetch_automod_rules.assert_awaited_once()
    antilink.delete.assert_awaited_once()
    protected.delete.assert_awaited_once()
    external.delete.assert_not_awaited()
    guild.create_automod_rule.assert_not_awaited()


@pytest.mark.asyncio
async def test_native_block_diagnostic_identifies_rule_and_user_without_message_content(caplog):
    import logging

    member = _member()
    member.guild_permissions = SimpleNamespace(administrator=True)
    member.guild.me.guild_permissions.manage_guild = True
    member.guild.get_member = Mock(return_value=member)
    foreign_rule = SimpleNamespace(name="Règle manuelle du serveur", creator_id=444)
    member.guild.fetch_automod_rule = AsyncMock(return_value=foreign_rule)
    bot = SimpleNamespace(
        user=SimpleNamespace(id=123),
        get_guild=Mock(return_value=member.guild),
    )
    cog = AutoMod(bot)
    execution = SimpleNamespace(
        guild_id=1, user_id=member.id, rule_id=55, channel_id=66,
        content="mot de passe qui ne doit pas apparaître dans les logs",
        action=SimpleNamespace(type=discord.AutoModRuleActionType.block_message),
    )

    with caplog.at_level(logging.WARNING, logger="bot"):
        await cog.on_automod_action(execution)
        await cog.on_automod_action(execution)

    member.guild.fetch_automod_rule.assert_awaited_once()
    assert "SENTRIX_BLOCK_SOURCE=discord_native" in caplog.text
    assert "rule_name=Règle manuelle du serveur" in caplog.text
    assert "privileged=True" in caplog.text
    assert "mot de passe" not in caplog.text


@pytest.mark.asyncio
async def test_admin_link_never_reaches_local_deletion_and_is_traced(caplog):
    import logging

    conf = _base_conf(antilink=1, antiscam=1, antispam=1)
    cog = _cog(conf)
    member = _member()
    member.guild_permissions = SimpleNamespace(administrator=True)
    msg = _message(member, "https://example.com/hello")
    with caplog.at_level(logging.INFO, logger="bot"):
        await cog.on_message(msg)

    cog._delete_and_warn.assert_not_awaited()
    assert "SENTRIX_LINK_BYPASS=staff" in caplog.text
