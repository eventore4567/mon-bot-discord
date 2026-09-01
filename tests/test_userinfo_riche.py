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


# ------------------------------------------------------------- channelinfo
def test_channelinfo_ouvre_sur_une_phrase():
    corps = _corps("channelinfo")
    assert "salon.mention" in corps and "`{salon.id}`" in corps
    assert "types_lisibles" in corps, "le type brut de discord.py est illisible"


def test_channelinfo_adapte_les_reglages_au_type_de_salon():
    corps = _corps("channelinfo")
    assert "VoiceChannel" in corps and "bitrate" in corps
    assert "TextChannel" in corps and "threads" in corps
    assert "slowmode_delay" in corps


def test_channelinfo_dit_qui_a_acces():
    """Un salon prive doit etre annonce comme tel, pas devine."""
    corps = _corps("channelinfo")
    assert "Salon privé" in corps
    assert "overwrites" in corps


def test_channelinfo_signale_ce_que_sentrix_ne_peut_pas_faire():
    """Le vrai piege : un salon configure ou le bot ne peut pas ecrire."""
    corps = _corps("channelinfo")
    assert "SentriX ne peut pas" in corps
    assert "permissions_for" in corps


def test_channelinfo_ne_fait_aucune_ecriture():
    corps = _corps("channelinfo")
    for interdit in ("db.execute", "INSERT", "UPDATE", "DELETE"):
        assert interdit not in corps


# ---------------------------------------------------------------- botinfo
def _corps_stats(nom: str) -> str:
    source = (ROOT / "cogs" / "stats.py").read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name == nom:
            return ast.unparse(node)
    raise AssertionError(f"{nom} introuvable")


def test_botinfo_ne_dit_plus_developpe_pour_ce_serveur():
    """C'etait un texte de remplissage, pas une information."""
    corps = _corps_stats("botinfo")
    assert "Développé pour ce serveur" not in corps


def test_botinfo_nomme_le_vrai_createur():
    corps = _corps_stats("botinfo")
    assert "PRIMARY_CREATOR_ID" in corps


def test_botinfo_donne_la_portee_reelle():
    corps = _corps_stats("botinfo")
    assert "member_count" in corps
    assert "walk_commands" in corps and "tree.walk_commands" in corps


def test_botinfo_qualifie_la_latence_au_lieu_de_l_afficher_brute():
    """« 87 ms — excellente » se lit ; « 0.087 » ne dit rien a un membre."""
    corps = _corps_stats("botinfo")
    assert "excellente" in corps and "dégradée" in corps


def test_botinfo_resiste_a_une_latence_indisponible():
    """bot.latency vaut nan tant que la websocket n'a pas de heartbeat."""
    corps = _corps_stats("botinfo")
    assert "latence == latence" in corps, "le cas nan n'est pas traite"
