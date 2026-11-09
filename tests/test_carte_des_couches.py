"""09/11/2026 : la carte des couches se génère et repère les fonctions les plus empilées."""
import importlib.util
import pathlib

OUTIL = pathlib.Path(__file__).resolve().parents[1] / "tools" / "carte_des_couches.py"


def test_la_carte_releve_les_couches_partagees():
    spec = importlib.util.spec_from_file_location("carte_des_couches", OUTIL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    cibles = module.relever()
    assert len(cibles["generate"]) >= 2                      # l'IA est enveloppée plusieurs fois
    assert "callback" not in cibles and "message" not in cibles  # le câblage d'interface n'est pas compté
    texte = module.ecrire(cibles)
    assert texte.startswith("# Carte des couches de SentriX") and "| `generate` |" in texte
