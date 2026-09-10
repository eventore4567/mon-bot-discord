"""Couverture du comportement ACTUEL de la pile de correctifs autour de
ai_service.generate()/generate_image() (Core V2, Phase 4 — audit, pas de
refonte). Un audit dédié a tracé la chaîne réelle sur un boot complet des 51
extensions et trouvé 11 couches pour generate() (pas 6-7 comme une recherche
précédente l'estimait) — voir docs/core-v2-audit-ai-patch-stack.md pour le
détail complet. Ces tests verrouillent deux garanties qui doivent survivre
telles quelles à n'importe quelle future consolidation :

1. Le garde-fou IA activée/désactivée bloque avant OpenAI, même appliqué
   plusieurs fois (en production, cogs/stability_runtime.py le réinstalle
   après CHAQUE extension chargée — confirmé : il apparaît 4 fois dans la
   chaîne réelle, jamais une seule comme son propre docstring "autorité
   unique" le prétend).
2. /image (cogs/v17_extras.py::image_v17, la vraie implémentation vivante —
   PAS cogs/ai.py::generate_image_command, remplacée à l'installation)
   applique bien un quota quotidien PAR RÔLE avant tout appel à
   ai_service.generate_image() — ce comportement doit être préservé tel
   quel avant toute migration future de cette commande.
"""
from __future__ import annotations

import contextlib
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

from cogs import ai_disable_guard, v17_extras
from utils import ai_service


@contextlib.asynccontextmanager
async def _async_nullcontext():
    yield


def _fake_ai_settings_row(*, enabled: bool):
    return {
        "enabled": 1 if enabled else 0,
        "default_model": None, "reasoning_effort": None,
        "allowed_channel_ids": None, "allowed_role_ids": None,
        "cooldown_seconds": None, "per_minute_limit": None, "daily_limit": None,
        "max_question_length": None, "memory_enabled": 0, "memory_minutes": None,
        "response_style": None, "language": None, "logs_enabled": 0,
    }


class DisableGuardSurvivesReapplicationTests(unittest.IsolatedAsyncioTestCase):
    """cogs/stability_runtime.py réinstalle le garde après chaque extension —
    ce test simule ce motif réel (réapplication par-dessus une couche
    intercalée) sans booter les 51 extensions."""

    def setUp(self):
        self._original_generate = ai_service.generate

    def tearDown(self):
        ai_service.generate = self._original_generate

    async def test_bloque_openai_meme_reapplique_par_dessus_une_autre_couche(self):
        bot = SimpleNamespace(db=SimpleNamespace(
            fetchone=AsyncMock(return_value=_fake_ai_settings_row(enabled=False))
        ))
        ai_disable_guard._install_service_guard(bot)  # 1ère application

        # Simule une couche non liée s'installant PAR-DESSUS (comme ai_context_v9
        # le ferait réellement) entre deux réinstallations du garde.
        inner = ai_service.generate

        async def unrelated_layer(*args, **kwargs):
            return await inner(*args, **kwargs)

        ai_service.generate = unrelated_layer
        ai_disable_guard._install_service_guard(bot)  # 2e application, ré-enveloppe par-dessus

        client = MagicMock()
        client.responses.create = AsyncMock(side_effect=AssertionError("OpenAI ne doit jamais être appelé"))
        with patch.object(ai_service, "get_client", return_value=client):
            result = await ai_service.generate("bonjour", guild_id=999)

        self.assertEqual(result.error, ai_disable_guard.AI_DISABLED_CODE)
        client.responses.create.assert_not_awaited()


def _install_image_v17(*, role_policy, generate_image_result):
    """Reproduit install_image_role_quota() avec les dépendances de
    v17_ai_economy_games mockées, pour extraire image_v17 sans booter le
    cog Ai ni la porte de priorité IA réelle."""
    # Une fonction nue, pas un AsyncMock : getattr(mock, "_sentrix_v17_image_quota", False)
    # renverrait un Mock auto-créé (donc vrai), trompant le contrôle d'idempotence
    # d'install_image_role_quota() et l'empêchant de remplacer le callback.
    original_calls: list[tuple] = []

    async def original_callback(*args, **kwargs):
        original_calls.append((args, kwargs))

    fake_command = SimpleNamespace(callback=original_callback)
    fake_ai_cog = SimpleNamespace()
    fake_bot = SimpleNamespace(
        get_cog=lambda name: fake_ai_cog if name == "Ai" else None,
        get_command=lambda name: fake_command if name == "image" else None,
    )

    @contextlib.asynccontextmanager
    async def fake_slot(priority):
        yield

    fake_gate = SimpleNamespace(slot=fake_slot)

    with patch("cogs.v17_ai_economy_games._ai_gate", return_value=fake_gate), \
         patch("cogs.v17_ai_economy_games._role_ai_policy", AsyncMock(return_value=role_policy)):
        v17_extras.install_image_role_quota(fake_bot)

    return fake_command.callback, original_calls


