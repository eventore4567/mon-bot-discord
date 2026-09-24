"""Les mini-jeux gardent leurs pictogrammes, et chaque manche solo ramène une prise.

Deux problèmes mesurés le 23/09/2026 sur le bot booté :
- la couche de sobriété typographique effaçait TOUS les emojis, y compris ceux des
  jeux : la machine à sous affichait « 🎰 |  |  », des rouleaux vides ;
- une manche gagnante affichait une phrase au hasard et un montant, sans rien qui
  distingue deux parties.
"""
from __future__ import annotations

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
