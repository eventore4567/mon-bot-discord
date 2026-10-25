"""Non-regression tests for the shared /setup and +aisetup AI switch."""
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from cogs import setup_v2_core
from utils import ai_service


class AiSetupSynchronizationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.bot = MagicMock()
        self.bot.db.fetchone = AsyncMock(return_value=None)
        self.bot.db.execute = AsyncMock()

    async def test_ai_is_opt_in_without_existing_settings(self):
        with patch.object(setup_v2_core, "ensure_schema", new_callable=AsyncMock), \
             patch.object(setup_v2_core, "module_row_value", new_callable=AsyncMock, return_value=None):
            self.assertFalse(await setup_v2_core.module_enabled(self.bot, 123, "ai"))
            self.assertEqual(
                await setup_v2_core.module_state(self.bot, 123, "ai"),
                setup_v2_core.MODULE_STATE_NOT_CONFIGURED,
            )

    async def test_legacy_ai_activation_is_visible_in_setup(self):
        self.bot.db.fetchone.return_value = {"enabled": 1}
        with patch.object(setup_v2_core, "ensure_schema", new_callable=AsyncMock), \
             patch.object(setup_v2_core, "module_row_value", new_callable=AsyncMock, return_value=None):
            self.assertTrue(await setup_v2_core.module_enabled(self.bot, 123, "ai"))
            self.assertEqual(
                await setup_v2_core.module_state(self.bot, 123, "ai"),
                setup_v2_core.MODULE_STATE_ENABLED,
            )

    async def test_aisetup_toggle_uses_setup_shared_switch(self):
        with patch.object(setup_v2_core, "set_module_enabled", new_callable=AsyncMock) as shared:
            await ai_service.update_setting(self.bot, 123, "enabled", 1)
            shared.assert_awaited_once_with(self.bot, 123, "ai", True)

    async def test_setup_state_is_reflected_in_aisetup(self):
        self.bot.db.fetchone.return_value = None
        with patch.object(setup_v2_core, "module_enabled", new_callable=AsyncMock, return_value=True):
            settings = await ai_service.get_settings(self.bot, 123)
        self.assertTrue(settings["enabled"])


if __name__ == "__main__":
    unittest.main()
