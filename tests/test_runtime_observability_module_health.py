import discord
from discord.ext import commands

from cogs.runtime_observability_v26 import _is_technical_module_failure


def test_user_and_permission_errors_do_not_degrade_module_health():
    assert _is_technical_module_failure(commands.BadArgument("bad")) is False
    assert _is_technical_module_failure(commands.CheckFailure("blocked")) is False
    assert _is_technical_module_failure(discord.Forbidden(type("R", (), {"status": 403, "reason": "forbidden"})(), "forbidden")) is False


def test_unexpected_runtime_error_counts_as_technical_failure():
    assert _is_technical_module_failure(RuntimeError("boom")) is True
