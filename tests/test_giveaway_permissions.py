"""`+giveaway` (`commands.group`, cogs/giveaway_center.py:88) affiche les giveaways en
cours quand on l'invoque sans sous-commande — aussi public que l'ancienne commande
`giveaway-list` qu'il remplace. Mais `access_matrix.py` ne classait "giveaway" que
dans `CATEGORY_COMMANDS["configuration"]` (Administrateur requis), et
`command_root_name()` résout TOUJOURS une sous-commande vers le nom de sa racine sauf
entrée `SUBCOMMAND_TIERS` explicite — donc `+giveaway` ET `+giveaway list` exigeaient
tous deux Administrateur, alors que `+giveaway-list` (l'ancienne commande plate,
toujours enregistrée) restait public. Un membre normal ne pouvait donc plus voir les
giveaways en cours via la nouvelle commande groupée.

`cogs/command_catalog_cleanup.py:190` tente bien d'ajouter "giveaway" à
`main.PUBLIC_COMMANDS`, mais c'est le mauvais module : la décision réelle passe par
`utils.access_matrix.PUBLIC_COMMANDS`, jamais modifié — ce correctif était mort.

Corrigé en ajoutant "giveaway" à `utils.access_matrix.PUBLIC_COMMANDS`, et en
déclarant les 6 sous-commandes réellement dangereuses (create/end/reroll/cancel/
blacklist/unblacklist) dans `SUBCOMMAND_TIERS` pour qu'elles restent PLUS strictes
que leur racine désormais publique."""
from __future__ import annotations

import os
import unittest
from unittest.mock import AsyncMock

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from types import SimpleNamespace

from utils import access_matrix


def _normal_member():
    return SimpleNamespace(id=1, guild_permissions=SimpleNamespace(administrator=False))


def _bot_not_owner():
    return SimpleNamespace(
        sentrix_access_backend=None,
        blacklist_cache={},
        db=SimpleNamespace(is_bot_creator=AsyncMock(return_value=False)),
    )


class GiveawayPermissionTests(unittest.IsolatedAsyncioTestCase):
    async def test_giveaway_bare_est_public(self):
        """C'est exactement le bug rapporté : avant le correctif, ce test échoue
        (allowed=False) — un membre normal ne pouvait pas voir les giveaways en
        cours avec la commande groupée, alors que l'ancienne +giveaway-list restait
        publique."""
        decision = await access_matrix.evaluate(
            _bot_not_owner(), command_name="giveaway", author=_normal_member(), guild=SimpleNamespace(id=1, owner_id=999)
        )
        self.assertTrue(decision.allowed)

    async def test_giveaway_list_est_public(self):
        decision = await access_matrix.evaluate(
            _bot_not_owner(), command_name="giveaway list", author=_normal_member(), guild=SimpleNamespace(id=1, owner_id=999)
        )
        self.assertTrue(decision.allowed)

    async def test_giveaway_create_end_reroll_cancel_blacklist_restent_reserves(self):
        """Non-régression : rendre la racine publique ne doit JAMAIS rendre les
        actions destructrices publiques avec elle."""
        guild = SimpleNamespace(id=1, owner_id=999)
        for name in (
            "giveaway create", "giveaway end", "giveaway reroll",
            "giveaway cancel", "giveaway blacklist", "giveaway unblacklist",
        ):
            with self.subTest(name=name):
                decision = await access_matrix.evaluate(
                    _bot_not_owner(), command_name=name, author=_normal_member(), guild=guild
                )
                self.assertFalse(decision.allowed, f"{name} ne doit pas être accessible à un membre normal")

    async def test_administrateur_garde_acces_aux_actions_sensibles(self):
        admin = SimpleNamespace(id=1, guild_permissions=SimpleNamespace(administrator=True))
        guild = SimpleNamespace(id=1, owner_id=999)
        decision = await access_matrix.evaluate(
            _bot_not_owner(), command_name="giveaway create", author=admin, guild=guild
        )
        self.assertTrue(decision.allowed)


if __name__ == "__main__":
    unittest.main()
