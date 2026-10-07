"""Service Suggestions, testé sur une vraie base SQLite en mémoire — sans bot.

Couvre le point 84 du brief SentriX : soumission, temps de recharge, vote,
décision du staff, suggestion supprimée, persistance (tout vit en base, rien en
mémoire du processus).
"""
from __future__ import annotations

import asyncio

import aiosqlite
import pytest

from services import suggestions as svc

GUILD = 111
OTHER_GUILD = 222


class Db:
    """Même interface que `bot.db` : execute (avec commit), fetchone, fetchall."""

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self.conn = conn

    async def execute(self, query, params=()):
        cur = await self.conn.execute(query, params)
        await self.conn.commit()
        return cur

    async def fetchone(self, query, params=()):
        cur = await self.conn.execute(query, params)
        row = await cur.fetchone()
        await cur.close()
        return row

    async def fetchall(self, query, params=()):
        cur = await self.conn.execute(query, params)
        rows = await cur.fetchall()
        await cur.close()
        return rows


def run(coro):
    return asyncio.run(coro)


async def _db(legacy: bool = False) -> Db:
    conn = await aiosqlite.connect(":memory:")
    db = Db(conn)
    if legacy:
        # Schéma et données de l'ancienne version : statut français, pas de numéro.
        await db.execute(
            "CREATE TABLE suggestions (id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER, "
            "user_id INTEGER, message_id INTEGER, content TEXT, status TEXT DEFAULT 'en_attente', "
            "created_at INTEGER)"
        )
        await db.execute("CREATE TABLE guild_config (guild_id INTEGER PRIMARY KEY, suggest_channel INTEGER)")
        await db.execute("INSERT INTO guild_config VALUES (?, ?)", (GUILD, 999))
        for user, ts in ((1, 10), (2, 20)):
            await db.execute(
                "INSERT INTO suggestions (guild_id, user_id, message_id, content, created_at) "
                "VALUES (?, ?, ?, ?, ?)", (GUILD, user, 500 + user, f"ancienne {user}", ts),
            )
    await svc.ensure_schema(db)
    return db


async def _configured(db: Db, cooldown: int = 0) -> svc.Settings:
    return await svc.save_settings(db, GUILD, actor_id=1, now=0, channel_id=42, cooldown_seconds=cooldown)


def test_sans_salon_le_module_refuse_proprement():
    async def scenario():
        db = await _db()
        settings = await svc.get_settings(db, GUILD)
        assert settings.configured is False
        with pytest.raises(svc.SuggestionError) as err:
            await svc.create(db, settings, author_id=1, title="t", content="c", now=100)
        assert err.value.code == "not_configured"
    run(scenario())


def test_numerotation_par_serveur_et_sans_trou():
    async def scenario():
        db = await _db()
        settings = await _configured(db)
        autre = await svc.save_settings(db, OTHER_GUILD, actor_id=1, now=0, channel_id=7, cooldown_seconds=0)
        a = await svc.create(db, settings, author_id=1, title="A", content="a", now=1)
        b = await svc.create(db, settings, author_id=2, title="B", content="b", now=2)
        c = await svc.create(db, autre, author_id=3, title="C", content="c", now=3)
        assert (a.number, b.number, c.number) == (1, 2, 1)
    run(scenario())


def test_temps_de_recharge_calcule_depuis_la_base():
    async def scenario():
        db = await _db()
        settings = await _configured(db, cooldown=300)
        await svc.create(db, settings, author_id=1, title="t", content="c", now=1000)
        with pytest.raises(svc.SuggestionError) as err:
            await svc.create(db, settings, author_id=1, title="t2", content="c2", now=1100)
        assert err.value.code == "cooldown" and err.value.details["seconds"] == 200
        # Un autre membre n'est pas concerné, et le même repasse après le délai.
        await svc.create(db, settings, author_id=2, title="x", content="y", now=1100)
        await svc.create(db, settings, author_id=1, title="t3", content="c3", now=1300)
    run(scenario())


def test_vote_bascule_et_retrait_sans_double_comptage():
    async def scenario():
        db = await _db()
        settings = await _configured(db)
        s = await svc.create(db, settings, author_id=1, title="t", content="c", now=1)
        assert await svc.vote(db, s, 10, 1, now=2) == 1
        assert await svc.vote(db, s, 11, 1, now=2) == 1
        assert await svc.counts(db, s.id) == (2, 0)
        # Deux clics identiques : le second retire le vote, il ne le double pas.
        assert await svc.vote(db, s, 10, 1, now=3) == 0
        assert await svc.counts(db, s.id) == (1, 0)
        # Cliquer sur l'autre bouton bascule le vote.
        assert await svc.vote(db, s, 11, -1, now=4) == -1
        assert await svc.counts(db, s.id) == (0, 1)
    run(scenario())


