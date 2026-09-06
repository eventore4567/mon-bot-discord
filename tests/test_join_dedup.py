"""Un seul système de bienvenue par arrivée, même quand plusieurs fonctionnalités
indépendantes veulent chacune annoncer le même membre.

Trois producteurs passent par ce verrou — la bienvenue standard de Setup
(cogs/setup_v2_completion.py), le « smart welcome » de +sentrixpro
(cogs/sentrix_ultimate.py), et l'onboarding avec choix de rôle de la Suite
Engagement (cogs/engagement_suite.py). Un QUATRIÈME producteur existait sans
passer par ce verrou : main.py définissait on_member_join/on_member_remove
directement sur la classe BotAllInOne. discord.py dispatche une méthode
définie ainsi via getattr(self, "on_member_join") AVANT même bot.extra_events
— donc invisible à ce verrou et à _replace_welcome_listeners, qui ne
surveillent que extra_events. Résultat : CHAQUE arrivée avec un salon de
bienvenue configuré recevait ce message-là (inconditionnel) EN PLUS de celui
du gagnant du verrou parmi les trois producteurs ci-dessus. Supprimé : voir
test_main_n_a_plus_son_propre_on_member_join ci-dessous.
"""
from __future__ import annotations

import asyncio
import os

os.environ.setdefault("DISCORD_TOKEN", "x")

from utils import join_dedup  # noqa: E402


def test_le_premier_appel_gagne():
    assert asyncio.run(join_dedup.reclamer(None, 1, 1, "welcome")) is True


def test_le_deuxieme_appel_pour_le_meme_evenement_perd():
    asyncio.run(join_dedup.reclamer(None, 2, 2, "welcome"))
    assert asyncio.run(join_dedup.reclamer(None, 2, 2, "welcome")) is False


def test_trois_producteurs_concurrents_un_seul_gagne():
    """Simule exactement la course entre les trois producteurs réels."""
    async def trois_appels():
        return await asyncio.gather(
            *[join_dedup.reclamer(None, 3, 3, "welcome") for _ in range(3)]
        )

    resultats = asyncio.run(trois_appels())
    assert sum(resultats) == 1


def test_un_membre_different_n_est_pas_bloque():
    asyncio.run(join_dedup.reclamer(None, 4, 4, "welcome"))
    assert asyncio.run(join_dedup.reclamer(None, 4, 5, "welcome")) is True


def test_un_evenement_different_n_est_pas_bloque():
    """« welcome » et « leave » ne doivent jamais se marcher dessus."""
    asyncio.run(join_dedup.reclamer(None, 6, 6, "welcome"))
    assert asyncio.run(join_dedup.reclamer(None, 6, 6, "leave")) is True


def test_les_trois_producteurs_reels_appellent_le_meme_verrou():
    """Vérifie le câblage effectif, pas seulement le module lui-même : si un
    futur refactor renomme ou retire un appel, ce test doit le voir."""
    import inspect

    from cogs import engagement_suite, sentrix_ultimate, setup_v2_completion

    for module, fonction in (
        (setup_v2_completion, "install"),
        (sentrix_ultimate, "SentrixUltimate"),
        (engagement_suite, "EngagementSuite"),
    ):
        source = inspect.getsource(module)
        assert "join_dedup.reclamer(" in source, f"{module.__name__} n'appelle plus join_dedup"
        assert '"welcome"' in source


def test_main_n_a_plus_son_propre_on_member_join():
    """Le 4e producteur : une méthode on_member_join sur BotAllInOne échapperait
    à join_dedup ET à _replace_welcome_listeners (tous deux ne regardent que
    bot.extra_events, jamais les méthodes définies directement sur la classe).
    Si quelqu'un la réintroduit, ce test doit le voir avant la prochaine bascule."""
    import inspect

    import main

    source = inspect.getsource(main.BotAllInOne)
    assert "async def on_member_join" not in source, (
        "une méthode on_member_join sur BotAllInOne est dispatchée par discord.py "
        "avant bot.extra_events : elle enverrait une bienvenue en double, invisible "
        "au verrou join_dedup — voir cogs/setup_v2_completion.py pour l'implémentation "
        "officielle unique"
    )
    assert "async def on_member_remove" not in source, (
        "même bug pour le message de départ : cogs/setup_v2_completion.py::_send_goodbye "
        "est déjà l'implémentation officielle unique"
    )
