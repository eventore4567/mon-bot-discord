"""La page d'accueil de +setup doit montrer l'ETAT, pas seulement des instructions.

Avant : « 1. Choisissez une categorie. 2. Modifiez. 3. Enregistrez. » — un
proprietaire de serveur ne pouvait pas savoir ce qui etait deja en place ni ce qui
manquait sans ouvrir chaque categorie une par une.
"""
import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "cogs" / "setup_experience_v2.py").read_text(encoding="utf-8")


def _fonction(nom: str):
    for node in ast.walk(ast.parse(SOURCE)):
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name == nom:
            return ast.unparse(node)
    raise AssertionError(f"{nom} introuvable")


def test_l_accueil_calcule_un_etat():
    corps = _fonction("spacious_home_embed")
    assert "_etat_configuration" in corps


def test_l_etat_distingue_configure_et_manquant():
    corps = _fonction("spacious_home_embed")
    assert "Déjà configuré" in corps
    assert "À configurer" in corps


def test_l_etat_signale_les_permissions_manquantes_du_bot():
    """Un reglage sans la permission Discord correspondante reste sans effet."""
    corps = _fonction("_etat_configuration")
    assert "guild_permissions" in corps
    assert "manage_roles" in corps and "ban_members" in corps
    accueil = _fonction("spacious_home_embed")
    assert "Permissions manquantes" in accueil


def test_l_etat_lit_les_routes_de_logs_par_categorie():
    corps = _fonction("_etat_configuration")
    assert "get_log_config" in corps
    assert "CATEGORIES" in corps


def test_chaque_bloc_est_isole_par_un_try_except():
    """Une categorie illisible ne doit jamais empecher le panneau de s'ouvrir."""
    corps = _fonction("_etat_configuration")
    assert corps.count("except Exception") >= 3
    accueil = _fonction("spacious_home_embed")
    assert "except Exception" in accueil


def test_l_etat_ne_fait_aucune_ecriture():
    """Afficher l'accueil ne doit rien modifier."""
    corps = _fonction("_etat_configuration")
    for interdit in ("db.execute", "set_log_config", "set_guild_config", "INSERT", "UPDATE", "DELETE"):
        assert interdit not in corps, f"l'affichage de l'accueil ecrit : {interdit}"


def test_la_fonction_locale_ne_passe_pas_par_self():
    """_etat_configuration est une fonction locale, pas une methode de SetupView."""
    corps = _fonction("_etat_configuration")
    assert "self." not in corps
    accueil = _fonction("spacious_home_embed")
    assert "self._etat_configuration" not in accueil
