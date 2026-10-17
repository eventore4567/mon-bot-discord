"""Une commande a UNE catégorie, la même partout.

Mesuré le 2026-10-17 sur les 327 commandes préfixées réellement publiées :
**47 catégories distinctes**, dont une vingtaine étaient des noms de modules
internes visibles par les membres — « SentriXV21 », « BotV10 »,
« V17TicketsLogs », « Autres ». Les jeux étaient éclatés en sept catégories,
la sécurité en cinq.

Et les deux surfaces ne répondaient pas la même chose : ``/help`` passait par
la table de ``cogs/help_components_v77`` (29 cogs couverts sur 47), la page
web ``/commands`` affichait le ``cog_name`` brut. **66 commandes sur 327
(20 %)** tombaient dans le repli « Administration », dont ``+starboard-setup``,
``+snipe``, ``+translate``, ``+poll``, ``+suggest`` et ``+incident``.

Après : 12 catégories, 0 cog non couvert, 16 commandes en Administration.
"""
from __future__ import annotations

import os

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import pytest

from utils import command_categories as cc

# Les 47 cogs réellement publiés le 2026-10-17, relevés sur /commands.
COGS_PUBLIES = [
    "Ai", "Automod", "Autres", "BotV10", "Configuration", "DirectMessage", "Economy",
    "Events", "ForbiddenWordsUI", "GamesArcade", "GamesCommunity", "GamesDuels",
    "GamesPlayerCommands", "GamesRapides", "GamesSolo", "GiveawayCenter", "Invites",
    "Levels", "Minigames", "Moderation", "Music", "NotificationRolePanels",
    "Notifications", "Owner", "PermissionsExplain", "PollUI", "ProofVerification",
    "Security", "SecurityHardening", "SentriXOpsV111", "SentriXPlus", "SentriXSetup",
    "SentriXUltimate", "SentriXV2", "SentriXV21", "Snipe", "Stats", "Suggestions",
    "SystemFeatures", "Tickets", "Trace", "Translation", "Utility",
    "V17TicketsLogs", "Verification", "VerificationConfigV96", "StaffSuite",
]


def test_il_y_a_douze_categories_pas_quarante_sept():
    assert len(cc.CATEGORIES) == 12


@pytest.mark.parametrize("cog", COGS_PUBLIES)
def test_chaque_cog_publie_est_classe_explicitement(cog):
    """Sans entrée explicite, un cog part au repli et finit mal rangé."""
    assert cog in cc.PAR_COG, (
        f"« {cog} » n'est pas dans la table : il sera classé par devinette. "
        "Ajoutez-le à utils/command_categories.PAR_COG."
    )


@pytest.mark.parametrize("cog", COGS_PUBLIES)
def test_chaque_cog_mene_a_une_categorie_connue(cog):
    assert cc.resoudre(cog) in cc.CATEGORIES


def test_aucun_nom_de_module_interne_ne_sort_vers_le_membre():
    """« SentriXV21 » ou « BotV10 » ne doivent jamais s'afficher."""
    labels = {nom for _e, nom, _d in cc.CATEGORIES.values()}
    for label in labels:
        assert "SentriX" not in label or label == "Modération", label
        assert not any(c.isdigit() for c in label), label


@pytest.mark.parametrize("commande,attendu", [
    ("server-health", "utility"),
    ("modcenter", "moderation"),
    ("systemstatus", "utility"),
    ("addbonusinvites", "moderation"),
    ("server-managed", "administration"),
])
def test_les_cogs_mixtes_sont_tranches_par_commande(commande, attendu):
    """SentriXPlus mélange starboard (communauté) et santé serveur (outils)."""
    assert cc.resoudre("SentriXPlus", commande) == attendu or cc.resoudre(None, commande) == attendu


def test_le_defaut_est_utilitaires_et_pas_administration():
    """Une commande non classée est bien plus souvent un outil qu'un réglage.

    La ranger dans Administration la rendait invisible aux membres.
    """
    assert cc.DEFAUT == "utility"
    assert cc.resoudre("CogQuiNExistePas") == "utility"


def test_les_deux_surfaces_consultent_la_meme_table():
    import inspect

    from cogs import help_components_v77 as v77

    assert v77.COG_CATEGORY is cc.PAR_COG
    assert v77.CATEGORY_META is cc.CATEGORIES

    from web import public_commands_v46 as web

    assert "command_categories" in inspect.getsource(web._categorie_affichee)
