"""Cache de lecture de log_config, et surtout : la relecture de confirmation.

set_log_config relit la base APRES ecriture et leve si elle ne contient pas ce qui
vient d'etre demande. C'est ce controle qui empeche le panneau +setup d'afficher
« ACTIF » pour une route qui n'a jamais ete ecrite.

Un cache de lecture pose ici un piege : si la relecture tapait le cache, elle
confirmerait une ecriture qui n'a pas eu lieu. Le test central de ce fichier verifie
exactement ce cas.
"""
import asyncio

import pytest

from utils import log_service


class FakeDB:
    """Base minimale. `accept_writes=False` simule une ecriture qui n'aboutit pas."""

    def __init__(self, accept_writes: bool = True):
        self.rows: dict[tuple[int, str], dict] = {}
        self.accept_writes = accept_writes
        self.reads = 0

    async def execute(self, query, params=()):
        if "INSERT INTO log_config" in query and self.accept_writes:
            guild_id, category, channel_id, enabled, updated = params
            self.rows[(int(guild_id), str(category))] = {
                "guild_id": int(guild_id), "category": str(category),
                "channel_id": channel_id, "enabled": enabled, "updated_at": updated,
            }
        return None

    async def fetchone(self, query, params=()):
        if "FROM log_config" in query:
            self.reads += 1
            return self.rows.get((int(params[0]), str(params[1])))
        return None

    async def fetchall(self, query, params=()):
        return []


class Bot:
    def __init__(self, accept_writes: bool = True):
        self.db = FakeDB(accept_writes)


@pytest.fixture(autouse=True)
def _clean():
    log_service.invalidate_log_config()
    log_service._SCHEMA_READY.clear()
    yield
    log_service.invalidate_log_config()
    log_service._SCHEMA_READY.clear()


def run(coro):
    return asyncio.run(coro)


CHAN = 1355855757991481480


def test_une_route_ecrite_est_relue_correctement():
    bot = Bot()
    saved = run(log_service.set_log_config(bot, 1, "messages", channel_id=CHAN, enabled=True))
    assert saved["channel_id"] == CHAN
    assert run(log_service.get_log_config(bot, 1, "messages"))["channel_id"] == CHAN


def test_la_relecture_de_confirmation_ne_passe_jamais_par_le_cache():
    """LE test critique.

    On chauffe le cache avec une route valide, puis on rend les ecritures inoperantes.
    Si la relecture tapait le cache, set_log_config confirmerait une ecriture fantome.
    """
    bot = Bot()
    run(log_service.set_log_config(bot, 1, "messages", channel_id=CHAN, enabled=True))
    run(log_service.get_log_config(bot, 1, "messages"))  # cache chaud

    bot.db.accept_writes = False
    with pytest.raises(RuntimeError, match="log_config_write_failed"):
        run(log_service.set_log_config(bot, 1, "messages", channel_id=999, enabled=True))


def test_lectures_repetees_ne_frappent_pas_la_base():
    """Apres une ecriture, la relecture de confirmation a deja rempli le cache."""
    bot = Bot()
    run(log_service.set_log_config(bot, 1, "messages", channel_id=CHAN, enabled=True))
    bot.db.reads = 0
    for _ in range(5):
        run(log_service.get_log_config(bot, 1, "messages"))
    assert bot.db.reads == 0, f"{bot.db.reads} lecture(s) alors que le cache est chaud"


def test_depart_a_froid_lit_la_base_une_seule_fois():
    bot = Bot()
    bot.db.rows[(1, "messages")] = {
        "guild_id": 1, "category": "messages",
        "channel_id": CHAN, "enabled": 1, "updated_at": 0,
    }
    log_service.invalidate_log_config()
    bot.db.reads = 0
    for _ in range(5):
        assert run(log_service.get_log_config(bot, 1, "messages"))["channel_id"] == CHAN
    assert bot.db.reads == 1, f"{bot.db.reads} lectures au lieu d'une"


def test_une_ecriture_est_immediatement_visible():
    bot = Bot()
    run(log_service.set_log_config(bot, 1, "messages", channel_id=CHAN, enabled=True))
    run(log_service.get_log_config(bot, 1, "messages"))
    run(log_service.set_log_config(bot, 1, "messages", channel_id=None, enabled=False))
    apres = run(log_service.get_log_config(bot, 1, "messages"))
    assert apres["channel_id"] is None
    assert apres["enabled"] is False


def test_les_serveurs_et_categories_ne_se_melangent_pas():
    bot = Bot()
    run(log_service.set_log_config(bot, 1, "messages", channel_id=111111111111111111, enabled=True))
    run(log_service.set_log_config(bot, 2, "messages", channel_id=222222222222222222, enabled=True))
    run(log_service.set_log_config(bot, 1, "moderation", channel_id=333333333333333333, enabled=True))
    assert run(log_service.get_log_config(bot, 1, "messages"))["channel_id"] == 111111111111111111
    assert run(log_service.get_log_config(bot, 2, "messages"))["channel_id"] == 222222222222222222
    assert run(log_service.get_log_config(bot, 1, "moderation"))["channel_id"] == 333333333333333333


def test_fresh_force_une_vraie_lecture():
    bot = Bot()
    run(log_service.set_log_config(bot, 1, "messages", channel_id=CHAN, enabled=True))
    run(log_service.get_log_config(bot, 1, "messages"))
    bot.db.reads = 0
    run(log_service.get_log_config(bot, 1, "messages", fresh=True))
    assert bot.db.reads == 1
