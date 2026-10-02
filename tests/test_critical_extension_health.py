from pathlib import Path
import ast


ROOT = Path(__file__).resolve().parents[1]


def _literal_assignment(source: str, name: str):
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name for target in node.targets
        ):
            if isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name):
                if node.value.func.id == "frozenset" and node.value.args:
                    return ast.literal_eval(node.value.args[0])
            return ast.literal_eval(node.value)
    raise AssertionError(f"{name} introuvable")


def test_critical_extensions_are_real_extensions():
    source = (ROOT / "main.py").read_text(encoding="utf-8")
    extensions = set(_literal_assignment(source, "EXTENSIONS"))
    critical = set(_literal_assignment(source, "CRITICAL_EXTENSIONS"))

    assert critical
    assert critical <= extensions
    assert {
        "cogs.moderation",
        "cogs.automod",
        "cogs.tickets",
        "cogs.logs",
    } <= critical


def test_healthcheck_fails_when_critical_extension_is_missing():
    source = (ROOT / "web" / "dashboard.py").read_text(encoding="utf-8")
    assert '"critical_failed"' in source
    assert "ok = bool(ready and not critical_failed)" in source
    assert "status=200 if ok else 503" in source


def test_v45_uses_critical_extension_health():
    source = (ROOT / "web" / "health_runtime_v45.py").read_text(encoding="utf-8")
    assert "_sentrix_extension_health" in source
    assert "critical_extensions_failed" in source
    assert "failed_extensions" in source
