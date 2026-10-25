"""Regression checks for production SentriX AI activation and reply mentions."""
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from utils import ai_service
from cogs import setup_v2_core


class AiDeploymentSetupSyncTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.bot = MagicMock()
        self.bot.db.fetchone = AsyncMock(return_value=None)
        self.bot.db.execute = AsyncMock()

    async def test_ai_inactive_without_explicit_setup(self):
        with patch.object(setup_v2_core, "ensure_schema", new_callable=AsyncMock), patch.object(
            setup_v2_core, "module_row_value", new_callable=AsyncMock, return_value=None
        ):
            self.assertFalse(await setup_v2_core.module_enabled(self.bot, 123, "ai"))

    async def test_aisetup_enables_same_module_as_setup(self):
        with patch.object(setup_v2_core, "set_module_enabled", new_callable=AsyncMock) as toggle:
            await ai_service.update_setting(self.bot, 123, "enabled", True)
            toggle.assert_awaited_once_with(self.bot, 123, "ai", True)

    async def test_aisetup_shows_setup_disabled_state(self):
        self.bot.db.fetchone.return_value = None
        with patch.object(setup_v2_core, "module_enabled", new_callable=AsyncMock, return_value=False):
            settings = await ai_service.get_settings(self.bot, 123)
        self.assertFalse(settings["enabled"])


if __name__ == "__main__":
    unittest.main()
