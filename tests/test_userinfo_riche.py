"""+userinfo doit renseigner, pas afficher quatre lignes.

Avant : ID, date de creation, date d'arrivee, liste des roles. Rien sur les pouvoirs
reels du membre, rien sur un timeout en cours, rien sur l'anciennete du compte —
alors que ce sont precisement les informations qu'un moderateur cherche.
"""
import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "cogs" / "utility.py").read_text(encoding="utf-8")


def _corps_de(chemin: str, nom: str) -> str:
    """Corps d'une fonction dans un AUTRE fichier que celui teste."""
    source = (ROOT / chemin).read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name == nom:
            return ast.unparse(node)
    raise AssertionError(f"{nom} introuvable dans {chemin}")


def _corps(nom: str) -> str:
    for node in ast.walk(ast.parse(SOURCE)):
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name == nom:
            return ast.unparse(node)
    raise AssertionError(f"{nom} introuvable")


def test_userinfo_ouvre_sur_une_phrase_pas_sur_un_tableau():
    corps = _corps("userinfo")
    assert "sous_titre=resume" in corps
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
    assert "Exclusion temporaire" in corps


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


# ------------------------------------------------- mention reelle et @@everyone
def test_userinfo_ping_reellement_la_personne_visee():
    """La fiche membre doit notifier la personne concernee.

    Le mecanisme A CHANGE avec le passage en panneau. Une mention dans un EMBED
    ne notifie jamais, d'ou l'ancien envoi via le `content` du message. Mais
    Discord REFUSE un `content` sur un message Components V2 : discord.py y pose
    le drapeau `components_v2` et l'API repond 400. La mention vit donc
    maintenant dans le texte du panneau, et `allowed_mentions` decide seul si
    elle notifie.

    Ce qui est verifiable ici : la mention est presente, la personne est
    nommement autorisee, et ni @everyone ni les roles ne le sont. Que Discord
    declenche effectivement la notification depuis un composant de texte ne peut
    se constater qu'en conditions reelles.
    """
    corps = _corps("userinfo")
    assert "membre.mention" in corps
    assert "mentionner=cible" in corps
    # Garde volontaire : ni soi-meme, ni un bot.
    assert "membre.id != ctx.author.id" in corps
    assert "not membre.bot" in corps

    envoi = _corps_de("utils/sentrix_panels.py", "envoyer")
    assert "users=[mentionner]" in envoi
    assert "roles=False" in envoi
    assert "everyone=False" in envoi
    # Un content passe par erreur ferait echouer l'envoi cote Discord.
    assert "kwargs.pop('content', None)" in envoi


def test_avatar_garde_le_ping_par_le_contenu():
    """+avatar repond encore en embed : pour lui, le content reste la bonne voie."""
    corps = _corps("_envoi_cible")
    assert "envoi['content'] = membre.mention" in corps
    assert "users=[membre]" in corps
    assert "_envoi_cible" in _corps("avatar")



def test_userinfo_ne_ping_ni_soi_meme_ni_un_bot():
    corps = _corps("_envoi_cible")
    assert "getattr(auteur, 'id', None) != getattr(membre, 'id', None)" in corps
    assert "getattr(membre, 'bot', False)" in corps


def test_userinfo_n_autorise_que_la_personne_visee():
    """Jamais everyone ni les roles : une fiche d'info ne doit pas alerter le serveur."""
    corps = _corps("_envoi_cible")
    assert "roles=False" in corps
    assert "everyone=False" in corps


def test_serverinfo_n_affiche_plus_everyone_dans_les_roles():
    """role.name du role par defaut vaut litteralement "@everyone" : d'ou le "@@everyone"."""
    corps = _corps("info_serveur")
    assert "role != guild.default_role" in corps


def test_le_helper_de_ping_n_est_pas_utilise_hors_portee():
    """Regression : un remplacement global l'avait glisse dans help_cmd, ou membre
    n'existe pas — NameError a chaque affichage de l'aide d'une commande."""
    source = (ROOT / "cogs" / "utility.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
            continue
        corps = ast.unparse(node)
        if "_envoi_cible(ctx, membre" not in corps:
            continue
        parametres = [a.arg for a in node.args.args]
        assert "membre" in parametres, f"{node.name} appelle _envoi_cible sans parametre membre"
