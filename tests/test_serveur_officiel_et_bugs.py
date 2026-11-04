"""04/11/2026 : nouveau lien du serveur officiel, et chaque bug signalé part en MP au propriétaire."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import config  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def test_un_seul_lien_officiel_partout(monkeypatch):
    assert config.OFFICIAL_SERVER_URL == "https://discord.gg/TZwhdmJWf"
    for env in ("SENTRIX_SUPPORT_URL", "SUPPORT_SERVER_URL"):
        monkeypatch.delenv(env, raising=False)
    assert config.official_server_url() == config.OFFICIAL_SERVER_URL
    # Une variable restée sur l'ancienne invitation est ignorée.
    monkeypatch.setenv("SUPPORT_SERVER_URL", "https://discord.gg/5P5Bqjqu5t")
    assert config.official_server_url() == config.OFFICIAL_SERVER_URL
    from cogs import guild_arrival, official_server, release_announcer

    assert official_server.OFFICIAL_INVITE == config.OFFICIAL_SERVER_URL
    assert release_announcer.TARGET_INVITE == config.OFFICIAL_SERVER_URL
    assert guild_arrival.OFFICIAL_SUPPORT_URL == config.OFFICIAL_SERVER_URL
    for fichier in ROOT.joinpath("cogs").glob("*.py"):
        assert "5P5Bqjqu5t" not in fichier.read_text(encoding="utf-8"), fichier.name


def test_un_bug_signale_part_en_mp_aux_proprietaires(monkeypatch):
    from cogs import utility
    from database.db import PRIMARY_CREATOR_ID

    monkeypatch.setattr(config, "OWNER_IDS", [PRIMARY_CREATOR_ID, 555])
    assert utility._destinataires_bugs() == [PRIMARY_CREATOR_ID, 555]
    recus = {}

    def utilisateur(uid):
        return SimpleNamespace(send=AsyncMock(side_effect=lambda contenu, **k: recus.setdefault(uid, contenu)))

    bot = SimpleNamespace(get_user=utilisateur, fetch_user=AsyncMock())
    ctx = SimpleNamespace(
        guild=SimpleNamespace(name="Serveur test", id=1),
        channel=SimpleNamespace(name="général", id=2),
        message=SimpleNamespace(jump_url="https://discord.com/channels/1/2/3"),
        author=SimpleNamespace(id=42, __str__=lambda self: "tomioka"),
    )
    envoyes = asyncio.run(utility._envoyer_bug_aux_proprietaires(bot, ctx, "le lecteur plante @everyone"))
    assert envoyes == 2
    message = recus[PRIMARY_CREATOR_ID]
    assert "Nouveau bug signalé" in message and "le lecteur plante" in message
    assert "@everyone" not in message  # mention neutralisée
    assert "Serveur test" in message and "https://discord.com/channels/1/2/3" in message
