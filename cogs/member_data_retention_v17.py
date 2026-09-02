"""Conservation permanente des données membres (audit V17).

Règle centrale : un départ, kick ou ban signifie uniquement que le membre n'est plus
présent sur le serveur. Cela ne signifie JAMAIS que sa progression doit être supprimée.

Cette couche additive :
- protège les tables de progression contre les DELETE/DROP accidentels ;
- laisse passer une suppression uniquement dans un contexte de reset explicite ;
- ajoute une confirmation aux commandes de reset existantes ;
- journalise l'état critique d'un membre lors d'un départ/ban ;
- réutilise cet état comme filet de sécurité au retour si une ligne critique manque ;
- renforce SQLite avec synchronous=FULL ;
- déclenche des snapshots PostgreSQL périodiques et après départ/ban lorsque le stockage
  durable est configuré.

Les données restent séparées par (guild_id, user_id). Aucun listener de départ/ban ne
réinitialise XP, messages, portefeuille, banque ou statistiques.
"""
from __future__ import annotations

import asyncio
import contextvars
import functools
import json
import logging
import os
import re
import time
from contextlib import contextmanager
from types import MethodType
from typing import Any, Awaitable, Callable

import discord
from discord.ext import commands

from utils import embeds
from utils import sentrix_panels as panels

logger = logging.getLogger("bot.member-data-retention-v17")

# Tables où une suppression n'est jamais une opération normale liée à un départ/ban.
# Les historiques économie/jeux sont inclus car ils servent aux statistiques et à l'audit.
PROTECTED_PROGRESS_TABLES = frozenset({
    "levels",
    "message_counts",
    "economy",
    "profiles",
    "voice_totals",
    "economy_transactions",
    "game_transactions",
    "ultimate_badges",
    "ultimate_member_seen",
})

# Tables explicitement auditées pour les listeners leave/ban. Certaines peuvent avoir des
# suppressions légitimes ailleurs (ex. consommation d'un objet), donc elles ne sont pas
# toutes bloquées globalement par la garde SQL.
AUDITED_MEMBER_PROGRESS_TABLES = PROTECTED_PROGRESS_TABLES | frozenset({
    "inventory",
    "shop_role_purchases",
    "pets",
    "game_cooldowns",
    "invite_bonuses",
    "member_invites",
    "reputation_history",
})

_DESTRUCTIVE_SQL_RE = re.compile(
    r"\b(?:DELETE\s+FROM|DROP\s+TABLE(?:\s+IF\s+EXISTS)?)\s+[`\"\[]?([A-Za-z0-9_]+)",
    flags=re.IGNORECASE,
)
_EXPLICIT_DATA_RESET: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "sentrix_explicit_data_reset", default=False
)

RETENTION_SCHEMA = """
CREATE TABLE IF NOT EXISTS member_data_retention_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_member_data_retention_lookup
ON member_data_retention_events (guild_id, user_id, created_at DESC, id DESC);
"""

# Copie légère des valeurs indispensables à l'exemple demandé. La base principale reste
# la source de vérité ; ce payload n'est qu'un filet de restauration en cas de suppression
# accidentelle future ayant réussi à contourner la garde.
CORE_SNAPSHOT_COLUMNS: dict[str, tuple[str, ...]] = {
    "levels": ("xp", "level", "last_message_time"),
    "message_counts": ("count",),
    "economy": (
        "cash",
        "bank",
        "last_daily",
        "last_weekly",
        "last_work",
        "last_crime",
        "last_beg",
        "last_rob",
        "protected_until",
    ),
    "voice_totals": ("seconds",),
}

RESET_COMMAND_LABELS = {
    "reset-levels": "tous les niveaux et XP du serveur",
    "reset-economy": "tous les soldes économiques du serveur",
    "represet": "la réputation du membre sélectionné",
}


class ProtectedProgressDeletionError(RuntimeError):
    """Levée lorsqu'un code tente de supprimer de la progression sans reset explicite."""


def destructive_progress_tables(sql: str) -> set[str]:
    """Retourne les tables de progression visées par un DELETE/DROP SQL."""
    found = {match.group(1).casefold() for match in _DESTRUCTIVE_SQL_RE.finditer(str(sql or ""))}
    return found & set(PROTECTED_PROGRESS_TABLES)


