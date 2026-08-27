"""Protège le langage naturel SentriX contre les faux positifs et les réponses trop scolaires.

Trois protections vivent ici :
- « fais-moi un résumé sur Pythagore » ne doit jamais devenir +resume musique ;
- les messages Discord très courts comme « cv ? » restent une vraie conversation et ne
  doivent jamais déclencher une définition de l'abréviation ni une liste d'exemples ;
- une demande explicite de lien force une recherche web et retourne toujours une URL visible,
  en supprimant les liens vidéo non sourcés qui pourraient mener vers une page inexistante.
"""
from __future__ import annotations

import functools
import logging
import re
import unicodedata
from urllib.parse import quote_plus, urlsplit

from discord.ext import commands

from utils import ai_service

logger = logging.getLogger("bot.ai.natural-music-guard")
_INSTALLED = False

MUSIC_COMMANDS = {
    "join",
    "leave",
    "play",
    "pause",
    "resume",
    "skip",
    "stop",
    "queue",
    "nowplaying",
    "volume",
    "loop",
    "shuffle",
    "remove-from-queue",
    "clear-queue",
    "playlist-save",
    "playlist-load",
}

SUMMARY_PATTERN = re.compile(
    r"\b(resume|resumes|resumer|resumee|resumee?s|synthese|synthetise|synthetiser)\b"
)
MUSIC_CONTEXT_PATTERN = re.compile(
    r"\b(musique|musiques|chanson|chansons|audio|son|sons|lecture|playlist|playlist[s]?|"
    r"vocal|voice|track|titre|file d['’ ]?attente|volume)\b"
)
PLAYBACK_RESUME_PATTERN = re.compile(
    r"\b(reprend|reprends|reprendre|continue|continuer|relance|relancer)\b"
)

# Le modèle comprend déjà ces expressions, mais un fast-path déterministe évite qu'une
# question de small-talk ultra courte soit parfois traitée comme une demande de définition.
# Cela rend aussi « cv ? » quasi instantané puisqu'aucun appel OpenAI n'est nécessaire.
_CASUAL_REPLIES = {
    "cv": "Oui tranquille, et toi ?",
    "ca va": "Oui tranquille, et toi ?",
    "sava": "Oui tranquille, et toi ?",
    "sa va": "Oui tranquille, et toi ?",
    "tu vas bien": "Oui tranquille, et toi ?",
    "comment ca va": "Ça va bien, et toi ?",
    "ca dit quoi": "Tranquille, et toi ?",
    "bien ou quoi": "Oui tranquille, et toi ?",
    "slt": "Salut !",
    "salut": "Salut !",
    "cc": "Coucou !",
    "coucou": "Coucou !",
    "yo": "Yo !",
    "wsh": "Wsh, ça dit quoi ?",
    "t es la": "Oui, je suis là.",
    "tes la": "Oui, je suis là.",
    "tu fais quoi": "Je suis là, je te réponds. Et toi ?",
}

_CASUAL_PROMPT_MARKER = "[SENTRIX_CASUAL_CHAT_V58]"
_CASUAL_PROMPT = (
    "\n\n[SENTRIX_CASUAL_CHAT_V58]\n"
    "Règles de conversation Discord naturelle :\n"
    "- Un message court comme « cv ? », « ça va ? », « slt », « wsh », « yo », « bien ou quoi » "
    "est une conversation, pas une demande de définition. Réponds directement comme dans un chat.\n"
    "- N'explique JAMAIS spontanément le sens d'un mot, d'une abréviation, d'un argot ou d'une "
    "expression si l'utilisateur ne demande pas explicitement sa signification.\n"
    "- Après une réponse de small-talk, n'ajoute ni définition, ni cours, ni liste d'exemples, "
    "ni formulations que l'utilisateur pourrait envoyer.\n"
    "- Pour les messages de conversation très courts, fais généralement une seule phrase courte.\n"
    "- Si l'utilisateur demande explicitement « ça veut dire quoi ? », « ça signifie quoi ? », "
    "« définis » ou équivalent, alors seulement tu peux expliquer le terme."
)

