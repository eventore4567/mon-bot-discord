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


def _automod_factice():
    """Le minimum pour exercer la détection de répétition, sans booter le bot."""
    from types import SimpleNamespace

    from cogs.automod import REPEAT_WINDOW

    return SimpleNamespace(repeat_tracker=FenetreGlissante(fenetre=REPEAT_WINDOW))


def _message(texte: str, salon: int = 1):
    from types import SimpleNamespace

    return SimpleNamespace(content=texte, channel=SimpleNamespace(id=salon))


def test_le_meme_message_repete_lentement_est_du_spam():
    """Le comptage par débit ne voyait QUE la vitesse : cent fois le même
    message espacé de dix secondes n'était pas du spam pour lui."""
    from cogs.automod import REPEAT_THRESHOLD, AutoMod

    cog = _automod_factice()
    resultats = [
        AutoMod._detecter_repetition(cog, _message("Rejoignez mon serveur promo"), ("g", "u"))
        for _ in range(REPEAT_THRESHOLD)
    ]
    assert resultats[-1], "la répétition n'est pas détectée"
    assert not any(resultats[:-1]), "sanction déclenchée avant le seuil"


def test_changer_la_casse_ou_espacer_ne_contourne_pas():
    from cogs.automod import AutoMod

    cog = _automod_factice()
    variantes = [
        "Rejoignez mon serveur promo",
        "REJOIGNEZ MON SERVEUR PROMO",
        "rejoignez  mon  serveur  promo",
        "R e j o i g n e z mon serveur promo",
    ]
    resultats = [AutoMod._detecter_repetition(cog, _message(v), ("g", "u")) for v in variantes]
    assert resultats[-1], "les quatre variantes ne comptent pas pour le même message"


def test_le_meme_message_dans_plusieurs_salons_part_plus_tot():
    """Recopier la même chose dans trois salons n'est jamais un accident."""
    from cogs.automod import REPEAT_CHANNEL_THRESHOLD, AutoMod

    cog = _automod_factice()
    resultats = [
        AutoMod._detecter_repetition(cog, _message("Venez voir ma boutique en ligne", salon), ("g", "u"))
        for salon in range(1, REPEAT_CHANNEL_THRESHOLD + 1)
    ]
    assert "salons" in (resultats[-1] or ""), resultats
    assert not any(resultats[:-1])


def test_une_conversation_normale_n_est_jamais_sanctionnee():
    """« ok », « lol », « +1 » se répètent toute la journée. Les sanctionner
    ferait couper la protection par les admins — donc plus de protection."""
    from cogs.automod import AutoMod

    cog = _automod_factice()
    for court in ("ok", "lol", "oui", "+1", "merci", "mdr", "ok", "oui", "lol", "merci", "ok", "oui"):
        assert not AutoMod._detecter_repetition(cog, _message(court), ("g", "u")), court

    cog = _automod_factice()
    conversation = (
        "je suis d'accord avec toi la-dessus",
        "moi aussi je pense pareil franchement",
        "on se retrouve demain vers dix-huit heures",
        "je suis d'accord avec toi la-dessus",
        "oui exactement c'est ce que je disais",
    )
    for phrase in conversation:
        assert not AutoMod._detecter_repetition(cog, _message(phrase), ("g", "u")), phrase


def test_le_raid_lent_est_detecte_sans_gener_un_serveur_qui_grandit():
    """Sept arrivées toutes les dix secondes — quarante-deux comptes par
    minute — n'atteignaient jamais le seuil d'afflux instantané."""
    from cogs.automod import (
        RAID_JOIN_THRESHOLD,
        RAID_JOIN_WINDOW,
        RAID_SLOW_THRESHOLD,
        RAID_SLOW_WINDOW,
    )

    # Un raid juste sous le seuil rapide, tenu pendant la fenêtre lente.
    par_minute = (RAID_JOIN_THRESHOLD - 1) * 60 / RAID_JOIN_WINDOW
    sur_la_fenetre_lente = par_minute * RAID_SLOW_WINDOW / 60
    assert sur_la_fenetre_lente >= RAID_SLOW_THRESHOLD, (
        "un raid sous le seuil rapide reste invisible sur la fenêtre lente"
    )

    # Un serveur populaire qui grandit vraiment ne doit pas être alerté : six
    # arrivées par minute soutenues restent sous le seuil lent.
    croissance_normale = 5 * RAID_SLOW_WINDOW / 60
    assert croissance_normale < RAID_SLOW_THRESHOLD, (
        "un serveur qui grandit normalement déclencherait l'alerte"
    )


def test_les_deux_fenetres_de_raid_existent_et_sont_reinitialisees():
    """Sans réinitialisation, l'alerte « raid lent » repartirait à chaque
    arrivée tant que la fenêtre de dix minutes reste pleine."""
    import inspect

    from cogs.automod import AutoMod

    init = inspect.getsource(AutoMod.__init__)
    assert "self.join_tracker = FenetreGlissante(" in init
    assert "self.slow_join_tracker = FenetreGlissante(" in init

    source = inspect.getsource(AutoMod)
    assert "slow_join_tracker.reinitialiser" in source
