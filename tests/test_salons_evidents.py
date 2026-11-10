"""10/11/2026 : le Setup ne demande pas ce que SentriX peut décider lui-même."""
from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from utils import salons_evidents as se  # noqa: E402


def _salon(nom: str, *, ecrivable: bool = True):
    return SimpleNamespace(
        name=nom, mention=f"#{nom}",
        permissions_for=lambda _moi: SimpleNamespace(
            view_channel=ecrivable, send_messages=ecrivable, embed_links=ecrivable,
        ),
    )


def _guild(salons, systeme=None):
    return SimpleNamespace(me=object(), system_channel=systeme, text_channels=list(salons))


def test_le_salon_systeme_de_discord_passe_avant_tout():
    general, bienvenue = _salon("général"), _salon("bienvenue")
    guild = _guild([general, bienvenue], systeme=general)
    assert se.salon_evident(guild, "bienvenue") is general
    assert "déclaré par le serveur" in se.pourquoi(guild, "bienvenue", general)


def test_sans_salon_systeme_le_nom_decide():
    bienvenue = _salon("・bienvenue 🎉")
    guild = _guild([_salon("blabla"), bienvenue])
    assert se.salon_evident(guild, "bienvenue") is bienvenue
    assert "porte déjà le nom" in se.pourquoi(guild, "bienvenue", bienvenue)
    logs = _salon("logs-moderation")
    assert se.salon_evident(_guild([_salon("blabla"), logs]), "logs") is logs


def test_un_nom_exact_passe_avant_un_nom_qui_contient():
    exact, approchant = _salon("welcome"), _salon("welcome-archives")
    assert se.salon_evident(_guild([approchant, exact]), "bienvenue") is exact


def test_un_salon_ou_sentrix_ne_peut_pas_ecrire_n_est_jamais_propose():
    verrouille = _salon("bienvenue", ecrivable=False)
    assert se.salon_evident(_guild([verrouille], systeme=verrouille), "bienvenue") is None
    assert se.salon_evident(_guild([verrouille]), "bienvenue") is None


def test_rien_d_evident_ne_propose_rien():
    assert se.salon_evident(_guild([_salon("blabla")]), "logs") is None
    assert se.salon_evident(None, "bienvenue") is None
    assert se.pourquoi(_guild([]), "bienvenue", None) == ""


def test_le_setup_propose_le_salon_au_lieu_de_le_demander():
    source = (Path(__file__).resolve().parents[1] / "cogs" / "complete_welcome_setup.py").read_text(encoding="utf-8")
    # Proposé seulement quand aucun salon n'est encore choisi.
    assert "if channel is None:" in source
    assert "salons_evidents.salon_evident(self.guild, besoin)" in source
    assert 'f"Utiliser {propose.name}"' in source
