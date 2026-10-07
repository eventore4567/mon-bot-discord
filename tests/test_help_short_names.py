from types import SimpleNamespace

from cogs import help as help_cog

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_help_uses_short_prefix_name_as_primary_display():
    source = (ROOT / "cogs" / "help.py").read_text(encoding="utf-8")

    assert "def _display_name(command: commands.Command)" in source
    assert 'prefix_name = f"{prefix}{_display_name(command)}"' in source
    assert 'label = f"/{slash}  ·  {prefix_name}" if slash else prefix_name' in source
    assert 'titre=_display_name(exact)' in source
    assert '@app_commands.command(name="help"' in source


def test_help_keeps_long_command_name_as_alternate():
    source = (ROOT / "cogs" / "help.py").read_text(encoding="utf-8")

    assert "if short_name != command.qualified_name:" in source
    assert "alias.append(command.qualified_name)" in source
    assert '"Autres noms"' in source


def test_help_examples_prefer_short_name_without_breaking_long_name():
    source = (ROOT / "cogs" / "help.py").read_text(encoding="utf-8")

    assert "def _example(command: commands.Command, prefix: str)" in source
    assert 'long_call = f"{prefix}{command.qualified_name}"' in source
    assert 'short_call = f"{prefix}{_display_name(command)}"' in source


def test_help_resolves_real_published_slash_path_by_callback():
    async def business_callback():
        return None

    async def published_wrapper():
        return None

    published_wrapper.__wrapped__ = business_callback

    slash_leaf = SimpleNamespace(
        name="play",
        callback=published_wrapper,
        commands=[],
    )
    slash_root = SimpleNamespace(
        name="music",
        callback=None,
        commands=[slash_leaf],
    )
    bot = SimpleNamespace(
        tree=SimpleNamespace(get_commands=lambda type=None: [slash_root]),
    )
    command = SimpleNamespace(
        qualified_name="music play",
        callback=business_callback,
        app_command=None,
    )

    assert help_cog._slash_name(bot, command) == "music play"


def test_help_keeps_music_security_and_levels_as_distinct_categories():
    def fake_command(cog_name):
        return SimpleNamespace(cog=SimpleNamespace(qualified_name=cog_name))

    assert help_cog._category(fake_command("Music")) == "Musique"
    assert help_cog._category(fake_command("Security")) == "Sécurité"
    assert help_cog._category(fake_command("Levels")) == "Niveaux"



def test_help_search_is_accent_and_separator_insensitive():
    assert help_cog._search_key("Sécurité anti-lien") == "securite anti lien"
    assert help_cog._search_key("/musique_playlist") == "musique playlist"


def test_help_exact_match_accepts_real_slash_path():
    async def business_callback():
        return None

    async def published_wrapper():
        return None

    published_wrapper.__wrapped__ = business_callback
    leaf = SimpleNamespace(name="play", callback=published_wrapper, commands=[])
    root = SimpleNamespace(name="music", callback=None, commands=[leaf])
    bot = SimpleNamespace(
        tree=SimpleNamespace(get_commands=lambda type=None: [root]),
    )
    command = SimpleNamespace(
        name="play",
        qualified_name="music play",
        callback=business_callback,
        app_command=None,
        aliases=[],
    )

    assert help_cog._exact_match(bot, [command], "/music play") is command


def test_help_catalog_hides_container_only_and_duplicate_business_callback():
    async def business_callback():
        return None

    container = SimpleNamespace(
        hidden=False,
        commands=[object()],
        invoke_without_command=False,
        qualified_name="music",
        callback=None,
    )
    first = SimpleNamespace(
        hidden=False,
        commands=[],
        invoke_without_command=False,
        qualified_name="play",
        callback=business_callback,
    )
    duplicate = SimpleNamespace(
        hidden=False,
        commands=[],
        invoke_without_command=False,
        qualified_name="music play",
        callback=business_callback,
    )
    hidden = SimpleNamespace(
        hidden=True,
        commands=[],
        invoke_without_command=False,
        qualified_name="secret",
        callback=lambda: None,
    )
    bot = SimpleNamespace(walk_commands=lambda: [container, first, duplicate, hidden])

    rows = help_cog._visible(bot)

    assert rows == [first]



def test_help_root_is_preserved_by_final_slash_rebuild():
    source = (ROOT / "sentrix_v95_runtime.py").read_text(encoding="utf-8")

    direct_line = source.split("DIRECT_ROOTS =", 1)[1].split("\n", 1)[0]
    preserved_line = source.split("PRESERVED_DIRECT_ROOTS =", 1)[1].split("\n", 1)[0]

    assert '"help"' in direct_line
    assert '"help"' in preserved_line
    assert '"aide"' not in direct_line
    assert '"aide"' not in preserved_line


def test_final_rebuild_removes_legacy_aide_but_keeps_help():
    source = (ROOT / "sentrix_v95_runtime.py").read_text(encoding="utf-8")

    direct_line = source.split("DIRECT_ROOTS =", 1)[1].split("\n", 1)[0]
    preserved_line = source.split("PRESERVED_DIRECT_ROOTS =", 1)[1].split("\n", 1)[0]

    assert '"help"' in direct_line
    assert '"help"' in preserved_line
    assert 'for name in ("aide",):' in source


def test_legacy_aide_is_removed_after_all_prepare_layers_before_audit():
    source = (ROOT / "sentrix_v95_runtime.py").read_text(encoding="utf-8")
    prepare = source.index("await prepare_bot(client)")
    cleanup = source.index("_remove_legacy_public_roots(self)", prepare)
    audit = source.index("issues = assert_registry_clean(client)", cleanup)
    sync = source.index("return await _ORIGINAL_SYNC(self, *args, **kwargs)", audit)

    assert prepare < cleanup < audit < sync



def test_components_detail_uses_real_published_slash_path():
    source = (ROOT / "cogs" / "help.py").read_text(encoding="utf-8")
    block = source[
        source.index("def _sections_detail("):
        source.index("def _sections_liste(", source.index("def _sections_detail("))
    ]

    assert "slash = _slash_name(bot, command)" in block
    assert "_slash_map(bot).get(command.qualified_name.casefold())" not in block
