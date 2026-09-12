from __future__ import annotations

import inspect
from types import SimpleNamespace

from sentrix_product_runtime_contract import (
    _force_mute_duration_required,
    _ha_leader_can_host_passive_ai,
)


def _signature_with_optional_duration() -> inspect.Signature:
    return inspect.Signature(
        [
            inspect.Parameter(
                "interaction",
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
            ),
            inspect.Parameter(
                "member",
                inspect.Parameter.KEYWORD_ONLY,
            ),
            inspect.Parameter(
                "duree",
                inspect.Parameter.KEYWORD_ONLY,
                default="10m",
            ),
            inspect.Parameter(
                "raison",
                inspect.Parameter.KEYWORD_ONLY,
                default="Aucune raison",
            ),
        ]
    )


def test_active_ha_leader_is_allowed_to_host_passive_ai_regardless_of_service_name():
    assert _ha_leader_can_host_passive_ai() is True


def test_mute_duration_becomes_required_in_slash_signature():
    command = SimpleNamespace(
        qualified_name="mute",
        clean_params={"member": object(), "duree": object(), "raison": object()},
    )
    signature = _force_mute_duration_required(
        command,
        _signature_with_optional_duration(),
        ("member", "duree", "raison"),
    )

    assert signature.parameters["duree"].default is inspect.Parameter.empty
    assert signature.parameters["raison"].default == "Aucune raison"


def test_non_mute_signature_is_not_changed():
    command = SimpleNamespace(
        qualified_name="warn",
        clean_params={"member": object(), "duree": object(), "raison": object()},
    )
    original = _signature_with_optional_duration()
    assert _force_mute_duration_required(
        command,
        original,
        ("member", "duree", "raison"),
    ) == original
