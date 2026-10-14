"""+server-restore sans sauvegarde : relire le journal d'audit Discord.

Une sauvegarde ne sert que si quelqu'un a pensé à la faire AVANT. Après un
nuke sur un serveur qui n'en avait aucune, `+server-restore` ne pouvait
rien faire. Le journal d'audit Discord, lui, existe toujours : chaque
suppression de salon ou de rôle y laisse le nom et les réglages de l'objet
supprimé.

Ce que le journal ne conserve PAS — et que la commande annonce au lieu de
le masquer : la catégorie d'origine d'un salon, ses permissions détaillées
et son historique de messages.
"""
from __future__ import annotations

import asyncio
import os
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import discord
import pytest

from cogs import security_tools


def _entree(nom, *, action, created_at, acteur=1, type_salon=None, perms=0):
    e = MagicMock()
    e.created_at = created_at
    e.user = MagicMock()
    e.user.id = acteur
    avant = MagicMock()
    avant.name = nom
    avant.topic = None
    avant.nsfw = False
    avant.hoist = False
    avant.mentionable = False
    avant.permissions = MagicMock(value=perms)
    avant.colour = MagicMock(value=0)
    avant.type = type_salon
    e.before = avant
    e.action = action
    return e


def _guild(entrees_role, entrees_salon, *, roles_vivants=(), salons_vivants=()):
    g = MagicMock(spec=discord.Guild)
    g.id = 9
    g.roles = [MagicMock(name=f"r{i}") for i, _ in enumerate(roles_vivants)]
    for r, nom in zip(g.roles, roles_vivants):
        r.name = nom
    g.channels = []
    for nom in salons_vivants:
        c = MagicMock()
        c.name = nom
        g.channels.append(c)

    def audit_logs(limit=None, action=None):
        choisies = entrees_role if action == discord.AuditLogAction.role_delete else entrees_salon

        class _Iter:
            def __aiter__(self):
                self._i = iter(choisies)
                return self

            async def __anext__(self):
                try:
                    return next(self._i)
                except StopIteration:
                    raise StopAsyncIteration

        return _Iter()

    g.audit_logs = audit_logs
    return g


def _cog():
    c = MagicMock(spec=security_tools.Security)
    c.LIMITE_ENTREES_AUDIT = security_tools.Security.LIMITE_ENTREES_AUDIT
    c._suppressions_recentes = security_tools.Security._suppressions_recentes.__get__(c)
    return c


def _maintenant():
    return discord.utils.utcnow()


def test_un_role_supprime_est_propose_a_la_recreation():
    g = _guild([_entree("Staff", action=discord.AuditLogAction.role_delete, created_at=_maintenant())], [])
    r = asyncio.run(_cog()._suppressions_recentes(g, 24))
    assert [x["name"] for x in r["roles"]] == ["Staff"]


def test_un_role_deja_recree_a_la_main_n_est_pas_propose_deux_fois():
    g = _guild(
        [_entree("Staff", action=discord.AuditLogAction.role_delete, created_at=_maintenant())],
        [],
        roles_vivants=("Staff",),
    )
    assert asyncio.run(_cog()._suppressions_recentes(g, 24))["roles"] == []


def test_everyone_n_est_jamais_recree():
    g = _guild([_entree("@everyone", action=discord.AuditLogAction.role_delete, created_at=_maintenant())], [])
    assert asyncio.run(_cog()._suppressions_recentes(g, 24))["roles"] == []


def test_les_categories_et_les_salons_sont_distingues():
    maintenant = _maintenant()
    salons = [
        _entree("général", action=discord.AuditLogAction.channel_delete,
                created_at=maintenant, type_salon=discord.ChannelType.text),
        _entree("Vocaux", action=discord.AuditLogAction.channel_delete,
                created_at=maintenant, type_salon=discord.ChannelType.category),
        _entree("Papote", action=discord.AuditLogAction.channel_delete,
                created_at=maintenant, type_salon=discord.ChannelType.voice),
    ]
    r = asyncio.run(_cog()._suppressions_recentes(_guild([], salons), 24))
    assert [x["name"] for x in r["categories"]] == ["Vocaux"]
    assert {x["name"]: x["kind"] for x in r["channels"]} == {"général": "text", "Papote": "voice"}


def test_une_suppression_hors_fenetre_est_ignoree():
    vieux = _maintenant() - timedelta(hours=48)
    g = _guild([_entree("Staff", action=discord.AuditLogAction.role_delete, created_at=vieux)], [])
    assert asyncio.run(_cog()._suppressions_recentes(g, 24))["roles"] == []


def test_le_meme_nom_supprime_deux_fois_n_est_recree_qu_une_fois():
    maintenant = _maintenant()
    doublons = [
        _entree("spam", action=discord.AuditLogAction.channel_delete,
                created_at=maintenant, type_salon=discord.ChannelType.text),
        _entree("spam", action=discord.AuditLogAction.channel_delete,
                created_at=maintenant, type_salon=discord.ChannelType.text),
    ]
    r = asyncio.run(_cog()._suppressions_recentes(_guild([], doublons), 24))
    assert len(r["channels"]) == 1


def test_les_auteurs_et_la_periode_sont_rapportes():
    """Le propriétaire doit savoir QUI a supprimé et QUAND, pas seulement quoi."""
    t0 = _maintenant() - timedelta(minutes=10)
    t1 = _maintenant()
    g = _guild(
        [_entree("A", action=discord.AuditLogAction.role_delete, created_at=t0, acteur=42),
         _entree("B", action=discord.AuditLogAction.role_delete, created_at=t1, acteur=42)],
        [],
    )
    r = asyncio.run(_cog()._suppressions_recentes(g, 24))
    assert r["auteurs"] == {42: 2}
    assert r["premiere"] == t0 and r["derniere"] == t1


def test_le_parametre_de_sauvegarde_est_devenu_optionnel():
    """Sans numéro, la commande bascule sur le journal d'audit."""
    import inspect

    # server_restore est une hybrid_command : l'attribut est l'objet Command,
    # la fonction se trouve derrière .callback.
    commande = security_tools.Security.server_restore
    fonction = getattr(commande, "callback", commande)
    params = inspect.signature(fonction).parameters
    assert params["backup_id"].default is None


def test_la_commande_annonce_ce_que_le_journal_ne_sait_pas():
    """Ne pas laisser croire à une restauration fidèle."""
    import inspect

    src = inspect.getsource(security_tools.Security._restaurer_depuis_audit)
    assert "ne conserve ni la catégorie d'origine" in src
    assert "view_audit_log" in src, "la permission requise doit être vérifiée"
