"""La modération ne peut plus être désactivée (24/11/2026).

Avant : /setup → Modération avait un bouton « Désactiver la modération »,
le centre de contrôle et le dashboard aussi ; une ligne module_settings
enabled=0 coupait /ban, /kick, /mute… sur le serveur.
"""
from __future__ import annotations

import asyncio
import inspect
import os

os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")

import pytest  # noqa: E402

from cogs import setup_control_center as scc  # noqa: E402
from cogs import setup_experience_v74 as v74  # noqa: E402
from cogs import setup_v2_core as core  # noqa: E402
from tests.test_module_cache_coherence import Bot  # noqa: E402


@pytest.fixture
def bot():
    core.invalidate_module_cache()
    instance = Bot()
    yield instance
    core.invalidate_module_cache()


def test_ancienne_ligne_desactivee_est_ignoree(bot):
    # Un serveur où la modération avait été coupée la retrouve active.
    bot.db.rows[(1, "moderation")] = 0
    assert asyncio.run(core.module_enabled(bot, 1, "moderation")) is True
    assert asyncio.run(core.module_state(bot, 1, "moderation")) == core.MODULE_STATE_ENABLED


def test_desactivation_refusee_avec_un_message(bot):
    with pytest.raises(core.ModuleSetupRequired, match="ne peut pas être désactivée"):
        asyncio.run(core.set_module_enabled(bot, 1, "moderation", False, actor_id=5))
    assert (1, "moderation") not in bot.db.rows


def test_les_autres_modules_restent_desactivables(bot):
    bot.db.rows[(1, "security")] = 0
    assert asyncio.run(core.module_enabled(bot, 1, "security")) is False


def test_plus_aucun_bouton_pour_couper_la_moderation():
    from cogs import setup_moderation_clear_v76 as v76

    assert "Désactiver la modération" not in inspect.getsource(v74)
    assert "Désactiver la modération" not in inspect.getsource(v76)
    view = type("V", (), {"bot": None, "guild": None})()
    select = scc.ModuleSwitchSelect(view, {"moderation": "enabled", "security": "enabled"})
    assert "moderation" not in [o.value for o in select.options]
    assert "security" in [o.value for o in select.options]
