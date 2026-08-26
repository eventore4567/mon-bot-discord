from pathlib import Path


def test_departure_module_contract():
    source = Path("cogs/guild_departure_notify.py").read_text(encoding="utf-8")
    compile(source, "cogs/guild_departure_notify.py", "exec")

    assert "async def on_guild_remove" in source
    assert "_send_creator_dm" in source
    assert "guild.owner_id" in source
    assert "guild.member_count" in source
    assert "<t:{timestamp}:F>" in source
    assert "Discord ne transmet pas toujours la raison exacte" in source
    assert "await bot.add_cog(GuildDepartureNotify(bot))" in source


def test_final_runtime_installs_departure_listener():
    source = Path("cogs/slash_error_completion_guard.py").read_text(encoding="utf-8")
    compile(source, "cogs/slash_error_completion_guard.py", "exec")

    assert "from . import guild_departure_notify" in source
    assert "await guild_departure_notify.install(bot)" in source
