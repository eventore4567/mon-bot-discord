"""Moteur commun de +massrole et /role mass : progression complète et lisible."""
from __future__ import annotations

import asyncio
import os
import re
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import discord  # noqa: E402

from utils import mass_role  # noqa: E402


class _Role:
    mention = "<@&5>"

    def __eq__(self, other):
        return other is self

    def __hash__(self):
        return 5


def _member(member_id: int, *, bot: bool = False, roles=()):
    return SimpleNamespace(
        id=member_id, bot=bot, roles=list(roles),
        add_roles=AsyncMock(), remove_roles=AsyncMock(),
    )


def _guild(members):
    async def fetch_members(limit=None):
        for member in members:
            yield member
    return SimpleNamespace(id=1, members=members, fetch_members=fetch_members)


def _texte(panneau) -> str:
    return "\n".join(section.rendu() for section in panneau.sections_source) + "\n" + panneau.sous_titre


def test_progression_affiche_total_restants_pourcentage_vitesse_eta_et_fin():
    suivi = mass_role.Progression(action="add", role_mention="<@&5>", total=1000, traites=250, pret=True)
    suivi.debut -= 50  # 250 membres en 50 s → 5 membres/s, 150 s restantes
    assert suivi.restants == 750
    assert suivi.pourcentage == 25
    assert round(suivi.vitesse) == 5
    assert 145 <= suivi.eta <= 155
    assert suivi.barre() == "████" + "░" * 12

    texte = _texte(suivi.panneau())
    assert "250 / 1\u202f000" in texte
    assert "**Restants** · 750" in texte
    assert "25 %" in texte
    assert "membres/s" in texte
    assert "Temps écoulé" in texte and "Temps restant estimé" in texte
    assert re.search(r"Fin estimée\*\* · <t:\d+:T> \(<t:\d+:R>\)", texte)
    assert "Ajout de <@&5> · membres humains" in texte


def test_progression_terminee_remplace_l_eta_par_la_duree_totale():
    suivi = mass_role.Progression(action="remove", role_mention="<@&5>", total=3, traites=3, termine=True)
    texte = _texte(suivi.panneau())
    assert "Durée totale" in texte
    assert "Fin estimée" not in texte
    assert "100 %" in texte
    assert suivi.panneau().titre.endswith("terminé")


def test_progression_en_anglais():
    suivi = mass_role.Progression(action="add", role_mention="<@&5>", total=10, traites=5, english=True, pret=True)
    suivi.debut -= 5
    texte = _texte(suivi.panneau())
    assert "Processed" in texte and "Estimated end" in texte and "Remaining" in texte


def test_executer_filtre_la_cible_compte_et_rafraichit_par_intervalle():
    role = _Role()
    humains = [_member(i) for i in range(1, 12)]
    deja = _member(50, roles=[role])
    bot = _member(99, bot=True)
    affichages: list[int] = []

    async def rafraichir(etat):
        affichages.append(etat.traites)

    suivi = mass_role.Progression(action="add", role_mention=role.mention)
    asyncio.run(mass_role.executer(
        _guild([*humains, deja, bot]), role, action="add", cible="members", raison="test",
        progression=suivi, rafraichir=rafraichir, intervalle=3600,
    ))
    assert suivi.total == 12 and suivi.traites == 12
    assert suivi.modifies == 11 and suivi.ignores == 1 and suivi.echecs == 0
    bot.add_roles.assert_not_awaited()
    assert suivi.termine
    # Intervalle d'une heure : seulement l'état initial et l'état final.
    assert affichages == [0, 12]


def test_executer_compte_les_echecs_et_protege_le_proprietaire():
    role = _Role()
    refuse = _member(2, roles=[role])
    refuse.remove_roles.side_effect = discord.Forbidden(SimpleNamespace(status=403, reason="x"), "non")
    proprietaire = _member(3, roles=[role])
    suivi = mass_role.Progression(action="remove", role_mention=role.mention)
    with patch.object(mass_role, "is_bot_owner_id", lambda uid: uid == 3):
        asyncio.run(mass_role.executer(
            _guild([refuse, proprietaire]), role, action="remove", cible="all", raison="t",
            progression=suivi,
        ))
    assert suivi.echecs == 1 and suivi.proteges == 1 and suivi.modifies == 0
    proprietaire.remove_roles.assert_not_awaited()


def test_liste_partielle_signalee():
    role = _Role()

    async def refuse(limit=None):
        raise discord.HTTPException(SimpleNamespace(status=500, reason="x"), "panne")
        yield  # pragma: no cover

    guild = SimpleNamespace(id=1, members=[_member(1)], fetch_members=refuse)
    suivi = mass_role.Progression(action="add", role_mention=role.mention)
    asyncio.run(mass_role.executer(guild, role, action="add", cible="members", raison="t", progression=suivi))
    assert suivi.liste_partielle and suivi.total == 1
    assert "seuls les membres en cache" in _texte(suivi.panneau())


def test_avant_la_liste_le_panneau_dit_qu_il_prepare():
    texte = _texte(mass_role.Progression(action="add", role_mention="<@&5>").panneau())
    assert "Récupération de la liste des membres" in texte
    assert "0 / 0" not in texte and "Temps restant" not in texte
