"""Fiabilise et accélère l'IA sans dupliquer les commandes existantes.

Cette couche est volontairement runtime : toutes les commandes IA historiques continuent
à appeler ``utils.ai_service`` mais gagnent automatiquement le cache de réglages, la
coalescence des doubles requêtes, une concurrence bornée et l'identité propre de chaque
instance Railway.
"""
from __future__ import annotations

import asyncio
import copy
import functools
import logging
import os
import time

from utils import ai_service, premium_style
from utils.instance_identity import brand_label, brand_text, instance_key

logger = logging.getLogger("bot.ai-reliability")
_INSTALLED = False

# 15 secondes était trop court pour GPT-5.6 Sol lorsqu'une commande demande du code
# complet. La limite reste bornée afin qu'une panne réseau ne bloque jamais le bot.
TEXT_TIMEOUT_SECONDS = 45.0


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)) or default)
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


AI_CONCURRENCY = _env_int("SENTRIX_AI_CONCURRENCY", 8, 1, 32)
SETTINGS_CACHE_TTL = _env_int("SENTRIX_AI_SETTINGS_CACHE_TTL", 20, 2, 300)
_SETTINGS_CACHE: dict[int, tuple[float, dict]] = {}
_INFLIGHT: dict[tuple, asyncio.Task] = {}
_INFLIGHT_LOCK: asyncio.Lock | None = None
_AI_SEMAPHORE: asyncio.Semaphore | None = None


def _semaphore() -> asyncio.Semaphore:
    global _AI_SEMAPHORE
    if _AI_SEMAPHORE is None:
        _AI_SEMAPHORE = asyncio.Semaphore(AI_CONCURRENCY)
    return _AI_SEMAPHORE


def _inflight_lock() -> asyncio.Lock:
    global _INFLIGHT_LOCK
    if _INFLIGHT_LOCK is None:
        _INFLIGHT_LOCK = asyncio.Lock()
    return _INFLIGHT_LOCK


def _instance_system_prompt() -> str:
    prompt = brand_text(ai_service.SYSTEM_PROMPT)
    brand = brand_label()
    if brand.casefold() != "sentrix":
        prompt += (
            f"\n\nIdentité de cette instance : ton nom public est {brand} AI. "
            "Ne te présente pas comme SentriX dans tes réponses sur cette instance."
        )
    return prompt


def _request_key(args, kwargs) -> tuple | None:
    """Clé courte pour fusionner un double clic sans partager de réponse entre membres."""
    guild_id = kwargs.get("guild_id")
    user_id = kwargs.get("user_id")
    if user_id is None:
        return None
    prompt = args[0] if args else kwargs.get("prompt")
    if prompt is None:
        return None
    return (
        instance_key(),
        guild_id,
        user_id,
        str(kwargs.get("command") or ""),
        str(kwargs.get("model_key") or ai_service.MODEL_TERRA),
        bool(kwargs.get("web_search", False)),
        hash(str(prompt)),
    )


