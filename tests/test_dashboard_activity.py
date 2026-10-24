"""Activité réelle de la vue d'ensemble : tranches de 24 h et fil d'événements."""
from __future__ import annotations

import asyncio
import os
import tempfile
import time
from types import SimpleNamespace

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from database.db import Database  # noqa: E402
from web import dashboard_activity as activity  # noqa: E402

GID = 42


def _guild():
    membres = {7: SimpleNamespace(display_name="Alice", display_avatar=None), 9: SimpleNamespace(display_name="Mod", display_avatar=None)}
    return SimpleNamespace(id=GID, get_member=lambda uid: membres.get(uid))


async def _base():
    db = Database(os.path.join(tempfile.mkdtemp(), "activite.db"))
    await db.connect()
    return db


def test_les_series_comptent_par_tranche_de_24h():
    async def run():
        db = await _base()
        now = int(time.time())
        for age in (60, 3600, 86400 + 60, 5 * 86400):
            await db.execute("INSERT INTO command_logs (guild_id, user_id, command_name, timestamp) VALUES (?,?,?,?)", (GID, 7, "ping", now - age))
        await db.execute("INSERT INTO command_logs (guild_id, user_id, command_name, timestamp) VALUES (?,?,?,?)", (999, 7, "ping", now))
        await db.execute("INSERT INTO command_logs (guild_id, user_id, command_name, timestamp) VALUES (?,?,?,?)", (GID, 7, "ping", now - 30 * 86400))
        data = await activity.activity_payload(SimpleNamespace(db=db), _guild())
        commandes = data["series"]["commands"]
        assert len(commandes) == activity.DAYS
        assert commandes[-1] == 2, "dernières 24 h"
        assert commandes[-2] == 1
        assert commandes[-6] == 1
        assert sum(commandes) == 4, "un autre serveur ou un événement trop ancien ne compte pas"
    asyncio.run(run())


def test_le_fil_melange_les_sources_du_plus_recent_au_plus_ancien():
    async def run():
        db = await _base()
        now = int(time.time())
        await db.execute("INSERT INTO sanctions (guild_id, case_number, user_id, moderator_id, action, reason, created_at) VALUES (?,?,?,?,?,?,?)", (GID, 1, 7, 9, "warn", "spam", now - 100))
        await db.execute("INSERT INTO automod_logs (guild_id, user_id, filter_name, action, reason, timestamp) VALUES (?,?,?,?,?,?)", (GID, 7, "antilink", "delete", "Lien non autorisé.", now - 10))
        await db.execute("INSERT INTO member_invites (guild_id, member_id, inviter_id, joined_at) VALUES (?,?,?,?)", (GID, 7, 9, now - 50))
        feed = (await activity.activity_payload(SimpleNamespace(db=db), _guild()))["feed"]
        assert [e["kind"] for e in feed] == ["automod", "arrival", "sanction"]
        assert feed[2]["title"] == "Avertissement" and feed[2]["member"]["name"] == "Alice"
        assert feed[2]["actor"]["name"] == "Mod"
        assert feed[1]["actor"]["name"] == "Mod", "l'invitant est nommé"
    asyncio.run(run())


def test_la_route_est_branchee_sur_l_application_du_dashboard():
    from pathlib import Path

    source = Path(__file__).resolve().parents[1].joinpath("main.py").read_text(encoding="utf-8")
    assert "register_activity_routes(app, dashboard_module)" in source
