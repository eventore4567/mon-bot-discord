"""SentriX V111 — centre d'opérations serveur.

Cette couche ajoute les fondations transverses demandées sans consommer de nouvelles
racines slash : versioning/rollback de configuration, historique admin, diagnostic
serveur, score sécurité actionnable, audit de doublons, simulation sans effet et
monitoring d'incidents runtime. Le hub utilisateur est préfixe-only (`+manage`) afin de
respecter la limite Discord de 100 racines slash déjà atteinte.

Les restaurations sont volontairement bornées aux données gérées par SentriX. Elles ne
suppriment jamais de rôle/salon Discord et ne rejouent jamais une sanction.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import deque
from dataclasses import asdict, dataclass
from typing import Any, Iterable

import discord
from discord.ext import commands

from utils import checks, embeds, helpers
from utils import sentrix_panels as panels

logger = logging.getLogger("bot.ops-v111")

_SCHEMA_VERSION = 1
_MAX_SNAPSHOTS = 10
_MAX_INCIDENTS = 50
_SAFE_AUTOMOD_FIXES = {
    "automod.antinuke": "antinuke",
    "automod.antiraid": "antiraid",
    "automod.antispam": "antispam",
    "automod.antiinvite": "antiinvite",
    "automod.antiaccount": "antiaccount",
    "automod.antiscam": "antiscam",
    "automod.escalation": "escalation",
}


@dataclass(frozen=True)
class HealthFinding:
    code: str
    severity: str
    title: str
    detail: str
    remediation: str
    auto_fixable: bool = False


@dataclass(frozen=True)
class GuildHealthReport:
    score: int
    label: str
    findings: tuple[HealthFinding, ...]
    db_ok: bool
    latency_ms: int
    extensions_loaded: int
    recent_incidents: int


@dataclass(frozen=True)
class SetupProposal:
    score: int
    ready: tuple[str, ...]
    proposed: tuple[str, ...]
    manual: tuple[str, ...]


class RuntimeIncidentHandler(logging.Handler):
    """Capture uniquement les warnings/errors SentriX, sans modifier les autres handlers."""

    def __init__(self, sink: deque[dict[str, Any]]):
        super().__init__(level=logging.WARNING)
        self.sink = sink

    def emit(self, record: logging.LogRecord) -> None:
        try:
            if not str(record.name).startswith("bot"):
                return
            self.sink.append(
                {
                    "at": int(time.time()),
                    "level": record.levelname,
                    "logger": record.name,
                    "message": record.getMessage()[:800],
                }
            )
        except Exception:
            return


def _row_dict(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    try:
        return dict(row)
    except Exception:
        return None


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    return str(value)


def _severity_cost(severity: str) -> int:
    return {"critical": 30, "high": 18, "medium": 10, "low": 5, "info": 2}.get(severity, 5)


def compute_health_score(findings: Iterable[HealthFinding]) -> int:
    return max(0, 100 - sum(_severity_cost(item.severity) for item in findings))


def health_label(score: int) -> str:
    if score >= 90:
        return "Excellent"
    if score >= 75:
        return "Bon"
    if score >= 50:
        return "À renforcer"
    return "Fragile"


def build_simulation(kind: str, *, target: str = "membre-test") -> dict[str, Any]:
    """Plan de simulation pur : aucune API Discord ni écriture DB n'est exécutée."""
    kind = str(kind or "").strip().casefold().replace("_", "-")
    plans = {
        "sanction": ["valider les permissions", "générer le DM", "écrire le log", "appliquer la sanction"],
        "join": ["évaluer l'anti-raid", "autorôle", "bienvenue", "log membre"],
        "verification": ["ouvrir le panneau", "valider les prérequis", "attribuer le rôle", "log vérification"],
        "ticket": ["valider le type", "créer le salon", "appliquer les overwrites", "envoyer les contrôles staff"],
        "log": ["résoudre la route", "vérifier les permissions", "dédupliquer", "envoyer le panneau"],
        "raid": ["détecter l'afflux", "évaluer les comptes", "activer les protections", "alerter le staff"],
    }
    if kind not in plans:
        raise ValueError("Simulation inconnue")
    return {"kind": kind, "target": target, "dry_run": True, "steps": plans[kind]}


