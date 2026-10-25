"""Prouve que l'audit observe le code ACTIF, pas seulement le fichier source."""
from pathlib import Path

from tools import critical_method_provenance as provenance


class Demo:
    async def critical(self):
        return "original"


def _reference():
    original = Demo.critical
    return Path(original.__code__.co_filename), original.__code__.co_firstlineno


def test_original_method_is_not_reported_as_replacement():
    path, line = _reference()
    result = provenance.inspect_effective_method(Demo, "critical", path, line)
    assert result["status"] == "original"
    assert not result["replaced"]


def test_explicit_wrapper_retains_link_to_original(monkeypatch):
    original = Demo.critical

    async def wrapped(self):
        return await original(self)

    monkeypatch.setattr(Demo, "critical", wrapped)
    path, line = Path(original.__code__.co_filename), original.__code__.co_firstlineno
    result = provenance.inspect_effective_method(Demo, "critical", path, line)
    assert result["status"] == "wrapped_original_reachable"
    assert result["replaced"] and result["original_linked"]


def test_hard_replacement_is_visible_without_claiming_it_is_broken(monkeypatch):
    original = Demo.critical

    async def replacement(self):
        return "new"

    monkeypatch.setattr(Demo, "critical", replacement)
    path, line = Path(original.__code__.co_filename), original.__code__.co_firstlineno
    result = provenance.inspect_effective_method(Demo, "critical", path, line)
    assert result["status"] == "replacement_without_observable_original_link"
    assert result["replaced"] and not result["original_linked"]


def test_missing_method_is_visible():
    path, line = _reference()
    assert provenance.inspect_effective_method(Demo, "missing", path, line)["status"] == "missing"


def test_ast_reference_is_independent_of_runtime_patch(tmp_path):
    folder = tmp_path / "cogs"
    folder.mkdir()
    path = folder / "synthetic.py"
    path.write_text(
        "class Synthetic:\n"
        "    async def target(self):\n"
        "        return None\n", encoding="utf-8",
    )
    file, line = provenance.original_definition(tmp_path, "cogs.synthetic", "Synthetic", "target")
    assert file == path.resolve()
    assert line == 2