def test_dix_clics_simultanes_du_meme_membre_ne_creent_qu_un_vote_au_plus():
    async def scenario():
        db = await _db()
        settings = await _configured(db)
        s = await svc.create(db, settings, author_id=1, title="t", content="c", now=1)
        await asyncio.gather(*(svc.vote(db, s, 10, 1, now=2) for _ in range(10)))
        up, down = await svc.counts(db, s.id)
        assert up in (0, 1) and down == 0
    run(scenario())


def test_on_ne_vote_plus_sur_une_suggestion_tranchee():
    async def scenario():
        db = await _db()
        settings = await _configured(db)
        s = await svc.create(db, settings, author_id=1, title="t", content="c", now=1)
        s = await svc.set_status(db, s, status="accepted", staff_id=9, response="Bientôt.", now=5)
        assert (s.status, s.staff_id, s.staff_response) == ("accepted", 9, "Bientôt.")
        with pytest.raises(svc.SuggestionError) as err:
            await svc.vote(db, s, 10, 1, now=6)
        assert err.value.code == "closed"
    run(scenario())


def test_statut_inconnu_refuse():
    async def scenario():
        db = await _db()
        settings = await _configured(db)
        s = await svc.create(db, settings, author_id=1, title="t", content="c", now=1)
        with pytest.raises(svc.SuggestionError):
            await svc.set_status(db, s, status="maybe", staff_id=9, response=None, now=2)
    run(scenario())


def test_suggestion_dont_le_message_a_echoue_est_annulee():
    async def scenario():
        db = await _db()
        settings = await _configured(db)
        s = await svc.create(db, settings, author_id=1, title="t", content="c", now=1)
        await svc.vote(db, s, 10, 1, now=2)
        await svc.discard(db, s.id)
        assert await svc.get(db, s.id) is None
        assert await svc.counts(db, s.id) == (0, 0)
    run(scenario())


def test_retrouvee_par_message_et_par_numero():
    async def scenario():
        db = await _db()
        settings = await _configured(db)
        s = await svc.create(db, settings, author_id=1, title="t", content="c", now=1)
        await svc.attach_message(db, s.id, channel_id=42, message_id=777)
        assert (await svc.by_message(db, 777)).id == s.id
        assert (await svc.by_number(db, GUILD, s.number)).id == s.id
        assert await svc.by_message(db, 778) is None
    run(scenario())


def test_migration_conserve_les_anciennes_suggestions():
    async def scenario():
        db = await _db(legacy=True)
        anciennes = await db.fetchall("SELECT number, status, content FROM suggestions ORDER BY id")
        assert [tuple(r) for r in anciennes] == [(1, "pending", "ancienne 1"), (2, "pending", "ancienne 2")]
        # L'ancien salon configuré devient la configuration du module.
        assert (await svc.get_settings(db, GUILD)).channel_id == 999
        # La migration est rejouable sans rien dupliquer.
        await svc.ensure_schema(db)
        assert len(await db.fetchall("SELECT id FROM suggestions")) == 2
        # Et la numérotation continue après les anciennes.
        s = await svc.create(db, await svc.get_settings(db, GUILD), author_id=3, title="t", content="c", now=99_999)
        assert s.number == 3
    run(scenario())


def test_reglage_partiel_ne_perd_pas_les_autres_champs():
    async def scenario():
        db = await _db()
        await svc.save_settings(db, GUILD, actor_id=1, now=0, channel_id=42, cooldown_seconds=60, anonymous=True)
        apres = await svc.save_settings(db, GUILD, actor_id=1, now=1, cooldown_seconds=120)
        assert (apres.channel_id, apres.cooldown_seconds, apres.anonymous) == (42, 120, True)
        with pytest.raises(svc.SuggestionError):
            await svc.save_settings(db, GUILD, actor_id=1, now=2, cooldown_seconds=-5)
    run(scenario())


def test_les_textes_francais_et_anglais_ont_les_memes_cles():
    """Une clé manquante dans une langue ferait planter l'affichage de la carte
    sur les serveurs de cette langue — on le voit ici, pas en production."""
    from cogs.suggestions import TEXTS

    def cles(d, prefixe=""):
        out = set()
        for k, v in d.items():
            out.add(prefixe + k)
            if isinstance(v, dict):
                out |= cles(v, prefixe + k + ".")
        return out

    assert cles(TEXTS["fr"]) == cles(TEXTS["en"])
    assert set(TEXTS["fr"]["status"]) == set(svc.STATUSES)
