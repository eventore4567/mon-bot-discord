"""Deux décisions du 20/11/2026, l'une venue des logs, l'autre de l'utilisateur.

1. « fait comme l'image » + une image : AUCUNE réponse. Les logs de production
   donnaient la cause exacte :

       TypeError: build_with_server_context() takes from 2 to 3 positional
       arguments but 4 were given

   Ai._prepare_and_generate est le seul appelant à passer `guild_id` en 3e
   argument, et c'est lui qu'emprunte le chemin des images. Deux wrappers de
   _build_system_instructions sur trois perdaient cet argument.
   community_v32.build_clean avait déjà été corrigé ainsi le 07/11 : la même
   correction manquait dans les deux autres. Cela cassait les images PARTOUT,
   pas seulement en privé.

2. SentriX ne discute plus en message privé. Les commandes préfixées y
   fonctionnent toujours ; seule la conversation libre est fermée.
"""
from __future__ import annotations

import inspect
import os

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import pytest  # noqa: E402

from cogs import bot_experience_v5  # noqa: E402


# ------------------------------------------------- un wrapper transmet TOUT
@pytest.mark.parametrize(
    "module, nom",
    [
        ("cogs.community_v3", "build_with_server_context"),
        ("cogs.community_v32", "build_clean"),
        ("cogs.ai_reply_recovery", "safe_builder"),
    ],
)
def test_chaque_wrapper_transmet_guild_id(module, nom):
    """Trois modules remplacent _build_system_instructions. Aucun ne doit perdre d'argument."""
    import importlib

    source = inspect.getsource(importlib.import_module(module))
    declaration = next(
        (ligne for ligne in source.splitlines() if f"def {nom}(" in ligne), None
    )
    assert declaration is not None, f"{nom} introuvable dans {module}"
    assert "*args" in declaration, (
        f"{module}.{nom} doit transmettre *args : sans cela, l'appel à trois arguments "
        "du chemin des images lève TypeError et SentriX ne répond pas du tout."
    )


def test_la_vraie_signature_accepte_bien_trois_arguments():
    from cogs.ai import Ai

    parametres = inspect.signature(Ai._build_system_instructions).parameters
    assert {"user_id", "author_name", "guild_id"} <= set(parametres)


def test_l_appel_a_trois_arguments_existe_toujours():
    """Si cet appel disparaît, les tests ci-dessus perdent leur raison d'être."""
    from cogs.ai import Ai

    source = inspect.getsource(Ai._prepare_and_generate)
    assert "_build_system_instructions(user_id, author_name, guild_id)" in source


# ------------------------------------------- plus de conversation en privé
def test_un_salon_de_serveur_n_est_pas_du_prive():
    from types import SimpleNamespace

    salon = SimpleNamespace(guild=SimpleNamespace(id=1))
    assert bot_experience_v5._est_en_prive(salon) is False


def test_un_message_prive_est_reconnu():
    from types import SimpleNamespace

    salon = SimpleNamespace(guild=None)
    assert bot_experience_v5._est_en_prive(salon) is True


def test_le_serveur_peut_venir_du_salon_ou_du_message_cite():
    from types import SimpleNamespace

    serveur = SimpleNamespace(id=1)
    depuis_le_salon = SimpleNamespace(guild=None, channel=SimpleNamespace(guild=serveur))
    assert bot_experience_v5._est_en_prive(depuis_le_salon) is False

    cite = SimpleNamespace(guild=serveur)
    assert bot_experience_v5._est_en_prive(SimpleNamespace(guild=None), cite) is False


def test_le_pipeline_refuse_le_prive_avant_tout_appel_au_modele():
    """Le garde est en tête : aucun appel au modèle, donc aucun coût."""
    source = inspect.getsource(bot_experience_v5._install_ai_pipeline_upgrade)
    avant_blacklist = source.split("_is_blacklisted")[0]
    assert "_est_en_prive(destination, reply_to)" in avant_blacklist
    assert "REFUS_MESSAGE_PRIVE" in avant_blacklist


def test_l_ecouteur_prive_ne_touche_plus_a_l_ia():
    source = inspect.getsource(bot_experience_v5._install_reply_and_dm_conversations)
    bloc = source.split("if message.guild is None:")[1].split("# Les mentions")[0]
    assert "REFUS_MESSAGE_PRIVE" in bloc
    # 22/11/2026 : « mp moi » rouvre le privé pour la personne qui l'a demandé,
    # 24 h (utils/mp_ouvertes). L'appel IA n'existe donc plus que DERRIÈRE ce
    # contrôle ; pour tous les autres, le refus reste la seule réponse. Le
    # comportement est vérifié dans tests/test_mp_moi.py.
    avant_appel = bloc.split("send_sentrix_reply")[0]
    assert "mp_ouvertes.est_ouverte" in avant_appel, "aucun appel IA en privé sans « mp moi »"
    assert "_send_generated_image_natural" not in bloc, "ni génération d'image"
    assert "ctx.valid" in bloc, "les commandes préfixées restent utilisables en privé"
