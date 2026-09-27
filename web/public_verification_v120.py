"""Public web verification flow for SentriX.

The Discord verification panel only opens this site. Identity is bound through the
existing Discord OAuth callback, then all challenge work happens on the web page.
No route in this module creates Discord channels or categories.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import html
import io
import json
import logging
import secrets
import time
from typing import Any

import discord
from aiohttp import web

import config
from utils import rules_flow

logger = logging.getLogger("bot.web-verification-v120")

PENDING_COOKIE = "sentrix_verify_pending"
SESSION_COOKIE = "sentrix_verify_session"
SESSION_TTL = 15 * 60
CHALLENGE_TTL = 3 * 60
CAPTCHA_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
MAX_WEB_FAILURES = 5
WEB_FAILURE_WINDOW = 10 * 60
WEB_LOCK_SECONDS = 10 * 60

_WEB_ATTEMPT_SCHEMA = """
CREATE TABLE IF NOT EXISTS web_verification_attempts (
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    failures INTEGER NOT NULL DEFAULT 0,
    window_started INTEGER NOT NULL DEFAULT 0,
    locked_until INTEGER NOT NULL DEFAULT 0,
    last_attempt INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, user_id)
)
"""


async def _ensure_attempt_schema(bot) -> None:
    await bot.db.execute(_WEB_ATTEMPT_SCHEMA)


async def _attempt_row(bot, guild_id: int, user_id: int):
    await _ensure_attempt_schema(bot)
    return await bot.db.fetchone(
        "SELECT failures,window_started,locked_until,last_attempt "
        "FROM web_verification_attempts WHERE guild_id=? AND user_id=?",
        (int(guild_id), int(user_id)),
    )


async def _locked_seconds(bot, guild_id: int, user_id: int) -> int:
    row = await _attempt_row(bot, guild_id, user_id)
    if not row:
        return 0
    return max(0, int(row["locked_until"] or 0) - int(time.time()))


async def _record_failure(bot, guild_id: int, user_id: int) -> int:
    now = int(time.time())
    row = await _attempt_row(bot, guild_id, user_id)
    failures = int(row["failures"] or 0) if row else 0
    started = int(row["window_started"] or 0) if row else 0
    locked_until = int(row["locked_until"] or 0) if row else 0

    if locked_until > now:
        return locked_until - now
    if not started or now - started > WEB_FAILURE_WINDOW:
        started = now
        failures = 0
    failures += 1
    locked_until = now + WEB_LOCK_SECONDS if failures >= MAX_WEB_FAILURES else 0
    await bot.db.execute(
        "INSERT INTO web_verification_attempts"
        "(guild_id,user_id,failures,window_started,locked_until,last_attempt) "
        "VALUES(?,?,?,?,?,?) ON CONFLICT(guild_id,user_id) DO UPDATE SET "
        "failures=excluded.failures,window_started=excluded.window_started,"
        "locked_until=excluded.locked_until,last_attempt=excluded.last_attempt",
        (int(guild_id), int(user_id), failures, started, locked_until, now),
    )
    return max(0, locked_until - now)


async def _clear_failures(bot, guild_id: int, user_id: int) -> None:
    await _ensure_attempt_schema(bot)
    await bot.db.execute(
        "DELETE FROM web_verification_attempts WHERE guild_id=? AND user_id=?",
        (int(guild_id), int(user_id)),
    )


async def _adaptive_security(cog, member: discord.Member) -> tuple[float, float, bool]:
    """Run the currently installed SentriX adaptive engine as a web verification stage."""
    settings = await cog.settings(member.guild.id)
    threshold = float(settings.get("threshold", 16))
    signals = await cog.collect_factors(member)

    if len(signals) >= 40:
        from cogs.automatic_verification_v5 import score_signals
        score, passed = score_signals(signals, threshold)
    else:
        from cogs.automatic_verification_v4 import score_factors
        score, passed = score_factors(signals, int(threshold))

    save = getattr(cog, "_save_result", None)
    if callable(save):
        try:
            await save(
                member,
                score,
                threshold,
                "web_ready" if passed else "web_review",
                signals,
            )
        except Exception:
            logger.debug("Adaptive web result persistence skipped.", exc_info=True)
    return float(score), threshold, bool(passed)


def _secret() -> bytes:
    value = (
        (getattr(config, "DISCORD_CLIENT_SECRET", "") or "").strip()
        or (getattr(config, "DISCORD_TOKEN", "") or "").strip()
    )
    if not value:
        raise RuntimeError("SentriX verification signing secret is unavailable")
    return value.encode("utf-8")


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64d(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _issue(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    body = _b64e(raw)
    sig = hmac.new(_secret(), body.encode("ascii"), hashlib.sha256).digest()
    return f"{body}.{_b64e(sig)}"


def _decode(token: str, *, kind: str | None = None) -> dict[str, Any] | None:
    try:
        body, sig = str(token or "").split(".", 1)
        expected = hmac.new(_secret(), body.encode("ascii"), hashlib.sha256).digest()
        if not hmac.compare_digest(expected, _b64d(sig)):
            return None
        payload = json.loads(_b64d(body))
        if int(payload.get("exp", 0) or 0) < int(time.time()):
            return None
        if kind and payload.get("kind") != kind:
            return None
        return payload
    except Exception:
        return None


def make_pending_token(guild_id: int) -> str:
    return _issue({
        "kind": "verify_pending",
        "gid": int(guild_id),
        "exp": int(time.time()) + 10 * 60,
        "nonce": secrets.token_urlsafe(10),
    })


def parse_pending_token(token: str) -> dict[str, Any] | None:
    return _decode(token, kind="verify_pending")


def make_session_token(guild_id: int, user_id: int) -> str:
    return _issue({
        "kind": "verify_session",
        "gid": int(guild_id),
        "uid": int(user_id),
        "exp": int(time.time()) + SESSION_TTL,
        "nonce": secrets.token_urlsafe(10),
    })


def parse_session_token(token: str, *, guild_id: int | None = None) -> dict[str, Any] | None:
    payload = _decode(token, kind="verify_session")
    if not payload:
        return None
    if guild_id is not None and int(payload.get("gid", 0) or 0) != int(guild_id):
        return None
    return payload


def verification_url(guild_id: int) -> str:
    return f"{str(config.DASHBOARD_PUBLIC_URL).rstrip('/')}/verify/{int(guild_id)}"


def _answer_digest(salt: str, label: str, value: str) -> str:
    payload = f"{salt}|{label}|{str(value).strip().upper()}".encode("utf-8")
    return hmac.new(_secret(), payload, hashlib.sha256).hexdigest()


def issue_challenge(guild_id: int, user_id: int, code: str, math_answer: str) -> str:
    salt = secrets.token_urlsafe(12)
    return _issue({
        "kind": "verify_challenge",
        "gid": int(guild_id),
        "uid": int(user_id),
        "salt": salt,
        "captcha": _answer_digest(salt, "captcha", code),
        "math": _answer_digest(salt, "math", math_answer),
        "exp": int(time.time()) + CHALLENGE_TTL,
        "nonce": secrets.token_urlsafe(10),
    })


def validate_challenge(
    token: str,
    *,
    guild_id: int,
    user_id: int,
    captcha: str,
    math_answer: str,
) -> bool:
    payload = _decode(token, kind="verify_challenge")
    if not payload:
        return False
    if int(payload.get("gid", 0) or 0) != int(guild_id):
        return False
    if int(payload.get("uid", 0) or 0) != int(user_id):
        return False
    salt = str(payload.get("salt") or "")
    if not salt:
        return False
    expected_captcha = str(payload.get("captcha") or "")
    expected_math = str(payload.get("math") or "")
    return (
        secrets.compare_digest(expected_captcha, _answer_digest(salt, "captcha", captcha))
        and secrets.compare_digest(expected_math, _answer_digest(salt, "math", math_answer))
    )


def _captcha_png(code: str) -> str:
    try:
        from PIL import Image, ImageDraw, ImageFont

        width, height = 380, 128
        image = Image.new("RGB", (width, height), (8, 13, 31))
        draw = ImageDraw.Draw(image)
        rng = secrets.SystemRandom()

        for _ in range(35):
            x1, y1 = rng.randrange(width), rng.randrange(height)
            x2, y2 = rng.randrange(width), rng.randrange(height)
            shade = rng.randrange(35, 90)
            draw.line((x1, y1, x2, y2), fill=(30, shade, 130), width=rng.randrange(1, 3))

        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 44)
        except Exception:
            font = ImageFont.load_default()

        spacing = width // (len(code) + 1)
        for index, char in enumerate(code, start=1):
            x = index * spacing - 17 + rng.randrange(-8, 9)
            y = 33 + rng.randrange(-10, 11)
            draw.text((x, y), char, font=font, fill=(225, 239, 255))

        for _ in range(520):
            x, y = rng.randrange(width), rng.randrange(height)
            draw.point(
                (x, y),
                fill=(rng.randrange(30, 120), rng.randrange(70, 150), rng.randrange(120, 235)),
            )

        out = io.BytesIO()
        image.save(out, format="PNG", optimize=True)
        return "data:image/png;base64," + base64.b64encode(out.getvalue()).decode("ascii")
    except Exception:
        safe = html.escape(code)
        svg = (
            "<svg xmlns='http://www.w3.org/2000/svg' width='380' height='128'>"
            "<rect width='100%' height='100%' fill='#080d1f'/>"
            "<text x='50%' y='58%' text-anchor='middle' fill='#e8f2ff' "
            "font-family='monospace' font-size='44' font-weight='700' letter-spacing='10'>"
            f"{safe}</text></svg>"
        )
        return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode("ascii")


def _json_error(message: str, status: int = 400, *, code: str = "verification_error") -> web.Response:
    return web.json_response({"ok": False, "error": message, "code": code}, status=status)


async def _resolve_session(request: web.Request, guild_id: int):
    payload = parse_session_token(request.cookies.get(SESSION_COOKIE, ""), guild_id=guild_id)
    if not payload:
        return None, None, _json_error(
            "Connecte-toi avec Discord pour continuer.", 401, code="auth_required"
        )

    bot = request.app["bot"]
    if not bot.is_ready():
        return None, None, _json_error(
            "SentriX se reconnecte à Discord. Réessaie dans un instant.", 503
        )

    guild = bot.get_guild(int(guild_id))
    if guild is None:
        return None, None, _json_error("SentriX n'est plus présent sur ce serveur.", 404)

    user_id = int(payload["uid"])
    member = guild.get_member(user_id)
    if member is None:
        try:
            member = await guild.fetch_member(user_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            member = None
    if member is None:
        return guild, None, _json_error(
            "Ton compte Discord n'est pas membre de ce serveur.", 403
        )

    return guild, member, None


async def _status_payload(
    bot,
    guild: discord.Guild,
    member: discord.Member,
) -> tuple[dict[str, Any] | None, web.Response | None]:
    cog = bot.get_cog("HoneypotVerification")
    if cog is None:
        return None, _json_error(
            "Le système de vérification est momentanément indisponible.", 503
        )

    conf = await cog.config(guild.id)
    if not conf:
        return None, _json_error(
            "La vérification renforcée n'est pas activée sur ce serveur.", 409
        )

    verified = guild.get_role(int(conf["verified_role_id"] or 0))
    unverified = guild.get_role(int(conf["unverified_role_id"] or 0))
    if verified is None or unverified is None:
        return None, _json_error(
            "La configuration des rôles de vérification est incomplète.", 409
        )

    account_age = max(
        0, int((discord.utils.utcnow() - member.created_at).total_seconds())
    )
    joined_for = 999999
    if member.joined_at is not None:
        joined_for = max(
            0, int((discord.utils.utcnow() - member.joined_at).total_seconds())
        )

    rules_record = await rules_flow.current_rules_record(bot, guild.id)
    accepted_rules = await rules_flow.has_accepted_current_rules(
        bot, guild.id, member.id
    )

    try:
        settings = await cog.settings(guild.id)
        min_account_age_seconds = max(
            0, int(settings.get("min_account_age_minutes", 30) or 0) * 60
        )
    except Exception:
        min_account_age_seconds = 30 * 60

    locked = await _locked_seconds(bot, guild.id, member.id)
    already_verified = verified in member.roles and unverified not in member.roles
    pending_role = unverified in member.roles

    return {
        "ok": True,
        "guild": {"id": str(guild.id), "name": guild.name},
        "user": {
            "id": str(member.id),
            "name": member.display_name,
            "avatar_url": str(member.display_avatar.url),
        },
        "already_verified": already_verified,
        "pending_role": pending_role,
        "discord_screening_pending": bool(getattr(member, "pending", False)),
        "account_age_seconds": account_age,
        "account_age_ok": account_age >= min_account_age_seconds,
        "min_account_age_seconds": min_account_age_seconds,
        "joined_for_seconds": joined_for,
        "join_delay_ok": joined_for >= 8,
        "locked_seconds": locked,
        "rules_published": bool(rules_record),
        "rules_accepted": bool(accepted_rules),
        "rules_text": str((rules_record or {}).get("rules_text") or ""),
        "verify_channel_id": int(conf["verify_channel_id"] or 0),
        "verified_role_id": str(verified.id),
    }, None


def _landing_channel(member: discord.Member):
    guild = member.guild
    candidates = []
    if guild.system_channel is not None:
        candidates.append(guild.system_channel)
    candidates.extend(guild.text_channels)
    seen: set[int] = set()
    for channel in candidates:
        if channel.id in seen:
            continue
        seen.add(channel.id)
        try:
            if channel.permissions_for(member).view_channel:
                return channel
        except Exception:
            continue
    return None


async def _send_success_dm(
    bot,
    member: discord.Member,
    guild: discord.Guild,
    channel,
) -> bool:
    destination = (
        f"https://discord.com/channels/{guild.id}/{channel.id}"
        if channel is not None
        else f"https://discord.com/channels/{guild.id}"
    )
    try:
        from cogs import language_runtime
        language = await language_runtime.get_language(bot, guild.id)
    except Exception:
        language = "fr"
    english = language == "en"

    top = discord.Embed(
        title=(
            f"Verification successful on {guild.name}"
            if english
            else f"Vérification réussie sur {guild.name}"
        ),
        colour=discord.Colour.green(),
    )
    body = discord.Embed(
        description=(
            "**Your Discord account has been verified successfully.**\n"
            "SentriX completed the security checks and unlocked your server access."
            if english
            else
            "**Ton compte Discord a été vérifié avec succès.**\n"
            "SentriX a terminé les contrôles de sécurité et débloqué ton accès au serveur."
        ),
        colour=discord.Colour.green(),
    )
    body.set_footer(
        text="SentriX • Web Verification" if english else "SentriX • Vérification web"
    )

    view = discord.ui.View(timeout=None)
    view.add_item(
        discord.ui.Button(
            label="Open server" if english else "Ouvrir le serveur",
            url=destination,
        )
    )
    try:
        await member.send(
            embeds=[top, body],
            view=view,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        return True
    except (discord.Forbidden, discord.HTTPException):
        return False


async def _complete_verification(
    bot,
    guild: discord.Guild,
    member: discord.Member,
    *,
    accept_rules: bool,
):
    MIN_JOIN_DELAY_SECONDS = 8

    cog = bot.get_cog("HoneypotVerification")
    conf = await cog.config(guild.id) if cog else None
    if cog is None or not conf:
        return None, _json_error("La vérification a été désactivée.", 409)

    unverified = guild.get_role(int(conf["unverified_role_id"] or 0))
    verified = guild.get_role(int(conf["verified_role_id"] or 0))
    if unverified is None or verified is None:
        return None, _json_error("Les rôles de vérification n'existent plus.", 409)

    if verified in member.roles and unverified not in member.roles:
        landing = _landing_channel(member)
        return {
            "already_verified": True,
            "dm_sent": False,
            "channel_id": str(landing.id) if landing else None,
        }, None

    if unverified not in member.roles:
        return None, _json_error(
            "Ton compte n'est plus marqué comme en attente de vérification.", 409
        )

    if bool(getattr(member, "pending", False)):
        return None, _json_error(
            "Accepte d'abord les règles natives de Discord pour ce serveur, puis relance la vérification.",
            409,
            code="discord_screening_pending",
        )

    account_age = max(
        0, int((discord.utils.utcnow() - member.created_at).total_seconds())
    )
    try:
        settings = await cog.settings(guild.id)
        min_account_age_seconds = max(
            0, int(settings.get("min_account_age_minutes", 30) or 0) * 60
        )
    except Exception:
        min_account_age_seconds = 30 * 60
    if account_age < min_account_age_seconds:
        remaining = max(60, min_account_age_seconds - account_age)
        return None, _json_error(
            f"Ton compte Discord est trop récent. Réessaie dans environ {max(1, remaining // 60)} minute(s).",
            429,
            code="account_too_new",
        )

    joined_for = 999999
    if member.joined_at is not None:
        joined_for = max(
            0, int((discord.utils.utcnow() - member.joined_at).total_seconds())
        )
    if joined_for < MIN_JOIN_DELAY_SECONDS:
        return None, _json_error(
            f"Attends encore {MIN_JOIN_DELAY_SECONDS - joined_for} seconde(s) avant de terminer la vérification.",
            429,
            code="join_delay",
        )

    locked = await _locked_seconds(bot, guild.id, member.id)
    if locked > 0:
        return None, _json_error(
            f"Trop de tentatives incorrectes. Réessaie dans environ {max(1, (locked + 59) // 60)} minute(s).",
            429,
            code="locked",
        )

    rules_record = await rules_flow.current_rules_record(bot, guild.id)
    accepted = await rules_flow.has_accepted_current_rules(bot, guild.id, member.id)
    if rules_record and not accepted:
        if not accept_rules:
            return None, _json_error(
                "Tu dois accepter la version actuelle du règlement avant de terminer.",
                409,
                code="rules_required",
            )
        version = await rules_flow.accept_current_rules(bot, guild.id, member.id)
        if version is None:
            return None, _json_error(
                "Le règlement a changé. Recharge la page et réessaie.", 409
            )

    # Dernière étape : le moteur adaptatif V5 est recomputé au moment exact de la
    # vérification web. Il ne peut plus attribuer le rôle tout seul en arrière-plan.
    try:
        security_score, security_threshold, security_passed = await _adaptive_security(
            cog, member
        )
    except Exception:
        logger.exception(
            "Adaptive security scan failed guild=%s user=%s", guild.id, member.id
        )
        return None, _json_error(
            "L'analyse de sécurité SentriX est momentanément indisponible. Réessaie.",
            503,
            code="security_scan_failed",
        )
    if not security_passed:
        event = getattr(cog, "_event", None)
        if callable(event):
            try:
                await event(guild.id, member.id, "web_review")
            except Exception:
                pass
        return None, _json_error(
            f"L'analyse de sécurité demande une revue staff ({security_score:.1f}/{security_threshold:.0f}). "
            "Ton accès reste protégé et aucun bannissement n'est appliqué.",
            403,
            code="security_review",
        )

    key = (guild.id, member.id)
    try:
        if verified not in member.roles:
            await member.add_roles(verified, reason="SentriX : vérification web réussie")
        if unverified in member.roles:
            await member.remove_roles(
                unverified, reason="SentriX : vérification web réussie"
            )
    except (discord.Forbidden, discord.HTTPException):
        return None, _json_error(
            "SentriX ne peut pas modifier tes rôles. Un administrateur doit vérifier la hiérarchie du bot.",
            503,
        )

    clear_pending = getattr(cog, "_clear_pending", None)
    if callable(clear_pending):
        await clear_pending(guild.id, member.id)
    else:
        await bot.db.execute(
            "DELETE FROM honeypot_pending_members WHERE guild_id=? AND user_id=?",
            (guild.id, member.id),
        )
    await bot.db.execute(
        "INSERT INTO honeypot_verified_members "
        "(guild_id,user_id,verified_at,method,account_age_seconds) VALUES (?,?,?,?,?) "
        "ON CONFLICT(guild_id,user_id) DO UPDATE SET "
        "verified_at=excluded.verified_at,method=excluded.method,"
        "account_age_seconds=excluded.account_age_seconds",
        (
            guild.id,
            member.id,
            int(time.time()),
            "web_oauth+captcha+math",
            account_age,
        ),
    )
    try:
        await bot.db.execute(
            "INSERT OR IGNORE INTO verified_users(guild_id,user_id,verified_at) "
            "VALUES(?,?,strftime('%s','now'))",
            (guild.id, member.id),
        )
    except Exception:
        logger.debug("verified_users compatibility write skipped", exc_info=True)

    await _clear_failures(bot, guild.id, member.id)
    event = getattr(cog, "_event", None)
    if callable(event):
        try:
            await event(guild.id, member.id, "verified_web")
        except Exception:
            logger.debug("Adaptive verification event skipped.", exc_info=True)

    landing = _landing_channel(member)
    dm_sent = await _send_success_dm(bot, member, guild, landing)

    try:
        from utils import log_service
        log_embed = discord.Embed(
            title="Membre vérifié — site SentriX",
            description=(
                f"{member.mention} ({member.id})\n"
                f"Compte âgé de : **{account_age // 86400} jour(s)**\n"
                f"Score sécurité : **{security_score:.1f}/{security_threshold:.0f}**\n"
                "Méthode : **OAuth Discord + règlement courant + CAPTCHA web + calcul + analyse adaptative**."
            ),
            colour=discord.Colour.green(),
        )
        await log_service.send_log(
            bot,
            guild,
            "security",
            log_embed,
            event_key=f"verification_web:{guild.id}:{member.id}:{int(time.time())}",
        )
    except Exception:
        logger.debug("Web verification log skipped.", exc_info=True)

    return {
        "already_verified": False,
        "dm_sent": dm_sent,
        "channel_id": str(landing.id) if landing else None,
        "security_score": round(security_score, 2),
        "security_threshold": security_threshold,
    }, None


COPY_FR = {
    "eyebrow": "SentriX Web Verification",
    "title": "Vérifie ton accès en toute sécurité.",
    "subtitle": (
        "Ton identité Discord, les règles du serveur et le CAPTCHA sont contrôlés "
        "sur cette page. Aucun challenge ne se fait dans le salon Discord."
    ),
    "loading": "Connexion sécurisée avec Discord…",
    "preparing": "Préparation du contrôle humain…",
    "start": "Commencer la vérification",
    "captchaTitle": "Vérification humaine",
    "captchaHint": "Recopie le code affiché puis réponds au calcul.",
    "captchaPlaceholder": "Code CAPTCHA",
    "mathPlaceholder": "Résultat du calcul",
    "rulesTitle": "Règlement du serveur",
    "rulesAccept": "J'ai lu et j'accepte la version actuelle du règlement.",
    "verify": "Me vérifier",
    "checking": "Vérification en cours…",
    "success": "Vérification réussie",
    "successText": (
        "Ton accès Discord a été débloqué. Un message privé SentriX vient de t'être envoyé."
    ),
    "redirect": "Retour vers Discord…",
    "retry": "Réessayer",
    "stages": [
        "Identité Discord",
        "Compte et serveur",
        "Règlement",
        "CAPTCHA",
        "Analyse de sécurité",
        "Attribution du rôle",
    ],
}

COPY_EN = {
    "eyebrow": "SentriX Web Verification",
    "title": "Verify your access securely.",
    "subtitle": (
        "Your Discord identity, server rules and CAPTCHA are checked on this page. "
        "No challenge happens inside the Discord channel."
    ),
    "loading": "Securely connecting with Discord…",
    "preparing": "Preparing the human check…",
    "start": "Start verification",
    "captchaTitle": "Human verification",
    "captchaHint": "Enter the code shown below and solve the quick math challenge.",
    "captchaPlaceholder": "CAPTCHA code",
    "mathPlaceholder": "Math answer",
    "rulesTitle": "Server rules",
    "rulesAccept": "I have read and accept the current server rules.",
    "verify": "Verify me",
    "checking": "Verification in progress…",
    "success": "Verification successful",
    "successText": (
        "Your Discord access has been unlocked. SentriX has sent you a direct message."
    ),
    "redirect": "Returning to Discord…",
    "retry": "Try again",
    "stages": [
        "Discord identity",
        "Account and server",
        "Server rules",
        "CAPTCHA",
        "Security analysis",
        "Role assignment",
    ],
}


PAGE = r"""<!doctype html>
<html lang="__LANG__">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#070918">
<title>SentriX — Verification</title>
<style>
:root{--bg:#070918;--panel:#11162d;--panel2:#171e3c;--line:#2a3767;--text:#f6f8ff;--muted:#9aa6c7;--blue:#5ea4ff;--green:#38d879;--danger:#ff667a}
*{box-sizing:border-box}
html{min-height:100%;margin:0;background:#070918;color-scheme:dark;overscroll-behavior-y:none}
body{min-height:100vh;min-height:100dvh;margin:0;background-color:#070918;background-image:radial-gradient(900px 600px at 50% -10%,rgba(74,112,255,.26),transparent 65%),linear-gradient(180deg,#070918,#0a0d20);color:var(--text);font:15px/1.5 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Inter,sans-serif;overflow-x:hidden;overscroll-behavior-y:none}
body{display:grid;place-items:center;padding:24px}.shell{width:min(760px,100%)}.brand{display:flex;align-items:center;gap:10px;margin:0 0 18px;color:#dfe8ff;font-weight:800}.dot{width:11px;height:11px;border-radius:50%;background:var(--blue);box-shadow:0 0 24px var(--blue)}
.card{position:relative;overflow:hidden;border:1px solid rgba(100,130,220,.24);background:linear-gradient(180deg,rgba(22,29,60,.95),rgba(13,18,41,.96));border-radius:24px;padding:30px;box-shadow:0 30px 80px rgba(0,0,0,.35)}
.card:before{content:"";position:absolute;inset:0 0 auto;height:3px;background:linear-gradient(90deg,transparent,var(--blue),transparent);opacity:.85}.eyebrow{font-size:12px;text-transform:uppercase;letter-spacing:.14em;color:#8fbbff;font-weight:800}
h1{font-size:clamp(30px,6vw,52px);line-height:1.02;margin:10px 0 14px;letter-spacing:-.04em}.sub{color:var(--muted);font-size:16px;max-width:640px}.server{display:inline-flex;margin-top:18px;padding:8px 12px;border:1px solid var(--line);border-radius:12px;background:#0b1026;color:#dce6ff;font-weight:700}
.stages{display:grid;gap:9px;margin:26px 0}.stage{display:flex;align-items:center;gap:12px;padding:12px 14px;border:1px solid rgba(100,130,220,.18);border-radius:14px;background:rgba(7,11,30,.5);color:#aab5d3;transition:.25s ease}.stage i{width:10px;height:10px;border-radius:50%;background:#394566;box-shadow:0 0 0 5px rgba(57,69,102,.12)}.stage.active{color:white;border-color:#4c71cf}.stage.active i{background:var(--blue);box-shadow:0 0 0 5px rgba(94,164,255,.14),0 0 18px rgba(94,164,255,.8)}.stage.done i{background:var(--green);box-shadow:0 0 0 5px rgba(56,216,121,.13)}
button{appearance:none;border:0;border-radius:13px;padding:13px 17px;font:inherit;font-weight:800;cursor:pointer;transition:.18s ease}.primary{background:linear-gradient(180deg,#58a1ff,#3878e9);color:white;box-shadow:0 10px 28px rgba(56,120,233,.25)}.primary:hover{transform:translateY(-1px);filter:brightness(1.07)}button:disabled{opacity:.55;cursor:not-allowed;transform:none}
.hidden{display:none!important}.challenge{margin-top:20px;padding:18px;border:1px solid var(--line);border-radius:16px;background:#0a1027}.challenge img{display:block;width:100%;max-width:380px;aspect-ratio:380/128;object-fit:cover;background:#080d1f;color:transparent;border-radius:12px;border:1px solid #263768;margin:14px 0}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}@media(max-width:600px){.grid{grid-template-columns:1fr}.card{padding:22px}}input{width:100%;border:1px solid #2a3767;background:#080d20;color:white;padding:13px 14px;border-radius:12px;outline:none;font:inherit}input:focus{border-color:#5ea4ff;box-shadow:0 0 0 3px rgba(94,164,255,.12)}
.rules{max-height:210px;overflow:auto;white-space:pre-wrap;margin:14px 0;padding:14px;border:1px solid #28355e;border-radius:12px;background:#080d20;color:#cbd6f5}.check{display:flex;gap:10px;align-items:flex-start;color:#cbd6f5}.check input{width:auto;margin-top:4px}
.error{margin-top:14px;color:#ff9baa;font-weight:650}.success{display:grid;place-items:center;text-align:center;padding:20px 0}.tick{width:76px;height:76px;border-radius:50%;display:grid;place-items:center;background:rgba(56,216,121,.12);border:2px solid var(--green);font-size:38px;animation:pop .4s ease}.spinner{width:30px;height:30px;border-radius:50%;border:3px solid #25345d;border-top-color:var(--blue);animation:spin .7s linear infinite;margin:20px 0}@keyframes spin{to{transform:rotate(360deg)}}@keyframes pop{0%{transform:scale(.65);opacity:0}100%{transform:scale(1);opacity:1}}
.small{font-size:13px;color:var(--muted);margin-top:8px}
</style>
</head>
<body>
<div class="shell">
  <div class="brand"><span class="dot"></span>SentriX</div>
  <main class="card">
    <div id="main">
      <div class="eyebrow" id="eyebrow"></div>
      <h1 id="title"></h1>
      <div class="sub" id="subtitle"></div>
      <div class="server">__GUILD_NAME__</div>
      <div class="stages" id="stages"></div>
      <div id="loading"><div class="spinner"></div><div id="loadingText"></div></div>
      <button id="start" class="primary hidden"></button>

      <section id="challenge" class="challenge hidden">
        <b id="captchaTitle"></b>
        <div class="small" id="captchaHint"></div>
        <img id="captchaImage" alt="CAPTCHA">
        <div class="grid">
          <input id="captcha" autocomplete="off" autocapitalize="characters" autocorrect="off" spellcheck="false" maxlength="6">
          <input id="math" inputmode="numeric" autocomplete="off">
        </div>
        <div id="rulesWrap" class="hidden">
          <h3 id="rulesTitle"></h3>
          <div id="rulesText" class="rules"></div>
          <label class="check"><input type="checkbox" id="acceptRules"><span id="rulesAccept"></span></label>
        </div>
        <button id="verify" class="primary" style="margin-top:16px"></button>
      </section>
      <div id="error" class="error hidden"></div>
    </div>

    <section id="success" class="success hidden">
      <div class="tick">✓</div>
      <h2 id="successTitle"></h2>
      <div class="sub" id="successText"></div>
      <div class="small" id="redirectText"></div>
    </section>
  </main>
</div>
<script>
const GUILD_ID=__GUILD_ID__;
const AUTHENTICATED=__AUTHENTICATED__;
const C=__COPY__;
let state=null,challengeToken=null,verifyInFlight=false,autoVerifyTimer=null;
const CAPTCHA_LENGTH=6;
const $=id=>document.getElementById(id);
$("eyebrow").textContent=C.eyebrow;$("title").textContent=C.title;$("subtitle").textContent=C.subtitle;
$("loadingText").textContent=C.loading;$("start").textContent=C.start;$("captchaTitle").textContent=C.captchaTitle;
$("captchaHint").textContent=C.captchaHint;$("captcha").placeholder=C.captchaPlaceholder;$("math").placeholder=C.mathPlaceholder;
$("rulesTitle").textContent=C.rulesTitle;$("rulesAccept").textContent=C.rulesAccept;$("verify").textContent=C.verify;
$("successTitle").textContent=C.success;$("successText").textContent=C.successText;$("redirectText").textContent=C.redirect;
C.stages.forEach((name,i)=>{const d=document.createElement("div");d.className="stage";d.dataset.i=i;const dot=document.createElement("i");const s=document.createElement("span");s.textContent=name;d.append(dot,s);$("stages").appendChild(d)});
function mark(i,mode){const el=document.querySelector('.stage[data-i="'+i+'"]');if(el)el.className="stage "+mode}
function fail(message){$("loading").classList.add("hidden");$("error").textContent=message;$("error").classList.remove("hidden");$("start").classList.remove("hidden");$("start").textContent=C.retry}
async function api(path,options={}){const r=await fetch(path,{credentials:"same-origin",headers:{"Content-Type":"application/json",...(options.headers||{})},...options});const data=await r.json().catch(()=>({}));if(!r.ok)throw new Error(data.error||("HTTP "+r.status));return data}
function rulesReady(){return $("rulesWrap").classList.contains("hidden")||$("acceptRules").checked}
function maybeAutoVerify(){
  clearTimeout(autoVerifyTimer);
  const captcha=$("captcha").value.trim().toUpperCase();
  const math=$("math").value.trim();
  if(verifyInFlight||captcha.length!==CAPTCHA_LENGTH||!/^-?\d+$/.test(math)||!rulesReady())return;
  autoVerifyTimer=setTimeout(()=>{if(!verifyInFlight&&rulesReady())$("verify").click()},900);
}
$("captcha").addEventListener("input",()=>{$("captcha").value=$("captcha").value.toUpperCase().replace(/[^A-Z0-9]/g,"").slice(0,CAPTCHA_LENGTH);maybeAutoVerify()});
$("math").addEventListener("input",maybeAutoVerify);
$("acceptRules").addEventListener("change",maybeAutoVerify);
async function boot(){
  if(!AUTHENTICATED){setTimeout(()=>location.href="/login?verify_guild="+GUILD_ID,700);return}
  try{
    state=await api("/api/verify/"+GUILD_ID+"/state");
    $("loading").classList.add("hidden");
    mark(0,"done");mark(1,state.account_age_ok&&!state.discord_screening_pending?"done":"active");
    if(state.rules_published&&state.rules_accepted)mark(2,"done");
    if(state.already_verified){showSuccess(state.channel_id);return}
    $("start").classList.remove("hidden");
  }catch(e){fail(e.message)}
}
$("start").onclick=async()=>{
  $("error").classList.add("hidden");$("start").disabled=true;$("start").classList.add("hidden");
  $("loadingText").textContent=C.preparing;$("loading").classList.remove("hidden");mark(0,"done");mark(1,"active");
  try{
    const data=await api("/api/verify/"+GUILD_ID+"/challenge",{method:"POST",body:"{}"});
    challengeToken=data.challenge_token;
    $("captcha").value="";$("math").value="";$("acceptRules").checked=false;
    const captchaImage=$("captchaImage");captchaImage.src=data.captcha_image;$("math").placeholder=data.math_question;
    try{if(captchaImage.decode)await captchaImage.decode()}catch(e){}
    if(data.rules_published&&!data.rules_accepted){$("rulesText").textContent=data.rules_text||"";$("rulesWrap").classList.remove("hidden")}else{$("rulesWrap").classList.add("hidden")}
    $("loading").classList.add("hidden");$("challenge").classList.remove("hidden");mark(1,"done");mark(2,data.rules_published&&!data.rules_accepted?"active":"done");mark(3,"active");
    $("captcha").focus();
  }catch(e){fail(e.message)}finally{$("start").disabled=false;$("start").textContent=C.start}
};
$("verify").onclick=async()=>{
  if(verifyInFlight)return;
  verifyInFlight=true;clearTimeout(autoVerifyTimer);
  $("error").classList.add("hidden");$("verify").disabled=true;$("verify").textContent=C.checking;
  $("challenge").classList.add("hidden");$("loadingText").textContent=C.checking;$("loading").classList.remove("hidden");
  const stages=[0,1,2,3,4,5];let idx=0;const timer=setInterval(()=>{if(idx<stages.length){mark(stages[idx],"active");idx++}},280);
  try{
    const data=await api("/api/verify/"+GUILD_ID+"/complete",{method:"POST",body:JSON.stringify({challenge_token:challengeToken,captcha:$("captcha").value,math_answer:$("math").value,accept_rules:$("acceptRules").checked})});
    clearInterval(timer);stages.forEach(i=>mark(i,"done"));showSuccess(data.channel_id);
  }catch(e){
    clearInterval(timer);$("loading").classList.add("hidden");fail(e.message);
    $("challenge").classList.remove("hidden");$("start").classList.add("hidden");
  }
  finally{verifyInFlight=false;$("verify").disabled=false;$("verify").textContent=C.verify}
};
function showSuccess(channelId){
  $("main").classList.add("hidden");$("success").classList.remove("hidden");
  const webUrl=channelId?("https://discord.com/channels/"+GUILD_ID+"/"+channelId):("https://discord.com/channels/"+GUILD_ID);
  const appUrl=channelId?("discord://-/channels/"+GUILD_ID+"/"+channelId):("discord://-/channels/"+GUILD_ID);
  setTimeout(()=>{try{location.href=appUrl}catch(e){}},850);
  setTimeout(()=>{try{window.close()}catch(e){}},2100);
  setTimeout(()=>{if(document.visibilityState==="visible")location.href=webUrl},3000);
}
boot();
</script>
</body>
</html>"""


def _page_copy(language: str) -> dict[str, Any]:
    return COPY_EN if language == "en" else COPY_FR


async def handle_page(request: web.Request) -> web.Response:
    try:
        guild_id = int(request.match_info["guild_id"])
    except (TypeError, ValueError):
        raise web.HTTPNotFound()

    bot = request.app["bot"]
    guild = bot.get_guild(guild_id) if bot.is_ready() else None
    guild_name = guild.name if guild else "Discord server"
    language = "fr"
    try:
        from cogs import language_runtime
        language = await language_runtime.get_language(bot, guild_id)
    except Exception:
        pass

    authenticated = bool(
        parse_session_token(
            request.cookies.get(SESSION_COOKIE, ""),
            guild_id=guild_id,
        )
    )
    page = (
        PAGE.replace("__LANG__", "en" if language == "en" else "fr")
        .replace("__GUILD_ID__", str(guild_id))
        .replace("__AUTHENTICATED__", "true" if authenticated else "false")
        .replace("__GUILD_NAME__", html.escape(guild_name))
        .replace("__COPY__", json.dumps(_page_copy(language), ensure_ascii=False))
    )
    response = web.Response(text=page, content_type="text/html")
    response.headers["Cache-Control"] = "private, no-store"
    return response


async def handle_state(request: web.Request) -> web.Response:
    try:
        guild_id = int(request.match_info["guild_id"])
    except (TypeError, ValueError):
        return _json_error("Identifiant de serveur invalide.", 400)
    guild, member, error = await _resolve_session(request, guild_id)
    if error:
        return error
    payload, error = await _status_payload(request.app["bot"], guild, member)
    return error or web.json_response(payload)


async def handle_challenge(request: web.Request) -> web.Response:
    try:
        guild_id = int(request.match_info["guild_id"])
    except (TypeError, ValueError):
        return _json_error("Identifiant de serveur invalide.", 400)
    guild, member, error = await _resolve_session(request, guild_id)
    if error:
        return error

    payload, error = await _status_payload(request.app["bot"], guild, member)
    if error:
        return error
    if payload["already_verified"]:
        return web.json_response({"ok": True, "already_verified": True})
    if not payload["pending_role"]:
        return _json_error("Ton compte n'est pas en attente de vérification.", 409)
    if payload["locked_seconds"] > 0:
        return _json_error(
            "Trop de tentatives incorrectes. Réessaie plus tard.",
            429,
        )
    if not payload["account_age_ok"]:
        return _json_error("Ton compte Discord est encore trop récent.", 429)
    if not payload["join_delay_ok"]:
        return _json_error(
            "Attends quelques secondes avant de lancer la vérification.",
            429,
        )
    if payload["discord_screening_pending"]:
        return _json_error(
            "Accepte d'abord les règles natives Discord du serveur, puis recharge cette page.",
            409,
            code="discord_screening_pending",
        )

    rng = secrets.SystemRandom()
    code = "".join(rng.choice(CAPTCHA_ALPHABET) for _ in range(6))
    left, right = rng.randrange(3, 17), rng.randrange(2, 12)
    answer = str(left + right)
    token = issue_challenge(guild.id, member.id, code, answer)
    return web.json_response({
        "ok": True,
        "challenge_token": token,
        "captcha_image": _captcha_png(code),
        "math_question": f"{left} + {right} = ?",
        "expires_in": CHALLENGE_TTL,
        "rules_published": payload["rules_published"],
        "rules_accepted": payload["rules_accepted"],
        "rules_text": payload["rules_text"],
    })


async def handle_complete(request: web.Request) -> web.Response:
    try:
        guild_id = int(request.match_info["guild_id"])
    except (TypeError, ValueError):
        return _json_error("Identifiant de serveur invalide.", 400)
    guild, member, error = await _resolve_session(request, guild_id)
    if error:
        return error
    try:
        payload = await request.json()
    except Exception:
        payload = {}

    token = str((payload or {}).get("challenge_token") or "")
    captcha = str((payload or {}).get("captcha") or "")
    math_answer = str((payload or {}).get("math_answer") or "")
    accept_rules = bool((payload or {}).get("accept_rules"))

    bot = request.app["bot"]
    cog = bot.get_cog("HoneypotVerification")
    if cog is None:
        return _json_error("Le système de vérification est indisponible.", 503)

    if not validate_challenge(
        token,
        guild_id=guild.id,
        user_id=member.id,
        captcha=captcha,
        math_answer=math_answer,
    ):
        locked = await _record_failure(bot, guild.id, member.id)
        event = getattr(cog, "_event", None)
        if callable(event):
            try:
                await event(guild.id, member.id, "web_captcha_failed")
            except Exception:
                pass
        message = "CAPTCHA ou calcul incorrect. Un nouveau challenge sera nécessaire."
        if locked > 0:
            message += f" Trop d'échecs : réessaie dans environ {max(1, (locked + 59) // 60)} minute(s)."
        return _json_error(message, 429 if locked else 400, code="challenge_failed")

    result, error = await _complete_verification(
        bot,
        guild,
        member,
        accept_rules=accept_rules,
    )
    if error:
        return error
    return web.json_response({"ok": True, **result})


def register(app: web.Application, dashboard) -> None:
    del dashboard
    app.router.add_get("/verify/{guild_id}", handle_page)
    app.router.add_get("/api/verify/{guild_id}/state", handle_state)
    app.router.add_post("/api/verify/{guild_id}/challenge", handle_challenge)
    app.router.add_post("/api/verify/{guild_id}/complete", handle_complete)


__all__ = [
    "PENDING_COOKIE",
    "SESSION_COOKIE",
    "make_pending_token",
    "parse_pending_token",
    "make_session_token",
    "parse_session_token",
    "verification_url",
    "register",
]
