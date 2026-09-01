"""Coherence du cache des interrupteurs de modules.

Ecrit AVANT l'optimisation : ces tests decrivent le comportement actuel de
setup_v2_core.module_enabled et doivent rester verts apres la mise en cache.

Un interrupteur de module est une donnee de CONFIGURATION : renvoyer une valeur
perimee reviendrait a laisser tourner un module que l'administrateur vient de couper.
L'invalidation doit donc etre exhaustive, pas seulement rapide.
"""
import asyncio

import pytest

from cogs import setup_v2_core as core


class FakeDB:
    """Base minimale qui compte les lectures pour prouver l'effet du cache."""

    def __init__(self):
        self.rows: dict[tuple[int, str], int] = {}
        self.ai_rows: dict[int, int] = {}
        self.reads = 0

    async def fetchone(self, query, params=()):
        if "module_settings" in query:
            self.reads += 1
            guild_id, module = int(params[0]), str(params[1])
            if (guild_id, module) not in self.rows:
                return None
            return {"enabled": self.rows[(guild_id, module)]}
        if "ai_settings" in query:
            guild_id = int(params[0])
            if guild_id not in self.ai_rows:
                return None
            return {"enabled": self.ai_rows[guild_id]}
        return None

    async def fetchall(self, query, params=()):
        return []

    async def execute(self, query, params=()):
        if "INSERT INTO module_settings" in query:
            self.rows[(int(params[0]), str(params[1]))] = int(params[2])
        elif "DELETE FROM module_settings" in query:
            self.rows.pop((int(params[0]), str(params[1])), None)
        return None


class Bot:
    def __init__(self):
        self.db = FakeDB()


@pytest.fixture
def bot():
    instance = Bot()
    invalidate = getattr(core, "invalidate_module_cache", None)
    if invalidate:
        invalidate()
    yield instance
    if invalidate:
        invalidate()


MODULE = "logs"


def run(coro):
    return asyncio.run(coro)


def test_module_inconnu_reste_autorise(bot):
    assert run(core.module_enabled(bot, 1, "module-qui-n-existe-pas")) is True


def test_absence_de_ligne_signifie_actif(bot):
    assert run(core.module_enabled(bot, 1, MODULE)) is True


def test_valeur_enregistree_est_respectee(bot):
    bot.db.rows[(1, MODULE)] = 0
    assert run(core.module_enabled(bot, 1, MODULE)) is False
    bot.db.rows[(1, MODULE)] = 1
    invalidate = getattr(core, "invalidate_module_cache", None)
    if invalidate:
        invalidate(1, MODULE)
    assert run(core.module_enabled(bot, 1, MODULE)) is True


def test_une_ecriture_est_immediatement_visible(bot):
    """LE test critique : couper un module doit prendre effet tout de suite."""
    assert run(core.module_enabled(bot, 1, MODULE)) is True
    run(core.set_module_enabled(bot, 1, MODULE, False))
    assert run(core.module_enabled(bot, 1, MODULE)) is False, "valeur perimee apres coupure"
    run(core.set_module_enabled(bot, 1, MODULE, True))
    assert run(core.module_enabled(bot, 1, MODULE)) is True, "valeur perimee apres reactivation"


def test_les_serveurs_ne_se_melangent_pas(bot):
    run(core.set_module_enabled(bot, 1, MODULE, False))
    run(core.set_module_enabled(bot, 2, MODULE, True))
    assert run(core.module_enabled(bot, 1, MODULE)) is False
    assert run(core.module_enabled(bot, 2, MODULE)) is True


def test_les_modules_ne_se_melangent_pas(bot):
    run(core.set_module_enabled(bot, 1, "logs", False))
    run(core.set_module_enabled(bot, 1, "tickets", True))
    assert run(core.module_enabled(bot, 1, "logs")) is False
    assert run(core.module_enabled(bot, 1, "tickets")) is True


def test_le_repli_ai_settings_est_conserve(bot):
    """Sans ligne module_settings, le module ai suit l'ancien reglage ai_settings."""
    bot.db.ai_rows[1] = 0
    assert run(core.module_enabled(bot, 1, "ai")) is False
    bot.db.ai_rows[1] = 1
    invalidate = getattr(core, "invalidate_module_cache", None)
    if invalidate:
        invalidate(1, "ai")
    assert run(core.module_enabled(bot, 1, "ai")) is True


def test_la_reinitialisation_du_setup_est_visible(bot):
    """setup_v2_completion supprime la ligne en SQL direct : le cache doit suivre."""
    run(core.set_module_enabled(bot, 1, MODULE, False))
    assert run(core.module_enabled(bot, 1, MODULE)) is False

    await_delete = bot.db.execute(
        "DELETE FROM module_settings WHERE guild_id=? AND module=?", (1, MODULE)
    )
    run(await_delete)
    invalidate = getattr(core, "invalidate_module_cache", None)
    if invalidate:
        invalidate(1, MODULE)
    assert run(core.module_enabled(bot, 1, MODULE)) is True, "suppression non repercutee"
