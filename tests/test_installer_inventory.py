"""Inventaire statique : signale les candidats sans les déclarer à tort inactifs."""
from tools.installer_inventory import declared_extensions, entrypoints, inventory


def test_entrypoints_only_detects_module_level_functions(tmp_path):
    source = tmp_path / "module.py"
    source.write_text(
        "async def install(bot): pass\n"
        "class Cog:\n"
        "    async def setup(self): pass\n"
        "    def install(self): pass\n",
        encoding="utf-8",
    )
    assert entrypoints(source) == {"install"}


def test_inventory_distinguishes_extension_setup_from_manual_installer(tmp_path):
    cogs = tmp_path / "cogs"
    cogs.mkdir()
    (cogs / "manual.py").write_text(
        "def install(bot): pass\n", encoding="utf-8",
    )
    (cogs / "active.py").write_text(
        "async def setup(bot): pass\n", encoding="utf-8",
    )
    (cogs / "legacy.py").write_text(
        "async def setup(bot): pass\n", encoding="utf-8",
    )
    (tmp_path / "main.py").write_text(
        'EXTENSIONS = ["cogs.active"]\n', encoding="utf-8",
    )
    (tmp_path / "railway_boot.py").write_text(
        'bot_main.EXTENSIONS.append("cogs.extra")\n', encoding="utf-8",
    )
    report = inventory(tmp_path)
    assert declared_extensions(tmp_path) == {"cogs.active", "cogs.extra"}
    assert report["install_without_setup"] == ["cogs.manual"]
    assert report["setup_not_declared_as_extension"] == ["cogs.legacy"]
    assert report["unknown_extension_modules"] == ["cogs.extra"]


def test_inventory_does_not_import_user_code(tmp_path):
    cogs = tmp_path / "cogs"
    cogs.mkdir()
    (cogs / "must_not_run.py").write_text(
        'raise RuntimeError("should not execute")\n'
        "def install(bot): pass\n",
        encoding="utf-8",
    )
    report = inventory(tmp_path)
    assert report["install_without_setup"] == ["cogs.must_not_run"]
