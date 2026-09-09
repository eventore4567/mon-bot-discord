"""Small product contracts that must hold on the real HA runtime.

This module intentionally does not duplicate moderation or AI business logic. It only
fixes two interface/runtime contracts before the final Discord command tree is built:

* passive ``sentrix ...`` replies follow the HA leader instead of a hard-coded Railway
  service name. ``utils.failover`` already guarantees that only the lease owner connects
  to Discord, so a standby that becomes leader must keep the passive AI responders;
* ``/moderation ... mute`` exposes the duration as a required slash option even though the
  legacy prefix callback still has its historical ``10m`` default.

The natural AI pipeline already keeps URLs in the question and ``utils.ai_service`` treats
``http://``/``https://`` as web-search triggers; this module therefore only preserves the
listener on the actual HA leader so messages such as ``sentrix https://...`` reach it.
"""
from __future__ import annotations

import inspect
import logging

import sentrix_v95_runtime as v95
from cogs import passive_ai_single_reply_final as passive_ai

logger = logging.getLogger("bot.product-runtime-contract")
_INSTALLED = False


def _ha_leader_can_host_passive_ai() -> bool:
    """The process that reached Discord is already the proven HA lease owner.

    ``railway_ha_boot`` waits for ``SentriXFailoverCoordinator.wait_for_leadership`` before
    opening the Discord gateway. Consequently the service name (primary/standby) must not
    decide whether natural AI responders exist.
    """
    return True


def _force_mute_duration_required(command, signature: inspect.Signature, option_names: tuple[str, ...]):
    qualified = str(getattr(command, "qualified_name", "") or "").casefold().strip()
    if not qualified or qualified.split()[-1] != "mute":
        return signature

    try:
        original_names = list(command.clean_params)
    except Exception:
        return signature

    exposed_for_duration = None
    for original, exposed in zip(original_names, option_names):
        if str(original).casefold() in {"duree", "durée", "duration"}:
            exposed_for_duration = exposed
            break
    if not exposed_for_duration:
        return signature

    parameter = signature.parameters.get(exposed_for_duration)
    if parameter is None or parameter.default is inspect.Parameter.empty:
        return signature

    replacement = parameter.replace(default=inspect.Parameter.empty)
    params = [replacement if item.name == exposed_for_duration else item for item in signature.parameters.values()]
    return signature.replace(parameters=params)


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    # The HA coordinator is the authority for which Railway service owns Discord.
    # Do not let the passive-AI reconciliation delete responders merely because the
    # active leader happens to be the standby service.
    passive_ai._is_primary_service = _ha_leader_can_host_passive_ai

    original_build_signature = v95._build_signature
    if not getattr(original_build_signature, "_sentrix_mute_duration_required", False):
        def build_signature(command):
            signature, native, option_names = original_build_signature(command)
            signature = _force_mute_duration_required(command, signature, option_names)
            return signature, native, option_names

        build_signature._sentrix_mute_duration_required = True
        build_signature.__wrapped__ = original_build_signature
        v95._build_signature = build_signature

    _INSTALLED = True
    logger.warning(
        "Contrats runtime produit actifs : IA passive suit le leader HA, duree de mute requise en slash, URLs IA conservees."
    )


__all__ = ["install", "_force_mute_duration_required", "_ha_leader_can_host_passive_ai"]
