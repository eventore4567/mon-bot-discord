from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("DISCORD_TOKEN", "test-token")

import discord
from discord.ext import commands

from utils.command_setup_prompt import should_offer_setup

ROOT = Path(__file__).resolve().parents[1]


def _bot() -> commands.Bot:
    return commands.Bot(command_prefix="+", intents=discord.Intents.none())


def test_complex_configuration_command_gets_interactive_setup():
    bot = _bot()

    @bot.command(name="reactionrole-add")
    async def reactionrole_add(
        ctx,
        message_id: int,
        emoji: str,
        role: discord.Role,
    ):
        pass

    assert should_offer_setup(bot.get_command("reactionrole-add")) is True


def test_fast_moderation_commands_stay_fast():
    bot = _bot()

    @bot.command(name="ban")
    async def ban(ctx, member: discord.Member, *, reason: str = "Aucune"):
        pass

    @bot.command(name="clear")
    async def clear(ctx, amount: int):
        pass

    assert should_offer_setup(bot.get_command("ban")) is False
    assert should_offer_setup(bot.get_command("clear")) is False


def test_multi_argument_non_destructive_command_can_use_setup():
    bot = _bot()

    @bot.command(name="poll")
    async def poll(ctx, question: str, options: str):
        pass

    assert should_offer_setup(bot.get_command("poll")) is True


def test_setup_engine_only_collects_values_and_invokes_existing_command():
    source = (ROOT / "utils" / "command_setup_prompt.py").read_text(encoding="utf-8")

    assert 'label="Configurer"' in source
    assert "await self.ctx.invoke(self.command" in source
    assert "run_converters" in source
    assert "create_text_channel(" not in source
    assert "create_role(" not in source


def test_all_prefix_error_layers_offer_setup_before_usage_fallback():
    final = (ROOT / "cogs" / "final_error_embed_v5.py").read_text(encoding="utf-8")
    runtime = (ROOT / "cogs" / "error_experience_v3.py").read_text(encoding="utf-8")
    main = (ROOT / "main.py").read_text(encoding="utf-8")

    for source in (final, runtime, main):
        assert "offer_setup_for_missing_argument" in source


def test_every_command_with_two_required_values_gets_setup_panel():
    bot = _bot()

    @bot.command(name="giverole")
    async def giverole(ctx, member: discord.Member, role: discord.Role):
        pass

    assert should_offer_setup(bot.get_command("giverole")) is True


def test_single_required_value_does_not_open_setup_panel():
    bot = _bot()

    @bot.command(name="nickname")
    async def nickname(ctx, member: discord.Member):
        pass

    assert should_offer_setup(bot.get_command("nickname")) is False


def test_setup_opening_is_a_real_compact_sentrix_panel():
    source = (ROOT / "utils" / "command_setup_prompt.py").read_text(encoding="utf-8")

    assert "panels.Panneau(" in source
    assert 'sections=[' in source
    assert 'panels.Section(' in source
    assert 'banniere=False' in source
    assert 'panels.avec_composants(' in source
    assert 'label="Configurer"' in source


def test_setup_rule_is_based_only_on_required_argument_count():
    source = (ROOT / "utils" / "command_setup_prompt.py").read_text(encoding="utf-8")

    start = source.index("def should_offer_setup")
    end = source.index("\n\ndef _field_label", start)
    block = source[start:end]

    assert "return len(params) >= 2" in block
    assert "_FAST_COMMANDS" not in block
    assert "_SETUP_HINTS" not in block
