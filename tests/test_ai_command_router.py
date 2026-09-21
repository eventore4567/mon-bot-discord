from types import SimpleNamespace

from utils import ai_command_router


class _FakeBot:
    def __init__(self, commands):
        self._commands = commands

    def walk_commands(self):
        return list(self._commands)


def _cmd(name, *, aliases=(), description="", signature="", hidden=False, enabled=True):
    return SimpleNamespace(
        qualified_name=name,
        name=name.split(" ", 1)[0],
        aliases=list(aliases),
        description=description,
        help="",
        signature=signature,
        hidden=hidden,
        enabled=enabled,
    )


def test_build_command_index_filters_hidden_disabled_and_ai_family(monkeypatch):
    monkeypatch.setattr(
        ai_command_router.access_matrix,
        "module_for_command",
        lambda root: "ai" if root == "ai" else "moderation",
    )
    bot = _FakeBot([
        _cmd("ban", aliases=["bannir"], description="Bannir un membre"),
        _cmd("ai ask", description="Question IA"),
        _cmd("secret", hidden=True),
        _cmd("disabled", enabled=False),
    ])

    index = ai_command_router.build_command_index(bot)

    names = [command.qualified_name for command, _qualified, _tokens in index]
    assert names == ["ban"]


def test_rank_command_candidates_prefers_explicit_command_name(monkeypatch):
    monkeypatch.setattr(
        ai_command_router.access_matrix,
        "module_for_command",
        lambda _root: "moderation",
    )
    ban = _cmd("ban", aliases=["bannir"], description="Bannir un membre")
    mute = _cmd("mute", aliases=["timeout"], description="Rendre muet un membre")
    setup = _cmd("setup", description="Configurer SentriX")
    index = ai_command_router.build_command_index(_FakeBot([ban, mute, setup]))

    ranked = ai_command_router.rank_command_candidates(
        index,
        "SentriX ban @Tomioka pour spam",
    )

    assert ranked
    assert ranked[0] is ban


def test_rank_command_candidates_uses_aliases_and_descriptions(monkeypatch):
    monkeypatch.setattr(
        ai_command_router.access_matrix,
        "module_for_command",
        lambda _root: "moderation",
    )
    clear = _cmd(
        "clear",
        aliases=["purge"],
        description="Supprimer plusieurs messages du salon",
        signature="[nombre]",
    )
    role = _cmd("role", description="Gérer les rôles")
    index = ai_command_router.build_command_index(_FakeBot([clear, role]))

    ranked = ai_command_router.rank_command_candidates(
        index,
        "supprime 20 messages du salon",
    )

    assert ranked
    assert ranked[0] is clear


def test_rank_command_candidates_respects_limit(monkeypatch):
    monkeypatch.setattr(
        ai_command_router.access_matrix,
        "module_for_command",
        lambda _root: "moderation",
    )
    commands = [
        _cmd(f"test{i}", description="commande test action serveur")
        for i in range(30)
    ]
    index = ai_command_router.build_command_index(_FakeBot(commands))

    ranked = ai_command_router.rank_command_candidates(
        index,
        "commande test action serveur",
        limit=7,
    )

    assert len(ranked) == 7
