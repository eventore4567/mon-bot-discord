"""Provider abstraction for SentriX social notifications.

Phyllo is optional. Existing yt-dlp polling remains the fallback and works without
credentials. This module deliberately does not invent undocumented Phyllo API
endpoints: the verified integration surface here is webhook ingestion/signature
verification plus a normalized event model shared by every provider.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import json
from urllib.parse import urlparse, urlunparse
from typing import Any, Iterable


@dataclass(frozen=True)
class SocialEvent:
    provider: str
    platform: str
    item_id: str
    url: str
    title: str
    creator: str | None = None
    creator_url: str | None = None
    thumbnail_url: str | None = None
    published_at: int | None = None
    kind: str = "post"
    raw_event: str | None = None


def _platform_from_text(value: object) -> str:
    text = str(value or "").strip().casefold()
    aliases = {
        "youtube": "YouTube",
        "youtube shorts": "YouTube",
        "tiktok": "TikTok",
        "twitch": "Twitch",
        "instagram": "Instagram",
        "twitter": "X",
        "x": "X",
        "facebook": "Facebook",
        "dailymotion": "Dailymotion",
        "vimeo": "Vimeo",
        "kick": "Kick",
    }
    for key, label in aliases.items():
        if key in text:
            return label
    return str(value or "").strip() or "Réseau social"


def _youtube_base(url: str) -> str:
    parsed = urlparse(str(url or "").strip())
    path = parsed.path.rstrip("/")
    for suffix in ("/videos", "/shorts", "/streams", "/live", "/featured"):
        if path.endswith(suffix):
            path = path[: -len(suffix)]
            break
    return urlunparse((parsed.scheme, parsed.netloc, path, "", "", ""))


def source_surfaces(source_url: str, platform: str) -> list[tuple[str, str, str]]:
    """Return (state_key, poll_url, content_kind).

    A YouTube channel is intentionally split into three independent surfaces.
    Keeping separate state avoids the old bug where a video ID masked a newer
    Short, or an old Short looked "new" after a normal video changed.
    """
    source_url = str(source_url or "").strip()
    if platform != "YouTube":
        return [("default", source_url, "live" if platform == "Twitch" else "post")]

    parsed = urlparse(source_url)
    path = parsed.path.rstrip("/")
    if "/watch" in path or "/playlist" in path:
        return [("videos", source_url, "video")]
    # Une URL de CONTENU précise reste une surface unique. Une URL d'onglet de
    # chaîne (/videos, /shorts, /streams) est au contraire ramenée à la chaîne
    # afin que SentriX surveille les trois formats ensemble.
    if "/shorts/" in path:
        return [("shorts", source_url, "short")]
    if "/live/" in path:
        return [("streams", source_url, "live")]

    base = _youtube_base(source_url)
    return [
        ("videos", f"{base}/videos", "video"),
        ("shorts", f"{base}/shorts", "short"),
        ("streams", f"{base}/streams", "live"),
    ]


def verify_phyllo_signature(body: bytes, signature: str, secret: str) -> bool:
    """Verify X-Phyllo-Signature (HMAC-SHA256 over raw body)."""
    if not body or not signature or not secret:
        return False
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    supplied = str(signature).strip()
    if supplied.casefold().startswith("sha256="):
        supplied = supplied.split("=", 1)[1]
    return hmac.compare_digest(expected.casefold(), supplied.casefold())


def _walk_dicts(value: Any) -> Iterable[dict]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_dicts(child)


def _first(mapping: dict, *keys: str) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def _epoch(value: Any) -> int | None:
    if isinstance(value, (int, float)):
        number = int(value)
        if number > 10_000_000_000:
            number //= 1000
        return number if number > 0 else None
    text = str(value or "").strip()
    if text.isdigit():
        return _epoch(int(text))
    if not text:
        return None
    try:
        from datetime import datetime
        return int(datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp())
    except Exception:
        return None


def parse_phyllo_webhook(payload: dict) -> list[SocialEvent]:
    """Best-effort normalizer for Phyllo webhook payloads.

    Phyllo product/event availability varies by account and API surface. We only
    emit an event when a payload actually contains a content-like object with a
    stable ID and public URL; unknown events are accepted but ignored safely.
    """
    if not isinstance(payload, dict):
        return []

    event_name = str(
        payload.get("event")
        or payload.get("event_type")
        or payload.get("type")
        or ""
    ).strip()
    events: list[SocialEvent] = []
    seen: set[tuple[str, str]] = set()

    # Les webhooks Phyllo couvrent aussi comptes/profils/syncs. Ne jamais
    # transformer un simple profil contenant {id,url} en "nouvelle vidéo".
    event_is_content = "CONTENT" in event_name.upper() if event_name else False

    for node in _walk_dicts(payload):
        node_is_content = any(
            key in node
            for key in (
                "content_id", "post_id", "video_id", "content_type",
                "media_type", "thumbnail_url", "post_url", "content_url",
            )
        )
        if not event_is_content and not node_is_content:
            continue

        item_id = _first(node, "content_id", "post_id", "video_id", "id")
        url = _first(
            node,
            "url",
            "content_url",
            "post_url",
            "permalink",
            "webpage_url",
            "share_url",
        )
        if not item_id or not isinstance(url, str) or not url.startswith("http"):
            continue

        platform = _platform_from_text(
            _first(node, "platform", "work_platform_name", "platform_name", "network")
        )
        host = (urlparse(url).hostname or "").casefold()
        if platform == "Réseau social":
            platform = _platform_from_text(host)

        title = str(
            _first(node, "title", "caption", "text", "description", "name")
            or f"Nouvelle publication sur {platform}"
        ).strip()
        creator = _first(
            node,
            "creator_name",
            "username",
            "handle",
            "profile_name",
            "channel_name",
            "uploader",
        )
        creator_url = _first(
            node,
            "creator_url",
            "profile_url",
            "channel_url",
        )
        thumbnail = _first(
            node,
            "thumbnail_url",
            "thumbnail",
            "cover_url",
            "image_url",
            "media_url",
        )
        published_at = _epoch(
            _first(node, "published_at", "published_time", "created_at", "timestamp")
        )

        kind_text = str(_first(node, "content_type", "type", "media_type", "format") or "").casefold()
        path = urlparse(url).path.casefold()
        if "short" in kind_text or "/shorts/" in path:
            kind = "short"
        elif "live" in kind_text or "stream" in kind_text:
            kind = "live"
        elif "video" in kind_text or platform in {"YouTube", "TikTok", "Twitch"}:
            kind = "video"
        else:
            kind = "post"

        key = (platform, str(item_id))
        if key in seen:
            continue
        seen.add(key)
        events.append(
            SocialEvent(
                provider="phyllo",
                platform=platform,
                item_id=str(item_id),
                url=url,
                title=title[:300],
                creator=str(creator)[:120] if creator else None,
                creator_url=str(creator_url) if creator_url else None,
                thumbnail_url=str(thumbnail) if thumbnail else None,
                published_at=published_at,
                kind=kind,
                raw_event=event_name or None,
            )
        )

    return events


def webhook_event_key(payload: dict, raw_body: bytes) -> str:
    explicit = (
        payload.get("webhook_id")
        or payload.get("event_id")
        or payload.get("id")
        if isinstance(payload, dict)
        else None
    )
    if explicit:
        return f"phyllo:{explicit}"
    return "phyllo:" + hashlib.sha256(raw_body).hexdigest()


def same_creator(source_url: str, event: SocialEvent) -> bool:
    """Conservative subscription matcher used for provider webhooks."""
    source = str(source_url or "").strip().casefold().rstrip("/")
    candidates = [
        str(event.creator_url or "").strip().casefold().rstrip("/"),
        str(event.url or "").strip().casefold().rstrip("/"),
    ]
    for candidate in candidates:
        if candidate and (candidate.startswith(source) or source.startswith(candidate)):
            return True

    source_path = urlparse(source).path.strip("/").casefold()
    creator = str(event.creator or "").strip().lstrip("@").casefold()
    if creator and source_path:
        last = source_path.split("/")[-1].lstrip("@")
        return creator == last
    return False


__all__ = [
    "SocialEvent",
    "parse_phyllo_webhook",
    "same_creator",
    "source_surfaces",
    "verify_phyllo_signature",
    "webhook_event_key",
]