@contextmanager
def explicit_data_reset():
    """Autorise temporairement une suppression volontaire et confirmée."""
    token = _EXPLICIT_DATA_RESET.set(True)
    try:
        yield
    finally:
        _EXPLICIT_DATA_RESET.reset(token)


def _install_db_guard(bot: commands.Bot) -> bool:
    db = bot.db
    current = db.execute
    if getattr(current, "_sentrix_member_retention_guard_v17", False):
        return True

    original = current

    async def guarded_execute(_db_self, query: str, params: tuple = ()):
        targeted = destructive_progress_tables(query)
        if targeted and not _EXPLICIT_DATA_RESET.get():
            tables = ", ".join(sorted(targeted))
            logger.error(
                "Suppression de progression bloquée hors reset explicite: tables=%s sql=%r",
                tables,
                str(query)[:300],
            )
            raise ProtectedProgressDeletionError(
                f"Suppression de données membre interdite hors reset explicite ({tables})."
            )
        return await original(query, params)

    guarded_execute._sentrix_member_retention_guard_v17 = True
    guarded_execute._sentrix_original = original
    db.execute = MethodType(guarded_execute, db)
    logger.info("Garde SQL V17 installée sur les tables de progression membres.")
    return True


class ResetConfirmationView(discord.ui.View):
    """Confirmation obligatoire pour toute commande de reset de progression existante."""

    def __init__(
        self,
        *,
        requester_id: int,
        description: str,
        runner: Callable[[], Awaitable[Any]],
    ) -> None:
        super().__init__(timeout=60)
        self.requester_id = requester_id
        self.description = description
        self.runner = runner
        self.used = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.requester_id:
            await panels.envoyer(interaction.response, panels.depuis_embed(embeds.error('Cette confirmation appartient à un autre utilisateur.')), ephemere=True)
            return False
        return True

    @discord.ui.button(label="Confirmer le reset", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.used:
            return await panels.envoyer(interaction.response, panels.depuis_embed(embeds.error('Ce reset a déjà été traité.')), ephemere=True)
        self.used = True
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(
            embed=embeds.warning(
                f"Reset confirmé : **{self.description}**.\nL'action est en cours et sera journalisée."
            ),
            view=self,
        )
        try:
            with explicit_data_reset():
                await self.runner()
        finally:
            self.stop()

    @discord.ui.button(label="Annuler", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.used = True
        await interaction.response.edit_message(
            embed=embeds.neutral(
                "Reset annulé",
                "Aucune progression n'a été supprimée ni remise à zéro.",
            ),
            view=None,
        )
        self.stop()


async def _send_reset_confirmation(
    ctx: commands.Context,
    description: str,
    runner: Callable[[], Awaitable[Any]],
):
    view = ResetConfirmationView(
        requester_id=ctx.author.id,
        description=description,
        runner=runner,
    )
    return await ctx.send(
        embed=embeds.warning(
            "Cette action est **volontairement séparée** d'un ban, kick ou départ.\n\n"
            f"Elle va réinitialiser **{description}**.\n"
            "Un ban ne déclenche jamais cette suppression.\n\n"
            "Confirmez uniquement si vous voulez réellement effacer cette progression.",
            title="Confirmation de suppression de données",
        ),
        view=view,
    )


def _install_reset_confirmations(bot: commands.Bot) -> list[str]:
    patched: list[str] = []
    for command_name, description in RESET_COMMAND_LABELS.items():
        command = bot.get_command(command_name)
        if command is None:
            logger.warning("Commande de reset introuvable pendant l'audit V17: %s", command_name)
            continue
        if getattr(command.callback, "_sentrix_reset_confirmation_v17", False):
            patched.append(command_name)
            continue

        original = command.callback
        original_params = command.params.copy()

        @functools.wraps(original)
        async def wrapped(cog_self, ctx: commands.Context, *args, __original=original,
                          __description=description, **kwargs):
            async def runner():
                return await __original(cog_self, ctx, *args, **kwargs)

            return await _send_reset_confirmation(ctx, __description, runner)

        wrapped._sentrix_reset_confirmation_v17 = True
        wrapped._sentrix_original = original
        command.callback = wrapped
        # discord.py a déjà analysé les paramètres à partir de la fonction historique.
        command.params = original_params
        patched.append(command_name)

    logger.info("Confirmations de reset V17 installées: %s", ", ".join(patched) or "aucune")
    return patched


def _snapshot_interval_seconds() -> int:
    try:
        value = int(os.getenv("SENTRIX_MEMBER_DATA_SNAPSHOT_INTERVAL", "60") or 60)
    except (TypeError, ValueError):
        value = 60
    return max(30, min(300, value))


class MemberDataRetentionV17(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._periodic_task: asyncio.Task | None = None
        self._event_snapshot_task: asyncio.Task | None = None
        self._snapshot_lock = asyncio.Lock()
        self._pending_snapshot_reasons: set[str] = set()

    async def cog_load(self):
        _install_db_guard(self.bot)
        _install_reset_confirmations(self.bot)

        # FULL force SQLite à synchroniser le journal avec le stockage avant de confirmer
        # un commit. WAL reste actif via Database.connect().
        try:
            await self.bot.db.execute("PRAGMA synchronous=FULL")
        except Exception:
            logger.exception("Impossible d'activer PRAGMA synchronous=FULL.")

        for statement in [part.strip() for part in RETENTION_SCHEMA.split(";") if part.strip()]:
            await self.bot.db.execute(statement)

        durable = getattr(self.bot, "sentrix_durable_store", None)
        if durable is not None and getattr(durable, "configured", False):
            self._periodic_task = asyncio.create_task(
                self._periodic_snapshot_loop(),
                name="sentrix-member-data-periodic-snapshot",
            )
            logger.info(
                "Snapshots PostgreSQL membres V17 actifs toutes les %ss.",
                _snapshot_interval_seconds(),
            )
        else:
            logger.warning(
                "Stockage PostgreSQL durable non configuré: SQLite reste persistant localement, "
                "mais un changement de machine nécessite un volume /data persistant pour garantir "
                "la conservation inter-machine."
            )

    def cog_unload(self):
        for task in (self._periodic_task, self._event_snapshot_task):
            if task is not None and not task.done():
                task.cancel()

    async def _read_core_snapshot(self, guild_id: int, user_id: int) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        for table, columns in CORE_SNAPSHOT_COLUMNS.items():
            column_sql = ", ".join(columns)
            try:
                row = await self.bot.db.fetchone(
                    f"SELECT {column_sql} FROM {table} WHERE guild_id = ? AND user_id = ?",
                    (guild_id, user_id),
                )
            except Exception:
                logger.exception("Lecture snapshot membre impossible pour table=%s", table)
                continue
            if row is not None:
                payload[table] = {column: row[index] for index, column in enumerate(columns)}
        return payload

    async def _record_retention_event(self, guild_id: int, user_id: int, event_type: str) -> None:
        payload = await self._read_core_snapshot(guild_id, user_id)
        await self.bot.db.execute(
            "INSERT INTO member_data_retention_events "
            "(guild_id,user_id,event_type,payload_json,created_at) VALUES (?,?,?,?,?)",
            (
                guild_id,
                user_id,
                str(event_type)[:40],
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                int(time.time()),
            ),
        )

    async def _latest_retained_snapshot(self, guild_id: int, user_id: int) -> dict[str, Any]:
        row = await self.bot.db.fetchone(
            "SELECT payload_json FROM member_data_retention_events "
            "WHERE guild_id = ? AND user_id = ? AND event_type IN ('member_remove','member_ban') "
            "ORDER BY created_at DESC, id DESC LIMIT 1",
            (guild_id, user_id),
        )
        if row is None:
            return {}
        try:
            payload = json.loads(row[0] or "{}")
        except (TypeError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    async def _restore_missing_core_rows(self, guild_id: int, user_id: int) -> list[str]:
        """Restaure uniquement les lignes ABSENTES ; une ligne existante n'est jamais écrasée."""
        retained = await self._latest_retained_snapshot(guild_id, user_id)
        restored: list[str] = []

        for table, columns in CORE_SNAPSHOT_COLUMNS.items():
            values = retained.get(table)
            if not isinstance(values, dict):
                continue
            if not all(column in values for column in columns):
                continue
            placeholders = ",".join("?" for _ in range(2 + len(columns)))
            column_sql = ",".join(("guild_id", "user_id", *columns))
            params = (guild_id, user_id, *(values[column] for column in columns))
            cursor = await self.bot.db.execute(
                f"INSERT OR IGNORE INTO {table} ({column_sql}) VALUES ({placeholders})",
                tuple(params),
            )
            # rowcount = 1 uniquement si la ligne manquait réellement.
            if getattr(cursor, "rowcount", 0) == 1:
                restored.append(table)

        # Nouveau membre sans snapshot : créer seulement les lignes de base. INSERT OR
        # IGNORE garantit qu'un ancien membre retrouve exactement ses valeurs existantes.
        await self.bot.db.execute(
            "INSERT OR IGNORE INTO levels (guild_id,user_id,xp,level,last_message_time) "
            "VALUES (?,?,0,0,0)",
            (guild_id, user_id),
        )
        await self.bot.db.execute(
            "INSERT OR IGNORE INTO message_counts (guild_id,user_id,count) VALUES (?,?,0)",
            (guild_id, user_id),
        )
        await self.bot.db.execute(
            "INSERT OR IGNORE INTO economy (guild_id,user_id,cash,bank) VALUES (?,?,0,0)",
            (guild_id, user_id),
        )
        return restored

    def _request_durable_snapshot(self, reason: str) -> None:
        durable = getattr(self.bot, "sentrix_durable_store", None)
        if durable is None or not getattr(durable, "configured", False):
            return
        self._pending_snapshot_reasons.add(str(reason or "member_event")[:40])
        if self._event_snapshot_task is None or self._event_snapshot_task.done():
            self._event_snapshot_task = asyncio.create_task(
                self._debounced_event_snapshot(),
                name="sentrix-member-data-event-snapshot",
            )

    async def _debounced_event_snapshot(self) -> None:
        # Un raid peut produire des dizaines de bans à la seconde. On regroupe les events
        # dans un unique snapshot cohérent au lieu de sauvegarder toute la DB par membre.
        await asyncio.sleep(2)
        reasons = sorted(self._pending_snapshot_reasons)
        self._pending_snapshot_reasons.clear()
        reason = "member_event:" + "+".join(reasons[:4])
        await self._snapshot_now(reason[:80])

    async def _snapshot_now(self, reason: str) -> None:
        durable = getattr(self.bot, "sentrix_durable_store", None)
        if durable is None or not getattr(durable, "configured", False):
            return
        async with self._snapshot_lock:
            try:
                result = await asyncio.wait_for(
                    durable.snapshot(reason=reason, clean_shutdown=False),
                    timeout=60,
                )
                if not result.get("stored"):
                    logger.warning("Snapshot durable membre non stocké: %s", result)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Snapshot durable membre V17 impossible (%s).", reason)

    async def _periodic_snapshot_loop(self) -> None:
        await self.bot.wait_until_ready()
        interval = _snapshot_interval_seconds()
        while not self.bot.is_closed():
            await asyncio.sleep(interval)
            await self._snapshot_now("member_data_periodic")

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        # Quit volontaire, kick ou étape du ban : même traitement = conservation.
        try:
            await self._record_retention_event(member.guild.id, member.id, "member_remove")
        except Exception:
            logger.exception(
                "Journalisation de conservation impossible après départ guild=%s user=%s",
                member.guild.id,
                member.id,
            )
        self._request_durable_snapshot("member_remove")

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User | discord.Member):
        # Déclenché aussi pour un ban fait à la main, par un autre bot ou par AutoMod.
        try:
            await self._record_retention_event(guild.id, user.id, "member_ban")
        except Exception:
            logger.exception(
                "Journalisation de conservation impossible après ban guild=%s user=%s",
                guild.id,
                user.id,
            )
        self._request_durable_snapshot("member_ban")

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        try:
            restored = await self._restore_missing_core_rows(member.guild.id, member.id)
            await self._record_retention_event(member.guild.id, member.id, "member_join")
            if restored:
                logger.warning(
                    "Progression restaurée au retour guild=%s user=%s tables=%s",
                    member.guild.id,
                    member.id,
                    ",".join(restored),
                )
                self._request_durable_snapshot("member_rejoin_restore")
        except Exception:
            logger.exception(
                "Vérification de progression au retour impossible guild=%s user=%s",
                member.guild.id,
                member.id,
            )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MemberDataRetentionV17(bot))
