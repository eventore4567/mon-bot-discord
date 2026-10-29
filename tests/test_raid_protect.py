"""Raid Protect (cogs/raid_protect.py) : rien ne s'active sans le choix du serveur,
et les réponses sont proportionnées (pause native, alerte, webhook seulement)."""
from __future__ import annotations

import asyncio
import datetime as dt
import os
import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import discord  # noqa: E402

from cogs import raid_protect as rp  # noqa: E402


class _Db:
    def __init__(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute(rp.TABLE)
        self.conn.execute("CREATE TABLE antinuke_whitelist (guild_id INTEGER, user_id INTEGER)")

    async def execute(self, sql, params=()):
        self.conn.execute(sql, params)
        self.conn.commit()

    async def fetchone(self, sql, params=()):
        return self.conn.execute(sql, params).fetchone()


def _guild(manage=True):
    g = MagicMock()
    g.id = 1
    g.owner_id = 99
    g.me.guild_permissions.manage_guild = manage
    g.invites_paused.return_value = False
    g.dms_paused.return_value = False
    g.edit = AsyncMock()
    return g


def _bot(db):
    return SimpleNamespace(db=db, user=SimpleNamespace(id=500), get_cog=lambda _n: None,
                           fetch_webhook=AsyncMock())


def test_tout_est_desactive_par_defaut():
    assert asyncio.run(rp.reglages(_Db(), 1)) == rp.DEFAUTS
    assert not any(rp.DEFAUTS[k] for k in ("auto_pause", "pause_dms", "webhook_guard"))


def test_un_raid_ne_met_rien_en_pause_sans_choix_du_serveur():
    g = _guild()
    assert asyncio.run(rp.sur_raid_detecte(_bot(_Db()), g)) is False
    g.edit.assert_not_awaited()


def test_pause_automatique_choisie_suspend_les_invitations_sans_sanction(monkeypatch):
    db = _Db()
    asyncio.run(rp.enregistrer(db, 1, auto_pause=1, pause_minutes=30))
    rp._derniere_pause.clear()
    monkeypatch.setattr(rp, "_journal", AsyncMock())
    g = _guild()
    assert asyncio.run(rp.sur_raid_detecte(_bot(db), g)) is True
    kwargs = g.edit.await_args.kwargs
    assert "invites_disabled_until" in kwargs and "dms_disabled_until" not in kwargs
    fin = kwargs["invites_disabled_until"]
    assert dt.timedelta(minutes=29) < fin - discord.utils.utcnow() <= dt.timedelta(minutes=30)
    # Même vague : pas de seconde pause.
    assert asyncio.run(rp.sur_raid_detecte(_bot(db), g)) is False


def test_pause_bornee_a_24_h_et_permission_verifiee():
    assert rp.borne_minutes(10_000) == 24 * 60 and rp.borne_minutes(1) == rp.PAUSE_MIN_MIN
    ok, fin, erreur = asyncio.run(rp.mettre_en_pause(_guild(manage=False), 60, raison="t"))
    assert not ok and "Gérer le serveur" in erreur


def test_noms_presque_identiques_alertent_une_fois():
    rp._arrivees_noms.clear()
    rp._alerte_noms.clear()
    assert rp.nom_de_base("Raider_0421") == rp.nom_de_base("r-a-i-d-e-r 77") == "raider"
    resultats = [rp.noter_arrivee(5, f"raider{i}", 100.0 + i) for i in range(6)]
    assert resultats[:3] == [None, None, None]
    assert resultats[3] == ("raider", 4)
    assert resultats[4] is None and resultats[5] is None
    # Des noms différents ne déclenchent rien.
    assert all(rp.noter_arrivee(6, n, 100.0) is None for n in ("alice", "bob", "carla", "denis", "emma"))


def _message(webhook_id=77, mid=1):
    me = MagicMock()
    channel = MagicMock()
    channel.id = 10
    channel.permissions_for.return_value.manage_messages = True
    channel.delete_messages = AsyncMock()
    guild = _guild()
    guild.me = me
    return SimpleNamespace(webhook_id=webhook_id, guild=guild, channel=channel, id=mid)


def test_garde_webhook_desactivee_par_defaut():
    assert asyncio.run(rp.surveiller_webhook(_bot(_Db()), _message())) is False


def test_webhook_qui_inonde_est_supprime_sauf_createur_de_confiance(monkeypatch):
    db = _Db()
    asyncio.run(rp.enregistrer(db, 1, webhook_guard=1, webhook_limit=5))
    monkeypatch.setattr(rp, "_journal", AsyncMock())
    bot = _bot(db)
    hook = MagicMock(type=discord.WebhookType.incoming, user=SimpleNamespace(id=42, mention="<@42>"))
    hook.delete = AsyncMock()
    bot.fetch_webhook.return_value = hook
    rp._rafales_webhook.clear()
    rp._webhooks_traites.clear()
    resultats = [asyncio.run(rp.surveiller_webhook(bot, _message(mid=i))) for i in range(7)]
    assert resultats[:5] == [False] * 5 and resultats[5] is True
    hook.delete.assert_awaited_once()

    # Créé par une personne de confiance : alerte seulement.
    asyncio.run(db.execute("INSERT INTO antinuke_whitelist VALUES (1, 42)"))
    hook.delete.reset_mock()
    rp._rafales_webhook.clear()
    rp._webhooks_traites.clear()
    for i in range(7):
        asyncio.run(rp.surveiller_webhook(bot, _message(mid=100 + i)))
    hook.delete.assert_not_awaited()
