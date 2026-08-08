"""Protection anti-double-compte des giveaways SentriX.

Discord ne transmet jamais l'adresse IP d'un membre à un bot. Pour obtenir un signal réseau
sans stocker l'adresse brute, la participation passe par une mini page web SentriX :
- le bouton Discord envoie un lien signé et éphémère (10 minutes) ;
- la page demande une confirmation explicite ;
- le serveur calcule une empreinte HMAC de l'adresse réseau, spécifique au giveaway ;
- une même empreinte réseau ne peut valider qu'un seul compte pour ce giveaway ;
- l'adresse IP brute n'est jamais écrite en base par ce module.

Cette protection reste un signal anti-alt, pas une preuve d'identité : un VPN ou un autre
réseau peut changer l'adresse visible, tandis que deux personnes légitimes sur le même Wi-Fi
peuvent partager la même adresse publique.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import html
import ipaddress
import json
import logging
import secrets
import sqlite3
import time
from urllib.parse import quote

import discord
from aiohttp import web
from discord.ext import commands

import config

logger = logging.getLogger("bot.giveaway-antialt")

_TOKEN_TTL_SECONDS = 10 * 60
_INSTALLED = False


def _secret() -> bytes:
    # Clé séparée dérivée du token : elle n'est jamais affichée ni stockée en base.
    # Un changement du token invalide seulement les liens de vérification encore ouverts.
    return hashlib.sha256(
        ("sentrix-giveaway-antialt-v1:" + str(config.DISCORD_TOKEN)).encode("utf-8")
    ).digest()


def _b64_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def make_verification_token(giveaway_id: int, guild_id: int, user_id: int) -> str:
    payload = {
        "g": int(giveaway_id),
        "s": int(guild_id),
        "u": int(user_id),
        "e": int(time.time()) + _TOKEN_TTL_SECONDS,
        "n": secrets.token_urlsafe(8),
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    encoded = _b64_encode(raw)
    signature = _b64_encode(hmac.new(_secret(), encoded.encode("ascii"), hashlib.sha256).digest())
    return f"{encoded}.{signature}"


def parse_verification_token(token: str) -> dict | None:
    try:
        if not token or len(token) > 1000 or "." not in token:
            return None
        encoded, supplied_signature = token.split(".", 1)
        expected_signature = _b64_encode(
            hmac.new(_secret(), encoded.encode("ascii"), hashlib.sha256).digest()
        )
        if not hmac.compare_digest(supplied_signature, expected_signature):
            return None
        payload = json.loads(_b64_decode(encoded).decode("utf-8"))
        giveaway_id = int(payload["g"])
        guild_id = int(payload["s"])
        user_id = int(payload["u"])
        expires_at = int(payload["e"])
        if giveaway_id <= 0 or guild_id <= 0 or user_id <= 0:
            return None
        now_ts = int(time.time())
        if expires_at < now_ts or expires_at > now_ts + _TOKEN_TTL_SECONDS + 60:
            return None
        return {
            "giveaway_id": giveaway_id,
            "guild_id": guild_id,
            "user_id": user_id,
            "expires_at": expires_at,
        }
    except (ValueError, TypeError, KeyError, json.JSONDecodeError, UnicodeDecodeError):
        return None


async def _ensure_table(bot: commands.Bot) -> None:
    await bot.db.execute(
        """
        CREATE TABLE IF NOT EXISTS giveaway_network_verifications (
            giveaway_id INTEGER NOT NULL,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            network_hash TEXT NOT NULL,
            verified_at INTEGER NOT NULL,
            PRIMARY KEY (giveaway_id, user_id),
            UNIQUE (giveaway_id, network_hash)
        )
        """
    )
    await bot.db.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_giveaway_network_guild
        ON giveaway_network_verifications (guild_id, giveaway_id)
        """
    )


