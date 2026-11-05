"""05/11/2026 : tout le monde peut ouvrir /setup ; seul le staff le modifie."""
from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from cogs import setup_components_v73 as v73  # noqa: E402


def _user(uid=10, admin=False, gerer=False):
    return SimpleNamespace(id=uid, guild_permissions=SimpleNamespace(administrator=admin, manage_guild=gerer))


def test_qui_peut_configurer():
    guild = SimpleNamespace(owner_id=1)
    assert v73.peut_configurer(_user(1), guild) is True          # propriétaire
    assert v73.peut_configurer(_user(admin=True), guild) is True
    assert v73.peut_configurer(_user(gerer=True), guild) is True
    assert v73.peut_configurer(_user(), guild) is False           # simple membre


def _vue(author_id):
    vue = v73.SentriXSetupV73.__new__(v73.SentriXSetupV73)
    vue.author_id = author_id
    vue.guild = SimpleNamespace(owner_id=1)
    return vue


def _interaction(user):
    return SimpleNamespace(user=user, response=SimpleNamespace())


def test_un_clic_de_simple_membre_est_refuse_en_carte(monkeypatch):
    envois = []

    async def envoyer(destination, panneau, **kwargs):
        envois.append((panneau, kwargs))

    monkeypatch.setattr(v73.panels, "envoyer", envoyer)
    autorise = asyncio.run(_vue(10).interaction_check(_interaction(_user(10))))
    assert autorise is False
    panneau, kwargs = envois[0]
    assert panneau.titre == "🔒 Accès refusé"
    assert "Administrateur ou Gérer le serveur" in str(panneau.sous_titre)
    assert kwargs.get("ephemere") is True


def test_un_clic_d_admin_passe(monkeypatch):
    monkeypatch.setattr(v73.panels, "envoyer", AsyncMock())
    assert asyncio.run(_vue(10).interaction_check(_interaction(_user(10, admin=True)))) is True


def test_le_panneau_servi_herite_du_controle_des_clics():
    # Le panneau réellement servi (setup_invitations → v74) hérite de V73 :
    # c'est lui qui refuse les modifications d'un simple membre.
    from cogs import setup_experience_v74 as v74

    assert issubclass(v74.SentriXSetupV74, v73.SentriXSetupV73)
    assert v74.SentriXSetupV74.interaction_check is v73.SentriXSetupV73.interaction_check
