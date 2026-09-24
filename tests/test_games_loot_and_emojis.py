"""Les mini-jeux gardent leurs pictogrammes, et chaque manche solo ramène une prise.

Deux problèmes mesurés le 23/09/2026 sur le bot booté :
- la couche de sobriété typographique effaçait TOUS les emojis, y compris ceux des
  jeux : la machine à sous affichait « 🎰 |  |  », des rouleaux vides ;
- une manche gagnante affichait une phrase au hasard et un montant, sans rien qui
  distingue deux parties.
"""
from __future__ import annotations

import textwrap
from types import SimpleNamespace

from cogs.games_catalog import GAME_CATALOG, RARETES, SOLO_FLAVORS, SOLO_LOOT


def _contexte_de_jeu(nom: str, cog: str = "GamesSolo"):
    from cogs import final_interaction_policy as policy

    return policy._COMMAND_CONTEXT.set(
        SimpleNamespace(command=SimpleNamespace(
            qualified_name=nom, name=nom, root_parent=None, cog_name=cog,
        ))
    )


def test_un_mini_jeu_garde_ses_pictogrammes():
    from cogs import final_interaction_policy as policy
    from utils import embeds
    from utils.game_context import commande_de_jeu

    rouleaux = "🎰 🍒 | 🍋 | 💎"
    jeton = _contexte_de_jeu("slots", "Minigames")
    try:
        assert commande_de_jeu() is True
        assert embeds.strip_emojis(rouleaux) == rouleaux, "les rouleaux ne doivent pas être vidés"
    finally:
        policy._COMMAND_CONTEXT.reset(jeton)


def test_le_reste_du_bot_reste_sobre():
    """L'exception ne vaut QUE pour les jeux : ailleurs, la règle ne change pas."""
    from cogs import final_interaction_policy as policy
    from utils import embeds
    from utils.game_context import commande_de_jeu

    jeton = _contexte_de_jeu("ban", "Moderation")
    try:
        assert commande_de_jeu() is False
        assert "🔨" not in embeds.strip_emojis("🔨 Membre banni")
    finally:
        policy._COMMAND_CONTEXT.reset(jeton)
    assert commande_de_jeu() is False  # hors commande


def test_perdre_une_partie_n_est_pas_une_erreur():
    """« Action impossible — Machine à sous » donnait à une défaite l'allure d'une panne."""
    from cogs import final_interaction_policy as policy
    from utils import design_system

    jeton = _contexte_de_jeu("slots", "Minigames")
    try:
        assert design_system.kind_title("Machine à sous", kind="danger", category_emoji="") == "Machine à sous"
    finally:
        policy._COMMAND_CONTEXT.reset(jeton)
    # Ailleurs, le libellé d'état reste affiché.
    assert design_system.kind_title("Bannissement", kind="danger", category_emoji="").startswith("Action impossible")


def test_chaque_jeu_solo_a_une_table_de_butin_complete():
    assert set(SOLO_LOOT) == set(SOLO_FLAVORS), "un jeu solo sans butin retomberait sur l'ancien texte"
    rarete_cles = {cle for cle, _libelle, _poids, _mult in RARETES}
    for jeu, table in SOLO_LOOT.items():
        assert set(table) == rarete_cles, f"{jeu} : raretés manquantes"
        for cle, objets in table.items():
            assert objets, f"{jeu}/{cle} vide"
            for emoji, nom in objets:
                assert emoji and nom, f"{jeu}/{cle} : objet incomplet"
                assert nom.strip() == nom


def test_les_poids_de_rarete_font_cent_et_montent_avec_le_gain():
    assert sum(poids for _cle, _libelle, poids, _mult in RARETES) == 100
    multiplicateurs = [mult for _cle, _libelle, _poids, mult in RARETES]
    poids = [p for _cle, _libelle, p, _mult in RARETES]
    assert multiplicateurs == sorted(multiplicateurs), "le gain doit croître avec la rareté"
    assert poids == sorted(poids, reverse=True), "plus c'est rare, plus c'est rare"


def test_le_tirage_de_butin_respecte_le_catalogue():
    from cogs.games_economy import tirer_butin

    for jeu in SOLO_LOOT:
        connus = {
            (emoji, nom): libelle
            for cle, libelle, _poids, _mult in RARETES
            for emoji, nom in SOLO_LOOT[jeu][cle]
        }
        for _ in range(60):
            butin = tirer_butin(jeu)
            assert butin is not None, jeu
            emoji, nom, rarete, multiplicateur = butin
            assert connus.get((emoji, nom)) == rarete, f"{jeu} : {nom} classé {rarete}"
            assert multiplicateur >= 1.0
    assert tirer_butin("commande-inconnue") is None


def test_le_journal_de_jeu_nomme_le_jeu_et_le_joueur():
    """Le journal affichait « Jeu : > » : un titre vide, sans le nom du jeu."""
    from utils.game_rewards import jeu_libelle

    assert jeu_libelle("slots") == GAME_CATALOG["slots"][0]
    assert jeu_libelle("fishing").endswith("Pêche")
    assert jeu_libelle("inconnu") == "inconnu"


