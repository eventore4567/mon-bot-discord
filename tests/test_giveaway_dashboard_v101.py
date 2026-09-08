from __future__ import annotations

import inspect
from types import SimpleNamespace

from aiohttp import web
from discord import app_commands

import sentrix_v101_command_runtime as v101
from cogs.embed_builder import EmbedBuilder
from cogs.setup_control_center import OfficialSetup
from web import giveaway_dashboard_v101 as giveaway_dashboard


def test_real_setup_is_native_and_never_exposes_internal_runtime_parameters():
    command = OfficialSetup.slash_setup
    assert isinstance(command, app_commands.Command)
    params = tuple(inspect.signature(command.callback).parameters)
    assert params == ("self", "interaction")
    assert "ctx" not in params
    assert "args" not in params
    assert "kwargs" not in params


def test_standard_railway_boot_installs_v101_before_v98():
    source = open("sentrix_v98_boot.py", encoding="utf-8").read()
    v101_pos = source.index("install_v101_command_runtime()")
    v98_pos = source.index("install_v98()")
    assert v101_pos < v98_pos


async def _bind_real_detached_embed_command():
    cog = EmbedBuilder(SimpleNamespace())
    command = EmbedBuilder.embed_group.copy()
    command.cog = None
    bot = SimpleNamespace(cogs={"EmbedBuilder": cog})
    ctx = SimpleNamespace(bot=bot)
    return cog, ctx, await v101._bind_native_arguments(command, ctx, (), {})


def test_real_embed_group_keeps_its_cog_when_bridge_command_is_detached():
    import asyncio

    cog, ctx, (args, kwargs) = asyncio.run(_bind_real_detached_embed_command())
    assert args == [cog, ctx]
    assert kwargs == {}


def test_giveaway_dashboard_is_one_panel_with_complete_create_fields():
    html = giveaway_dashboard.GIVEAWAY_HTML
    assert html.count('class="gw-card"') == 1
    for control in (
        'id="prize"',
        'id="duration"',
        'id="winners"',
        'id="channel"',
        'id="pingRole"',
        'id="imageUrl"',
        'id="description"',
        'id="requiredRoles"',
        'id="excludedRoles"',
        'id="bonusRoles"',
        'id="bonusMultiplier"',
        'id="minInvites"',
        'id="accountAge"',
        'id="serverAge"',
        'id="customCondition"',
    ):
        assert control in html
    for action in ('data-action="end"', 'data-action="reroll"', 'data-action="cancel"'):
        assert action in html


def test_giveaway_dashboard_registers_page_and_api_without_replacing_core_loader():
    dashboard = SimpleNamespace(
        INDEX_HTML='<nav class="nav"><button data-tab="tickets">Tickets</button></nav></head>',
        build_app=lambda _bot: web.Application(),
    )
    giveaway_dashboard.install(dashboard)
    app = dashboard.build_app(SimpleNamespace())
    paths = {route.resource.canonical for route in app.router.routes()}
    assert "/giveaways" in paths
    assert "/api/guilds/{guild_id}/giveaways" in paths
    assert "/api/guilds/{guild_id}/giveaways/{message_id}/{action}" in paths
    assert 'href="/giveaways"' in dashboard.INDEX_HTML


def test_giveaway_management_reuses_existing_v2_business_handlers():
    source = inspect.getsource(giveaway_dashboard.install)
    assert "cog.handle_end" in source
    assert "cog.handle_reroll" in source
    assert "cog.handle_cancel" in source
    assert "cog.publish" in source
