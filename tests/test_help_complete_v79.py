from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
V79 = ROOT / "cogs" / "help_complete_v79.py"
V78 = ROOT / "cogs" / "help_components_v78.py"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_v79_catalog_hides_hidden_internal_and_merged_commands():
    """02/11/2026 : plus de commandes cachées, internes ni doublons dans l'aide ;
    leur fiche reste accessible par leur nom exact (avec_masquees)."""
    from types import SimpleNamespace

    from cogs import help_complete_v79 as v79

    def command(name, *, hidden=False, cog="Moderation", parents=()):
        return SimpleNamespace(qualified_name=name, name=name, hidden=hidden, cog_name=cog, parents=list(parents))

    assert v79._cachee(command("debug", hidden=True))
    assert v79._cachee(command("bot-leave", cog="Owner"))
    assert v79._cachee(command("blacklist add", parents=[SimpleNamespace(hidden=True)]))
    assert not v79._cachee(command("ban"))
    source = _source(V79)
    assert "for command in bot.walk_commands():" in source
    assert "_commandes_retirees_de_l_aide()" in source


def test_v79_catalog_includes_leaf_slash_commands_and_subcommands():
    source = _source(V79)

    assert "bot.tree.get_commands(type=discord.AppCommandType.chat_input)" in source
    assert "yield from walk(child, name)" in source
    assert "yield name, node" in source
    assert "entry.slash_name = slash_name" in source
    assert "entry.slash_command = slash_command" in source


def test_v79_merges_matching_prefix_and_slash_invocations(monkeypatch):
    """Une commande disponible en + et en / est UNE entrée d'aide, y compris quand
    son chemin slash ne porte pas le même nom : depuis utils/slash_catalog.py,
    « /economy balance » exécute +balance. Rapprocher seulement par nom faisait
    annoncer « 741 commandes uniques, 239 uniquement en / » pour 502 commandes.

    Test de comportement, pas de recherche de chaîne dans le source : l'ancienne
    version cherchait `key = _normalise(slash_name)` et rougissait à la moindre
    reformulation sans rien dire du résultat.
    """
    from types import SimpleNamespace

    import discord
    from cogs import help_complete_v79 as v79

    monkeypatch.setattr(v79.v77, "_category_key", lambda command: "economy")

    def prefix(name):
        return SimpleNamespace(qualified_name=name, name=name, hidden=False, cog_name="Economy", parents=[])

    def slash(name, source):
        callback = lambda: None  # noqa: E731
        if source:
            callback._sentrix_original_command = source
        return SimpleNamespace(name=name, callback=callback, commands=(), binding=None)

    economy = SimpleNamespace(
        name="economy", commands=(slash("balance", "balance"), slash("deposit", "deposit")), callback=None,
    )
    racines = [slash("ping", "ping"), economy, slash("orphan", None)]
    tree = SimpleNamespace(get_commands=lambda type=None: racines)
    bot = SimpleNamespace(
        walk_commands=lambda: [prefix("balance"), prefix("deposit"), prefix("ping")],
        tree=tree,
    )
    monkeypatch.setattr(v79, "_binding_name", lambda node: "")

    rows = {row.name: row for row in v79._catalog(bot)}

    # Trois commandes + : chacune réunie à son chemin slash, quel que soit son nom.
    assert rows["balance"].slash_name == "economy balance"
    assert rows["deposit"].slash_name == "economy deposit"
    assert rows["ping"].slash_name == "ping"
    # Une commande slash sans source connue reste une entrée à part.
    assert "orphan" in rows and rows["orphan"].prefix_command is None
    assert len(rows) == 4


def test_v79_has_complete_catalog_button_and_paginated_listing():
    source = _source(V79)

    assert "LIST_PAGE_SIZE = 6" in source
    assert "Toutes les commandes" in source
    assert "self.show_all()" in source
    assert "self.rows = _catalog(self.bot)" in source


def test_v79_home_shows_one_short_count():
    # Plus de « 512 commandes · 511 en + · 256 en / · 1 uniquement en / ».
    source = _source(V79)
    assert 'f"**{len(entries)} commandes**"' in source
    assert "slash_only" not in source and "prefix_count" not in source


def test_v79_is_installed_by_v78_after_v78_patch():
    source = _source(V78)

    assert "help_complete_v79" in source
    assert "v79.install(bot)" in source
