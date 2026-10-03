from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_ticket_autoclose_loop_is_fault_isolated_and_restartable():
    source = (ROOT / "cogs" / "tickets.py").read_text(encoding="utf-8")

    assert "async def _process_autoclose_row" in source
    assert "WHERE id = ? AND status = 'ouvert'" in source
    assert "@check_autoclose.error" in source
    assert "self.check_autoclose.restart()" in source
    assert "for row in rows:" in source
    assert "await self._process_autoclose_row(row)" in source
    assert "except Exception:" in source


def test_ticket_autoclose_has_safe_fallbacks():
    source = (ROOT / "cogs" / "tickets.py").read_text(encoding="utf-8")

    # Un transcript ou un journal indisponible ne doit pas empêcher la fermeture :
    # le ticket se ferme quand même, sans sa pièce jointe.
    assert "transcript = None" in source
    assert "Journal auto-close indisponible" in source


def test_lautoclose_ferme_mais_ne_supprime_jamais():
    """L'assertion précédente exigeait « délai de secours 30s » — le repli du
    délai qui servait à PLANIFIER la suppression du salon.

    Cette suppression a été retirée volontairement le 03/10/2026 : auto-close
    ferme le ticket, la suppression reste une action staff explicite. Le repli a
    donc disparu avec ce qu'il protégeait, et l'assertion rougissait sur une
    phrase de commentaire tout en contredisant
    tests/test_ticket_fermer_nest_pas_supprimer.py.

    Ce qui compte vraiment est l'inverse : la boucle ne doit JAMAIS programmer
    une suppression. Lu sur l'AST, pas par sous-chaîne — `_auto_delete` reste
    défini, et c'est son APPEL qui est interdit.
    """
    import ast

    arbre = ast.parse((ROOT / "cogs" / "tickets.py").read_text(encoding="utf-8"))
    appels = [
        ast.unparse(noeud)
        for noeud in ast.walk(arbre)
        if isinstance(noeud, ast.Call)
        and ast.unparse(noeud.func).endswith("_auto_delete")
    ]
    assert appels == [], (
        f"une suppression automatique est de nouveau programmée : {appels}"
    )