def install() -> None:
    """Installe les optimisations une seule fois pour SentriX et Bot'Odboug."""
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

    # Le texte interne reste commun dans GitHub ; l'identité publique est injectée à
    # l'exécution selon le service Railway. Le bot SentriX principal reste inchangé.
    for code, message in tuple(ai_service.ERROR_MESSAGES.items()):
        ai_service.ERROR_MESSAGES[code] = brand_text(message)

    # Les erreurs IA éditent parfois un ancien message de chargement sans contexte de
    # commande. On reconnaît donc explicitement les termes IA pour conserver la catégorie.
    original_infer_category = premium_style.infer_category

    @functools.wraps(original_infer_category)
    def infer_category_with_ai_context(*args, **kwargs):
        embed = kwargs.get("embed")
        if embed is not None:
            text = f"{getattr(embed, 'title', '')} {getattr(embed, 'description', '')}".casefold()
            markers = ("service ia", "erreur ia", "sentrix ai", "odboug ai", "openai", "gpt-")
            if any(marker in text for marker in markers):
                return "ai"
        return original_infer_category(*args, **kwargs)

    premium_style.infer_category = infer_category_with_ai_context

    original_pick_reasoning = ai_service.pick_reasoning_effort

    @functools.wraps(original_pick_reasoning)
    def responsive_reasoning(model_key: str, base_effort: str = "medium") -> str:
        effort = original_pick_reasoning(model_key, base_effort)
        # High sur Sol peut ajouter beaucoup de latence pour +code. Medium conserve un
        # raisonnement avancé mais réduit fortement le temps d'attente moyen.
        if model_key == ai_service.MODEL_SOL and effort in {"high", "xhigh", "max"}:
            return "medium"
        return effort

    ai_service.pick_reasoning_effort = responsive_reasoning

    # ---------------------------------------------------------------- réglages serveur
    # +ai lit les mêmes réglages plusieurs fois pendant une réponse. Un cache très court
    # enlève ces lectures SQLite/Postgres répétées sans rendre les changements admin lents :
    # update_setting invalide immédiatement l'entrée concernée.
    original_get_settings = ai_service.get_settings
    original_update_setting = ai_service.update_setting

    @functools.wraps(original_get_settings)
    async def cached_get_settings(bot, guild_id: int) -> dict:
        now = time.monotonic()
        cached = _SETTINGS_CACHE.get(int(guild_id))
        if cached and cached[0] > now:
            return copy.deepcopy(cached[1])
        settings = await original_get_settings(bot, guild_id)
        _SETTINGS_CACHE[int(guild_id)] = (now + SETTINGS_CACHE_TTL, copy.deepcopy(settings))
        return settings

    @functools.wraps(original_update_setting)
    async def invalidating_update_setting(bot, guild_id: int, field: str, value):
        result = await original_update_setting(bot, guild_id, field, value)
        _SETTINGS_CACHE.pop(int(guild_id), None)
        return result

    ai_service.get_settings = cached_get_settings
    ai_service.update_setting = invalidating_update_setting

    # ---------------------------------------------------------------- appels OpenAI
    original_generate = ai_service.generate

    async def execute_once(args, kwargs):
        call_kwargs = dict(kwargs)
        call_kwargs.setdefault("instructions", _instance_system_prompt())

        async with _semaphore():
            result = await original_generate(*args, **call_kwargs)

        model_key = call_kwargs.get("model_key", ai_service.MODEL_TERRA)
        command = str(call_kwargs.get("command") or "")

        # Une panne réseau très brève mérite une seconde tentative. Aucune relance n'est
        # faite pour les erreurs auth, quota, contenu ou bad-request.
        if result.error == ai_service.ERROR_CONNECTION:
            await asyncio.sleep(0.20)
            retry_kwargs = dict(call_kwargs)
            retry_kwargs["command"] = f"{command or 'ai'}-connection-retry"
            async with _semaphore():
                retry = await original_generate(*args, **retry_kwargs)
            if retry.ok:
                return retry

        # Repli avancé historique : si Sol expire, Terra répond à la place au lieu de
        # laisser l'utilisateur attendre une troisième tentative coûteuse.
        if result.error == ai_service.ERROR_TIMEOUT:
            should_retry = model_key == ai_service.MODEL_SOL or command == "code"
            if should_retry:
                retry_kwargs = dict(call_kwargs)
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
                async with _semaphore():
                    retry = await original_generate(*args, **retry_kwargs)
                if retry.ok or retry.error != ai_service.ERROR_TIMEOUT:
                    return retry
        return result

    @functools.wraps(original_generate)
    async def reliable_generate(*args, **kwargs):
        # Discord peut envoyer deux interactions très proches lors d'un double clic ou d'une
        # reconnexion. On partage uniquement le travail d'une requête strictement identique
        # du même utilisateur : aucune donnée ne traverse un utilisateur ou un serveur.
        key = _request_key(args, kwargs)
        if key is None:
            return await execute_once(args, kwargs)

        owner = False
        async with _inflight_lock():
            task = _INFLIGHT.get(key)
            if task is None or task.done():
                task = asyncio.create_task(execute_once(args, kwargs))
                _INFLIGHT[key] = task
                owner = True

        try:
            return await asyncio.shield(task)
        finally:
            if owner:
                async with _inflight_lock():
                    if _INFLIGHT.get(key) is task:
                        _INFLIGHT.pop(key, None)

    ai_service.generate = reliable_generate
    ai_service.ERROR_MESSAGES[ai_service.ERROR_TIMEOUT] = brand_text(
        "⏱️ Le service IA n'a pas répondu après deux tentatives. Réessaie dans quelques instants."
    )
    ai_service._SENTRIX_AI_RUNTIME = {
        "brand": brand_label(),
        "instance_key": instance_key(),
        "concurrency": AI_CONCURRENCY,
        "settings_cache_ttl": SETTINGS_CACHE_TTL,
    }
    logger.info(
        "IA V2 active pour %s : timeout=%ss, concurrence=%s, cache réglages=%ss, coalescence double-clic active.",
        brand_label(),
        TEXT_TIMEOUT_SECONDS,
        AI_CONCURRENCY,
        SETTINGS_CACHE_TTL,
    )
