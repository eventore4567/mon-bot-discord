"""Fiabilise les réponses IA longues sans modifier les commandes existantes."""

from __future__ import annotations

import functools
import logging

from utils import ai_service, premium_style

logger = logging.getLogger("bot.ai-reliability")
_INSTALLED = False

# 15 secondes était trop court pour GPT-5.6 Sol lorsqu'une commande demande du code
# complet. La limite reste bornée afin qu'une panne réseau ne bloque jamais le bot.
TEXT_TIMEOUT_SECONDS = 45.0


def install() -> None:
    """Allonge le délai utile et retente automatiquement avec Terra après un timeout Sol."""
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    ai_service.REQUEST_TIMEOUT_SECONDS = max(
        float(getattr(ai_service, "REQUEST_TIMEOUT_SECONDS", 15.0)),
        TEXT_TIMEOUT_SECONDS,
    )

    # Le client est normalement encore inutilisé au chargement des cogs. Le remettre à
    # None garantit néanmoins que le nouveau timeout sera bien appliqué au premier appel.
    ai_service._TEXT_CLIENT = None

    # Les erreurs IA éditent parfois un ancien message de chargement sans contexte de
    # commande. On reconnaît donc explicitement les termes IA pour éviter l’auteur
    # incorrect « SentriX • Utilitaires » vu dans la capture.
    original_infer_category = premium_style.infer_category

    @functools.wraps(original_infer_category)
    def infer_category_with_ai_context(*args, **kwargs):
        embed = kwargs.get("embed")
        if embed is not None:
            text = f"{getattr(embed, 'title', '')} {getattr(embed, 'description', '')}".casefold()
            if any(marker in text for marker in ("service ia", "erreur ia", "sentrix ai", "openai", "gpt-")):
                return "ai"
        return original_infer_category(*args, **kwargs)

    premium_style.infer_category = infer_category_with_ai_context

    original_pick_reasoning = ai_service.pick_reasoning_effort

    @functools.wraps(original_pick_reasoning)
    def responsive_reasoning(model_key: str, base_effort: str = "medium") -> str:
        effort = original_pick_reasoning(model_key, base_effort)
        # Le niveau high sur Sol dépassait fréquemment les 15 secondes pour +code. Medium
        # conserve un raisonnement avancé tout en répondant nettement plus vite.
        if model_key == ai_service.MODEL_SOL and effort in {"high", "xhigh", "max"}:
            return "medium"
        return effort

    ai_service.pick_reasoning_effort = responsive_reasoning

    original_generate = ai_service.generate

    @functools.wraps(original_generate)
    async def reliable_generate(*args, **kwargs):
        result = await original_generate(*args, **kwargs)
        if result.error != ai_service.ERROR_TIMEOUT:
            return result

        model_key = kwargs.get("model_key", ai_service.MODEL_TERRA)
        command = str(kwargs.get("command") or "")
        should_retry = model_key == ai_service.MODEL_SOL or command == "code"
        if not should_retry:
            return result

        retry_kwargs = dict(kwargs)
        retry_kwargs.update(
            model_key=ai_service.MODEL_TERRA,
            reasoning_effort="low",
            previous_response_id=None,
            command=f"{command or 'ai'}-timeout-retry",
        )
        logger.warning(
            "Timeout du modèle avancé : nouvelle tentative automatique avec Terra — commande=%s",
            command or "ai",
        )
        retry = await original_generate(*args, **retry_kwargs)
        return retry if retry.ok or retry.error != ai_service.ERROR_TIMEOUT else result

    ai_service.generate = reliable_generate
    ai_service.ERROR_MESSAGES[ai_service.ERROR_TIMEOUT] = (
        "⏱️ Le service IA n'a pas répondu après deux tentatives. Réessaie dans quelques instants."
    )
    logger.info("Fiabilité IA activée : timeout texte %ss et repli automatique Sol → Terra.", TEXT_TIMEOUT_SECONDS)
