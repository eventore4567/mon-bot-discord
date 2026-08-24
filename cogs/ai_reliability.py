"""Fiabilise et accélère l'IA sans dupliquer les commandes existantes.

Cette couche est volontairement runtime : toutes les commandes IA historiques continuent
à appeler ``utils.ai_service`` mais gagnent automatiquement le cache de réglages, la
coalescence des doubles requêtes, une concurrence bornée et l'identité propre de chaque
instance Railway.

V56 renforce aussi les appels OpenAI contre les 429 transitoires : le SDK peut retenter
une fois, les rafales sont davantage bornées et SentriX bascule automatiquement sur un
modèle de secours si la limite du modèle demandé est atteinte.
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


# 8 appels simultanés était trop agressif pour les limites de petits projets OpenAI et
# pouvait transformer une courte rafale Discord en 429 répétés. 3 garde le bot réactif
# tout en laissant de la marge aux limites de requêtes/tokens du projet.
AI_CONCURRENCY = _env_int("SENTRIX_AI_CONCURRENCY", 3, 1, 16)
SETTINGS_CACHE_TTL = _env_int("SENTRIX_AI_SETTINGS_CACHE_TTL", 20, 2, 300)
_SETTINGS_CACHE: dict[int, tuple[float, dict]] = {}
_INFLIGHT: dict[tuple, asyncio.Task] = {}
_INFLIGHT_LOCK: asyncio.Lock | None = None
_AI_SEMAPHORE: asyncio.Semaphore | None = None

# Modèle de secours indépendant de Luna/Terra/Sol. Les rate limits OpenAI pouvant être
# différents selon les familles de modèles, ce repli permet souvent de répondre même si
# le modèle 5.6 demandé est momentanément limité.
_FALLBACK_MODEL_KEY = "sentrix-fallback-mini"
_FALLBACK_MODEL_ID = (os.getenv("OPENAI_MODEL_FALLBACK", "gpt-5.4-mini") or "gpt-5.4-mini").strip()
_RATE_LIMIT_RETRY_DELAYS = (0.35, 0.90)


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


def _rate_limit_fallbacks(model_key: str) -> tuple[str, ...]:
    """Ordre des modèles à essayer après un 429, sans refaire trois fois le même modèle."""
    if model_key == ai_service.MODEL_LUNA:
        return (ai_service.MODEL_TERRA, _FALLBACK_MODEL_KEY)
    if model_key == ai_service.MODEL_TERRA:
        return (ai_service.MODEL_LUNA, _FALLBACK_MODEL_KEY)
    if model_key == ai_service.MODEL_SOL:
        return (ai_service.MODEL_TERRA, _FALLBACK_MODEL_KEY)
    return (ai_service.MODEL_LUNA, ai_service.MODEL_TERRA)


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

    # Le code historique désactivait totalement les retries du SDK (max_retries=0). Une
    # unique réponse 429 transitoire devenait donc immédiatement l'erreur visible par
    # l'utilisateur. On conserve un seul retry SDK, puis le repli multi-modèles ci-dessous.
    def robust_get_client():
        if not getattr(ai_service.config, "OPENAI_API_KEY", None):
            return None
        if ai_service._TEXT_CLIENT is None:
            from openai import AsyncOpenAI
            ai_service._TEXT_CLIENT = AsyncOpenAI(
                api_key=ai_service.config.OPENAI_API_KEY,
                timeout=ai_service.REQUEST_TIMEOUT_SECONDS,
                max_retries=1,
            )
        return ai_service._TEXT_CLIENT

    ai_service.get_client = robust_get_client
    ai_service._TEXT_CLIENT = None

    # Repli interne : il n'apparaît jamais dans +aisetup, il ne sert que lorsqu'un 429 est
    # renvoyé par le modèle normalement sélectionné.
    ai_service.MODEL_IDS[_FALLBACK_MODEL_KEY] = _FALLBACK_MODEL_ID
    ai_service.MODEL_LABELS[_FALLBACK_MODEL_KEY] = "GPT-5.4 Mini (secours)"

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

    async def call_openai(args, kwargs):
        async with _semaphore():
            return await original_generate(*args, **kwargs)

    async def execute_once(args, kwargs):
        call_kwargs = dict(kwargs)
        call_kwargs.setdefault("instructions", _instance_system_prompt())

        result = await call_openai(args, call_kwargs)

        model_key = call_kwargs.get("model_key", ai_service.MODEL_TERRA)
        command = str(call_kwargs.get("command") or "")

        # Un 429 n'est plus affiché dès la première tentative. On essaie un autre pool de
        # modèle, puis le mini de secours. Cela couvre les limites transitoires propres à
        # Luna/Terra/Sol sans faire une boucle infinie en cas de quota réellement épuisé.
        if result.error == ai_service.ERROR_RATE_LIMIT:
            last = result
            for index, fallback_key in enumerate(_rate_limit_fallbacks(model_key)):
                await asyncio.sleep(_RATE_LIMIT_RETRY_DELAYS[min(index, len(_RATE_LIMIT_RETRY_DELAYS) - 1)])
                retry_kwargs = dict(call_kwargs)
                retry_kwargs.update(
                    model_key=fallback_key,
                    reasoning_effort="none" if fallback_key in {ai_service.MODEL_LUNA, _FALLBACK_MODEL_KEY} else "low",
                    previous_response_id=None,
                    command=f"{command or 'ai'}-429-fallback-{index + 1}",
                )
                logger.warning(
                    "429 OpenAI : repli automatique %s -> %s — commande=%s",
                    model_key,
                    fallback_key,
                    command or "ai",
                )
                retry = await call_openai(args, retry_kwargs)
                last = retry
                if retry.ok:
                    return retry
                if retry.error != ai_service.ERROR_RATE_LIMIT:
                    return retry
            result = last

        # Une panne réseau très brève mérite une seconde tentative. Aucune relance n'est
        # faite pour les erreurs auth, quota persistant, contenu ou bad-request.
        if result.error == ai_service.ERROR_CONNECTION:
            await asyncio.sleep(0.20)
            retry_kwargs = dict(call_kwargs)
            retry_kwargs["command"] = f"{command or 'ai'}-connection-retry"
            retry = await call_openai(args, retry_kwargs)
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
                retry = await call_openai(args, retry_kwargs)
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
    ai_service.ERROR_MESSAGES[ai_service.ERROR_RATE_LIMIT] = brand_text(
        "⏳ OpenAI refuse encore la requête après les modèles de secours. Réessaie dans quelques instants."
    )
    ai_service._SENTRIX_AI_RUNTIME = {
        "brand": brand_label(),
        "instance_key": instance_key(),
        "concurrency": AI_CONCURRENCY,
        "settings_cache_ttl": SETTINGS_CACHE_TTL,
        "sdk_retries": 1,
        "rate_limit_fallback": _FALLBACK_MODEL_ID,
    }
    logger.info(
        "IA V56 active pour %s : timeout=%ss, concurrence=%s, retry SDK=1, repli 429=%s, cache=%ss.",
        brand_label(),
        TEXT_TIMEOUT_SECONDS,
        AI_CONCURRENCY,
        _FALLBACK_MODEL_ID,
        SETTINGS_CACHE_TTL,
    )
