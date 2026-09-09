"""`+setup`/`/setup` appartiennent à la catégorie "configuration" de la matrice
centrale (utils/access_matrix.py:223, CATEGORY_COMMANDS["configuration"] contient
"setup") : cette catégorie exige "Gérer le serveur" (manage_guild), pas
Administrateur (cogs/permission_setup_hardening_v65.py:CATEGORY_REQUIRED_PERMISSION).
C'est ce que Discord affiche (default_permissions), ce que la matrice décide, et ce
que le projet teste lui-même (test_permissions_setup_hardening_v65.py::
test_manage_guild_allows_configuration_command).

Mais cogs/setup_control_center.py::_can_setup, appelé par les DEUX points d'entrée
(+setup et /setup), exigeait Administrateur en dur — un second verrou local jamais
synchronisé avec la matrice. Un staff avec "Gérer le serveur" mais sans
"Administrateur" voyait /setup proposé par Discord, validé par la matrice testée,
puis se faisait rejeter ici même. Test d'exécution réel, pas une lecture de code."""
from __future__ import annotations

import os
import unittest
from unittest.mock import AsyncMock, Mock

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import discord

from cogs import setup_control_center


def _member(*, manage_guild: bool, administrator: bool, member_id: int = 555) -> Mock:
    member = Mock(spec=discord.Member)
    member.id = member_id
    member.guild_permissions = Mock(spec=discord.Permissions)
    member.guild_permissions.manage_guild = manage_guild
    member.guild_permissions.administrator = administrator
    return member


def _bot_not_creator() -> Mock:
    bot = Mock()
    bot.db = Mock()
    bot.db.is_bot_creator = AsyncMock(return_value=False)
    return bot


class CanSetupTests(unittest.IsolatedAsyncioTestCase):
    async def test_manage_guild_seul_suffit_desormais(self):
        """C'est exactement le bug rapporté : avant le correctif, ce test échoue
        (False), alors que Discord affiche /setup à ce membre et que la matrice
        centrale l'autoriserait."""
        member = _member(manage_guild=True, administrator=False)
        allowed = await setup_control_center._can_setup(_bot_not_creator(), member, Mock())
        self.assertTrue(allowed)

    async def test_administrateur_continue_de_fonctionner(self):
        member = _member(manage_guild=False, administrator=True)
        allowed = await setup_control_center._can_setup(_bot_not_creator(), member, Mock())
        self.assertTrue(allowed)

    async def test_membre_sans_aucune_des_deux_permissions_reste_refuse(self):
        member = _member(manage_guild=False, administrator=False)
        allowed = await setup_control_center._can_setup(_bot_not_creator(), member, Mock())
        self.assertFalse(allowed)


if __name__ == "__main__":
    unittest.main()