async def _eligibility_error(bot: commands.Bot, giveaway, member: discord.Member) -> str | None:
    if member.bot:
        return "Les bots ne peuvent pas participer aux giveaways."

    blacklisted = await bot.db.fetchone(
        "SELECT 1 FROM giveaway_blacklist WHERE guild_id = ? AND user_id = ?",
        (member.guild.id, member.id),
    )
    if blacklisted:
        return "Vous n'êtes pas autorisé à participer aux giveaways."

    excluded_role_id = giveaway["excluded_role_id"]
    if excluded_role_id and any(role.id == excluded_role_id for role in member.roles):
        return "Votre rôle vous empêche de participer à ce giveaway."

    required_role_id = giveaway["required_role_id"]
    if required_role_id and not any(role.id == required_role_id for role in member.roles):
        role = member.guild.get_role(required_role_id)
        return (
            f"Il faut avoir le rôle {role.mention} pour participer."
            if role
            else "Le rôle requis pour ce giveaway n'existe plus."
        )

    required_level = giveaway["required_level"]
    if required_level:
        level_row = await bot.db.get_level(member.guild.id, member.id)
        level = int(level_row["level"] if level_row else 0)
        if level < int(required_level):
            return f"Il faut être au moins niveau {required_level} pour participer (vous êtes niveau {level})."

    return None


def _normalise_ip(value: str | None) -> str | None:
    if not value:
        return None
    raw = value.strip().strip('"')
    if raw.lower().startswith("for="):
        raw = raw[4:].strip().strip('"')
    if raw.startswith("[") and "]" in raw:
        raw = raw[1 : raw.index("]")]
    elif raw.count(":") == 1 and "." in raw:
        host, maybe_port = raw.rsplit(":", 1)
        if maybe_port.isdigit():
            raw = host
    try:
        return ipaddress.ip_address(raw).compressed
    except ValueError:
        return None


def _client_ip(request: web.Request) -> str | None:
    # Railway transmet normalement X-Forwarded-For. On parcourt la chaîne depuis la droite
    # et on préfère la dernière adresse publique : cela évite de faire confiance à un préfixe
    # X-Forwarded-For éventuellement fourni par le client lui-même.
    forwarded = request.headers.get("X-Forwarded-For", "")
    valid: list[str] = []
    for chunk in forwarded.split(","):
        normalised = _normalise_ip(chunk)
        if normalised:
            valid.append(normalised)

    for candidate in reversed(valid):
        try:
            if ipaddress.ip_address(candidate).is_global:
                return candidate
        except ValueError:
            continue
    if valid:
        return valid[-1]

    real_ip = _normalise_ip(request.headers.get("X-Real-IP"))
    if real_ip:
        return real_ip
    return _normalise_ip(request.remote)


def _network_fingerprint(giveaway_id: int, ip: str) -> str:
    # L'ID du giveaway fait partie du HMAC : deux giveaways ne peuvent pas être reliés
    # entre eux en comparant les empreintes enregistrées.
    material = f"giveaway:{int(giveaway_id)}:network:{ip}".encode("utf-8")
    return hmac.new(_secret(), material, hashlib.sha256).hexdigest()


def _page(title: str, message: str, *, ok: bool = False, form_token: str | None = None) -> web.Response:
    safe_title = html.escape(title)
    safe_message = html.escape(message)
    accent = "#57F287" if ok else "#8c7cff"
    form = ""
    if form_token:
        safe_token = html.escape(form_token, quote=True)
        form = f"""
        <form method="post" action="/giveaway/verify">
          <input type="hidden" name="token" value="{safe_token}">
          <button type="submit">🔐 Vérifier ma participation</button>
        </form>
        """
    body = f"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="theme-color" content="#090b12">
