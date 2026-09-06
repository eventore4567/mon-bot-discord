from __future__ import annotations

import inspect

import discord
from discord.ext import commands

import cogs.verify_setup_interactive_v78 as v78
from cogs.verify_setup_interactive_v78 import VerifySetupView, _safe_image, install


def _bot() -> commands.Bot:
    return commands.Bot(command_prefix="+", intents=discord.Intents.none())


def test_v78_replaces_legacy_verification_commands_with_zero_argument_setup():
    bot = _bot()

    @bot.command(name="verify-setup")
    async def old_setup(ctx, role: str):
        return role

    @bot.command(name="verify-panel")
    async def old_panel(ctx):
        return None

    assert install(bot)
    assert bot.get_command("verify-panel") is None
    command = bot.get_command("verify-setup")
    assert command is not None
    assert list(command.clean_params) == []


def test_v78_contains_the_complete_discord_configuration_flow():
    source = inspect.getsource(v78)
    view_source = inspect.getsource(VerifySetupView)
    for marker in (
        "ChannelSelect",
        "RoleSelect",
        "Écrire / modifier le règlement",
        "Configurer l'image",
        "CAPTCHA",
        "Tentatives",
        "Enregistrer et publier",
        "verification_channel",
        "verify_role",
        "verify_captcha_enabled",
        "dashboard_verification_panels",
        "VerifyView",
        "panels.avec_composants",
        "panels.editer",
    ):
        assert marker in source, marker
    assert "interaction.response.edit_message(embed=" not in view_source
    assert "self.message.edit(embed=" not in view_source


def test_v78_only_accepts_public_https_images():
    assert _safe_image("") == ""
    assert _safe_image(" https://cdn.example.com/rules.png ") == "https://cdn.example.com/rules.png"
    try:
        _safe_image("http://example.com/rules.png")
    except ValueError as exc:
        assert "HTTPS" in str(exc)
    else:
        raise AssertionError("Une image HTTP non sécurisée a été acceptée.")
