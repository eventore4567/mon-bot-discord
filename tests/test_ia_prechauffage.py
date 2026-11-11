"""11/11/2026 : la première question à l'IA gelait SentriX pour tout le monde.

Le détecteur de blocage de boucle l'a dit lui-même, plusieurs fois en production :

    Boucle bloquée 1.2 s — utils/ai_service.py:548 get_client ← generate ← ...
    Boucle bloquée 1.1 s — utils/ai_service.py:557 get_client ← translation._openai

L'appel à OpenAI, lui, est asynchrone. Ce qui bloquait, c'est le CHARGEMENT du
SDK au premier usage : des centaines de modules et un contexte TLS, construits
sur la boucle d'événements. Une seconde entière sans commande, sans AutoMod,
sans battement — et ce coût tombait sur la première personne qui posait une
question, donc au pire moment.
"""
from __future__ import annotations

import asyncio
import os
import threading
import time

import pytest

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from utils import ai_service  # noqa: E402


@pytest.mark.asyncio
async def test_sans_cle_aucun_prechauffage(monkeypatch):
    """Pas de clé, pas de client à construire : rien à préchauffer, et aucun échec."""
    monkeypatch.setattr(ai_service.config, "OPENAI_API_KEY", "")
    assert await ai_service.prechauffer_le_client() is False


@pytest.mark.asyncio
async def test_le_chargement_lourd_ne_bloque_pas_la_boucle(monkeypatch):
    """Le test qui compte : la boucle doit continuer de tourner pendant le chargement."""
    monkeypatch.setattr(ai_service.config, "OPENAI_API_KEY", "cle-de-test")

    def _client_lent():
        time.sleep(0.4)  # ce que coûte le premier import du SDK
        return object()

    monkeypatch.setattr(ai_service, "get_client", _client_lent)

    battements = 0

    async def battre():
        nonlocal battements
        while True:
            battements += 1
            await asyncio.sleep(0.02)

    coeur = asyncio.create_task(battre())
    try:
        assert await ai_service.prechauffer_le_client() is True
    finally:
        coeur.cancel()

    # Si le chargement s'était fait sur la boucle, elle n'aurait battu qu'une fois.
    assert battements > 5, f"la boucle n'a battu que {battements} fois : elle était gelée"


@pytest.mark.asyncio
async def test_le_prechauffage_se_fait_bien_sur_un_autre_fil(monkeypatch):
    monkeypatch.setattr(ai_service.config, "OPENAI_API_KEY", "cle-de-test")
    fil_principal = threading.main_thread().ident
    vu = {}

    def _client():
        vu["fil"] = threading.current_thread().ident
        return object()

    monkeypatch.setattr(ai_service, "get_client", _client)
    await ai_service.prechauffer_le_client()
    assert vu["fil"] != fil_principal


@pytest.mark.asyncio
async def test_un_prechauffage_rate_n_empeche_pas_de_repondre(monkeypatch):
    """L'IA doit rester utilisable même si le préchauffage échoue."""
    monkeypatch.setattr(ai_service.config, "OPENAI_API_KEY", "cle-de-test")

    def _casse():
        raise RuntimeError("SDK indisponible")

    monkeypatch.setattr(ai_service, "get_client", _casse)
    assert await ai_service.prechauffer_le_client() is False


@pytest.mark.asyncio
async def test_sans_client_le_prechauffage_le_dit(monkeypatch):
    monkeypatch.setattr(ai_service.config, "OPENAI_API_KEY", "cle-de-test")
    monkeypatch.setattr(ai_service, "get_client", lambda: None)
    assert await ai_service.prechauffer_le_client() is False


def test_le_cog_ia_prechauffe_sans_ajouter_d_ecouteur():
    """Le budget d'écouteurs est tenu : on se greffe sur une boucle qui existait."""
    import inspect

    from cogs.ai import Ai

    source = inspect.getsource(Ai._before_cleanup)
    assert "prechauffer_le_client" in source
    assert "add_listener" not in source and "Cog.listener" not in source
