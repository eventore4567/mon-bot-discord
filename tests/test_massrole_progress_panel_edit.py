"""+massrole (cogs/server_choice_roles.py::_massrole_all_members) mettait à
jour son message de progression avec `progress.edit(embed=...)`, alors que ce
message était né en panneau Components V2 (`panels.envoyer(ctx, panels.
depuis_embed(...))`). Discord refuse ce mélange une fois le message créé
(voir utils/sentrix_panels.py::editer, et tests/test_coherence_components_v2.py
qui détecte cette classe de bug par analyse statique) — sur un serveur d'au
moins 2000 membres, la première mise à jour de progression aurait donc levé
une discord.HTTPException à chaque fois (silencieusement avalée par le
`except discord.HTTPException: pass` existant, donc sans jamais planter la
commande, mais sans jamais afficher de progression non plus).

Corrigé en remplaçant `progress.edit(embed=...)` par `panels.editer(progress,
panels.depuis_embed(...))`, la fonction dédiée à l'édition d'un message déjà
né en panneau. Ce test vérifie que c'est bien panels.editer qui est appelé —
`progress` est un objet nu sans `.edit()` : l'ancien code lèverait donc une
AttributeError ici si la régression revenait.

Le seuil de mise à jour (tous les 2000 membres traités) n'est atteint que si
``processed`` (qui n'augmente que par lots de 15, ``batch_size``) tombe
exactement sur un multiple de 2000 — le plus petit tel nombre est
PPCM(15, 2000) = 6000, d'où le nombre de membres simulés ci-dessous."""
from __future__ import annotations

import asyncio
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from cogs import server_choice_roles


class _FakeRole:
    def __init__(self, position: int):
        self.position = position
        self.managed = False
        self.mention = "@Role"

    def is_default(self) -> bool:
        return False

    def __ge__(self, other) -> bool:
        return self.position >= other.position

    def __eq__(self, other) -> bool:
        return isinstance(other, _FakeRole) and self.position == other.position

    def __hash__(self) -> int:
        return id(self)


class _FakeMember:
    def __init__(self, member_id: int):
        self.id = member_id
        self.bot = False
        self.roles = []
        self.add_roles = AsyncMock()
        self.remove_roles = AsyncMock()


async def _members(count: int):
    for i in range(count):
        yield _FakeMember(i)


class _ProgressMessage:
    """Volontairement dépourvu de .edit() : l'ancien code (progress.edit(...))
    lèverait AttributeError s'il était encore appelé."""


class MassroleProgressPanelEditTests(unittest.IsolatedAsyncioTestCase):
    async def test_la_progression_est_editee_via_panels_editer_pas_edit_embed(self):
        role = _FakeRole(position=1)
        me = SimpleNamespace(
            guild_permissions=SimpleNamespace(manage_roles=True),
            top_role=_FakeRole(position=5),
        )
        guild = SimpleNamespace(
            me=me,
            member_count=6000,
            fetch_members=lambda limit=None: _members(6000),
        )
        progress = _ProgressMessage()
        ctx = SimpleNamespace(guild=guild, author=SimpleNamespace())

        with patch.object(server_choice_roles.panels, "envoyer", AsyncMock(return_value=progress)), \
             patch.object(server_choice_roles.panels, "editer", AsyncMock()) as editer:
            await server_choice_roles._massrole_all_members(None, ctx, "add", role)

        editer.assert_awaited()
        cible, panneau = editer.await_args.args[:2]
        self.assertIs(cible, progress)
        self.assertIsInstance(panneau, server_choice_roles.panels.Panneau)


if __name__ == "__main__":
    unittest.main()
