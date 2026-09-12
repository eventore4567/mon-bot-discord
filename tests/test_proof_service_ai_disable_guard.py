"""utils/proof_service.py — la vérification de preuves appelait OpenAI directement
(client.responses.create()), contournant le garde-fou IA activée/désactivée par
serveur (cogs/ai_disable_guard.py). Corrigé pour passer par ai_service.generate(),
le seul point d'entrée que le garde protège.

Ces tests installent le VRAI garde (cogs.ai_disable_guard._install_service_guard,
pas une reconstitution) sur une capture fraîche de ai_service.generate, pour
prouver — pas supposer — qu'aucun appel OpenAI n'a lieu quand l'IA est désactivée,
et que la vérification fonctionne toujours normalement quand elle est activée."""
from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from cogs import ai_disable_guard
from utils import ai_service, proof_service


def _fake_bot(*, ai_enabled: bool):
    # ai_service.get_settings() lit ces colonnes par indexation (comme un vrai sqlite3.Row),
    # donc la ligne factice doit toutes les fournir, pas seulement "enabled".
    row = {
        "enabled": 1 if ai_enabled else 0,
        "default_model": None,
        "reasoning_effort": None,
        "allowed_channel_ids": None,
        "allowed_role_ids": None,
        "cooldown_seconds": None,
        "per_minute_limit": None,
        "daily_limit": None,
        "max_question_length": None,
        "memory_enabled": 0,
        "memory_minutes": None,
        "response_style": None,
        "language": None,
        "logs_enabled": 0,
    }
    return SimpleNamespace(db=SimpleNamespace(fetchone=AsyncMock(return_value=row)))


def _fake_openai_response(payload: str):
    return SimpleNamespace(output_text=payload, id="resp_test", usage=None)


class ProofServiceRespectsAiDisableGuardTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._original_generate = ai_service.generate

    def tearDown(self):
        ai_service.generate = self._original_generate

    async def test_aucun_appel_openai_quand_l_ia_est_desactivee(self):
        bot = _fake_bot(ai_enabled=False)
        ai_disable_guard._install_service_guard(bot)

        client = MagicMock()
        client.responses.create = AsyncMock(
            side_effect=AssertionError("OpenAI ne doit jamais être appelé : IA désactivée")
        )
        with patch.object(ai_service, "get_client", return_value=client):
            # analyze_candidate() dégrade gracieusement (comportement existant, inchangé) :
            # une erreur devient CandidateAnalysis(ok=False), jamais une exception propagée.
            analysis = await proof_service.analyze_candidate(
                b"donnees-image-factices",
                instructions="Vérifie la capture.",
                references=[],
                guild_id=999,
            )

        self.assertFalse(analysis.ok)
        self.assertEqual(analysis.error, "RuntimeError")
        client.responses.create.assert_not_awaited()

    async def test_aucun_appel_openai_pour_analyze_reference_quand_desactivee(self):
        bot = _fake_bot(ai_enabled=False)
        ai_disable_guard._install_service_guard(bot)

        client = MagicMock()
        client.responses.create = AsyncMock(
            side_effect=AssertionError("OpenAI ne doit jamais être appelé : IA désactivée")
        )
        with patch.object(ai_service, "get_client", return_value=client):
            with self.assertRaises(RuntimeError):
                await proof_service.analyze_reference(
                    b"donnees-image-factices",
                    label="preuve",
                    instructions="",
                    guild_id=999,
                )

        client.responses.create.assert_not_awaited()

    async def test_fonctionne_normalement_quand_l_ia_est_activee(self):
        bot = _fake_bot(ai_enabled=True)
        ai_disable_guard._install_service_guard(bot)

        payload = (
            '{"score": 87, "best_reference": 0, "proof_type": "capture", '
            '"matched": ["bouton"], "missing": [], "tampering_risk": 0, '
            '"device_variant": "pc", "reason": "ok"}'
        )
        client = MagicMock()
        client.responses.create = AsyncMock(return_value=_fake_openai_response(payload))
        with patch.object(ai_service, "get_client", return_value=client):
            analysis = await proof_service.analyze_candidate(
                b"donnees-image-factices",
                instructions="Vérifie la capture.",
                references=[],
                guild_id=999,
            )

        client.responses.create.assert_awaited_once()
        self.assertEqual(analysis.score, 87)

    async def test_sans_guild_id_le_garde_laisse_passer(self):
        """guild_id=None (pas de contexte serveur) : le garde ne bloque jamais —
        comportement de _ai_enabled() déjà établi (if not guild_id: return True),
        conservé à l'identique."""
        bot = _fake_bot(ai_enabled=False)
        ai_disable_guard._install_service_guard(bot)

        payload = '{"summary": "ok", "proof_type": "x", "required_text": [], "visual_anchors": [], "confirmation_signals": [], "anti_signals": []}'
        client = MagicMock()
        client.responses.create = AsyncMock(return_value=_fake_openai_response(payload))
        with patch.object(ai_service, "get_client", return_value=client):
            result = await proof_service.analyze_reference(
                b"donnees-image-factices", label="preuve", instructions="", guild_id=None,
            )

        client.responses.create.assert_awaited_once()
        self.assertEqual(result["summary"], "ok")


if __name__ == "__main__":
    unittest.main()
