import asyncio
import inspect
from types import SimpleNamespace

import sentrix_v103_setup_fix as v103


class _FakeConfiguration:
    def __init__(self):
        self.active_by_guild = {}
        self.calls = []

    async def _open_setup_panel(self, interaction, *, author=None):
        self.calls.append((interaction, author))


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
        self.configuration = _FakeConfiguration()
        self.tree = _FakeTree()

    def get_cog(self, name):
        if name == "Configuration":
            return self.configuration
        return None

    async def is_owner(self, user):
        return True


def _interaction():
    return SimpleNamespace(
        guild=SimpleNamespace(id=1234),
        user=SimpleNamespace(id=5678),
        channel=SimpleNamespace(id=9999),
    )


def test_v103_no_longer_executes_legacy_setup_route():
    source = inspect.getsource(v103._replace_setup_slash) + inspect.getsource(v103._send_setup_v114)
    # Vérifie le code exécutable historique, sans faire échouer le test si un docstring
    # explique simplement pourquoi l'ancien routeur ne doit plus être utilisé.
    assert "from cogs.setup_control_center import" not in source
    assert ".send_setup(" not in source
    assert 'bot.get_cog("Configuration")' in source
    assert '"_open_setup_panel"' in source


def test_v103_registers_native_zero_option_v114_setup():
    bot = _FakeBot()
    assert v103._replace_setup_slash(bot) is True
    command = bot.tree.command
    assert command is not None
    assert command.name == "setup"
    assert bot.tree.override is True
    assert getattr(command.callback, "_sentrix_setup_authority", None) == "configuration-v114"
    assert list(inspect.signature(command.callback).parameters) == ["interaction"]


def test_v103_setup_callback_opens_configuration_panel():
    bot = _FakeBot()
    interaction = _interaction()
    asyncio.run(v103._send_setup_v114(bot, interaction))
    assert bot.configuration.calls == [(interaction, interaction.user)]
