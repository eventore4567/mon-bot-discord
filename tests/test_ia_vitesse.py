"""09/11/2026 : « rends l'IA plus rapide » — mesures de production : Terra avec
raisonnement 10 à 20 s, relance de réponse vide sur Terra ≈ 15 s de plus."""
from __future__ import annotations

import asyncio
import os
from unittest.mock import AsyncMock

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from utils import ai_service as ia  # noqa: E402


def test_terra_sans_raisonnement_sol_garde_le_sien():
    for effort in ("none", "low", "medium"):
        assert ia.pick_reasoning_effort(ia.MODEL_TERRA, effort) == "none"
    assert ia.pick_reasoning_effort(ia.MODEL_TERRA, "high") == "high"      # choix explicite du serveur
    assert ia.pick_reasoning_effort(ia.MODEL_LUNA, "medium") == "none"
    assert ia.pick_reasoning_effort(ia.MODEL_SOL, "low") == "high"


def test_une_reponse_vide_est_relancee_sur_le_modele_rapide(monkeypatch):
    from cogs import community_v33

    appels = []

    async def generate(prompt, **kwargs):
        appels.append(kwargs)
        if len(appels) == 1:
            return ia.AiResult(text="", model_key=kwargs.get("model_key"))
        return ia.AiResult(text="réponse", model_key=kwargs.get("model_key"))

    monkeypatch.setattr(ia, "generate", generate)
    community_v33._install_ai_empty_retry()
    resultat = asyncio.run(ia.generate("salut", model_key=ia.MODEL_TERRA, command="ai-reply"))
    assert resultat.text == "réponse"
    assert appels[1]["model_key"] == ia.MODEL_LUNA and appels[1]["reasoning_effort"] == "none"
    assert appels[1]["command"] == "ai-reply-empty-retry"
