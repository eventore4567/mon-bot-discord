"""Régressions des problèmes remontés depuis Discord le 01/11/2026."""
from __future__ import annotations

import ast
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")
ROOT = Path(__file__).resolve().parents[1]


def source(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def test_prefix_plus_is_never_replaced_by_custom_prefix():
    code = source("main.py")
    function = code.split("async def get_prefix(", 1)[1].split("class BotAllInOne", 1)[0]
    assert "return commands.when_mentioned_or(str(cached))(bot, message)" in function
    assert "Le préfixe personnalisé est réservé au listener PlatformV4" in function
    assert 'bot.prefix_cache[message.guild.id] = cached' in function


def test_legacy_ai_wrappers_cannot_see_extra_attachment_argument():
    code = source("cogs/ai.py")
    listener = code.split("    async def on_message(self, message", 1)[1]
    assert "_PASSIVE_IMAGE_CONTEXT.set(tuple(images))" in listener
    assert "_PASSIVE_IMAGE_CONTEXT.reset(token)" in listener
    after = listener.split("await self.send_sentrix_reply(", 1)[1].split(")", 1)[0]
    assert "attachments=" not in after
    assert "reply_to=message" in after
    for name in ("cogs/ai_reliability.py", "cogs/ai_api_hotfix.py"):
        assert "send_sentrix_reply" in source(name)


@pytest.mark.asyncio
async def test_ai_uses_image_from_current_message_without_polluting_next_request():
    from cogs.ai import Ai, _PASSIVE_IMAGE_CONTEXT

    fake = SimpleNamespace(
        bot=None,
        _build_system_instructions=AsyncMock(return_value="Instructions"),
    )
    output = SimpleNamespace(ok=True, text="Je vois un panneau de configuration.")
    generate = AsyncMock(return_value=output)
    token = _PASSIVE_IMAGE_CONTEXT.set(("data:image/jpeg;base64,ZGF0YQ==",))
    try:
        with patch("cogs.ai.ai_service.generate", generate):
            answer = await Ai.ask_ai(fake, "Décris l'image")
        assert "Je vois" in answer
        payload = generate.await_args.args[0]
        assert isinstance(payload, list)
        assert payload[-1]["content"][1]["type"] == "input_image"
        assert payload[-1]["content"][1]["image_url"].startswith("data:image/jpeg;base64,")
    finally:
        _PASSIVE_IMAGE_CONTEXT.reset(token)
    generate.reset_mock()
    with patch("cogs.ai.ai_service.generate", generate):
        await Ai.ask_ai(fake, "Bonjour")
    assert isinstance(generate.await_args.args[0], str)


def test_private_setup_acks_before_loading():
    code = source("sentrix_v95_runtime.py")
    portion = code.split('if str(getattr(command, "qualified_name", "")).casefold().strip() == "setup":',1)[1]
    assert "defer(ephemeral=True, thinking=True)" in portion
    assert portion.index("defer(ephemeral=True, thinking=True)") < portion.index("setup.send_setup(interaction)")


def test_custom_role_select_numeric_modal_and_embed_option():
    custom = source("cogs/setup_custom_commands.py")
    assert "class ChoisirRoleAction(discord.ui.View)" in custom
    assert "discord.ui.RoleSelect(" in custom
    assert 'label="Montant" if kind == "money" else "Points d\'expérience"' in custom
    assert "class DureeRoleModal(discord.ui.Modal" in custom
    assert 'label="Mode : embed"' not in custom or "toggle_format" in custom
    assert "ping_role_id" in custom
    platform = source("cogs/platform_v4.py")
    assert "ADD COLUMN ping_role_id" in platform
    assert "roles=[ping_role] if ping_role else False" in platform
    assert "message.channel.send(content=ping, embed=embed" in platform
    for name in ("main.py", "cogs/ai.py", "cogs/setup_custom_commands.py",
                 "cogs/platform_v4.py", "sentrix_v95_runtime.py"):
        ast.parse(source(name), filename=name)


def test_custom_prefix_applies_to_native_commands_and_cache_refreshes():
    custom = source("cogs/custom_commands.py")
    main = source("main.py")
    assert "set_custom_prefix(self.bot, ctx.guild.id, prefixe)" in custom
    assert "self.bot.db.set_guild_config(ctx.guild.id, \"prefix\", prefixe)" not in custom
    assert 'prefix_cache_refreshed' in main
    assert 'now - last_refresh >= 20' in main


def test_image_only_followup_and_private_setup_transport():
    ai = source("cogs/ai.py")
    assert "_PENDING_IMAGE_FOLLOWUPS" in ai
    assert "image_attachments and (pending or reply_to_bot)" in ai
    assert "_PASSIVE_IMAGE_CONTEXT.set(tuple(images))" in ai
    assert "ephemeral=True" in source("cogs/setup_experience_v74.py")
    assert "ephemere=True" in source("cogs/setup_invitations.py")
    assert "interaction.user.id) != self.author_id" in source("cogs/setup_components_v73.py")
    for name in ("cogs/ai.py", "cogs/setup_experience_v74.py",
                 "cogs/setup_components_v73.py", "cogs/setup_invitations.py",
                 "main.py", "cogs/custom_commands.py"):
        ast.parse(source(name), filename=name)
