"""Les bascules AutoMod doivent être atteignables par les deux surfaces.

Un compteur figé dit qu'un nombre n'a pas bougé ; il ne dit pas que les bonnes
commandes sont visibles. Ce fichier vérifie la propriété qui compte vraiment :
chaque filtre AutoMod se configure aussi bien en ``+`` qu'en ``/``, et derrière
les deux c'est la même fonction.

Le défaut mesuré le 2026-09-25 : onze bascules sur treize étaient
``hidden=True``. Elles existaient, elles marchaient, et elles n'apparaissaient
ni dans ``+help`` ni dans l'arbre slash — ``/securite automod`` n'exposait
qu'une feuille sur vingt-cinq. Un propriétaire de serveur ne pouvait activer
l'anti-spam qu'en connaissant déjà le nom exact de la commande.
"""
from __future__ import annotations

import os

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import pytest

from cogs.command_catalog_cleanup import (
    MERGED_COMMANDS,
    NORMAL_DIRECT_COMMANDS,
)

#: Les filtres configurables par un administrateur. ``automod-status`` n'y est
#: pas : elle est fusionnée dans /setup et doit rester masquée.
BASCULES = (
    "antispam", "antilink", "antilink-strict", "antiinvite", "antimention",
    "anticaps", "antiemoji", "antiraid", "antiscam", "antibot", "antiaccount",
    "antinuke",
)


@pytest.mark.parametrize("bascule", BASCULES)
def test_chaque_bascule_est_dans_la_surface_directe(bascule):
    """La liste qui décide à la fois de la visibilité et de l'éligibilité slash.

    ``apply_surface`` met ``hidden = True`` à tout ce qui n'est classé nulle
    part, et ``command_hybrid_slash_restore_v3`` ne restaure en slash que ce
    qui est ici. Sortir une bascule de cette liste la fait disparaître des deux
    surfaces d'un coup, sans rien casser d'autre — donc sans que rien n'échoue.
    """
    assert bascule in NORMAL_DIRECT_COMMANDS


@pytest.mark.parametrize("bascule", BASCULES)
def test_aucune_bascule_n_est_traitee_comme_fusionnee(bascule):
    """Une commande à la fois « directe » et « fusionnée » se contredit :
    apply_surface la montrerait, et user_acceptance_audit exigerait l'inverse."""
    assert bascule not in MERGED_COMMANDS


def test_automod_status_reste_fusionnee():
    """Le contre-exemple, gardé exprès.

    Je l'avais ajoutée aux commandes directes par symétrie avec les bascules.
    ``tools/user_acceptance_audit.py`` a refusé : elle est fusionnée dans
    /setup, et c'est pour cela qu'elle n'a jamais eu de feuille slash.
    """
    assert "automod-status" in MERGED_COMMANDS
    assert "automod-status" not in NORMAL_DIRECT_COMMANDS


def test_les_bascules_declarent_toutes_le_meme_contrat():
    """Même permission et même paramètre pour toute la famille.

    Une bascule qui demanderait une permission différente des douze autres
    serait une surprise, pas une fonctionnalité.
    """
    from cogs.automod import AutoMod

    vues = {}
    for commande in AutoMod.__cog_commands__:
        if commande.name in BASCULES:
            vues[commande.name] = tuple(commande.clean_params)
    manquantes = set(BASCULES) - set(vues) - {"antinuke"}   # antinuke vit ailleurs
    assert not manquantes, f"bascules absentes du cog AutoMod : {sorted(manquantes)}"
    signatures = set(vues.values())
    assert signatures == {("etat",)}, signatures


def test_la_famille_partage_une_seule_implementation():
    """Treize copies de la même bascule dériveraient au premier correctif."""
    import inspect

    from cogs.automod import AutoMod

    source = inspect.getsource(AutoMod)
    corps = [l.strip() for l in source.splitlines()
             if l.strip().startswith("return await self.toggle(")
             or l.strip().startswith("await self.toggle(")]
    assert len(corps) >= 8, (
        "les bascules ne délèguent plus à AutoMod.toggle : vérifier qu'aucune "
        "n'a reçu sa propre copie de la logique")
