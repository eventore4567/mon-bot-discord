"""SentriX V112 — intégrations avancées du centre d'opérations V111.

Aucune nouvelle racine slash : les fonctions sont ajoutées comme sous-commandes du hub
préfixe-only +manage. Cette couche ajoute previews, corrections groupées, explication de
sanctions, diagnostic précis de permissions, AutoMod contextuel et watchdog runtime.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import discord
from discord.ext import commands

from utils import embeds
from utils import sentrix_panels as panels
from utils.moderation_dataset import ModerationMatch, normalize_message

logger = logging.getLogger("bot.ops-v112")
_CONTEXT_MARKERS = (
    "ça veut dire", "ca veut dire", "signifie", "définition", "definition",
    "exemple", "citation", "je cite", "le mot", "la phrase", "comment dire",
    "comment écrire", "comment ecrire", "traduction", "translate", "quote",
)
_CRITICAL_COGS = ("Automod", "Security", "Configuration")


def should_downgrade_dataset_match(text: str, kind: str) -> bool:
    """Réduit seulement la SANCTION des détections ambiguës ; ne les ignore jamais.

    Les phrases/groupes précis restent inchangés. Un mot isolé utilisé dans un contexte
    manifestement explicatif/cité est supprimé mais n'entraîne plus automatiquement un
    timeout de 10 minutes. Cela réduit les faux positifs sans transformer le filtre en
    passoire.
    """
    if kind != "mot":
        return False
    raw = str(text or "").casefold()
    normalized = normalize_message(text)
    tokens = normalized.split()
    if not tokens:
        return False
    quoted = any(marker in raw for marker in _CONTEXT_MARKERS)
    code_like = "```" in raw or ("`" in raw and len(tokens) >= 4)
    explanatory = quoted or code_like
    return explanatory and len(tokens) >= 3


async def build_preview(ops, guild: discord.Guild, kind: str) -> tuple[str, list[tuple[str, str]]]:
    kind = str(kind or "").casefold().replace("_", "-")
    conf = await ops.bot.db.get_guild_config(guild.id)
    data = dict(conf) if conf else {}

    def channel_value(key: str) -> str:
        cid = int(data.get(key) or 0)
        ch = guild.get_channel(cid) if cid else None
        return ch.mention if ch else "Non configuré"

    def role_value(*keys: str) -> str:
        rid = 0
        for key in keys:
            if data.get(key):
                rid = int(data[key])
                break
        role = guild.get_role(rid) if rid else None
        return role.mention if role else "Non configuré"

    if kind == "welcome":
        return "Aperçu bienvenue", [
            ("Salon", channel_value("welcome_channel")),
            ("Message", str(data.get("welcome_message") or "Message par défaut")),
            ("Rôle automatique", role_value("autorole")),
        ]
    if kind == "verification":
        return "Aperçu vérification", [
            ("Salon", channel_value("verification_channel")),
            ("Rôle vérifié", role_value("verification_role", "verify_role")),
            ("CAPTCHA", "Activé" if int(data.get("verify_captcha_enabled", 1) or 0) else "Désactivé"),
            ("Tentatives max", str(data.get("verify_captcha_max_attempts") or 3)),
        ]
    if kind == "giveaway":
        return "Aperçu giveaway", [("Salon par défaut", channel_value("giveaway_channel")), ("Publication", "Aucune publication : preview uniquement")]
    if kind == "roles":
        return "Aperçu rôles", [
            ("Rôle staff", role_value("mod_role")),
            ("Autorôle", role_value("autorole")),
            ("Rôle avertissement", role_value("warn_role")),
        ]
    if kind == "tickets":
        try:
            row = await ops.bot.db.fetchone("SELECT COUNT(*) AS n FROM ticket_panels_v2 WHERE guild_id = ?", (guild.id,))
            count = int(row["n"] if row else 0)
        except Exception:
            count = 0
        return "Aperçu tickets", [("Panels configurés", str(count)), ("Logs de repli", channel_value("ticket_log_channel")), ("Publication", "Aucun salon créé : preview uniquement")]
    if kind == "embed":
        return "Aperçu embed", [("Couleur", "Thème SentriX actuel"), ("Mentions", "Désactivées par défaut"), ("Publication", "Aucun message envoyé : preview uniquement")]
    raise ValueError("Preview inconnue")


async def explain_latest_sanction(ops, guild_id: int, user_id: int) -> str:
    row = await ops.bot.db.fetchone(
        "SELECT * FROM sanctions WHERE guild_id = ? AND user_id = ? ORDER BY created_at DESC, id DESC LIMIT 1",
        (guild_id, user_id),
    )
    if not row:
        return "Aucune sanction enregistrée par SentriX pour ce membre sur ce serveur."
    duration = int(row["duration_seconds"] or 0)
    duration_text = f" • durée {duration}s" if duration else ""
    return (
        f"Dossier **#{row['case_number']}** : **{row['action']}** par <@{row['moderator_id']}> "
        f"<t:{row['created_at']}:R>{duration_text}.\n**Raison :** {row['reason'] or 'Aucune raison fournie'}."
    )


async def _watchdog(bot, ops) -> None:
    try:
        await bot.wait_until_ready()
        last_signature = None
        while not bot.is_closed():
            missing = tuple(name for name in _CRITICAL_COGS if bot.get_cog(name) is None)
            latency_ms = int(max(0.0, float(getattr(bot, "latency", 0.0))) * 1000)
            signature = (missing, latency_ms >= 2500)
            if signature != last_signature:
                if missing:
                    ops.incidents.append({
                        "at": int(time.time()), "level": "ERROR", "logger": "bot.watchdog",
                        "message": f"Modules critiques absents : {', '.join(missing)}",
                    })
                if latency_ms >= 2500:
                    ops.incidents.append({
                        "at": int(time.time()), "level": "WARNING", "logger": "bot.watchdog",
                        "message": f"Latence Discord élevée : {latency_ms} ms",
                    })
                last_signature = signature
            await asyncio.sleep(60)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("Watchdog V112 interrompu.")


def _patch_contextual_automod(bot, ops) -> None:
    automod = bot.get_cog("Automod")
    if automod is None:
        return
    dataset = getattr(automod, "moderation_dataset", None)
    current_match = getattr(dataset, "match", None)
    if callable(current_match) and not getattr(current_match, "_sentrix_v112", False):
        def match_v112(text: str, _original=current_match):
            result = _original(text)
            if result is not None and should_downgrade_dataset_match(text, result.kind):
                return ModerationMatch("mot_contextuel")
            return result
        match_v112._sentrix_v112 = True
        dataset.match = match_v112

    current_timeout = getattr(automod, "_delete_and_timeout", None)
    if callable(current_timeout) and not getattr(current_timeout, "_sentrix_v112", False):
        async def delete_timeout_v112(message, reason, *, detection_kind, _original=current_timeout):
            if detection_kind == "mot_contextuel":
                await ops.bot.db.log_automod_action(
                    message.guild.id, message.author.id, "multilingual_contextual",
                    "downgrade", "Contexte explicatif détecté : timeout évité",
                )
                return await automod._delete_and_warn(
                    message,
                    "Contenu sensible détecté dans un contexte explicatif : message retiré sans timeout automatique.",
                    "multilingual_contextual",
                )
            return await _original(message, reason, detection_kind=detection_kind)
        delete_timeout_v112._sentrix_v112 = True
        automod._delete_and_timeout = delete_timeout_v112


def _add_manage_commands(bot, ops) -> None:
    manage = bot.get_command("manage")
    if not isinstance(manage, commands.Group):
        return

    if manage.get_command("preview") is None:
        async def preview_callback(ctx: commands.Context, kind: str):
            try:
                title, fields = await build_preview(ops, ctx.guild, kind)
            except ValueError:
                return await panels.envoyer(ctx, panels.depuis_embed(embeds.error("Choisis : welcome, verification, giveaway, roles, tickets ou embed.")))
            e = embeds.brand(title, "**PREVIEW** — aucune modification n'est appliquée et rien n'est publié.")
            for name, value in fields:
                e.add_field(name=name, value=str(value)[:1024], inline=False)
            await panels.envoyer(ctx, panels.depuis_embed(e))
        manage.add_command(commands.Command(preview_callback, name="preview", help="Prévisualiser une configuration sans la publier."))

    if manage.get_command("permissions") is None:
        async def permissions_callback(ctx: commands.Context, membre: discord.Member | None = None):
            notes = ops.permission_explanation(ctx.guild, ctx.channel, ctx.author, target=membre)
            e = embeds.neutral("Diagnostic précis des permissions", "\n".join(f"• {note}" for note in notes))
            if membre is None:
                e.add_field(name="Astuce", value="`+manage permissions @membre` vérifie aussi les deux hiérarchies de rôles.", inline=False)
            await panels.envoyer(ctx, panels.depuis_embed(e))
        manage.add_command(commands.Command(permissions_callback, name="permissions", help="Expliquer exactement les blocages de permissions."))

    if manage.get_command("fixall") is None:
        async def fixall_callback(ctx: commands.Context):
            report = await ops.health_report(ctx.guild)
            fixable = [f for f in report.findings if f.auto_fixable]
            if not fixable:
                return await panels.envoyer(ctx, panels.depuis_embed(embeds.success("Aucune correction automatique sûre n'est nécessaire.")))
            sid = await ops.capture_snapshot(ctx.guild.id, ctx.author.id, label="Avant fixall sécurité", source="security-fixall")
            done, failed = [], []
            for finding in fixable:
                try:
                    await ops.apply_safe_fix(ctx.guild, ctx.author.id, finding.code)
                    done.append(finding.code)
                except Exception:
                    failed.append(finding.code)
            e = embeds.success(f"Corrections sûres appliquées : **{len(done)}**. Snapshot global avant opération : **#{sid}**.")
            if done:
                e.add_field(name="Corrigé", value="\n".join(f"• {x}" for x in done), inline=False)
            if failed:
                e.add_field(name="À vérifier", value="\n".join(f"• {x}" for x in failed), inline=False)
            await panels.envoyer(ctx, panels.depuis_embed(e))
        manage.add_command(commands.Command(fixall_callback, name="fixall", help="Appliquer seulement les corrections automatiques sûres."))

    if manage.get_command("ignore") is None:
        async def ignore_callback(ctx: commands.Context, code: str):
            report = await ops.health_report(ctx.guild, include_ignored=True)
            known = {f.code for f in report.findings}
            if code not in known:
                return await panels.envoyer(ctx, panels.depuis_embed(embeds.error("Code de diagnostic inconnu ou problème déjà résolu.")))
            await ops.ignore_health_code(ctx.guild.id, ctx.author.id, code)
            await ops.log_admin_action(ctx.guild.id, ctx.author.id, "health.ignore", target_type="finding", target_id=code, after={"ignored": True})
            await panels.envoyer(ctx, panels.depuis_embed(embeds.success(f"Le point `{code}` est ignoré dans le score de ce serveur. La fonctionnalité concernée n'est pas désactivée.")))
        manage.add_command(commands.Command(ignore_callback, name="ignore", help="Ignorer volontairement un point de diagnostic."))

    if manage.get_command("sanction") is None:
        async def sanction_callback(ctx: commands.Context, membre: discord.Member):
            text = await explain_latest_sanction(ops, ctx.guild.id, membre.id)
            await panels.envoyer(ctx, panels.depuis_embed(embeds.brand("Explication de sanction", text)))
        manage.add_command(commands.Command(sanction_callback, name="sanction", help="Expliquer la dernière sanction SentriX d'un membre."))


def _instrument_log_changes(bot, ops) -> None:
    configuration = bot.get_cog("Configuration")
    if configuration is None:
        return
    current = getattr(configuration, "create_log_channels", None)
    if callable(current) and not getattr(current, "_sentrix_v112", False):
        async def create_logs_v112(guild, author, _original=current):
            sid = await ops.capture_snapshot(guild.id, author.id, label="Avant création/réparation logs", source="logs")
            created = await _original(guild, author)
            if created:
                await ops.log_admin_action(
                    guild.id, author.id, "logs.create", target_type="channels",
                    before={"snapshot": sid}, after={"created_ids": [ch.id for ch in created]}, reversible=True,
                )
            return created
        create_logs_v112._sentrix_v112 = True
        configuration.create_log_channels = create_logs_v112


async def _install_features(bot) -> None:
    ops = getattr(bot, "sentrix_ops", None)
    if ops is None:
        return
    _patch_contextual_automod(bot, ops)
    _instrument_log_changes(bot, ops)
    _add_manage_commands(bot, ops)
    try:
        from sentrix_setup_compact_v113 import install_for_bot
        install_for_bot(bot)
    except Exception:
        logger.exception("Installation du Setup compact V113 impossible.")
    try:
        from sentrix_setup_polish_v114 import install_for_bot as install_setup_polish
        install_setup_polish(bot)
    except Exception:
        logger.exception("Installation du polish Setup V114 impossible.")
    task = getattr(bot, "_sentrix_ops_watchdog", None)
    if task is None or task.done():
        bot._sentrix_ops_watchdog = asyncio.create_task(_watchdog(bot, ops), name="sentrix-ops-watchdog")


def install() -> None:
    import sentrix_v95_runtime as v95

    current = v95.prepare_bot
    if getattr(current, "_sentrix_ops_v112", False):
        return

    async def prepare_bot_v112(bot):
        result = await current(bot)
        try:
            await _install_features(bot)
        except Exception:
            logger.exception("Installation des intégrations V112 impossible.")
        return result

    prepare_bot_v112._sentrix_ops_v112 = True
    prepare_bot_v112._sentrix_original = current
    v95.prepare_bot = prepare_bot_v112
    logger.info("SentriX Ops V112 installé.")


__all__ = ["build_preview", "explain_latest_sanction", "install", "should_downgrade_dataset_match"]