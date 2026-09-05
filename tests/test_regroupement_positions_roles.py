"""Déplacer UN rôle faisait rate-limiter le bot.

Dans Discord, déplacer un rôle décale tous les rôles situés entre l'ancienne et la
nouvelle position : l'API émet donc un évènement ``on_guild_role_update`` PAR rôle
touché. L'ancien code traitait chacun séparément, avec pour chaque évènement :

- une lecture d'audit log (appel API) ;
- un message Components V2 **avec upload de la bannière**.

Un simple glissement dans une liste de 20 rôles produisait donc 20 lectures d'audit
et 20 messages en rafale, d'où les ``We are being rate limited. POST /channels/.../messages``
relevés en production (26 lignes sur un échantillon de 500).

La rafale est désormais accumulée puis émise en UN seul log. Rien n'est perdu :
tous les déplacements sont listés. Ces tests verrouillent le comportement.
"""
from __future__ import annotations

import asyncio
import os
from unittest.mock import AsyncMock, Mock, patch

os.environ.setdefault("DISCORD_TOKEN", "x")

import discord  # noqa: E402

from cogs import create_sentrix_v3 as v3  # noqa: E402

_DELAI_TEST = 0.05


def _role(role_id: int, position: int) -> Mock:
    role = Mock(spec=discord.Role)
    role.id = role_id
    role.position = position
    role.mention = f"<@&{role_id}>"
    return role


def _guild(guild_id: int = 4242) -> Mock:
    guild = Mock(spec=discord.Guild)
    guild.id = guild_id
    guild.get_role = lambda rid: _role(rid, 0)
    return guild


async def _rafale(mouvements: list[tuple[int, int, int]]):
    """Joue une rafale de déplacements et renvoie les appels à send_log."""
    cog = v3.CreateSentriXV3(Mock())
    guild = _guild()

    envois: list[dict] = []

    async def faux_send_log(bot, g, log_type, panel, **kwargs):
        envois.append({"log_type": log_type, "panel": panel, "kwargs": kwargs})

    audit = AsyncMock(return_value=None)

    with patch.object(v3, "_DELAI_REGROUPEMENT_POSITIONS", _DELAI_TEST), \
         patch.object(v3.log_service, "send_log", faux_send_log), \
         patch.object(v3, "_audit_actor_for", audit):
        for role_id, avant, apres in mouvements:
            before = _role(role_id, avant)
            after = _role(role_id, apres)
            after.guild = guild
            await cog.on_guild_role_update(before, after)

        # Laisse la fenêtre de regroupement se refermer.
        await asyncio.sleep(_DELAI_TEST * 6)

    return envois, audit


async def _vingt_deplacements_donnent_un_seul_log():
    mouvements = [(1000 + i, i, i + 1) for i in range(20)]
    envois, audit = await _rafale(mouvements)

    assert len(envois) == 1, f"une rafale de 20 rôles doit produire 1 log, pas {len(envois)}"
    assert audit.await_count == 1, "une seule lecture d'audit log pour toute la rafale"

    champs = {f.name: f.value for f in envois[0]["panel"].fields}
    assert "Rôles concernés" in champs
    assert "**20**" in champs["Rôles concernés"]
    # Aucun déplacement n'est perdu.
    for role_id, _, _ in mouvements:
        assert str(role_id) in champs["Positions modifiées"]


def test_une_rafale_de_vingt_roles_ne_produit_qu_un_log():
    asyncio.run(_vingt_deplacements_donnent_un_seul_log())


async def _un_seul_deplacement_garde_le_format_historique():
    envois, _ = await _rafale([(777, 3, 9)])
    assert len(envois) == 1
    panel = envois[0]["panel"]
    champs = {f.name: f.value for f in panel.fields}
    assert "Rôle" in champs and "Position modifiée" in champs
    assert "`3` → `9`" in champs["Position modifiée"]


def test_un_deplacement_isole_conserve_le_format_detaille():
    asyncio.run(_un_seul_deplacement_garde_le_format_historique())


async def _role_revenu_a_sa_place_n_est_pas_journalise():
    # Le rôle bouge puis revient : au final il n'a pas changé de place.
    envois, _ = await _rafale([(55, 4, 7), (55, 7, 4)])
    assert envois == [], "un déplacement annulé ne doit produire aucun log"


def test_un_deplacement_annule_ne_produit_aucun_log():
    asyncio.run(_role_revenu_a_sa_place_n_est_pas_journalise())


async def _positions_identiques_ignorees():
    envois, audit = await _rafale([(9, 5, 5)])
    assert envois == []
    assert audit.await_count == 0, "aucun appel API pour un évènement sans déplacement"


def test_un_evenement_sans_deplacement_ne_coute_aucun_appel_api():
    asyncio.run(_positions_identiques_ignorees())


async def _deux_serveurs_ne_se_melangent_pas():
    cog = v3.CreateSentriXV3(Mock())
    envois: list[int] = []

    async def faux_send_log(bot, g, log_type, panel, **kwargs):
        envois.append(g.id)

    with patch.object(v3, "_DELAI_REGROUPEMENT_POSITIONS", _DELAI_TEST), \
         patch.object(v3.log_service, "send_log", faux_send_log), \
         patch.object(v3, "_audit_actor_for", AsyncMock(return_value=None)):
        for guild_id in (111, 222):
            after = _role(1, 2)
            after.guild = _guild(guild_id)
            await cog.on_guild_role_update(_role(1, 1), after)
        await asyncio.sleep(_DELAI_TEST * 6)

    assert sorted(envois) == [111, 222], "chaque serveur garde son propre regroupement"


def test_les_serveurs_sont_regroupes_separement():
    asyncio.run(_deux_serveurs_ne_se_melangent_pas())


async def _cog_unload_annule_les_taches():
    cog = v3.CreateSentriXV3(Mock())
    with patch.object(v3, "_DELAI_REGROUPEMENT_POSITIONS", 30.0):
        after = _role(1, 2)
        after.guild = _guild()
        await cog.on_guild_role_update(_role(1, 1), after)
        assert cog._taches_positions, "une tâche de regroupement doit être en attente"
        taches = list(cog._taches_positions.values())
        cog.cog_unload()
        await asyncio.sleep(0)
        assert all(t.cancelled() or t.done() for t in taches)
        assert not cog._taches_positions and not cog._positions_roles


def test_le_dechargement_du_cog_ne_laisse_aucune_tache():
    asyncio.run(_cog_unload_annule_les_taches())