class SentriXOps:
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.incidents: deque[dict[str, Any]] = deque(maxlen=_MAX_INCIDENTS)
        self._handler: RuntimeIncidentHandler | None = None
        self._schema_ready = False

    async def ensure_schema(self) -> None:
        if self._schema_ready:
            return
        statements = (
            """
            CREATE TABLE IF NOT EXISTS sentrix_config_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                actor_id INTEGER NOT NULL,
                label TEXT NOT NULL,
                source TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                schema_version INTEGER NOT NULL DEFAULT 1,
                created_at INTEGER NOT NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_sentrix_snapshots_guild_time ON sentrix_config_snapshots (guild_id, created_at DESC)",
            """
            CREATE TABLE IF NOT EXISTS sentrix_admin_actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                actor_id INTEGER NOT NULL,
                action TEXT NOT NULL,
                target_type TEXT,
                target_id TEXT,
                before_json TEXT,
                after_json TEXT,
                reversible INTEGER NOT NULL DEFAULT 0,
                created_at INTEGER NOT NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_sentrix_admin_actions_guild_time ON sentrix_admin_actions (guild_id, created_at DESC)",
            """
            CREATE TABLE IF NOT EXISTS sentrix_health_ignores (
                guild_id INTEGER NOT NULL,
                code TEXT NOT NULL,
                actor_id INTEGER NOT NULL,
                created_at INTEGER NOT NULL,
                PRIMARY KEY (guild_id, code)
            )
            """,
        )
        for sql in statements:
            await self.bot.db.execute(sql)
        self._schema_ready = True

    def install_runtime_monitor(self) -> None:
        if self._handler is not None:
            return
        self._handler = RuntimeIncidentHandler(self.incidents)
        logging.getLogger("bot").addHandler(self._handler)

    async def _table_rows(self, table: str, guild_id: int) -> list[dict[str, Any]]:
        # Les noms sont constants internes, jamais construits depuis une entrée utilisateur.
        rows = await self.bot.db.fetchall(f"SELECT * FROM {table} WHERE guild_id = ?", (guild_id,))
        return [dict(row) for row in rows]

    async def capture_snapshot(self, guild_id: int, actor_id: int, *, label: str, source: str) -> int:
        await self.ensure_schema()
        guild_config = _row_dict(await self.bot.db.get_guild_config(guild_id))
        automod = _row_dict(await self.bot.db.get_automod(guild_id))
        try:
            log_config = await self._table_rows("log_config", guild_id)
        except Exception:
            log_config = []
        payload = {
            "guild_config": guild_config,
            "automod_settings": automod,
            "log_config": log_config,
        }
        cur = await self.bot.db.execute(
            "INSERT INTO sentrix_config_snapshots (guild_id, actor_id, label, source, payload_json, schema_version, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (guild_id, actor_id, label[:120], source[:80], json.dumps(_json_safe(payload), ensure_ascii=False), _SCHEMA_VERSION, int(time.time())),
        )
        # Garde seulement les N versions les plus récentes par serveur.
        await self.bot.db.execute(
            "DELETE FROM sentrix_config_snapshots WHERE guild_id = ? AND id NOT IN (SELECT id FROM sentrix_config_snapshots WHERE guild_id = ? ORDER BY created_at DESC, id DESC LIMIT ?)",
            (guild_id, guild_id, _MAX_SNAPSHOTS),
        )
        return int(cur.lastrowid)

    async def list_snapshots(self, guild_id: int, limit: int = _MAX_SNAPSHOTS):
        await self.ensure_schema()
        return await self.bot.db.fetchall(
            "SELECT id, actor_id, label, source, schema_version, created_at FROM sentrix_config_snapshots WHERE guild_id = ? ORDER BY created_at DESC, id DESC LIMIT ?",
            (guild_id, max(1, min(int(limit), _MAX_SNAPSHOTS))),
        )

    async def _restore_single_row(self, table: str, guild_id: int, payload: dict[str, Any] | None) -> None:
        if not payload:
            return
        columns = await self.bot.db.fetchall(f"PRAGMA table_info({table})")
        allowed = {str(row["name"]) for row in columns}
        data = {k: v for k, v in payload.items() if k in allowed and k != "guild_id"}
        if not data:
            return
        assignments = ", ".join(f'"{key}" = ?' for key in data)
        await self.bot.db.execute(
            f"UPDATE {table} SET {assignments} WHERE guild_id = ?",
            tuple(data.values()) + (guild_id,),
        )

    async def _restore_rows(self, table: str, guild_id: int, rows: list[dict[str, Any]]) -> None:
        columns = await self.bot.db.fetchall(f"PRAGMA table_info({table})")
        allowed = [str(row["name"]) for row in columns]
        if "guild_id" not in allowed:
            return
        await self.bot.db.execute(f"DELETE FROM {table} WHERE guild_id = ?", (guild_id,))
        for source in rows:
            data = {key: source.get(key) for key in allowed if key in source}
            data["guild_id"] = guild_id
            keys = list(data)
            placeholders = ", ".join("?" for _ in keys)
            quoted = ", ".join(f'"{key}"' for key in keys)
            await self.bot.db.execute(
                f"INSERT INTO {table} ({quoted}) VALUES ({placeholders})",
                tuple(data[key] for key in keys),
            )

    async def restore_snapshot(self, guild_id: int, actor_id: int, snapshot_id: int) -> dict[str, Any]:
        await self.ensure_schema()
        row = await self.bot.db.fetchone(
            "SELECT * FROM sentrix_config_snapshots WHERE id = ? AND guild_id = ?",
            (snapshot_id, guild_id),
        )
        if not row:
            raise LookupError("Snapshot introuvable")
        before_id = await self.capture_snapshot(
            guild_id, actor_id, label=f"Avant rollback #{snapshot_id}", source="rollback-safety"
        )
        payload = json.loads(row["payload_json"])
        await self._restore_single_row("guild_config", guild_id, payload.get("guild_config"))
        await self._restore_single_row("automod_settings", guild_id, payload.get("automod_settings"))
        try:
            await self._restore_rows("log_config", guild_id, list(payload.get("log_config") or []))
        except Exception:
            logger.exception("Restauration log_config incomplète pour guild=%s", guild_id)
        invalidate = getattr(self.bot.db, "invalidate_guild_config", None)
        if callable(invalidate):
            invalidate(guild_id)
        automod_cog = self.bot.get_cog("Automod")
        cache = getattr(automod_cog, "automod_cache", None)
        if isinstance(cache, dict):
            cache.pop(guild_id, None)
        await self.log_admin_action(
            guild_id, actor_id, "config.rollback", target_type="snapshot", target_id=str(snapshot_id),
            before={"safety_snapshot": before_id}, after={"restored_snapshot": snapshot_id}, reversible=True,
        )
        return {"restored": snapshot_id, "safety_snapshot": before_id, "label": row["label"]}

    async def log_admin_action(
        self,
        guild_id: int,
        actor_id: int,
        action: str,
        *,
        target_type: str | None = None,
        target_id: str | None = None,
        before: Any = None,
        after: Any = None,
        reversible: bool = False,
    ) -> int:
        await self.ensure_schema()
        cur = await self.bot.db.execute(
            "INSERT INTO sentrix_admin_actions (guild_id, actor_id, action, target_type, target_id, before_json, after_json, reversible, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                guild_id, actor_id, action[:100], target_type, target_id,
                json.dumps(_json_safe(before), ensure_ascii=False) if before is not None else None,
                json.dumps(_json_safe(after), ensure_ascii=False) if after is not None else None,
                1 if reversible else 0, int(time.time()),
            ),
        )
        return int(cur.lastrowid)

    async def list_admin_actions(self, guild_id: int, limit: int = 15):
        await self.ensure_schema()
        return await self.bot.db.fetchall(
            "SELECT * FROM sentrix_admin_actions WHERE guild_id = ? ORDER BY created_at DESC, id DESC LIMIT ?",
            (guild_id, max(1, min(int(limit), 50))),
        )

    async def ignored_health_codes(self, guild_id: int) -> set[str]:
        await self.ensure_schema()
        rows = await self.bot.db.fetchall("SELECT code FROM sentrix_health_ignores WHERE guild_id = ?", (guild_id,))
        return {str(row["code"]) for row in rows}

    async def ignore_health_code(self, guild_id: int, actor_id: int, code: str) -> None:
        await self.ensure_schema()
        await self.bot.db.execute(
            "INSERT OR REPLACE INTO sentrix_health_ignores (guild_id, code, actor_id, created_at) VALUES (?, ?, ?, ?)",
            (guild_id, code[:100], actor_id, int(time.time())),
        )

    async def health_report(self, guild: discord.Guild, *, include_ignored: bool = False) -> GuildHealthReport:
        await self.ensure_schema()
        findings: list[HealthFinding] = []
        ignored = set() if include_ignored else await self.ignored_health_codes(guild.id)
        me = guild.me

        async def add(item: HealthFinding):
            if item.code not in ignored:
                findings.append(item)

        db_ok = True
        try:
            await self.bot.db.fetchone("SELECT 1 AS ok")
        except Exception:
            db_ok = False
            await add(HealthFinding("db.unavailable", "critical", "Base de données indisponible", "SentriX ne peut pas lire/écrire les données du serveur.", "Vérifier le stockage et redémarrer uniquement après diagnostic."))

        conf = await self.bot.db.get_guild_config(guild.id)
        conf_map = _row_dict(conf) or {}
        automod = _row_dict(await self.bot.db.get_automod(guild.id)) or {}

        if not conf_map.get("mod_role") or guild.get_role(int(conf_map.get("mod_role") or 0)) is None:
            await add(HealthFinding("config.mod-role", "medium", "Rôle staff non configuré", "Les contrôles SentriX doivent alors se reposer uniquement sur les permissions Discord.", "Configurer le rôle staff dans +setup."))

        configured_logs = 0
        try:
            routes = await self._table_rows("log_config", guild.id)
            configured_logs = sum(1 for row in routes if row.get("enabled") and row.get("channel_id"))
        except Exception:
            routes = []
        if configured_logs == 0:
            await add(HealthFinding("logs.missing", "medium", "Logs non routés", "Aucune route de log active avec salon n'a été trouvée.", "Ouvrir +setup › Logs ou lancer +create-logs."))

        required_toggles = (
            ("antinuke", "critical", "Anti-nuke désactivé"),
            ("antiraid", "high", "Anti-raid désactivé"),
            ("antiscam", "medium", "Anti-scam désactivé"),
            ("antispam", "medium", "Anti-spam désactivé"),
            ("antiaccount", "low", "Protection des comptes récents désactivée"),
        )
        for key, severity, title in required_toggles:
            if not bool(automod.get(key)):
                await add(HealthFinding(f"automod.{key}", severity, title, f"Le réglage AutoMod `{key}` est désactivé.", "SentriX peut l'activer automatiquement après confirmation.", True))
        if not bool(automod.get("escalation", 1)):
            await add(HealthFinding("automod.escalation", "medium", "Escalade AutoMod désactivée", "Les infractions répétées ne montent plus automatiquement en sévérité.", "Réactiver l'escalade après validation.", True))

        if me is None:
            await add(HealthFinding("bot.member", "critical", "Membre bot introuvable", "Discord n'a pas fourni le membre SentriX pour ce serveur.", "Réinviter le bot ou vérifier son état de connexion."))
        else:
            perms = me.guild_permissions
            for perm, label in (
                ("manage_roles", "Gérer les rôles"),
                ("manage_channels", "Gérer les salons"),
                ("view_audit_log", "Voir le journal d'audit"),
                ("moderate_members", "Modérer les membres"),
            ):
                if not getattr(perms, perm, False) and not perms.administrator:
                    await add(HealthFinding(f"botperm.{perm}", "high", f"Permission bot manquante : {label}", "Certaines fonctions administratives peuvent échouer.", f"Accorder `{label}` au rôle {me.top_role.name}."))
            manageable_roles = [r for r in guild.roles if not r.managed and r != guild.default_role]
            if manageable_roles and me.top_role.position <= max(r.position for r in manageable_roles):
                await add(HealthFinding("hierarchy.bot", "high", "Rôle SentriX trop bas", "Le bot ne pourra pas gérer les membres/rôles placés au-dessus de lui.", f"Déplacer {me.top_role.mention} au-dessus des rôles qu'il doit gérer."))

        recent = [item for item in self.incidents if int(time.time()) - int(item["at"]) <= 3600]
        if len(recent) >= 5:
            await add(HealthFinding("runtime.errors", "medium", "Erreurs runtime récentes", f"{len(recent)} warning/error ont été observés sur la dernière heure.", "Consulter +manage incidents et corriger les erreurs répétitives."))

        score = compute_health_score(findings)
        latency = int(max(0.0, float(getattr(self.bot, "latency", 0.0))) * 1000)
        return GuildHealthReport(score, health_label(score), tuple(findings), db_ok, latency, len(getattr(self.bot, "extensions", {})), len(recent))

    async def apply_safe_fix(self, guild: discord.Guild, actor_id: int, code: str) -> str:
        await self.ensure_schema()
        field = _SAFE_AUTOMOD_FIXES.get(code)
        if not field:
            raise ValueError("Ce point nécessite une correction manuelle")
        previous = _row_dict(await self.bot.db.get_automod(guild.id)) or {}
        snapshot_id = await self.capture_snapshot(guild.id, actor_id, label=f"Avant correction {code}", source="security-fix")
        await self.bot.db.execute(f'UPDATE automod_settings SET "{field}" = 1 WHERE guild_id = ?', (guild.id,))
        automod_cog = self.bot.get_cog("Automod")
        cache = getattr(automod_cog, "automod_cache", None)
        if isinstance(cache, dict):
            cache.pop(guild.id, None)
        await self.log_admin_action(
            guild.id, actor_id, "security.auto-fix", target_type="automod", target_id=field,
            before={field: previous.get(field)}, after={field: 1, "snapshot": snapshot_id}, reversible=True,
        )
        return f"`{field}` activé. Snapshot de sécurité #{snapshot_id}."

    async def setup_proposal(self, guild: discord.Guild) -> SetupProposal:
        report = await self.health_report(guild)
        ready: list[str] = []
        proposed: list[str] = []
        manual: list[str] = []
        codes = {finding.code for finding in report.findings}
        if "config.mod-role" in codes:
            manual.append("Choisir le rôle staff")
        else:
            ready.append("Rôle staff")
        if "logs.missing" in codes:
            manual.append("Créer/configurer les salons de logs")
        else:
            ready.append("Logs")
        auto = [f for f in report.findings if f.auto_fixable]
        if auto:
            proposed.extend(f"Activer {f.code.split('.', 1)[-1]}" for f in auto)
        else:
            ready.append("AutoMod essentiel")
        if guild.me is not None and any(f.code.startswith("botperm.") or f.code == "hierarchy.bot" for f in report.findings):
            manual.append("Corriger les permissions/hiérarchie du bot")
        else:
            ready.append("Permissions SentriX")
        return SetupProposal(report.score, tuple(ready), tuple(proposed), tuple(manual))

    def duplicate_command_audit(self) -> list[tuple[str, str, str]]:
        commands_list = list(self.bot.walk_commands())
        duplicates: list[tuple[str, str, str]] = []
        callback_owner: dict[int, str] = {}
        name_owner: dict[str, str] = {}
        for command in commands_list:
            qualified = str(command.qualified_name).casefold()
            callback = getattr(command, "callback", None)
            if callback is not None:
                key = id(callback)
                other = callback_owner.get(key)
                if other and other != qualified:
                    duplicates.append((other, qualified, "même callback"))
                else:
                    callback_owner[key] = qualified
            for alias in getattr(command, "aliases", ()):
                alias_key = str(alias).casefold()
                other = name_owner.get(alias_key)
                if other and other != qualified:
                    duplicates.append((other, qualified, f"alias `{alias_key}` en collision"))
                else:
                    name_owner[alias_key] = qualified
            if qualified in name_owner and name_owner[qualified] != qualified:
                duplicates.append((name_owner[qualified], qualified, "nom/alias en collision"))
            else:
                name_owner[qualified] = qualified
        # Déduplication stable.
        output: list[tuple[str, str, str]] = []
        seen = set()
        for item in duplicates:
            key = tuple(sorted(item[:2])) + (item[2],)
            if key not in seen:
                seen.add(key)
                output.append(item)
        return output

    def permission_explanation(
        self,
        guild: discord.Guild,
        channel: discord.abc.GuildChannel | None,
        actor: discord.Member,
        *,
        required: str | None = None,
        target: discord.Member | None = None,
    ) -> list[str]:
        notes: list[str] = []
        if required and not actor.guild_permissions.administrator and not getattr(actor.guild_permissions, required, False):
            notes.append(f"Tu n'as pas la permission Discord `{required}`.")
        me = guild.me
        if me is None:
            notes.append("SentriX ne peut pas résoudre son membre Discord sur ce serveur.")
            return notes
        bot_perms = channel.permissions_for(me) if channel is not None else me.guild_permissions
        if required and not bot_perms.administrator and not getattr(bot_perms, required, False):
            notes.append(f"SentriX n'a pas `{required}` dans ce salon/serveur.")
        if channel is not None:
            if not bot_perms.view_channel:
                notes.append(f"Le rôle {me.top_role.mention} doit avoir **Voir le salon** dans {getattr(channel, 'mention', '#salon')}.")
            if not bot_perms.send_messages:
                notes.append(f"Le rôle {me.top_role.mention} doit avoir **Envoyer des messages** dans {getattr(channel, 'mention', '#salon')}.")
        if target is not None:
            if actor.id != guild.owner_id and actor.top_role <= target.top_role:
                notes.append(f"Ton rôle {actor.top_role.mention} doit être au-dessus de {target.top_role.mention}.")
            if me.top_role <= target.top_role:
                notes.append(f"Le rôle {me.top_role.mention} doit être au-dessus de {target.top_role.mention}.")
        if not notes:
            notes.append("Aucun blocage de permission ou de hiérarchie évident n'a été détecté.")
        return notes

    async def assistant_answer(self, guild: discord.Guild, question: str) -> str:
        q = str(question or "").casefold()
        if any(word in q for word in ("sécurité", "securite", "audit", "safe")):
            report = await self.health_report(guild)
            top = list(report.findings[:3])
            details = "\n".join(f"• {item.title} — {item.remediation}" for item in top) or "• Aucun problème majeur détecté."
            return f"Sécurité : **{report.score}/100 ({report.label})**.\n{details}"
        if any(word in q for word in ("setup", "config", "installer", "configure")):
            plan = await self.setup_proposal(guild)
            proposed = ", ".join(plan.proposed) or "aucune correction automatique"
            manual = ", ".join(plan.manual) or "aucune étape manuelle"
            return f"Plan setup (score {plan.score}/100) : corrections proposées : **{proposed}**. Étapes manuelles : **{manual}**."
        if any(word in q for word in ("erreur", "bug", "panne", "incident")):
            recent = list(self.incidents)[-5:]
            if not recent:
                return "Aucun warning/error runtime récent n'a été capturé par le centre de santé."
            return "Incidents récents :\n" + "\n".join(f"• [{x['level']}] {x['message'][:160]}" for x in recent)
        return "Je peux analyser la **sécurité**, le **setup/config**, les **permissions** et les **incidents** du serveur à partir des données réelles de SentriX."


