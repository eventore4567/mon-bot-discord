from pathlib import Path

path = Path("tests/test_access_matrix.py")
text = path.read_text(encoding="utf-8")
old = "        from cogs import permission_guard as pg\n"
new = '''        # Load only permission_guard.py. Importing ``cogs`` executes the whole\n        # cog registry and incorrectly requires a production DISCORD_TOKEN in\n        # this isolated unit test.\n        import importlib.util\n        guard_path = os.path.join(\n            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),\n            "cogs", "permission_guard.py",\n        )\n        spec = importlib.util.spec_from_file_location(\n            "sentrix_permission_guard_under_test", guard_path\n        )\n        self.assertIsNotNone(spec)\n        self.assertIsNotNone(spec.loader)\n        pg = importlib.util.module_from_spec(spec)\n        spec.loader.exec_module(pg)\n'''
if text.count(old) != 1:
    raise SystemExit(f"expected one package import, found {text.count(old)}")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
print("isolated permission_guard test import installed")