<title>SentriX — Vérification giveaway</title>
<style>
*{{box-sizing:border-box}}
body{{margin:0;min-height:100vh;display:grid;place-items:center;background:#090b12;color:#f3f5ff;
font:15px system-ui,-apple-system,"Segoe UI",sans-serif;padding:20px}}
main{{width:min(560px,100%);background:#111522;border:1px solid #29304a;border-radius:20px;
padding:30px;box-shadow:0 24px 70px #0008}}
.badge{{display:inline-block;padding:6px 10px;border-radius:999px;background:{accent}18;
border:1px solid {accent}55;color:{accent};font-weight:800;font-size:12px}}
h1{{font-size:24px;margin:16px 0 10px}}p{{color:#b3bad0;line-height:1.6}}
.notice{{margin-top:18px;padding:13px 14px;border-radius:12px;background:#0b0f19;border:1px solid #252c42;
font-size:13px;color:#9fa8c1}}
button{{width:100%;margin-top:20px;border:0;border-radius:12px;padding:13px 16px;background:#6f5cff;
color:white;font:inherit;font-weight:800;cursor:pointer}}
button:hover{{filter:brightness(1.08)}}
</style>
</head>
<body><main>
<span class="badge">SENTRIX • ANTI DOUBLE COMPTE</span>
<h1>{safe_title}</h1>
<p>{safe_message}</p>
{form}
<div class="notice">Confidentialité : SentriX ne conserve pas votre adresse IP brute. Une empreinte
cryptographique différente pour chaque giveaway est utilisée uniquement pour empêcher plusieurs
comptes de valider la même participation depuis la même connexion.</div>
</main></body></html>"""
    response = web.Response(text=body, content_type="text/html")
    response.headers["Cache-Control"] = "no-store"
    return response


async def _get_member(bot: commands.Bot, guild: discord.Guild, user_id: int) -> discord.Member | None:
    member = guild.get_member(user_id)
    if member is not None:
        return member
    try:
        return await guild.fetch_member(user_id)
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        return None


async def _load_target(bot: commands.Bot, payload: dict):
    giveaway = await bot.db.fetchone(
        "SELECT * FROM giveaways WHERE id = ? AND guild_id = ?",
        (payload["giveaway_id"], payload["guild_id"]),
    )
    if not giveaway or giveaway["status"] != "actif" or int(giveaway["end_at"]) <= int(time.time()):
        return None, None, "Ce giveaway est terminé ou n'existe plus."

    guild = bot.get_guild(payload["guild_id"])
    if guild is None:
        return None, None, "Le serveur du giveaway est indisponible."

    member = await _get_member(bot, guild, payload["user_id"])
    if member is None:
        return None, None, "Vous devez encore être membre du serveur pour participer."

    reason = await _eligibility_error(bot, giveaway, member)
    if reason:
        return None, None, reason
    return giveaway, member, None


async def _verify_get(request: web.Request) -> web.Response:
    token = request.query.get("token", "")
    payload = parse_verification_token(token)
    if payload is None:
        return _page("Lien invalide ou expiré", "Retournez sur Discord et recliquez sur « Participer ».")

    bot = request.app["bot"]
    giveaway, _member, error = await _load_target(bot, payload)
    if error:
        return _page("Participation impossible", error)

    prize = str(giveaway["prize"] or "ce giveaway")
    return _page(
        "Dernière étape",
        f"Confirmez votre participation pour « {prize} ». Une seule participation est autorisée par connexion réseau.",
        form_token=token,
    )


async def _verify_post(request: web.Request) -> web.Response:
    try:
        form = await request.post()
    except Exception:
        return _page("Vérification impossible", "La demande reçue n'est pas valide.")

    token = str(form.get("token") or "")
    payload = parse_verification_token(token)
    if payload is None:
        return _page("Lien invalide ou expiré", "Retournez sur Discord et recliquez sur « Participer ».")

    bot = request.app["bot"]
    giveaway, member, error = await _load_target(bot, payload)
    if error:
        return _page("Participation impossible", error)

    ip = _client_ip(request)
    if not ip:
        return _page(
            "Vérification réseau impossible",
            "SentriX n'a pas pu vérifier votre connexion. Réessayez depuis Discord ou contactez le staff.",
        )

    await _ensure_table(bot)
    giveaway_id = int(giveaway["id"])
    user_id = int(member.id)
    network_hash = _network_fingerprint(giveaway_id, ip)

    already = await bot.db.fetchone(
        "SELECT user_id FROM giveaway_network_verifications WHERE giveaway_id = ? AND network_hash = ?",
        (giveaway_id, network_hash),
    )
    if already and int(already["user_id"]) != user_id:
        logger.warning(
            "Giveaway anti-alt : deuxième compte refusé sur la même empreinte réseau "
            "(giveaway=%s, guild=%s, user=%s).",
            giveaway_id,
            member.guild.id,
            user_id,
        )
        return _page(
            "Participation refusée",
            "Cette connexion a déjà servi à valider un compte pour ce giveaway. "
            "Les doubles comptes sont interdits. Si plusieurs personnes de votre foyer partagent le même Wi-Fi, contactez le staff.",
        )

    try:
        await bot.db.execute(
            """
            INSERT INTO giveaway_network_verifications
                (giveaway_id, guild_id, user_id, network_hash, verified_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(giveaway_id, user_id) DO UPDATE SET
                network_hash = excluded.network_hash,
                verified_at = excluded.verified_at
            """,
            (giveaway_id, member.guild.id, user_id, network_hash, int(time.time())),
        )
    except sqlite3.IntegrityError:
        # Course entre deux validations de comptes différents sur la même connexion :
        # la contrainte UNIQUE tranche atomiquement en base.
        return _page(
            "Participation refusée",
            "Cette connexion vient déjà d'être utilisée pour un autre compte sur ce giveaway.",
        )

    await bot.db.execute(
        "INSERT OR IGNORE INTO giveaway_entries (giveaway_id, user_id) VALUES (?, ?)",
        (giveaway_id, user_id),
    )

    logger.info(
        "Giveaway anti-alt : participation réseau validée (giveaway=%s, guild=%s, user=%s).",
        giveaway_id,
        member.guild.id,
        user_id,
    )
    return _page(
        "Participation validée 🎉",
        "Votre compte est maintenant inscrit au giveaway. Vous pouvez fermer cette page et revenir sur Discord.",
        ok=True,
    )


async def install(bot: commands.Bot) -> None:
    """Installe la vérification sur le bouton giveaway et ajoute les routes web."""
    global _INSTALLED
    if _INSTALLED:
        return

    await _ensure_table(bot)

    from . import events
    from web import dashboard

    async def enter_giveaway_with_antialt(self, interaction: discord.Interaction):
        if interaction.guild is None or interaction.message is None:
            return await interaction.response.send_message(
                "Cette vérification doit être lancée depuis le giveaway dans un serveur.",
                ephemeral=True,
            )

        giveaway = await self.bot.db.fetchone(
            "SELECT * FROM giveaways WHERE message_id = ? AND status = 'actif'",
            (interaction.message.id,),
        )
        if not giveaway or int(giveaway["end_at"]) <= int(time.time()):
            return await interaction.response.send_message("Ce giveaway n'est plus actif.", ephemeral=True)

        member = interaction.user
        if not isinstance(member, discord.Member):
            return await interaction.response.send_message(
                "Impossible de vérifier votre profil sur ce serveur.", ephemeral=True
            )

        # Un deuxième clic retire toujours la participation, même si le membre a depuis
        # perdu un rôle requis : il ne reste jamais « bloqué » dans le giveaway.
        existing = await self.bot.db.fetchone(
            "SELECT 1 FROM giveaway_entries WHERE giveaway_id = ? AND user_id = ?",
            (giveaway["id"], member.id),
        )
        if existing:
            await self.bot.db.execute(
                "DELETE FROM giveaway_entries WHERE giveaway_id = ? AND user_id = ?",
                (giveaway["id"], member.id),
            )
            await self.bot.db.execute(
                "DELETE FROM giveaway_network_verifications WHERE giveaway_id = ? AND user_id = ?",
                (giveaway["id"], member.id),
            )
            return await interaction.response.send_message(
                "○ Vous ne participez plus à ce giveaway.", ephemeral=True
            )

        reason = await _eligibility_error(self.bot, giveaway, member)
        if reason:
            return await interaction.response.send_message(f"🚫 {reason}", ephemeral=True)

        token = make_verification_token(giveaway["id"], interaction.guild.id, member.id)
        url = f"{config.DASHBOARD_PUBLIC_URL.rstrip('/')}/giveaway/verify?token={quote(token, safe='')}"
        view = discord.ui.View(timeout=600)
        view.add_item(
            discord.ui.Button(
                label="🔐 Vérifier et participer",
                style=discord.ButtonStyle.link,
                url=url,
            )
        )

        await interaction.response.send_message(
            "🛡️ **Vérification anti-double-compte**\n"
            "Pour participer, confirmez votre connexion avec le bouton ci-dessous. "
            "**Une seule participation est autorisée par connexion réseau pour ce giveaway.**\n\n"
            "SentriX ne stocke pas votre adresse IP brute : uniquement une empreinte cryptographique "
            "spécifique à ce giveaway. Le lien expire dans **10 minutes**.",
            view=view,
            ephemeral=True,
        )

    events.Events.enter_giveaway = enter_giveaway_with_antialt

    original_build_app = dashboard.build_app

    def build_app_with_giveaway_verification(web_bot) -> web.Application:
        app = original_build_app(web_bot)
        app.router.add_get("/giveaway/verify", _verify_get)
        app.router.add_post("/giveaway/verify", _verify_post)
        return app

    dashboard.build_app = build_app_with_giveaway_verification
    _INSTALLED = True
    logger.info("Protection anti-double-compte des giveaways activée.")
