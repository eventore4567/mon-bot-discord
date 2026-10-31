"""Le panel public doit respecter le texte administrateur et rester sans blocs automatiques."""
import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace
import unittest


SOURCE = Path(__file__).resolve().parents[1] / "cogs" / "tickets.py"


def _renderer():
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    ticket_class = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Tickets")
    render = next(n for n in ticket_class.body if isinstance(n, ast.AsyncFunctionDef)
                  and n.name == "build_public_panel")
    scope = {
        "language_runtime": SimpleNamespace(
            LANG_FR="fr", LANG_EN="en",
            get_language=lambda *_args: _language()
        ),
        "sx_panels": SimpleNamespace(
            Panneau=lambda **kw: kw,
            avec_composants=lambda panel, view: (panel, view),
        ),
        "TicketPanelView": lambda panel, types, lang: (panel, types, lang),
    }
    exec(compile(ast.fix_missing_locations(ast.Module(body=[render], type_ignores=[])),
                 str(SOURCE), "exec"), scope)
    return scope["build_public_panel"]


async def _language():
    return "en"  # Simule un ancien serveur configuré en anglais.


class TicketPanelFrenchOnly(unittest.TestCase):
    def test_no_auto_sections_even_with_multiple_categories(self):
        panel = {
            "guild_id": 123, "title": "Centre d'assistance",
            "description": "Bienvenue chez Tomioka et Selimor.",
            "thumbnail_url": None, "image_url": None, "footer_text": None,
        }
        types = [{"name": "Assistance"}, {"name": "Signalement"}]
        renderer = _renderer()
        public, view = asyncio.run(renderer(SimpleNamespace(bot=object()), panel, types))
        self.assertEqual(public["sous_titre"], panel["description"])
        self.assertEqual(public["sections"], [])
        self.assertEqual(public["titre"], panel["title"])
        self.assertEqual(view[1], types)

    def test_empty_description_uses_short_french_fallback(self):
        panel = {
            "guild_id": 123, "title": "Tickets",
            "description": "", "thumbnail_url": None, "image_url": None, "footer_text": None,
        }
        public, _view = asyncio.run(_renderer()(SimpleNamespace(bot=object()), panel, []))
        self.assertIn("Choisissez une catégorie", public["sous_titre"])
        self.assertNotIn("Choose", public["sous_titre"])
        self.assertEqual(public["sections"], [])

    def test_select_placeholder_not_english(self):
        tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
        select_class = next(n for n in tree.body if isinstance(n, ast.ClassDef)
                            and n.name == "TicketOpenSelect")
        init = next(n for n in select_class.body if isinstance(n, ast.FunctionDef)
                    and n.name == "__init__")
        placeholders = []
        for node in ast.walk(init):
            if isinstance(node, ast.keyword) and node.arg == "placeholder":
                placeholders.append(node.value)
        self.assertEqual(len(placeholders), 1)
        self.assertIsInstance(placeholders[0], ast.Constant)
        self.assertIn("Choisissez une catégorie", placeholders[0].value)
        self.assertNotIn("Choose a category", placeholders[0].value)


if __name__ == "__main__":
    unittest.main()