def test_une_etiquette_en_gras_n_est_jamais_prise_pour_un_nom():
    """« **Joueur :** <@123> » affichait « Joueur : » comme titre du journal."""
    import discord

    from utils import wide_logs

    embed = discord.Embed(
        title="Récompense",
        description="**Joueur :** <@100000000000000042>\n**Récompense :** 20",
    )
    nom, identifiant, _icone = wide_logs.derive_identity(embed, log_type="game_reward")
    assert nom != "Joueur :"
    assert identifiant == 100000000000000042


def test_la_prise_est_bien_affichee_dans_la_manche_gagnee():
    """Un rebase avait déjà supprimé le butin du rendu : le tirage existait,
    mais le joueur ne voyait jamais ce qu'il avait ramené."""
    import ast
    import inspect

    from cogs.games_economy import GamesSolo

    source = inspect.getsource(GamesSolo._run_solo)
    arbre = ast.parse(textwrap.dedent(source))
    appels = {
        n.func.id
        for n in ast.walk(arbre)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    }
    assert "tirer_butin" in appels, "la manche ne tire plus de prise"
    noms = {n.id for n in ast.walk(arbre) if isinstance(n, ast.Name)}
    assert "butin_text" in noms, "la prise est tirée mais jamais rendue"
    # Le texte de la prise doit vraiment atterrir dans une f-string du rendu.
    rendus = [
        n
        for n in ast.walk(arbre)
        if isinstance(n, ast.JoinedStr)
        and any(
            isinstance(v, ast.FormattedValue)
            and isinstance(v.value, ast.Name)
            and v.value.id == "butin_text"
            for v in n.values
        )
    ]
    assert rendus, "butin_text n'apparaît dans aucun texte envoyé au joueur"


def test_la_prise_part_avec_la_manche_dans_les_metadonnees():
    """Sans ce passage, la collection resterait vide quoi qu'on ramène."""
    import asyncio

    from cogs import games_economy
    from utils import game_rewards

    vu = {}

    async def _faux_reward(bot, guild_id, user_id, game_name, base, sid, result="win", metadata=None):
        vu["metadata"] = metadata
        return None

    async def _rien(*a, **k):
        return None

    ctx = SimpleNamespace(
        guild=SimpleNamespace(id=1),
        author=SimpleNamespace(id=2),
    )
    anciens = (game_rewards.reward_game_winner, game_rewards.touch_cooldown, game_rewards.release_play_lock)
    game_rewards.reward_game_winner = _faux_reward
    game_rewards.touch_cooldown = _rien
    game_rewards.release_play_lock = lambda *a, **k: None
    try:
        asyncio.run(games_economy._finish(
            None, ctx, "fishing", "sid", "win", 40,
            metadata={"butin": {"emoji": "🐟", "nom": "Truite", "rarete": "Commun"}},
        ))
    finally:
        (game_rewards.reward_game_winner, game_rewards.touch_cooldown,
         game_rewards.release_play_lock) = anciens

    assert vu["metadata"]["butin"]["nom"] == "Truite"


def test_la_collection_ne_retient_que_les_manches_gagnees_avec_prise():
    """La requête filtre en SQL : une défaite ou un simple boost ne doit pas
    entrer dans la collection, sinon le compteur ment."""
    import ast
    import json as _json
    import sqlite3

    arbre = ast.parse(open("database/db.py", encoding="utf-8").read())
    fonction = next(
        n for n in ast.walk(arbre)
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "get_game_loot"
    )
    requete = next(
        n.value for n in ast.walk(fonction)
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and "SELECT" in n.value
    )

    base = sqlite3.connect(":memory:")
    base.row_factory = sqlite3.Row
    base.execute(
        "CREATE TABLE game_transactions (id INTEGER PRIMARY KEY, guild_id INTEGER,"
        " user_id INTEGER, game_name TEXT, game_session_id TEXT, result TEXT,"
        " reward_amount INTEGER, created_at INTEGER, metadata_json TEXT)"
    )
    prise = _json.dumps({"butin": {"emoji": "🐟", "nom": "Truite", "rarete": "Commun"}})
    base.executemany(
        "INSERT INTO game_transactions (guild_id, user_id, game_name, game_session_id,"
        " result, reward_amount, created_at, metadata_json) VALUES (?,?,?,?,?,?,?,?)",
        [
            (1, 1, "fishing", "s1", "win", 40, 100, prise),
            (1, 1, "fishing", "s2", "win", 40, 101, _json.dumps({"money_boost": 1.5})),
            (1, 1, "mining", "s3", "loss", 0, 102, prise),
            (1, 2, "fishing", "s4", "win", 40, 103, prise),
        ],
    )
    lignes = list(base.execute(requete, (1, 1, 50)))
    assert [l["game_name"] for l in lignes] == ["fishing"], "la collection compte des manches qu'elle ne devrait pas"