class SecurityFixView(discord.ui.View):
    def __init__(self, ops: SentriXOps, guild_id: int, author_id: int, findings: tuple[HealthFinding, ...]):
        super().__init__(timeout=180)
        self.ops = ops
        self.guild_id = guild_id
        self.author_id = author_id
        fixable = [item for item in findings if item.auto_fixable][:4]
        for item in fixable:
            button = discord.ui.Button(label=f"Corriger {item.code.split('.', 1)[-1]}", style=discord.ButtonStyle.success, custom_id=f"sxops:fix:{item.code}")
            async def callback(interaction: discord.Interaction, *, code=item.code):
                if interaction.user.id != self.author_id:
                    return await interaction.response.send_message("Ce panneau appartient à un autre administrateur.", ephemeral=True)
                guild = interaction.guild
                if guild is None:
                    return await interaction.response.send_message("Serveur introuvable.", ephemeral=True)
                try:
                    text = await self.ops.apply_safe_fix(guild, interaction.user.id, code)
                except Exception as exc:
                    return await interaction.response.send_message(f"Correction impossible : {exc}", ephemeral=True)
                await interaction.response.send_message(text, ephemeral=True)
            button.callback = callback
            self.add_item(button)


class OpsCenter(commands.Cog, name="SentriXOpsV111"):
    def __init__(self, bot: commands.Bot, ops: SentriXOps):
        self.bot = bot
        self.ops = ops

    @commands.group(name="manage", aliases=["gerer"], invoke_without_command=True)
    @checks.is_owner_or_admin()
    async def manage(self, ctx: commands.Context):
        e = embeds.brand(
            "Centre d'opérations SentriX",
            "Une interface admin sans nouvelle racine slash : santé, sécurité, versions de config, historique, audit et simulations.",
        )
        e.add_field(name="Diagnostic", value="`+manage health` • `+manage security` • `+manage incidents`", inline=False)
        e.add_field(name="Configuration", value="`+manage setup` • `+manage snapshot [nom]` • `+manage history` • `+manage rollback <id>`", inline=False)
        e.add_field(name="Contrôle", value="`+manage duplicates` • `+manage simulate <sanction|join|verification|ticket|log|raid>` • `+manage ask <question>`", inline=False)
        await panels.envoyer(ctx, panels.depuis_embed(e))

    @manage.command(name="health")
    async def manage_health(self, ctx: commands.Context):
        report = await self.ops.health_report(ctx.guild)
        colour = 0x23A559 if report.score >= 75 else (0xF0B232 if report.score >= 50 else 0xF23F43)
        e = discord.Embed(title="Santé SentriX", description=f"**{report.score}/100 — {report.label}**", colour=colour)
        e.add_field(name="Runtime", value=f"DB : {'OK' if report.db_ok else 'ERREUR'}\nLatence : {report.latency_ms} ms\nExtensions : {report.extensions_loaded}\nIncidents 1h : {report.recent_incidents}", inline=False)
        if report.findings:
            for finding in report.findings[:8]:
                e.add_field(name=f"{finding.severity.upper()} • {finding.title}", value=f"{finding.detail}\n**Correction :** {finding.remediation}", inline=False)
        else:
            e.add_field(name="Résultat", value="Aucun problème important détecté.", inline=False)
        await panels.envoyer(ctx, panels.depuis_embed(e))

    @manage.command(name="security")
    async def manage_security(self, ctx: commands.Context):
        report = await self.ops.health_report(ctx.guild)
        security_findings = tuple(f for f in report.findings if f.code.startswith(("automod.", "botperm.", "hierarchy.", "config.mod-role")))
        security_score = compute_health_score(security_findings)
        e = embeds.brand("Sécurité intelligente SentriX", f"**{security_score}/100** — {health_label(security_score)}")
        if not security_findings:
            e.add_field(name="Résultat", value="Aucun problème de sécurité prioritaire détecté.", inline=False)
        for finding in security_findings[:8]:
            e.add_field(name=finding.title, value=f"{finding.detail}\n**À faire :** {finding.remediation}", inline=False)
        view = SecurityFixView(self.ops, ctx.guild.id, ctx.author.id, security_findings)
        await panels.envoyer(ctx, panels.avec_composants(panels.depuis_embed(e), view))

    @manage.command(name="setup")
    async def manage_setup(self, ctx: commands.Context):
        proposal = await self.ops.setup_proposal(ctx.guild)
        e = embeds.brand("Analyse automatique du setup", f"État actuel : **{proposal.score}/100**. Rien n'est modifié tant que tu ne confirmes pas une action.")
        e.add_field(name="Déjà prêt", value="\n".join(f"• {x}" for x in proposal.ready) or "Aucun", inline=False)
        e.add_field(name="Corrections sûres proposées", value="\n".join(f"• {x}" for x in proposal.proposed) or "Aucune", inline=False)
        e.add_field(name="À choisir manuellement", value="\n".join(f"• {x}" for x in proposal.manual) or "Aucune", inline=False)
        e.add_field(name="Continuer", value="Utilise `+setup` pour ouvrir les panneaux existants. Lance `+manage snapshot avant-setup` avant un gros changement.", inline=False)
        await panels.envoyer(ctx, panels.depuis_embed(e))

    @manage.command(name="snapshot")
    async def manage_snapshot(self, ctx: commands.Context, *, label: str = "Snapshot manuel"):
        sid = await self.ops.capture_snapshot(ctx.guild.id, ctx.author.id, label=label, source="manual")
        await self.ops.log_admin_action(ctx.guild.id, ctx.author.id, "config.snapshot", target_type="snapshot", target_id=str(sid), after={"label": label})
        await panels.envoyer(ctx, panels.depuis_embed(embeds.success(f"Configuration SentriX sauvegardée : **snapshot #{sid}**. Les 10 versions les plus récentes sont conservées.")))

    @manage.command(name="history")
    async def manage_history(self, ctx: commands.Context, limit: int = 10):
        snapshots = await self.ops.list_snapshots(ctx.guild.id, limit=min(limit, 10))
        actions = await self.ops.list_admin_actions(ctx.guild.id, limit=min(limit, 10))
        e = embeds.neutral("Historique administratif SentriX")
        e.add_field(name="Versions de configuration", value="\n".join(f"`#{r['id']}` <t:{r['created_at']}:R> — {r['label']} (<@{r['actor_id']}>)" for r in snapshots) or "Aucun snapshot", inline=False)
        e.add_field(name="Actions récentes", value="\n".join(f"`#{r['id']}` <t:{r['created_at']}:R> — **{r['action']}** par <@{r['actor_id']}>" for r in actions) or "Aucune action", inline=False)
        await panels.envoyer(ctx, panels.depuis_embed(e))

    @manage.command(name="rollback")
    async def manage_rollback(self, ctx: commands.Context, snapshot_id: int):
        preview = embeds.warning(
            f"Restaurer la configuration SentriX depuis le **snapshot #{snapshot_id}** ?\n\nUn snapshot de sécurité sera créé juste avant. Aucun rôle/salon n'est supprimé par ce rollback.",
            title="Confirmer le rollback",
        )
        view = helpers.ConfirmView(ctx.author.id)
        msg = await panels.envoyer(ctx, panels.avec_composants(panels.depuis_embed(preview), view))
        await view.wait()
        if not view.value:
            return await panels.editer(msg, panels.depuis_embed(embeds.error("Rollback annulé.")))
        try:
            result = await self.ops.restore_snapshot(ctx.guild.id, ctx.author.id, snapshot_id)
        except LookupError:
            return await panels.editer(msg, panels.depuis_embed(embeds.error("Snapshot introuvable sur ce serveur.")))
        await panels.editer(msg, panels.depuis_embed(embeds.success(f"Snapshot **#{result['restored']}** restauré. Snapshot de sécurité créé juste avant : **#{result['safety_snapshot']}**.")))

    @manage.command(name="duplicates")
    async def manage_duplicates(self, ctx: commands.Context):
        rows = self.ops.duplicate_command_audit()
        e = embeds.neutral("Audit des commandes SentriX")
        e.description = f"**{len(rows)}** conflit(s)/doublon(s) potentiel(s) détecté(s). Cet audit ne supprime rien automatiquement."
        if rows:
            e.add_field(name="Premiers résultats", value="\n".join(f"• `{a}` ↔ `{b}` — {reason}" for a, b, reason in rows[:20])[:1024], inline=False)
        await panels.envoyer(ctx, panels.depuis_embed(e))

    @manage.command(name="incidents")
    async def manage_incidents(self, ctx: commands.Context):
        rows = list(self.ops.incidents)[-10:]
        e = embeds.neutral("Incidents runtime récents")
        e.description = "\n".join(f"<t:{x['at']}:R> **{x['level']}** `{x['logger']}` — {x['message'][:220]}" for x in reversed(rows)) or "Aucun warning/error capturé depuis l'activation du centre d'opérations."
        await panels.envoyer(ctx, panels.depuis_embed(e))

    @manage.command(name="simulate")
    async def manage_simulate(self, ctx: commands.Context, kind: str):
        try:
            plan = build_simulation(kind, target=str(ctx.author.id))
        except ValueError:
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error("Type inconnu. Choisis : sanction, join, verification, ticket, log ou raid.")))
        e = embeds.brand("Simulation SentriX — aucun effet réel", f"Scénario : **{plan['kind']}**\nCible fictive : `{plan['target']}`")
        e.add_field(name="Étapes qui seraient exécutées", value="\n".join(f"{i}. {step}" for i, step in enumerate(plan["steps"], 1)), inline=False)
        e.set_footer(text="DRY-RUN • aucune sanction, aucun salon et aucune donnée utilisateur modifiés")
        await panels.envoyer(ctx, panels.depuis_embed(e))

    @manage.command(name="ask")
    async def manage_ask(self, ctx: commands.Context, *, question: str):
        answer = await self.ops.assistant_answer(ctx.guild, question)
        await panels.envoyer(ctx, panels.depuis_embed(embeds.brand("Assistant administrateur SentriX", answer)))


