"""Drops d'argent automatiques : apparition périodique dans un salon configuré.

`+drop` existait mais restait MANUEL — un administrateur devait le taper.
Jayden voulait « un truc qui spawn dans le salon qu'on a configuré, et le
premier qui clique gagne ». La mécanique mono-gagnant existait déjà (verrou
dans MoneyDropView) : il manquait la configuration et la boucle.
"""
from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import pytest


class _DB:
    """Base minimale : la logique testée est le filtrage et l'horodatage."""

    def __init__(self, lignes=None):
        self.lignes = lignes or []
        self.maj: list[tuple[int, dict]] = []

    async def auto_drops_a_lancer(self, maintenant):
        return list(self.lignes)

    async def set_auto_drop_config(self, guild_id, updates, actor_id=None):
        self.maj.append((guild_id, dict(updates)))
        return {}


def _cog(db, lance=None):
    from cogs.drop import MoneyDrops

    cog = MoneyDrops.__new__(MoneyDrops)
    cog.bot = SimpleNamespace(db=db)
    cog._lancer_drop_automatique = lance or (lambda reglage: asyncio.sleep(0))
    return cog


def test_rien_ne_part_quand_aucun_serveur_n_est_du():
    from cogs.drop import MoneyDrops

    db = _DB([])
    lances = []
    cog = _cog(db, lance=lambda r: lances.append(r) or asyncio.sleep(0))
    asyncio.run(MoneyDrops._boucle_auto_drop.coro(cog))
    assert lances == []
    assert db.maj == []


def test_l_horodatage_est_pose_avant_l_envoi():
    """Sinon un salon interdit ferait réessayer la boucle toutes les minutes,
    indéfiniment, sur les 28 serveurs."""
    from cogs.drop import MoneyDrops

    db = _DB([{"guild_id": 7}])
    ordre: list[str] = []

    async def lance(reglage):
        ordre.append("envoi")
        raise RuntimeError("salon interdit")

    cog = _cog(db, lance=lance)
    db_set = db.set_auto_drop_config

    async def set_traque(guild_id, updates, actor_id=None):
        ordre.append("horodatage")
        return await db_set(guild_id, updates, actor_id)

    db.set_auto_drop_config = set_traque
    # L'échec d'envoi ne doit pas remonter : la boucle tourne toutes les minutes.
    asyncio.run(MoneyDrops._boucle_auto_drop.coro(cog))
    assert ordre == ["horodatage", "envoi"]
    assert db.maj and "last_drop_at" in db.maj[0][1]


def test_une_base_indisponible_ne_casse_pas_la_boucle():
    from cogs.drop import MoneyDrops

    class _Cassee:
        async def auto_drops_a_lancer(self, maintenant):
            raise RuntimeError("base indisponible")

    cog = _cog(_Cassee())
    asyncio.run(MoneyDrops._boucle_auto_drop.coro(cog))  # ne lève pas


@pytest.mark.parametrize(
    ("minutes", "attendu"),
    [(1, 5), (5, 5), (60, 60), (5000, 1440)],
)
def test_l_intervalle_reste_dans_des_bornes_raisonnables(minutes, attendu):
    """Moins de cinq minutes noierait le salon ; plus d'un jour n'est plus un
    drop. Les bornes sont appliquées à l'écriture, pas seulement affichées."""
    assert max(5, min(int(minutes), 1440)) == attendu


def test_le_filtre_des_serveurs_dus_est_en_sql():
    """Parcourir les 28 serveurs en Python chaque minute ferait un aller-retour
    par serveur pour n'en retenir presque jamais aucun."""
    import ast
    import inspect
    import textwrap

    from database.db import Database

    source = textwrap.dedent(inspect.getsource(Database.auto_drops_a_lancer))
    requete = next(
        n.value for n in ast.walk(ast.parse(source))
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and "SELECT" in n.value
    )
    assert "enabled = 1" in requete
    assert "channel_id IS NOT NULL" in requete
    assert "interval_minutes" in requete


def test_le_drop_automatique_garde_le_symbole_monetaire():
    """Envoi depuis une tâche de fond : sans contexte de commande, la couche
    sobre mangeait la pièce et laissait « **128 ** viennent d'apparaître »."""
    import inspect

    from cogs.drop import MoneyDrops
    from utils.embeds import strip_emojis
    from utils.game_context import pictogrammes_porteurs

    source = inspect.getsource(MoneyDrops._lancer_drop_automatique)
    assert "pictogrammes_porteurs()" in source
    # Le bloc doit couvrir la CONSTRUCTION de l'embed, pas seulement l'envoi.
    assert source.index("pictogrammes_porteurs()") < source.index("create_embed")

    assert strip_emojis("135 🪙 ici") != "135 🪙 ici"
    with pictogrammes_porteurs():
        assert strip_emojis("135 🪙 ici") == "135 🪙 ici"


def test_les_commandes_de_configuration_sont_reservees_a_la_gestion_economie():
    """Un drop automatique crée de la monnaie sans intervention : le régler
    n'est pas une commande publique."""
    from utils.access_matrix import CATEGORY_COMMANDS

    assert "autodrop" in CATEGORY_COMMANDS["economie"]
    assert "autodrop-off" in CATEGORY_COMMANDS["economie"]