class ImageRoleQuotaTests(unittest.IsolatedAsyncioTestCase):
    async def test_bloque_avant_tout_appel_generate_image_si_limite_atteinte(self):
        image_v17, original_calls = _install_image_v17(
            role_policy={"daily_limit": 5, "priority": 2}, generate_image_result=None,
        )
        settings = _fake_ai_settings_row(enabled=True)
        settings["max_question_length"] = 500
        ai_cog_self = SimpleNamespace(bot=SimpleNamespace())
        ctx = SimpleNamespace(
            guild=SimpleNamespace(id=555), channel=SimpleNamespace(id=1),
            author=SimpleNamespace(id=2002, roles=()), interaction=None,
            typing=lambda: _async_nullcontext(),
        )

        with patch.object(ai_service, "get_settings", AsyncMock(return_value=settings)), \
             patch.object(ai_service, "is_channel_allowed", return_value=True), \
             patch.object(ai_service, "is_role_allowed", return_value=True), \
             patch.object(ai_service, "moderate_input", return_value=None), \
             patch.object(ai_service, "get_daily_usage", AsyncMock(return_value=5)), \
             patch.object(ai_service, "generate_image", AsyncMock(side_effect=AssertionError("ne doit jamais être appelé"))) as gen_image, \
             patch("cogs.v17_extras.panels.envoyer", AsyncMock()):
            await image_v17(ai_cog_self, ctx, description="un chat")

        gen_image.assert_not_awaited()
        self.assertEqual(original_calls, [])

    async def test_utilise_la_limite_du_role_pas_le_reglage_par_defaut_du_serveur(self):
        """Le quota par rôle (role_policy.daily_limit) prime sur le réglage
        par défaut du serveur (settings.daily_limit) — comportement à
        préserver tel quel avant toute migration."""
        image_v17, _original_calls = _install_image_v17(
            role_policy={"daily_limit": 50, "priority": 3}, generate_image_result=None,
        )
        settings = _fake_ai_settings_row(enabled=True)
        settings["max_question_length"] = 500
        settings["daily_limit"] = 2  # réglage serveur, ne doit PAS s'appliquer ici
        fake_result = SimpleNamespace(ok=True, data=b"", model="test-model")
        ai_cog_self = SimpleNamespace(
            bot=SimpleNamespace(),
            _embed=AsyncMock(return_value=SimpleNamespace(add_field=lambda **k: None, set_image=lambda **k: None)),
            _prepare_4k_discord_jpeg=lambda data: b"jpeg-bytes",
        )
        ctx = SimpleNamespace(
            guild=SimpleNamespace(id=555), channel=SimpleNamespace(id=1),
            author=SimpleNamespace(id=2002, roles=()), interaction=None,
            typing=lambda: _async_nullcontext(),
        )

        with patch.object(ai_service, "get_settings", AsyncMock(return_value=settings)), \
             patch.object(ai_service, "is_channel_allowed", return_value=True), \
             patch.object(ai_service, "is_role_allowed", return_value=True), \
             patch.object(ai_service, "moderate_input", return_value=None), \
             patch.object(ai_service, "get_daily_usage", AsyncMock(return_value=10)), \
             patch.object(ai_service, "record_usage", AsyncMock()), \
             patch.object(ai_service, "generate_image", AsyncMock(return_value=fake_result)) as gen_image, \
             patch("cogs.v17_extras.panels.envoyer", AsyncMock()):
            await image_v17(ai_cog_self, ctx, description="un chat")

        # used_today(10) < role_policy.daily_limit(50) : appel autorisé, même si
        # 10 >= settings.daily_limit(2) — la limite du rôle prime bien.
        gen_image.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
