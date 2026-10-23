"""Ouvrir le panneau de configuration ne doit notifier personne.

Signalé par Jayden le 2026-10-23, capture à l'appui : la page « Rôles
automatiques » affiche ses règles avec de vraies mentions —
« Vérification → @🌌 • HABITANT », « Avertissement → @En prison » — et
chaque rafraîchissement du panneau notifiait tous les membres portant
ces rôles.

Cause : les éditions de panneau appelaient ``edit_original_response`` et
``edit_message`` sans ``allowed_mentions``. Le défaut du bot s'applique
alors, et il est déclaré ``roles=True`` dans main.py.

Les pastilles bleues restent — elles sont lisibles et utiles. Seule la
notification part.
"""
from __future__ import annotations

import inspect
import os
import re

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import pytest

MODULES = (
    "setup_components_v73",
    "setup_control_center",
    "setup_experience_v2",
    "setup_v118_integrations",
)


def _source(nom: str) -> str:
    import importlib

    return inspect.getsource(importlib.import_module(f"cogs.{nom}"))


@pytest.mark.parametrize("nom", MODULES)
def test_aucune_edition_de_panneau_ne_laisse_discord_choisir(nom):
    src = _source(nom)
    manquants = []
    for methode in ("edit_original_response", "edit_message"):
        for m in re.finditer(rf"\.{methode}\(", src):
            debut = m.end() - 1
            prof, i = 0, debut
            while i < len(src):
                if src[i] == "(":
                    prof += 1
                elif src[i] == ")":
                    prof -= 1
                    if prof == 0:
                        break
                i += 1
            appel = src[debut:i + 1]
            if "allowed_mentions" not in appel:
                manquants.append(f"{methode} ligne ~{src[:m.start()].count(chr(10)) + 1}")
    assert not manquants, (
        f"{nom} : édition(s) sans allowed_mentions, le défaut du bot (roles=True) "
        f"s'appliquerait et notifierait les rôles affichés : {manquants}"
    )


@pytest.mark.parametrize("nom", MODULES)
def test_la_constante_coupe_bien_toutes_les_mentions(nom):
    import importlib

    module = importlib.import_module(f"cogs.{nom}")
    sans_ping = getattr(module, "_SANS_PING", None)
    assert sans_ping is not None, f"{nom} ne déclare pas _SANS_PING"
    assert sans_ping.roles is False
    assert sans_ping.everyone is False
    assert sans_ping.users is False


def test_le_defaut_du_bot_autorise_bien_les_roles():
    """La garde ci-dessus n'a de sens que tant que ce défaut existe.

    Si quelqu'un passe main.py à roles=False, ces tests deviennent
    redondants — mais ils ne gênent pas, et le jour où le défaut
    reviendrait à roles=True ils protègent encore.
    """
    import pathlib

    src = pathlib.Path("main.py").read_text(encoding="utf-8")
    assert "roles=True" in src, (
        "le défaut du bot a changé : revérifier si _SANS_PING reste nécessaire"
    )