async def _install_ops(bot: commands.Bot) -> None:
    existing = getattr(bot, "sentrix_ops", None)
    if isinstance(existing, SentriXOps):
        return
    ops = SentriXOps(bot)
    await ops.ensure_schema()
    ops.install_runtime_monitor()
    bot.sentrix_ops = ops
    if bot.get_cog("SentriXOpsV111") is None:
        await bot.add_cog(OpsCenter(bot, ops))

    # Versioning automatique des réglages qui passent par le point d'écriture commun
    # de /setup. Cela couvre les réglages principaux sans modifier leur callback métier.
    try:
        import cogs.configuration as configuration
        original = configuration._appliquer_reglage
        if not getattr(original, "_sentrix_v111", False):
            async def apply_setting_v111(cog, ctx, cle, valeur):
                conf = await cog.bot.db.get_guild_config(ctx.guild.id)
                before = _row_dict(conf) or {}
                sid = await ops.capture_snapshot(ctx.guild.id, ctx.author.id, label=f"Avant {cle}", source="setup-setting")
                result = await original(cog, ctx, cle, valeur)
                await ops.log_admin_action(
                    ctx.guild.id, ctx.author.id, "config.set", target_type="guild_config", target_id=str(cle),
                    before={cle: before.get(cle)}, after={cle: valeur, "snapshot": sid}, reversible=True,
                )
                return result
            apply_setting_v111._sentrix_v111 = True
            apply_setting_v111._sentrix_original = original
            configuration._appliquer_reglage = apply_setting_v111
    except Exception:
        logger.exception("Instrumentation du setup V111 impossible.")

    # AutoMod centralise déjà ses changements dans toggle(); on l'instrumente une fois.
    try:
        automod = bot.get_cog("Automod")
        current = getattr(automod, "toggle", None)
        if callable(current) and not getattr(current, "_sentrix_v111", False):
            async def toggle_v111(ctx, field, etat, _original=current):
                before = _row_dict(await bot.db.get_automod(ctx.guild.id)) or {}
                sid = await ops.capture_snapshot(ctx.guild.id, ctx.author.id, label=f"Avant AutoMod {field}", source="automod-toggle")
                result = await _original(ctx, field, etat)
                after = _row_dict(await bot.db.get_automod(ctx.guild.id)) or {}
                await ops.log_admin_action(
                    ctx.guild.id, ctx.author.id, "automod.set", target_type="automod", target_id=str(field),
                    before={field: before.get(field)}, after={field: after.get(field), "snapshot": sid}, reversible=True,
                )
                return result
            toggle_v111._sentrix_v111 = True
            automod.toggle = toggle_v111
    except Exception:
        logger.exception("Instrumentation AutoMod V111 impossible.")


def install() -> None:
    """S'installe après V110 en enveloppant le prepare_bot final."""
    import sentrix_v95_runtime as v95

    current = v95.prepare_bot
    if getattr(current, "_sentrix_ops_v111", False):
        return

    async def prepare_bot_v111(bot):
        result = await current(bot)
        try:
            await _install_ops(bot)
        except Exception:
            logger.exception("Installation du centre d'opérations V111 impossible.")
        return result

    prepare_bot_v111._sentrix_ops_v111 = True
    prepare_bot_v111._sentrix_original = current
    v95.prepare_bot = prepare_bot_v111
    logger.info("SentriX Ops V111 installé.")


__all__ = [
    "GuildHealthReport",
    "HealthFinding",
    "SetupProposal",
    "SentriXOps",
    "build_simulation",
    "compute_health_score",
    "health_label",
    "install",
]