_LINK_REQUEST_PATTERN = re.compile(
    r"(?:\b(?:donne|envoie|passe|partage|trouve|cherche|file|balance|mets?|met)\b.{0,32}"
    r"\b(?:lien|url)\b|\b(?:lien|url)\b\s+(?:de|du|des|vers|pour)\b|"
    r"\b(?:tu\s+as|t\s+as|tas|as\s+tu)\b.{0,12}\b(?:lien|url)\b)"
)
_LINK_RELATION_PATTERN = re.compile(r"\b(?:lien|relation)\s+entre\b")
_MARKDOWN_LINK_PATTERN = re.compile(r"\[([^\]]+)\]\((https?://[^\s)]+)\)", re.IGNORECASE)
_URL_PATTERN = re.compile(r"https?://[^\s<>]+", re.IGNORECASE)
_VIDEO_HOST_SUFFIXES = (
    "youtube.com",
    "youtu.be",
    "tiktok.com",
    "twitch.tv",
    "instagram.com",
    "dailymotion.com",
    "vimeo.com",
)


def _normalize_casual_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(text or ""))
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    normalized = normalized.casefold().replace("’", "'")
    normalized = re.sub(r"[^a-z0-9' ]+", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def _casual_reply(text: str) -> str | None:
    """Réponse locale uniquement pour les small-talks sans ambiguïté.

    Les demandes de définition (« cv veut dire quoi ? ») ne correspondent volontairement
    à aucune clé exacte et continuent donc vers l'IA normalement.
    """
    return _CASUAL_REPLIES.get(_normalize_casual_text(text))


def _looks_like_link_request(text: str) -> bool:
    """Détecte une vraie demande d'URL sans confondre « le lien entre X et Y »."""
    normalized = _normalize_casual_text(text)
    if not normalized or _LINK_RELATION_PATTERN.search(normalized):
        return False
    if normalized in {"lien", "url", "le lien", "un lien", "le url", "l url"}:
        return True
    return bool(_LINK_REQUEST_PATTERN.search(normalized))


def _request_text(args, kwargs) -> str:
    prompt = args[0] if args else kwargs.get("prompt", "")
    latest = getattr(ai_service, "_latest_user_text", None)
    if callable(latest):
        try:
            return str(latest(prompt) or "")
        except Exception:
            pass
    return str(prompt or "")


def _clean_url(url: str) -> str:
    return str(url or "").rstrip(".,;:!?)]}>\"'")


def _url_host(url: str) -> str:
    try:
        host = (urlsplit(_clean_url(url)).hostname or "").casefold()
    except Exception:
        return ""
    return host[4:] if host.startswith("www.") else host


def _is_video_url(url: str) -> bool:
    host = _url_host(url)
    return any(host == suffix or host.endswith("." + suffix) for suffix in _VIDEO_HOST_SUFFIXES)


def _canonical_url(url: str) -> str:
    """Normalise juste assez pour comparer www.youtube.com et youtube.com sans réécrire l'URL."""
    cleaned = _clean_url(url)
    try:
        parts = urlsplit(cleaned)
    except Exception:
        return cleaned
    host = (parts.hostname or "").casefold()
    if host.startswith("www."):
        host = host[4:]
    port = f":{parts.port}" if parts.port else ""
    return f"{parts.scheme.casefold()}://{host}{port}{parts.path or '/'}?{parts.query}".rstrip("?")


def _visible_markdown_links(text: str) -> str:
    """Discord cache l'URL de [titre](url) ; on affiche aussi l'URL brute demandée."""
    def replace(match: re.Match) -> str:
        title, url = match.group(1).strip(), _clean_url(match.group(2))
        return f"{title} — {url}"

    return _MARKDOWN_LINK_PATTERN.sub(replace, str(text or ""))


def _fallback_search_url(request_text: str) -> str:
    normalized = _normalize_casual_text(request_text)
    query = re.sub(r"\b(?:sentrix|donne|envoie|passe|partage|trouve|cherche|file|balance|mets?|met|moi|le|la|les|un|une|lien|url|de|du|des)\b", " ", normalized)
    query = re.sub(r"\s+", " ", query).strip() or normalized or "SentriX"
    encoded = quote_plus(query)
    if "youtube" in normalized or "video" in normalized or "vidéo" in str(request_text).casefold():
        return f"https://www.youtube.com/results?search_query={encoded}"
    if "tiktok" in normalized:
        return f"https://www.tiktok.com/search?q={encoded}"
    if "twitch" in normalized:
        return f"https://www.twitch.tv/search?term={encoded}"
    return f"https://www.google.com/search?q={encoded}"


def _ensure_visible_link_result(text: str, request_text: str) -> str:
    """Rend les sources visibles et neutralise les URLs vidéo non sourcées.

    ``utils.ai_service`` ajoute ses citations web sous « Sources : ». Ces URLs proviennent
    réellement du web_search. Une URL vidéo située uniquement dans le texte du modèle n'est
    donc pas considérée comme vérifiée et est retirée avant envoi à Discord.
    """
    raw = str(text or "").strip()
    source_match = re.search(r"\n\s*Sources\s*:\s*\n", raw, flags=re.IGNORECASE)
    if source_match:
        main = raw[:source_match.start()].rstrip()
        sources = raw[source_match.end():].strip()
    else:
        main, sources = raw, ""

    sources = _visible_markdown_links(sources)
    verified_urls = [_clean_url(url) for url in _URL_PATTERN.findall(sources)]
    verified_keys = {_canonical_url(url) for url in verified_urls}

    # Les liens vidéo inventés sont précisément ceux qui produisent une page YouTube
    # « inaccessible ». Ils ne survivent que s'ils apparaissent aussi dans les citations.
    def sanitize_url(match: re.Match) -> str:
        url = _clean_url(match.group(0))
        if _is_video_url(url) and _canonical_url(url) not in verified_keys:
            return ""
        return url

    main = _visible_markdown_links(main)
    main = _URL_PATTERN.sub(sanitize_url, main)
    main = re.sub(r"[ \t]+\n", "\n", main)
    main = re.sub(r" {2,}", " ", main).strip(" \n—-")

    parts = [main] if main else []
    if sources:
        parts.append("Liens vérifiés :\n" + sources)

    combined = "\n\n".join(part for part in parts if part).strip()
    urls = [_clean_url(url) for url in _URL_PATTERN.findall(combined)]

    is_video_request = bool(
        getattr(ai_service, "is_video_search_request", lambda _text: False)(request_text)
        or any(token in _normalize_casual_text(request_text) for token in ("youtube", "tiktok", "twitch", "video"))
    )
    if is_video_request:
        verified_video = next((url for url in verified_urls if _is_video_url(url)), None)
        if verified_video:
            if verified_video not in main:
                combined = f"{combined}\n\nLien direct vérifié : {verified_video}".strip()
            return combined
        fallback = _fallback_search_url(request_text)
        return f"{combined}\n\nLien de recherche vérifié : {fallback}".strip()

    if not urls:
        fallback = _fallback_search_url(request_text)
        combined = f"{combined}\n\nLien de recherche : {fallback}".strip()
    return combined


def _install_link_reliability() -> None:
    """Force le web_search pour les demandes de lien et fiabilise la sortie Discord."""
    original_needs_web_search = ai_service.needs_web_search
    if not getattr(original_needs_web_search, "_sentrix_link_intent_v59", False):
        @functools.wraps(original_needs_web_search)
        def link_aware_needs_web_search(text: str) -> bool:
            return original_needs_web_search(text) or _looks_like_link_request(text)

        link_aware_needs_web_search._sentrix_link_intent_v59 = True
        ai_service.needs_web_search = link_aware_needs_web_search

    original_generate = ai_service.generate
    if getattr(original_generate, "_sentrix_visible_links_v59", False):
        return

    @functools.wraps(original_generate)
    async def link_safe_generate(*args, **kwargs):
        request_text = _request_text(args, kwargs)
        wants_link = _looks_like_link_request(request_text) or bool(
            getattr(ai_service, "is_video_search_request", lambda _text: False)(request_text)
        )
        call_kwargs = dict(kwargs)
        if wants_link:
            # Même si un appelant historique oublie de passer web_search=True, une demande
            # explicite de lien ne doit jamais être laissée à la mémoire du modèle.
            call_kwargs["web_search"] = True

        result = await original_generate(*args, **call_kwargs)
        if wants_link and getattr(result, "ok", False):
            result.text = _ensure_visible_link_result(getattr(result, "text", ""), request_text)
        return result

    link_safe_generate._sentrix_visible_links_v59 = True
    ai_service.generate = link_safe_generate
    logger.info("Liens IA V59 actifs : recherche forcée, URL visible et liens vidéo sourcés uniquement.")


def _install_casual_chat_guard(ai_module) -> None:
    """Ajoute les règles globales et le fast-path aux routes legacy /sentrix/passives."""
    if _CASUAL_PROMPT_MARKER not in ai_service.SYSTEM_PROMPT:
        ai_service.SYSTEM_PROMPT += _CASUAL_PROMPT

    original_ask_ai = ai_module.Ai.ask_ai
    if getattr(original_ask_ai, "_sentrix_casual_chat_v58", False):
        return

    @functools.wraps(original_ask_ai)
    async def casual_aware_ask_ai(self, prompt, *args, **kwargs):
        if isinstance(prompt, str):
            direct = _casual_reply(prompt)
            if direct is not None:
                logger.debug("Réponse small-talk locale SentriX : %r", prompt[:80])
                return direct
        return await original_ask_ai(self, prompt, *args, **kwargs)

    casual_aware_ask_ai._sentrix_casual_chat_v58 = True
    ai_module.Ai.ask_ai = casual_aware_ask_ai
    logger.info("Conversation naturelle IA V58 active : small-talk court sans définition parasite.")


def install(bot: commands.Bot) -> None:
    """Protège Ai contre les faux positifs musique, les small-talks et les liens cassés."""
    global _INSTALLED
    if _INSTALLED:
        return

    from . import ai

    _install_link_reliability()
    _install_casual_chat_guard(ai)

    original = ai.Ai._natural_command_line
    if getattr(original, "_sentrix_music_intent_guard", False):
        _INSTALLED = True
        return

    def guarded_natural_command_line(
        self,
        question: str,
        prefix: str,
        *,
        has_attachment: bool,
    ) -> str | None:
        normalized = self._normalize_request(question)

        # L'accent est volontairement retiré par _normalize_request : « résumé » devient
        # donc « resume ». On donne la priorité au sens scolaire/IA avant toute recherche
        # de commande. Une vraie reprise audio formulée avec « reprends/relance » reste libre.
        if SUMMARY_PATTERN.search(normalized):
            explicit_playback_resume = bool(
                PLAYBACK_RESUME_PATTERN.search(normalized)
                and MUSIC_CONTEXT_PATTERN.search(normalized)
            )
            if not explicit_playback_resume:
                return None

        command_line = original(
            self,
            question,
            prefix,
            has_attachment=has_attachment,
        )
        if not command_line:
            return None

        raw = command_line[len(prefix):] if command_line.startswith(prefix) else command_line
        command_name = raw.split(maxsplit=1)[0].casefold()
        if command_name not in MUSIC_COMMANDS:
            return command_line

        # Une commande musique trouvée au milieu d'une phrase n'est exécutée que si la
        # phrase parle réellement d'audio. « SentriX pause » / « SentriX play X » restent
        # valides parce que le nom de commande est alors le début explicite de la demande.
        direct_music_command = bool(
            re.match(rf"^\s*{re.escape(command_name)}(?:\s|$)", normalized)
        )
        has_music_context = bool(MUSIC_CONTEXT_PATTERN.search(normalized))
        if not direct_music_command and not has_music_context:
            logger.info(
                "Commande musique naturelle ignorée (faux positif probable) : %s <- %r",
                command_name,
                question[:160],
            )
            return None

        return command_line

    guarded_natural_command_line._sentrix_music_intent_guard = True
    ai.Ai._natural_command_line = guarded_natural_command_line
    _INSTALLED = True
    logger.info("Protection des intentions musique du langage naturel activée.")
