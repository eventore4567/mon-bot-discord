"""Configuration des logs depuis le dashboard : rollback fiable et booléens stricts."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, call, patch

import pytest

from web.dashboard_api_logs import _parse_enabled, _save_verified_route, _resolve_channel_id


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (True, True),
        (False, False),
        (1, True),
        (0, False),
        ("true", True),
        ("false", False),
        ("0", False),
        ("1", True),
        ("off", False),
        ("on", True),
    ],
)
def test_enabled_n_interprete_pas_la_chaine_false_comme_true(value, expected):
    assert _parse_enabled(value, default=True) is expected


def test_enabled_refuse_les_valeurs_ambiguës():
    for value in ("non", "yes", "disabled", "", 2, [], {}, -1):
        with pytest.raises(ValueError):
            _parse_enabled(value, default=False)
    assert _parse_enabled(None, default=False) is False


@pytest.mark.asyncio
async def test_test_log_echoue_l_ancienne_route_est_restoree():
    bot = SimpleNamespace()
    guild = SimpleNamespace(id=42, me=SimpleNamespace(id=9))
    previous = {"enabled": True, "channel_id": 101}
    with patch(
        "web.dashboard_api_logs.log_service.get_log_setting",
        AsyncMock(return_value=previous),
    ), patch(
        "web.dashboard_api_logs.log_service.set_log_config",
        AsyncMock(side_effect=[{"channel_id": 202, "enabled": True}, previous]),
    ) as update, patch(
        "web.dashboard_api_logs.log_service.send_test_log",
        AsyncMock(return_value=(False, "Discord interdit l'envoi")),
    ):
        saved, detail, problem = await _save_verified_route(
            bot, guild, "messages", 202, True,
        )

    assert saved is None
    assert detail is None
    assert "ancienne configuration" in problem
    assert update.await_args_list == [
        call(bot, 42, "messages", channel_id=202, enabled=True),
        call(bot, 42, "messages", channel_id=101, enabled=True),
    ]


@pytest.mark.asyncio
async def test_test_log_reussi_n_effectue_pas_de_rollback():
    bot = SimpleNamespace()
    guild = SimpleNamespace(id=42, me=SimpleNamespace(id=9))
    updated = {"channel_id": 202, "enabled": True}
    with patch(
        "web.dashboard_api_logs.log_service.get_log_setting",
        AsyncMock(return_value={"enabled": True, "channel_id": 101}),
    ), patch(
        "web.dashboard_api_logs.log_service.set_log_config",
        AsyncMock(return_value=updated),
    ) as update, patch(
        "web.dashboard_api_logs.log_service.send_test_log",
        AsyncMock(return_value=(True, "Test envoyé")),
    ):
        saved, detail, problem = await _save_verified_route(
            bot, guild, "messages", 202, True,
        )

    assert saved == updated
    assert detail == "Test envoyé"
    assert problem is None
    update.assert_awaited_once()


@pytest.mark.asyncio
async def test_exception_pendant_test_log_restaurera_la_route():
    bot = SimpleNamespace()
    guild = SimpleNamespace(id=42, me=SimpleNamespace(id=9))
    with patch(
        "web.dashboard_api_logs.log_service.get_log_setting",
        AsyncMock(return_value={"enabled": True, "channel_id": 101}),
    ), patch(
        "web.dashboard_api_logs.log_service.set_log_config",
        AsyncMock(return_value={"channel_id": 202, "enabled": True}),
    ) as update, patch(
        "web.dashboard_api_logs.log_service.send_test_log",
        AsyncMock(side_effect=RuntimeError("Gateway down")),
    ):
        saved, _detail, problem = await _save_verified_route(
            bot, guild, "messages", 202, True,
        )
    assert saved is None
    assert "ancienne configuration" in problem
    assert update.await_count == 2


@pytest.mark.asyncio
async def test_disabled_route_ne_declenche_pas_d_envoi():
    bot = SimpleNamespace()
    guild = SimpleNamespace(id=42, me=None)
    with patch(
        "web.dashboard_api_logs.log_service.get_log_setting",
        AsyncMock(return_value={"enabled": True, "channel_id": 101}),
    ), patch(
        "web.dashboard_api_logs.log_service.set_log_config",
        AsyncMock(return_value={"enabled": False, "channel_id": None}),
    ), patch(
        "web.dashboard_api_logs.log_service.send_test_log",
        AsyncMock(),
    ) as test_send:
        saved, detail, problem = await _save_verified_route(
            bot, guild, "messages", None, False,
        )
    assert saved["enabled"] is False
    assert detail is None and problem is None
    test_send.assert_not_awaited()


@pytest.mark.asyncio
async def test_desactiver_sans_rechoisir_salon_conserve_la_destination():
    bot = SimpleNamespace()
    with patch(
        "web.dashboard_api_logs.log_service.get_log_setting",
        AsyncMock(return_value={"channel_id": 987654321, "enabled": True}),
    ) as get_settings:
        channel_id = await _resolve_channel_id(bot, 42, "messages", {"enabled": False})
    assert channel_id == 987654321
    get_settings.assert_awaited_once_with(bot, 42, "messages")


@pytest.mark.asyncio
async def test_reactiver_sans_rechoisir_salon_utilise_la_destination_enregistree():
    bot = SimpleNamespace()
    with patch(
        "web.dashboard_api_logs.log_service.get_log_setting",
        AsyncMock(return_value={"channel_id": 987654321, "enabled": False}),
    ):
        channel_id = await _resolve_channel_id(bot, 42, "messages", {"enabled": True})
    assert channel_id == 987654321


@pytest.mark.asyncio
async def test_effacement_explicitement_demande_ou_zero_retire_le_salon():
    bot = SimpleNamespace()
    with patch(
        "web.dashboard_api_logs.log_service.get_log_setting",
        AsyncMock(),
    ) as read:
        for chosen in (None, "", 0, "0"):
            channel_id = await _resolve_channel_id(
                bot, 42, "messages", {"channel_id": chosen, "enabled": False},
            )
            assert channel_id is None
    read.assert_not_awaited()


@pytest.mark.asyncio
async def test_identifiant_salon_invalide_est_refuse():
    bot = SimpleNamespace()
    for chosen in ("invalide", -3, "-10", [], {}, True):
        with pytest.raises(ValueError):
            await _resolve_channel_id(bot, 42, "messages", {"channel_id": chosen})
