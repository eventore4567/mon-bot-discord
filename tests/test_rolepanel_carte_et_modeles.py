"""04/11/2026 : /role menu en vraie carte, avec des modèles de rôles prêts à l'emploi."""
from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import discord  # noqa: E402

import sentrix_regression_runtime as srr  # noqa: E402


class _Guild:
    def __init__(self, noms_existants=()):
        self.roles = [SimpleNamespace(name=n, id=100 + i) for i, n in enumerate(noms_existants)]
        self.crees = []

    async def create_role(self, *, name, colour, mentionable, reason):
        role = SimpleNamespace(name=name, id=500 + len(self.crees))
        self.crees.append(name)
        self.roles.append(role)
        return role

    def get_role(self, role_id):
        return next((r for r in self.roles if r.id == role_id), None)


def test_un_modele_reutilise_l_existant_et_cree_le_reste():
    guild = _Guild(noms_existants=["🔔 annonces"])
    roles, erreurs = asyncio.run(srr.creer_roles_du_modele(guild, "notifications"))
    attendus = [nom for nom, _ in srr.ROLE_PRESETS["notifications"][2]]
    assert [r.name for r in roles][0] == "🔔 annonces"  # même nom, casse différente
    assert guild.crees == attendus[1:]
    assert erreurs == []


def test_sans_permission_on_s_arrete_proprement():
    class Refus(_Guild):
        async def create_role(self, **kwargs):
            raise discord.Forbidden(SimpleNamespace(status=403, reason="Forbidden"), "non")

    roles, erreurs = asyncio.run(srr.creer_roles_du_modele(Refus(), "couleurs"))
    assert roles == [] and len(erreurs) == 1 and "Gérer les rôles" in erreurs[0]


def test_le_constructeur_est_une_carte_v2_avec_les_menus_dedans():
    async def scenario():
        guild = _Guild()
        vue = srr.RolePanelBuilder(SimpleNamespace(), guild, 42)
        return vue

    vue = asyncio.run(scenario())
    assert isinstance(vue, discord.ui.LayoutView)
    carte = vue.children[0]
    assert isinstance(carte, discord.ui.Container)
    assert carte.accent_colour is not None
    elements = [type(e.children[0]).__name__ for e in carte.children if isinstance(e, discord.ui.ActionRow)]
    assert elements[:3] == ["BuilderRolePicker", "BuilderPresetSelect", "BuilderModeSelect"]
    texte = carte.children[0].content
    assert "Panneau de rôles" in texte and "modèle" in texte
    # « Créer le panneau » attend au moins un rôle.
    boutons = [e for e in carte.children if isinstance(e, discord.ui.ActionRow)][-1].children
    assert boutons[0].label == "Créer le panneau" and boutons[0].disabled
