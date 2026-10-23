"""Un arrêt gracieux ne doit pas ressembler à un crash.

Mesuré le 23/10/2026 sur les journaux Railway : à chaque déploiement, les deux
services imprimaient une pile complète en ERROR —

    File "/app/utils/failover.py", line 361, in wait_for_leadership
        raise asyncio.CancelledError
    asyncio.exceptions.CancelledError

C'est le signal d'arrêt volontaire d'une instance passive remplacée pendant
qu'elle attendait le bail. Une pile à chaque déploiement noie les vraies
erreurs : c'est précisément dans ces journaux qu'on trouve les bugs réels.
"""
import ast
import os
import pathlib

os.environ.setdefault("DISCORD_TOKEN", "x")

RACINE = pathlib.Path(__file__).resolve().parent.parent


def _bloc_principal(chemin):
    arbre = ast.parse((RACINE / chemin).read_text(encoding="utf-8"))
    for noeud in arbre.body:
        if isinstance(noeud, ast.If) and ast.unparse(noeud.test).startswith("__name__"):
            return noeud
    raise AssertionError(f"{chemin} n'a pas de bloc __main__")


def _exceptions_rattrapees(bloc):
    rattrapees = set()
    for noeud in ast.walk(bloc):
        if isinstance(noeud, ast.ExceptHandler) and noeud.type is not None:
            rattrapees.add(ast.unparse(noeud.type))
    return rattrapees


def test_le_lanceur_ha_rattrape_l_annulation():
    rattrapees = _exceptions_rattrapees(_bloc_principal("railway_ha_boot.py"))
    assert any("CancelledError" in nom for nom in rattrapees), (
        "l'arrêt pendant l'attente du bail doit sortir proprement, pas en pile : "
        f"rattrapées = {rattrapees}"
    )
    assert any("KeyboardInterrupt" in nom for nom in rattrapees), (
        "l'arrêt manuel était déjà traité, il doit le rester"
    )


def test_c_est_bien_une_annulation_qui_est_levee_pendant_l_attente():
    # Si failover cessait de signaler l'arrêt par CancelledError, la branche
    # ci-dessus deviendrait du code mort sans que rien ne le dise.
    source = (RACINE / "utils" / "failover.py").read_text(encoding="utf-8")
    debut = source.index("async def wait_for_leadership")
    fin = source.index("async def ", debut + 10)
    assert "raise asyncio.CancelledError" in source[debut:fin]
