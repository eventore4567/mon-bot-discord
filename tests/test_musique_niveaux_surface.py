"""Musique et niveaux : les deux derniers défauts de la même famille.

Garde d'intention du langage naturel
  ``cogs/natural_music_intent_guard`` porte trois protections décrites dans
  son en-tête : « fais-moi un résumé sur Pythagore » ne doit jamais devenir
  ``+resume musique``, un message très court comme « cv ? » reste une
  conversation, et une demande explicite de lien retourne une vraie URL.
  Mesuré le 2026-09-26 sur la chaîne v8 : le module n'était pas installé —
  même cause que +panic, un ``install()`` sans ``setup()`` suspendu à
  l'enveloppe morte de ``cogs/__init__``.

Interrupteurs de système
  ``cogs/feature_systems.py`` écrit que « les interrupteurs doivent TOUJOURS
  rester accessibles aux administrateurs, sinon +level-system off bloquerait
  lui-même +level-system on ». Ils étaient masqués et classés nulle part.
"""
from __future__ import annotations

import ast
import inspect
import os
import pathlib

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import pytest

RACINE = pathlib.Path(__file__).resolve().parents[1]


def test_le_garde_musique_expose_un_setup():
    source = (RACINE / "cogs" / "natural_music_intent_guard.py").read_text(encoding="utf-8")
    noms = {n.name for n in ast.parse(source).body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assert "setup" in noms


def test_le_garde_musique_est_charge_par_la_production():
    import main

    assert "cogs.natural_music_intent_guard" in main.EXTENSIONS


def test_le_garde_musique_se_charge_apres_le_cog_ai():
    """install() fait « from . import ai » et remplace une méthode de Ai."""
    import main

    assert main.EXTENSIONS.index("cogs.ai") < main.EXTENSIONS.index(
        "cogs.natural_music_intent_guard")


def test_les_trois_protections_sont_toujours_posees():
    """Retirer l'une d'elles rouvrirait un faux positif décrit en tête de module."""
    from cogs import natural_music_intent_guard as garde

    source = inspect.getsource(garde.install)
    assert "_install_link_reliability" in source
    assert "_install_casual_chat_guard" in source
    assert "_sentrix_music_intent_guard" in source


@pytest.mark.parametrize("interrupteur", ["level-system", "economy-system"])
def test_les_interrupteurs_de_systeme_sont_trouvables(interrupteur):
    """Le module exige lui-même qu'ils restent accessibles : sans cela, couper
    les niveaux devient irréversible sans toucher la base à la main."""
    from cogs.command_catalog_cleanup import HELP_VISIBLE_EXTRA_COMMANDS

    assert interrupteur in HELP_VISIBLE_EXTRA_COMMANDS


def test_les_interrupteurs_restent_accessibles_a_leur_propre_cog():
    """C'est la garantie que le module décrit : un interrupteur coupé ne doit
    pas se bloquer lui-même."""
    from cogs import feature_systems

    source = inspect.getsource(feature_systems.SystemFeatureCommands.bot_check)
    assert '"SystemFeatures"' in source
    assert "return True" in source


def test_rendre_visible_ne_change_pas_la_permission():
    """La découvrabilité n'est pas une autorisation : ces interrupteurs
    restent réservés aux administrateurs."""
    from cogs.command_catalog_cleanup import (
        ADMIN_DIRECT_COMMANDS,
        HELP_VISIBLE_EXTRA_COMMANDS,
        NORMAL_DIRECT_COMMANDS,
    )

    for interrupteur in ("level-system", "economy-system"):
        assert interrupteur not in NORMAL_DIRECT_COMMANDS
        assert interrupteur not in ADMIN_DIRECT_COMMANDS
    assert {"level-system", "economy-system"} <= HELP_VISIBLE_EXTRA_COMMANDS
