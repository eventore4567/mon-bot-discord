"""L'historique d'invitations d'autrui est une information de staff.

Relevé par tools/permission_audit_sweep.py le 2026-10-14 — la seule
anomalie classée « escalade » sur 5715 combinaisons testées :

    | `+invitehistory <@…>` | membre | module-on | refuse (permission) | autorise |

La commande n'avait aucun contrôle. N'importe quel membre pouvait lire qui
un autre avait invité, avec les codes d'invitation, le départ éventuel de
chaque invité et le marqueur « compte récent ».

Consulter son propre historique reste libre : couper l'accès à tout le
monde aurait réglé l'escalade en supprimant un usage légitime.
"""
from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import discord
import pytest


def _contexte(auteur_id: int, *, staff: bool):
    ctx = MagicMock()
    # spec=discord.Member est nécessaire : checks.is_mod_or_permission commence
    # par un isinstance et refuserait un mock générique, ce qui ferait passer
    # le test du staff pour la mauvaise raison.
    ctx.author = MagicMock(spec=discord.Member)
    ctx.author.id = auteur_id
    ctx.author.guild_permissions = MagicMock(manage_guild=staff)
    ctx.author.roles = []
    ctx.guild = MagicMock()
    ctx.guild.id = 500
    ctx.guild.get_role.return_value = None
    ctx.bot = MagicMock()
    ctx.bot.db.get_guild_config = AsyncMock(return_value=None)
    ctx.bot.db.fetchall = AsyncMock(return_value=[])
    return ctx


def _cible(user_id: int):
    m = MagicMock()
    m.id = user_id
    m.mention = f"<@{user_id}>"
    m.display_name = "Cible"
    return m


async def _appeler(ctx, cible, envoyer):
    from cogs import invites

    cog = MagicMock(spec=invites.Invites)
    cog.bot = ctx.bot
    commande = invites.Invites.invite_history
    fonction = getattr(commande, "callback", commande)
    return await fonction(cog, ctx, cible)


@pytest.fixture
def envoyer(monkeypatch):
    from cogs import invites

    faux = AsyncMock()
    monkeypatch.setattr(invites.panels, "envoyer", faux)
    return faux


@pytest.mark.asyncio
async def test_un_membre_simple_ne_lit_pas_l_historique_d_un_autre(envoyer):
    ctx = _contexte(1, staff=False)
    await _appeler(ctx, _cible(2), envoyer)
    ctx.bot.db.fetchall.assert_not_awaited(), "la requête ne doit même pas partir"
    envoyer.assert_awaited_once()


@pytest.mark.asyncio
async def test_un_membre_simple_lit_son_propre_historique(envoyer):
    ctx = _contexte(1, staff=False)
    await _appeler(ctx, _cible(1), envoyer)
    ctx.bot.db.fetchall.assert_awaited_once()


@pytest.mark.asyncio
async def test_sans_argument_on_voit_le_sien(envoyer):
    ctx = _contexte(1, staff=False)
    await _appeler(ctx, None, envoyer)
    ctx.bot.db.fetchall.assert_awaited_once()


@pytest.mark.asyncio
async def test_le_staff_lit_l_historique_d_un_autre(envoyer):
    ctx = _contexte(1, staff=True)
    await _appeler(ctx, _cible(2), envoyer)
    ctx.bot.db.fetchall.assert_awaited_once()


@pytest.mark.asyncio
async def test_le_role_staff_configure_suffit_aussi(envoyer):
    """Pas besoin de « Gérer le serveur » si le rôle staff de Setup est posé."""
    ctx = _contexte(1, staff=False)
    role = MagicMock()
    ctx.author.roles = [role]
    ctx.guild.get_role.return_value = role
    ctx.bot.db.get_guild_config = AsyncMock(return_value={"mod_role": 77})
    await _appeler(ctx, _cible(2), envoyer)
    ctx.bot.db.fetchall.assert_awaited_once()
