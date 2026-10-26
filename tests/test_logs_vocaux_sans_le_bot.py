"""SentriX ne journalise pas ses propres reconnexions vocales.

Prod 25-26/10 : la musique persistante se reconnectait (coupures 1006 côté
Discord) et chaque reconnexion postait une carte « Déconnexion » puis
« Connexion » au nom de SentriX dans les logs du serveur, toutes les ~10 min.
"""
import asyncio
import os
from types import SimpleNamespace

os.environ.setdefault("DISCORD_TOKEN", "x")

from cogs import voice_logs_v2  # noqa: E402

BOT_ID, MEMBRE_ID = 900, 42


def _installer():
    envois = []

    class _Logs:
        def _embed(self, title, fields=()):
            return SimpleNamespace(title=title, fields=fields)

        async def _send(self, guild, event_type, panel, **_k):
            envois.append(event_type)

    bot = SimpleNamespace(
        user=SimpleNamespace(id=BOT_ID), extra_events={}, guilds=[],
        get_cog=lambda name: _Logs() if name == "Logs" else None,
    )
    ecouteurs = {}
    bot.add_listener = lambda fn, name: ecouteurs.__setitem__(name, fn)
    bot.remove_listener = lambda *_a, **_k: None
    assert voice_logs_v2.install(bot)
    return ecouteurs["on_voice_state_update"], envois


def _vocal(channel):
    return SimpleNamespace(channel=channel)


def _membre(uid):
    return SimpleNamespace(id=uid, mention=f"<@{uid}>", guild=SimpleNamespace(id=1))


def test_la_reconnexion_de_sentrix_n_est_pas_journalisee():
    ecouteur, envois = _installer()
    salon = SimpleNamespace(id=5, mention="<#5>")
    asyncio.run(ecouteur(_membre(BOT_ID), _vocal(salon), _vocal(None)))
    asyncio.run(ecouteur(_membre(BOT_ID), _vocal(None), _vocal(salon)))
    assert envois == []


def test_un_membre_reste_journalise():
    ecouteur, envois = _installer()
    salon = SimpleNamespace(id=5, mention="<#5>")
    asyncio.run(ecouteur(_membre(MEMBRE_ID), _vocal(None), _vocal(salon)))
    assert envois == ["voice_join"]
