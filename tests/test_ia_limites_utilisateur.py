"""08/11/2026 : « mets une limite à l'IA par utilisateur » — images par jour et limite
globale tous serveurs, en plus de la limite par serveur."""
from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from utils import ai_service as ia  # noqa: E402


class _Base:
    """ai_usage en mémoire : (guild, user, day) -> requests."""

    def __init__(self):
        self.lignes = {}

    async def fetchone(self, sql, params):
        if "SUM(requests)" in sql:
            user, jour = params
            return {"total": sum(n for (g, u, d), n in self.lignes.items() if u == user and d == jour)}
        g, u, d = params
        n = self.lignes.get((g, u, d))
        return None if n is None else {"requests": n}

    async def execute(self, sql, params):
        g, u, d = params[:3]
        self.lignes[(g, u, d)] = self.lignes.get((g, u, d), 0) + 1


def _bot():
    return SimpleNamespace(db=_Base())


def test_limite_par_serveur():
    bot = _bot()
    reglages = {"daily_limit": 2}
    for _ in range(2):
        asyncio.run(ia.record_usage(bot, 1, 7))
    message = asyncio.run(ia.limite_atteinte(bot, 1, 7, reglages))
    assert message and "2 demandes par jour" in message and "<t:" in message
    assert asyncio.run(ia.limite_atteinte(bot, 2, 7, reglages)) is None   # autre serveur : libre


def test_limite_d_images(monkeypatch):
    monkeypatch.setattr(ia, "IMAGES_PAR_JOUR", 2)
    bot = _bot()
    for _ in range(2):
        asyncio.run(ia.record_image_usage(bot, 1, 7))
    assert "limite d'images" in asyncio.run(ia.limite_atteinte(bot, 1, 7, {"daily_limit": 50}, image=True))
    assert asyncio.run(ia.limite_atteinte(bot, 1, 7, {"daily_limit": 50})) is None   # le texte reste permis


def test_limite_globale_tous_serveurs(monkeypatch):
    monkeypatch.setattr(ia, "LIMITE_GLOBALE_PAR_JOUR", 3)
    bot = _bot()
    for serveur in (1, 2, 3):
        asyncio.run(ia.record_usage(bot, serveur, 7))
    message = asyncio.run(ia.limite_atteinte(bot, 4, 7, {"daily_limit": 50}))
    assert message and "tous serveurs" in message


def test_les_chemins_d_images_comptent_et_verifient():
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "cogs" / "ai.py").read_text(encoding="utf-8")
    assert source.count("ai_service.limite_atteinte(") == 2
    assert source.count("ai_service.record_image_usage(") == 2
    assert "ai_service.get_global_usage(self.bot, user_id)" in source
