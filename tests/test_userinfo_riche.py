"""+userinfo doit renseigner, pas afficher quatre lignes.

Avant : ID, date de creation, date d'arrivee, liste des roles. Rien sur les pouvoirs
reels du membre, rien sur un timeout en cours, rien sur l'anciennete du compte —
alors que ce sont precisement les informations qu'un moderateur cherche.
"""
import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "cogs" / "utility.py").read_text(encoding="utf-8")


def _corps(nom: str) -> str:
    for node in ast.walk(ast.parse(SOURCE)):
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name == nom:
            return ast.unparse(node)
    raise AssertionError(f"{nom} introuvable")


def test_userinfo_ouvre_sur_une_phrase_pas_sur_un_tableau():
    corps = _corps("userinfo")
    assert "description=ouverture" in corps
    assert "Membre du serveur depuis" in corps


def test_l_identifiant_est_en_inline_code_apres_la_mention():
    corps = _corps("userinfo")
    assert "membre.mention" in corps and "`{membre.id}`" in corps


def test_les_dates_utilisent_le_format_discord():
    """Jamais de date formatee a la main : Discord l'affiche dans le fuseau du lecteur."""
    corps = _corps("userinfo")
    assert "<t:{cree}:D>" in corps
    assert "strftime" not in corps


def test_un_compte_recent_est_signale():
    """Information cle pour la moderation : un compte de moins de 7 jours."""
    corps = _corps("userinfo")
    assert "anciennete < 7" in corps
    assert "Compte récent" in corps


def test_un_timeout_en_cours_est_visible():
    corps = _corps("userinfo")
    assert "timed_out_until" in corps
    assert "En timeout" in corps


def test_les_pouvoirs_sont_resumes_pas_enumeres():
    """Lister les 40 permissions Discord n'aide personne ; on montre les 8 qui comptent."""
    corps = _corps("userinfo")
    assert "guild_permissions" in corps
    assert "moderate_members" in corps and "ban_members" in corps
    # Administrateur remplace la liste au lieu de s'y ajouter.
    assert "perms.administrator" in corps


def test_le_proprietaire_du_serveur_est_identifie():
    corps = _corps("userinfo")
    assert "owner_id == membre.id" in corps


def test_la_liste_des_roles_reste_bornee():
    """_limited_list evite de depasser la limite de 1024 caracteres d'un champ."""
    corps = _corps("userinfo")
    assert "_limited_list(roles" in corps


def test_userinfo_ne_fait_aucune_ecriture():
    corps = _corps("userinfo")
    for interdit in ("db.execute", "INSERT", "UPDATE", "DELETE", "set_guild_config"):
        assert interdit not in corps, f"userinfo ecrit : {interdit}"
