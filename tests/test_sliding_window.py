"""Les compteurs de l'AutoMod doivent compter juste ET oublier.

Ils étaient quatre dictionnaires `{(serveur, membre): [horodatages]}`. Les
horodatages étaient bien élagués ; les CLÉS ne l'étaient jamais. Une entrée par
membre ayant parlé une seule fois, gardée à vie, même après son départ.
Mesuré à 12,4 Mo pour 50 000 membres sur le seul compteur anti-spam, sans
jamais redescendre — sur un conteneur limité, la fin de l'histoire est un OOM,
et un bot tué ne protège plus rien.
"""
from __future__ import annotations

import os

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from utils.sliding_window import FenetreGlissante


def test_le_compteur_compte_dans_la_fenetre():
    fenetre = FenetreGlissante(fenetre=6)
    base = 1000.0
    for attendu, decalage in enumerate((0.0, 0.5, 1.0, 1.5, 2.0), start=1):
        assert fenetre.ajouter("cle", maintenant=base + decalage) == attendu


def test_le_compteur_oublie_ce_qui_sort_de_la_fenetre():
    fenetre = FenetreGlissante(fenetre=6)
    base = 1000.0
    for decalage in (0.0, 1.0, 2.0):
        fenetre.ajouter("cle", maintenant=base + decalage)
    # Sept secondes plus tard, les trois premiers sont hors fenêtre.
    assert fenetre.ajouter("cle", maintenant=base + 9.0) == 1


def test_les_cles_inactives_sont_oubliees():
    """Le cœur du correctif : c'est ici que 12,4 Mo se perdaient."""
    fenetre = FenetreGlissante(fenetre=6, purge_toutes=100)
    base = 1000.0
    for index in range(5000):
        fenetre.ajouter(("serveur", index), maintenant=base + index * 0.001)
    # Seules les clés encore dans la fenêtre doivent survivre : 5 000 insertions
    # espacées d'une milliseconde tiennent en 5 s, donc tout est encore vivant.
    assert len(fenetre) <= 5000
    # Une insertion très postérieure déclenche la purge des 5 000 précédentes.
    for index in range(100):
        fenetre.ajouter(("tard", index), maintenant=base + 10_000 + index)
    assert len(fenetre) < 200, f"{len(fenetre)} clés encore suivies"


def test_reinitialiser_retire_la_cle_au_lieu_de_la_vider():
    """Une liste vide reste une entrée de dictionnaire — c'est exactement ce
    qui fuyait après chaque sanction."""
    fenetre = FenetreGlissante(fenetre=6)
    fenetre.ajouter("cle", maintenant=1000.0)
    assert len(fenetre) == 1
    fenetre.reinitialiser("cle")
    assert len(fenetre) == 0


def test_vider_et_clear_sont_le_meme_geste():
    """tools/security_runtime_audit appelle clear() : garder le nom évite de
    casser un appelant pour une question de vocabulaire."""
    fenetre = FenetreGlissante(fenetre=6)
    fenetre.ajouter("a", maintenant=1000.0)
    fenetre.ajouter("b", maintenant=1000.0)
    fenetre.clear()
    assert len(fenetre) == 0
    assert FenetreGlissante.clear is FenetreGlissante.vider


def test_l_automod_utilise_des_compteurs_qui_oublient():
    """Les quatre compteurs doivent être des fenêtres glissantes, pas des dicts."""
    import inspect

    from cogs.automod import AutoMod

    source = inspect.getsource(AutoMod.__init__)
    for nom in ("spam_tracker", "join_tracker", "nuke_tracker", "infraction_tracker"):
        assert f"self.{nom} = FenetreGlissante(" in source, nom


def test_le_filtre_de_contenu_partage_le_meme_compteur():
    """Il réimplémentait la logique avec ses propres dictionnaires : au premier
    changement de structure, il aurait levé une AttributeError en production,
    sur le chemin des sanctions."""
    import inspect

    from cogs import content_filter_policy

    source = inspect.getsource(content_filter_policy)
    assert "infraction_tracker.setdefault" not in source
    assert "infraction_tracker.ajouter" in source
