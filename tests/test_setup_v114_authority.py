import asyncio
import inspect
from types import SimpleNamespace

import sentrix_v103_setup_fix as v103


class _FakeSetupCog:
    """Le seul moteur de setup : cogs.setup_control_center.OfficialSetup.send_setup."""

    def __init__(self):
        self.calls = []

    async def send_setup(self, target):
        self.calls.append(target)


class _FakeTree:
    def __init__(self):
        self.removed = []
        self.command = None

    def remove_command(self, name, **kwargs):
        self.removed.append((name, kwargs))

    def add_command(self, command, *, override=False):
        self.command = command
        self.override = override


class _FakeBot:
    def __init__(self):
        self.setup_cog = _FakeSetupCog()
        self.tree = _FakeTree()

    def get_cog(self, name):
        if name == "SentriXSetup":
            return self.setup_cog
        return None

    async def is_owner(self, user):
        return True


def _interaction():
    return SimpleNamespace(
        guild=SimpleNamespace(id=1234),
        user=SimpleNamespace(id=5678),
        channel=SimpleNamespace(id=9999),
    )


def test_v103_routes_slash_setup_to_the_single_setup_engine():
    """/setup et +setup ouvrent le MÊME centre (OfficialSetup.send_setup) : plus de
    seconde interface Configuration.SetupView derrière la commande slash."""
    source = inspect.getsource(v103._replace_setup_slash) + inspect.getsource(v103._send_setup_v114)
    assert 'bot.get_cog("SentriXSetup")' in source
    assert ".send_setup(" in source
    assert "_open_setup_panel" not in source


def test_v103_registers_native_zero_option_v114_setup():
    bot = _FakeBot()
    assert v103._replace_setup_slash(bot) is True
    command = bot.tree.command
    assert command is not None
    assert command.name == "setup"
    assert bot.tree.override is True
    assert getattr(command.callback, "_sentrix_setup_authority", None) == "configuration-v114"
    assert list(inspect.signature(command.callback).parameters) == ["interaction"]


def test_v103_setup_callback_opens_the_same_panel_as_prefix_setup():
    bot = _FakeBot()
    interaction = _interaction()
    asyncio.run(v103._send_setup_v114(bot, interaction))
    assert bot.setup_cog.calls == [interaction]
