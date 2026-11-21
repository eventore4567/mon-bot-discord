"""Donner un rôle Administrateur à un complice : le rôle repart (21/11/2026).

« fait que quand permission dangereuse vas juste retirer le role donner, bien
sûr il sanctionne pas les admin et owner. »

La garde des permissions surveillait la création d'un rôle, la modification
d'un rôle et les permissions de salon. Elle ne surveillait PAS le geste le plus
simple pour préparer un nuke : donner un rôle Administrateur déjà existant à un
deuxième compte. Aucun écouteur ``on_member_update`` n'existait dans le cog, le
rôle restait donc en place indéfiniment.
"""
from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import pytest  # noqa: E402

from cogs.automod import AutoMod  # noqa: E402


class _Perms:
    def __init__(self, **flags):
        self._flags = flags

    def __getattr__(self, nom):
        return self._flags.get(nom, False)


def _role(identifiant, nom="staff", **perms):
    return SimpleNamespace(id=identifiant, name=nom, mention=f"<@&{identifiant}>",
                           permissions=_Perms(**perms))


def _membre(identifiant, roles):
    membre = SimpleNamespace(
        id=identifiant, roles=list(roles), mention=f"<@{identifiant}>",
        remove_roles=AsyncMock(),
    )
    return membre


def _cog(*, exempt=False, security_permissions=1, owner_id=999):
    cog = AutoMod.__new__(AutoMod)
    cog.bot = SimpleNamespace(user=SimpleNamespace(id=2))
    cog.get_automod_cached = AsyncMock(
        return_value={"antinuke": 1, "security_permissions": security_permissions}
    )
    cog.get_audit_actor = AsyncMock(return_value=SimpleNamespace(id=77))
    cog.is_antinuke_exempt = AsyncMock(return_value=exempt)
    cog.add_risk_signal = AsyncMock()
    cog.record_nuke_action = AsyncMock(return_value=True)
    cog.punish_nuker = AsyncMock()
    cog._journal_securite = AsyncMock()
    return cog


def _serveur(membre, owner_id=999):
    guild = SimpleNamespace(id=1, owner_id=owner_id)
    membre.guild = guild
    return guild


ADMIN = lambda i=50: _role(i, "admin", administrator=True)  # noqa: E731
BANAL = lambda i=60: _role(i, "membre")  # noqa: E731


async def _changer(cog, avant_roles, apres_roles, *, membre_id=5, owner_id=999):
    avant = _membre(membre_id, avant_roles)
    apres = _membre(membre_id, apres_roles)
    _serveur(avant, owner_id)
    _serveur(apres, owner_id)
    await cog.on_member_update(avant, apres)
    return apres


@pytest.mark.asyncio
async def test_le_role_administrateur_donne_est_retire():
    cog = _cog()
    admin = ADMIN()
    apres = await _changer(cog, [BANAL()], [BANAL(), admin])

    apres.remove_roles.assert_awaited_once()
    assert apres.remove_roles.await_args.args[0] is admin
    cog._journal_securite.assert_awaited_once()


@pytest.mark.asyncio
async def test_seul_le_role_dangereux_part_les_autres_restent():
    """« juste retirer le rôle donné » : on ne déshabille pas le membre.

    Retirer tous ses rôles ferait perdre à un modérateur légitime son accès
    aux salons staff à cause d'un rôle qu'un autre lui a donné.
    """
    cog = _cog()
    admin = ADMIN()
    apres = await _changer(cog, [], [BANAL(61), admin, BANAL(62)])

    assert apres.remove_roles.await_count == 1
    assert apres.remove_roles.await_args.args[0] is admin


@pytest.mark.asyncio
async def test_l_auteur_n_est_jamais_sanctionne_par_cette_garde():
    """Un admin qui se trompe de rôle ne mérite pas un bannissement.

    Le signal part au moteur de risque (un vrai nuke sera donc vu par les
    compteurs), mais cette garde-là ne bannit, n'expulse et n'exclut personne.
    """
    cog = _cog()
    await _changer(cog, [], [ADMIN()])

    cog.add_risk_signal.assert_awaited_once()
    cog.punish_nuker.assert_not_awaited()
    cog.record_nuke_action.assert_not_awaited()


@pytest.mark.asyncio
async def test_un_role_sans_permission_dangereuse_ne_declenche_rien():
    cog = _cog()
    apres = await _changer(cog, [], [BANAL()])
    apres.remove_roles.assert_not_awaited()
    cog.add_risk_signal.assert_not_awaited()


@pytest.mark.asyncio
async def test_un_role_retire_ne_declenche_rien():
    """Sens du changement : on ne réagit qu'aux rôles GAGNÉS.

    Sans ce filtre, retirer un rôle admin à quelqu'un déclencherait la garde,
    qui tenterait de le retirer une deuxième fois.
    """
    cog = _cog()
    apres = await _changer(cog, [ADMIN()], [])
    apres.remove_roles.assert_not_awaited()


@pytest.mark.asyncio
async def test_un_auteur_exempte_est_laisse_tranquille():
    """Admins, propriétaire, propriétaires de SentriX, liste blanche.

    ``is_antinuke_exempt`` les couvre déjà tous — y compris le bot lui-même,
    sinon un autorôle verrait son rôle retiré aussitôt donné.
    """
    cog = _cog(exempt=True)
    apres = await _changer(cog, [], [ADMIN()])
    apres.remove_roles.assert_not_awaited()
    cog._journal_securite.assert_not_awaited()


@pytest.mark.asyncio
async def test_le_proprietaire_du_serveur_garde_ses_roles():
    """Lui retirer un rôle ne protège rien : il a déjà tous les droits.

    En revanche ça casserait son propre serveur, et le propriétaire se
    retrouverait sans rôle staff visible.
    """
    cog = _cog()
    apres = await _changer(cog, [], [ADMIN()], membre_id=999, owner_id=999)
    apres.remove_roles.assert_not_awaited()


@pytest.mark.asyncio
async def test_garde_des_permissions_coupee_ne_fait_rien():
    cog = _cog(security_permissions=0)
    apres = await _changer(cog, [], [ADMIN()])
    apres.remove_roles.assert_not_awaited()


@pytest.mark.asyncio
async def test_un_retrait_refuse_par_discord_est_journalise_comme_un_echec():
    """Rôle au-dessus de celui de SentriX : il faut le dire, pas se taire."""
    import discord

    cog = _cog()
    avant = _membre(5, [])
    apres = _membre(5, [ADMIN()])
    apres.remove_roles = AsyncMock(side_effect=discord.Forbidden(
        SimpleNamespace(status=403, reason="Forbidden"), "missing permissions"
    ))
    _serveur(avant)
    _serveur(apres)
    await cog.on_member_update(avant, apres)

    cog._journal_securite.assert_awaited_once()
    assert cog._journal_securite.await_args.kwargs["echec"] is True
