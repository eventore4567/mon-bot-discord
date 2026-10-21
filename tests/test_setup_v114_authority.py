"""V103 : la surface slash finale /config partage le moteur historique."""

import asyncio
import inspect
from types import SimpleNamespace

from discord import app_commands

import sentrix_v103_setup_fix as v103


class _FakeSetupCog:
    def __init__(self):
        self.calls = []

    async def send_setup(self, target, **kwargs):
        self.calls.append((target, kwargs))


class _FakeTree:
    def __init__(self):
        self.removed = []
        self.group = app_commands.Group(name="config", description="Réglages SentriX")
        self.existing = app_commands.Command(
            name="ancien", description="Commande historique",
            callback=self._noop,
        )
        self.group.add_command(self.existing)
        self.added = []

    async def _noop(self, interaction):
        return None

    def remove_command(self, name, **kwargs):
        self.removed.append((name, kwargs))

    def get_command(self, name, **kwargs):
        return self.group if name == "config" else None

    def get_commands(self, **kwargs):
        return [self.group]

    def add_command(self, command, *, override=False):
        self.group = command
        self.added.append((command, override))


class _FakeBot:
    def __init__(self):
        self.setup_cog = _FakeSetupCog()
        self.tree = _FakeTree()

    def get_cog(self, name):
        return self.setup_cog if name == "SentriXSetup" else None

    async def is_owner(self, user):
        return True


def _interaction():
    return SimpleNamespace(
        guild=SimpleNamespace(id=1234),
        user=SimpleNamespace(id=5678),
        channel=SimpleNamespace(id=9999),
    )


def test_v103_final_surface_routes_to_existing_official_setup_engine():
    source = inspect.getsource(v103._replace_setup_slash)
    assert 'bot.get_cog("SentriXSetup")' in source
    assert ".send_setup(" in source
    assert "_open_setup_panel" not in source


def test_v103_reuses_existing_config_group_keeps_legacy_leaf_and_preserves_setup():
    bot = _FakeBot()
    assert v103._replace_setup_slash(bot) is True
    group = bot.tree.group
    assert group.name == "config"
    assert bot.tree.added == []  # V98 /config n'est pas écrasé !
    names = {command.name for command in group.commands}
    assert "ancien" in names
    assert names >= {
        "accueil", "automod", "logs", "tickets", "bienvenue",
        "moderation", "niveaux",
    }
    assert "setup" not in [name for name, _ in bot.tree.removed]
    for leaf in ("accueil", "niveaux"):
        callback = group.get_command(leaf).callback
        assert getattr(callback, "_sentrix_setup_authority") == "configuration-v114"
        assert list(inspect.signature(callback).parameters) == ["interaction"]


def test_v103_config_automod_callback_opens_private_security_category():
    bot = _FakeBot()
    assert v103._replace_setup_slash(bot)
    interaction = _interaction()
    asyncio.run(bot.tree.group.get_command("automod").callback(interaction))
    assert bot.setup_cog.calls == [
        (interaction, {"category": "security", "diagnostic": False, "private": True})
    ]


def test_v103_legacy_setup_bridge_still_uses_same_engine_for_prefix():
    bot = _FakeBot()
    interaction = _interaction()
    asyncio.run(v103._send_setup_v114(bot, interaction))
    assert bot.setup_cog.calls == [(interaction, {})]
