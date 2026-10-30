"""Audit de sécurité et de configuration à la demande : +auditbot.

Lecture seule : NE JAMAIS exécuter les callbacks inspectés (ban/clear/pay/etc.).
Un rapport local au serveur est envoyé uniquement en MP au créateur principal.
Les erreurs passées du bot sont montrées uniquement au propriétaire global.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import inspect
import io
import logging
import math
import time
from dataclasses import dataclass
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands, tasks

from database.db import PRIMARY_CREATOR_ID

logger = logging.getLogger("bot.auditbot")

MAX_ISSUES = 150
MAX_ITEMS_PER_QUERY = 100
SEVERITIES = ("CRITIQUE", "ERREUR", "AVERTISSEMENT")


@dataclass(frozen=True)
class Finding:
    level: str
    section: str
    subject: str
    reason: str
    fix: str


class AuditReport:
    def __init__(self, guild_id: int):
        self.guild_id = guild_id
        self.started_at = dt.datetime.now(dt.timezone.utc)
        self.findings: list[Finding] = []
        self.counts: dict[str, int] = {}
        self.details: list[str] = []
        self.truncated = False

    def add(self, level: str, section: str, subject: str, reason: str, fix: str):
        if level not in SEVERITIES:
            raise ValueError("Invalid severity")
        if len(self.findings) >= MAX_ISSUES:
            self.truncated = True
            return
        self.findings.append(Finding(level, section, subject, reason, fix))

    def count(self, name: str, value: int):
        self.counts[name] = int(value)

    def note(self, text: str):
        self.details.append(text)

    def summary(self) -> str:
        totals = {level: sum(x.level == level for x in self.findings) for level in SEVERITIES}
        return (
            f"**Audit SentriX terminé** — "
            f"{totals['CRITIQUE']} critique(s), {totals['ERREUR']} erreur(s), "
            f"{totals['AVERTISSEMENT']} avertissement(s).\n"
            "**Rapport détaillé en message privé.** "
            "Aucune commande de sanction n'a été exécutée."
        )

    def markdown(self) -> str:
        lines = [
            "# SentriX — rapport d'audit",
            f"Guilde ID : {self.guild_id}",
            "Date UTC : " + self.started_at.strftime("%Y-%m-%d %H:%M"),
            "",
            "## Méthode et limites",
            "Audit statique et contrôles de lecture seule sur le serveur courant.",
            "Toutes les commandes enregistrées sont inspectées, mais aucune commande "
            "de modération, de paiement, de suppression, de publication ou de configuration "
            "n'est réellement lancée. Impossible de garantir l'absence de bug métier "
            "sans exécuter des tests en environnement isolé.",
            "Les commandes slash côté Discord distant ne sont pas resynchronisées ici.",
            "Aucun secret ou contenu de message n'est inclus.",
            "",
            "## Couverture",
        ]
        lines.extend(f"- {k}: {v}" for k, v in sorted(self.counts.items()))
        lines.extend(("", "## Remarques"))
        lines.extend(f"- {note}" for note in self.details)
        lines.extend(("", "## Anomalies et corrections"))
        if not self.findings:
            lines.append("Aucune anomalie détectée par les contrôles disponibles.")
        for i, item in enumerate(sorted(
            self.findings, key=lambda x: SEVERITIES.index(x.level)
        ), 1):
            lines.extend([
                f"### {i}. [{item.level}] {item.section} — {item.subject}",
                "Constat : " + item.reason,
                "À faire : " + item.fix,
                "",
            ])
        if self.truncated:
            lines.append("ATTENTION : nombre d'anomalies plafonné ; compléter l'audit après correction.")
        return "\n".join(lines)[:300_000]


def _value(row: Any, key: str, default: Any = None) -> Any:
    if row is None:
        return default
    try:
        return row[key]
    except (TypeError, LookupError, KeyError):
        return default


async def _read(bot, query: str, params: tuple = (), *, many: bool = False):
    call = bot.db.fetchall if many else bot.db.fetchone
    return await asyncio.wait_for(call(query, params), timeout=3.5)


def _channel(bot_guild: discord.Guild, channel_id: Any):
    try:
        return bot_guild.get_channel(int(channel_id))
    except (TypeError, ValueError, OverflowError):
        return None


def _user_can_audit(ctx: commands.Context) -> bool:
    """Commande privée : ID du créateur principal uniquement, sans exception staff."""
    return bool(
        getattr(ctx, "guild", None) is not None
        and getattr(getattr(ctx, "author", None), "id", None) == PRIMARY_CREATOR_ID
    )


def _check_registered_commands(bot: commands.Bot, report: AuditReport):
    prefix = list(bot.walk_commands())
    report.count("Commandes préfixées inspectées", len(prefix))
    report.count("Commandes slash locales inspectées", 0)
    report.count("Extensions chargées", len(bot.extensions))

    seen: set[str] = set()
    for command in prefix:
        name = str(command.qualified_name)
        if name in seen:
            report.add("ERREUR", "Commandes", name, "Nom qualifié enregistré plusieurs fois.",
                       "Revoir les aliases et les groupes de commandes.")
        seen.add(name)
        if not callable(getattr(command, "callback", None)):
            report.add("CRITIQUE", "Commandes", name, "Callback introuvable.",
                       "Réinstaller ou corriger le Cog qui expose cette commande.")
        else:
            try:
                inspect.signature(command.callback)
            except (ValueError, TypeError):
                report.add("AVERTISSEMENT", "Commandes", name, "Signature non inspectable.",
                           "Vérifier manuellement la signature du callback.")

    slash_names: set[str] = set()
    for command in bot.tree.walk_commands():
        if not isinstance(command, (app_commands.Command, app_commands.Group)):
            continue
        name = str(getattr(command, "qualified_name", command.name))
        slash_names.add(name)
        if isinstance(command, app_commands.Command) and not callable(
            getattr(command, "callback", None)
        ):
            report.add("ERREUR", "Slash", name, "Callback slash non appelable.",
                       "Vérifier la synchronisation du catalogue et le Cog.")
    report.count("Commandes slash locales inspectées", len(slash_names))
    try:
        from utils import slash_catalog
        entries = list(slash_catalog.CATALOG)
        report.count("Entrées prévues au catalogue slash", len(entries))
        # Les sources natives ne disposent pas toutes d'une commande « + ».
        # La présence du chemin côté arbre reste un signal ; ne jamais prétendre
        # qu'un alias dynamique différent est une panne avérée.
        missing = [e.path for e in entries if e.path not in slash_names]
        if missing:
            report.add(
                "AVERTISSEMENT", "Catalogue slash", f"{len(missing)} chemin(s)",
                "Certains chemins attendus n'ont pas été trouvés dans l'arbre local : "
                + ", ".join(missing[:8]) + ". Les routes aliasées peuvent différer.",
                "Comparer avec l'audit de publication et la synchronisation Discord.",
            )
    except Exception:
        report.add("AVERTISSEMENT", "Catalogue slash", "Lecture du catalogue",
                   "Comparaison non disponible.", "Lancer l'audit CI du catalogue.")

    try:
        import main
        expected = list(getattr(main, "EXTENSIONS", ()))
    except Exception:
        expected = []
    if expected:
        missing = sorted(set(expected) - set(bot.extensions))
        report.count("Extensions attendues", len(expected))
        if missing:
            for ext in missing[:25]:
                report.add("ERREUR", "Extensions", ext, "Extension attendue non chargée.",
                           "Vérifier le démarrage et la trace de chargement du module.")
    else:
        report.note("Catalogue d'extensions indisponible ; extensions non comparées.")

    try:
        from cogs.command_health import snapshot
        state = snapshot(bot, limit=20)
        report.count("Erreurs techniques depuis le démarrage", int(state["total_errors"]))
        report.count("Commandes en erreur depuis le démarrage", int(state["broken_commands"]))
    except Exception:
        report.note("Compteurs d'erreurs de commandes indisponibles.")


def _check_loops(bot: commands.Bot, report: AuditReport):
    active = 0
    stopped = 0
    for cog in bot.cogs.values():
        for attr in dir(cog):
            if attr.startswith("_"):
                continue
            try:
                loop = getattr(cog, attr)
            except Exception:
                continue
            if isinstance(loop, tasks.Loop):
                if loop.is_running():
                    active += 1
                else:
                    stopped += 1
    report.count("Boucles actives", active)
    report.count("Boucles non lancées (certaines sont optionnelles)", stopped)
    # Une boucle arrêtée peut être normalement désactivée par serveur :
    # seule la supervision doit décider si c'est un vrai incident.
    supervisor = getattr(bot, "module_supervisor", None)
    snap = supervisor.snapshot() if supervisor is not None and hasattr(supervisor, "snapshot") else {}
    for stopped_loop in list(snap.get("failed_background_loops") or [])[:15]:
        name = str(stopped_loop)[:100]
        report.add("ERREUR", "Tâches", name, "Échec signalé par le superviseur.",
                   "Consulter les logs de cette boucle ; corriger sa dernière exception.")


async def _check_guild_config(bot, guild: discord.Guild, report: AuditReport):
    try:
        conf = await asyncio.wait_for(bot.db.get_guild_config(guild.id), timeout=3.5)
    except Exception:
        report.add("ERREUR", "Base", "Configuration du serveur",
                   "Impossible de lire la configuration.", "Vérifier l'accès à guild_config.")
        return

    if conf is not None:
        for field, label in (
            ("welcome_channel", "Bienvenue"),
            ("goodbye_channel", "Départ"),
        ):
            ident = _value(conf, field)
            if not ident:
                continue  # Non configuré n'est PAS un bug.
            channel = _channel(guild, ident)
            if not isinstance(channel, discord.TextChannel):
                report.add("ERREUR", "Configuration", label, "Salon configuré supprimé ou invalide.",
                           "Choisir à nouveau le salon dans /setup.")
            elif guild.me and not channel.permissions_for(guild.me).send_messages:
                report.add("ERREUR", "Permissions", label,
                           "SentriX ne peut pas envoyer de message dans ce salon.",
                           "Accorder Voir le salon et Envoyer des messages à SentriX.")
        autorole = _value(conf, "autorole")
        if autorole:
            try:
                role = guild.get_role(int(autorole))
            except (ValueError, TypeError):
                role = None
            if role is None:
                report.add("ERREUR", "Rôles", "Auto-rôle", "Rôle configuré introuvable.",
                           "Choisir un nouveau rôle dans /setup.")
            elif guild.me and role >= guild.me.top_role:
                report.add("ERREUR", "Rôles", "Auto-rôle", "Rôle supérieur à celui de SentriX.",
                           "Placer SentriX au-dessus du rôle dans les paramètres Discord.")

    try:
        rows = await _read(bot,
            "SELECT category,channel_id,enabled FROM log_config WHERE guild_id=?",
            (guild.id,), many=True)
    except Exception:
        report.add("AVERTISSEMENT", "Logs", "Base des salons",
                   "Impossible de lire les destinations des logs.",
                   "Vérifier la migration log_config dans les journaux de démarrage.")
        rows = []
    report.count("Catégories de logs configurées", len(rows))
    for row in rows[:MAX_ITEMS_PER_QUERY]:
        if not _value(row, "enabled"):
            continue
        category = str(_value(row, "category", "inconnue"))[:60]
        channel = _channel(guild, _value(row, "channel_id"))
        if not isinstance(channel, discord.TextChannel):
            report.add("ERREUR", "Logs", category,
                       "Catégorie active sans salon valide.",
                       "Corriger sa destination dans /setup > Surveillance > Logs.")
        elif guild.me:
            perms = channel.permissions_for(guild.me)
            if not (perms.view_channel and perms.send_messages):
                report.add("ERREUR", "Logs", category,
                           "SentriX ne peut pas publier dans le salon choisi.",
                           "Accorder Voir le salon et Envoyer des messages.")
            elif not perms.attach_files:
                report.add("AVERTISSEMENT", "Logs", category,
                           "Pièces jointes interdites : transcripts ou fichiers manquants.",
                           "Autoriser Joindre des fichiers dans le salon des logs.")
    if len(rows) > MAX_ITEMS_PER_QUERY:
        report.note("Destinations des logs limitées à 100 lignes dans ce rapport.")

    try:
        rows = await _read(bot, "SELECT module,enabled FROM module_settings WHERE guild_id=?",
                           (guild.id,), many=True)
    except Exception:
        report.add("AVERTISSEMENT", "Modules", "États des modules",
                   "Impossible de lire les interrupteurs enregistrés.",
                   "Vérifier la table module_settings.")
        rows = []
    report.count("Modules avec choix explicite", len(rows))
    for row in rows:
        name = str(_value(row, "module", ""))[:60]
        enabled = bool(_value(row, "enabled"))
        if not enabled:
            report.note(f"Module {name} désactivé explicitement (choix administrateur, pas une erreur).")

    try:
        from cogs.honeypot_verification_v48 import HoneypotVerification
        cog = bot.get_cog("HoneypotVerification")
        if cog is not None:
            config = await asyncio.wait_for(cog.config(guild.id, enabled_only=False), timeout=3.5)
            if config and _value(config, "enabled"):
                for field, label in (
                    ("verify_channel_id", "Salon de vérification"),
                    ("unverified_role_id", "Rôle Non vérifié"),
                ):
                    ident = _value(config, field)
                    target = (_channel(guild, ident) if "channel" in field
                              else guild.get_role(int(ident)) if ident else None)
                    if target is None:
                        report.add("CRITIQUE", "Vérification", label,
                                   "Ressource obligatoire supprimée.",
                                   "Ouvrir /setup > Vérification, puis Diagnostic et Réparer.")
    except Exception:
        report.add("AVERTISSEMENT", "Vérification", "Lecture",
                   "Diagnostic des ressources de vérification indisponible.",
                   "Consulter le diagnostic de /setup > Vérification.")


async def run_readonly_audit(bot: commands.Bot, guild: discord.Guild) -> AuditReport:
    report = AuditReport(guild.id)
    try:
        result = await _read(bot, "SELECT 1 AS ok")
        report.count("Base PostgreSQL accessible", int(bool(result)))
    except Exception:
        report.add("CRITIQUE", "Base", "Connexion", "Lecture SELECT 1 impossible.",
                   "Vérifier Railway PostgreSQL, les volumes et la connexion au pool.")

    if not bot.is_ready():
        report.add("ERREUR", "Discord", "Gateway", "Client Discord non prêt.",
                   "Consulter Railway > Deploy Logs et vérifier le bail HA.")
    latency = getattr(bot, "latency", None)
    if isinstance(latency, (int, float)) and math.isfinite(latency):
        report.count("Latence Gateway en ms", int(latency * 1000))
        if latency > 1:
            report.add("AVERTISSEMENT", "Discord", "Latence",
                       f"Latence supérieure à 1 seconde ({latency*1000:.0f} ms).",
                       "Vérifier la connexion et les tâches bloquantes.")
    _check_registered_commands(bot, report)
    _check_loops(bot, report)
    await _check_guild_config(bot, guild, report)
    return report


class AuditBot(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._running: set[int] = set()

    @commands.command(name="auditbot", help="Audit en lecture seule des commandes et de ce serveur.")
    @commands.guild_only()
    @commands.check(_user_can_audit)
    @commands.cooldown(1, 120, commands.BucketType.guild)
    async def auditbot(self, ctx: commands.Context):
        if not _user_can_audit(ctx):
            return await ctx.send("Accès réservé au créateur principal de SentriX.",
                                  allowed_mentions=discord.AllowedMentions.none())
        if ctx.guild.id in self._running:
            return await ctx.send("Un audit est déjà en cours sur ce serveur.",
                                  allowed_mentions=discord.AllowedMentions.none())
        self._running.add(ctx.guild.id)
        try:
            report = await asyncio.wait_for(
                run_readonly_audit(self.bot, ctx.guild), timeout=30,
            )
            content = report.markdown().encode("utf-8")
            filename = "sentrix-audit-" + report.started_at.strftime("%Y%m%d-%H%M%S") + ".md"
            try:
                await ctx.author.send(
                    "Rapport de diagnostic SentriX (lecture seule) :",
                    file=discord.File(io.BytesIO(content), filename=filename),
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            except (discord.Forbidden, discord.HTTPException):
                return await ctx.send(
                    "Audit terminé, mais je ne peux pas envoyer le rapport en MP. "
                    "Autorisez les messages privés, puis relancez la commande.",
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            await ctx.send(report.summary(), allowed_mentions=discord.AllowedMentions.none())
        except asyncio.TimeoutError:
            await ctx.send("Audit interrompu : délai de 30 secondes dépassé. Aucun réglage modifié.",
                           allowed_mentions=discord.AllowedMentions.none())
        except Exception:
            logger.exception("Échec auditbot (guild=%s)", ctx.guild.id)
            await ctx.send("Audit impossible. Consultez les logs de SentriX.",
                           allowed_mentions=discord.AllowedMentions.none())
        finally:
            self._running.discard(ctx.guild.id)


async def setup(bot: commands.Bot):
    await bot.add_cog(AuditBot(bot))
