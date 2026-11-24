"""La réouverture /setup récupère le règlement réellement publié."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from sentrix_verification_v96 import VerificationConfigV96


@pytest.mark.asyncio
async def test_setup_v96_restores_v78_published_panel_without_republishing():
    async def fetchone(sql, _params):
        if "verification_panels_v96" in sql:
            return None
        if "dashboard_verification_panels" in sql:
            return {
                "message_id": 54321, "rules_text": "Respect obligatoire.",
                "image_url": "https://example.org/banner.png", "updated_at": 100,
            }
        raise AssertionError(sql)

    db = SimpleNamespace(
        execute=AsyncMock(),
        fetchall=AsyncMock(return_value=[(0, "verification_auto_access")]),
        fetchone=AsyncMock(side_effect=fetchone),
        get_guild_config=AsyncMock(return_value={
            "verification_channel": 10, "verify_role": 20,
            "verification_auto_access": 0,
        }),
    )
    manager = VerificationConfigV96(SimpleNamespace(db=db))
    state = await manager._load_setup_state(SimpleNamespace(id=5))
    assert state["has_existing_panel"] is True
    assert state["channel_id"] == 10
    assert state["role_id"] == 20
    assert state["rules_text"] == "Respect obligatoire."
    assert state["image_url"] == "https://example.org/banner.png"
    db.execute.assert_awaited()


@pytest.mark.asyncio
async def test_draft_configuration_remains_unpublished():
    async def fetchone(sql, _params):
        if "verification_panels_v96" in sql:
            return {
                "channel_id": 10, "role_id": 20,
                "message_id": None, "rules_text": "Brouillon",
                "updated_at": 100,
            }
        if "dashboard_verification_panels" in sql:
            return None
        raise AssertionError(sql)

    db = SimpleNamespace(
        execute=AsyncMock(),
        fetchall=AsyncMock(return_value=[(0, "verification_auto_access")]),
        fetchone=AsyncMock(side_effect=fetchone),
        get_guild_config=AsyncMock(return_value={
            "verification_channel": 10, "verify_role": 20,
            "verification_auto_access": 0,
        }),
    )
    manager = VerificationConfigV96(SimpleNamespace(db=db))
    state = await manager._load_setup_state(SimpleNamespace(id=5))
    assert state["has_existing_panel"] is False
