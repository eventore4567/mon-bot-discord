"""Import CSV/JSON autorisé d'anciens bots vers les données membres de SentriX."""
from __future__ import annotations

import asyncio
import csv
import hashlib
import io
import json
import logging
import time
from dataclasses import dataclass, asdict

import aiosqlite
import discord

from cogs.economy_import import ImportErrorData, _snowflake, _key, MAX_FILE_BYTES, MAX_MEMBERS
from utils import stats_service

logger = logging.getLogger("bot.bot-import")
MAX_BALANCE = 10**12
MAX_XP = 10**10
MAX_STAT = 10**10
_LOCKS: dict[int, asyncio.Lock] = {}
FIELDS = {
    "cash": ("cash", "wallet", "balance", "money", "coins", "argent"),
    "bank": ("bank", "banque", "savings", "bankbalance"),
    "total_xp": ("totalxp", "xptotal", "experience"),
    "xp": ("xp", "currentxp"),
    "level": ("level", "niveau"),
    "messages": ("messages", "messagecount", "totalmessages"),
    "voice_seconds": ("voiceseconds", "voicetime", "totalseconds"),
    "reputation": ("reputation", "rep"),
}


@dataclass(frozen=True)
class ImportedMember:
    user_id: int
    cash: int | None = None
    bank: int | None = None
    total_xp: int | None = None
    messages: int | None = None
    voice_seconds: int | None = None
    reputation: int | None = None


def _number(value, label: str, maximum: int) -> int:
    if value is None or isinstance(value, bool):
        raise ImportErrorData(f"{label} : entier obligatoire.")
    raw = str(value).strip().replace(" ", "").replace("_", "")
    if not raw.isdecimal() or int(raw) > maximum:
        raise ImportErrorData(f"{label} : entier positif valide requis (max {maximum}).")
    return int(raw)


def _rows(payload: bytes | str, filename: str) -> list[dict]:
    if isinstance(payload, bytes):
        if len(payload) > MAX_FILE_BYTES:
            raise ImportErrorData("Fichier supérieur à 512 Ko.")
        try:
            payload = payload.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ImportErrorData("Encodage UTF-8 requis.") from exc
    payload = payload.lstrip("\ufeff")
    if len(payload.encode("utf-8")) > MAX_FILE_BYTES or not payload.strip():
        raise ImportErrorData("Fichier vide ou supérieur à 512 Ko.")
    if filename.casefold().endswith(".json") or payload.lstrip().startswith(("{", "[")):
        try:
            entries = json.loads(payload)
        except ValueError as exc:
            raise ImportErrorData("JSON invalide.") from exc
        if isinstance(entries, dict):
            for key in ("members", "users", "balances", "levels", "data"):
                if key in entries:
                    entries = entries[key]
                    break
        if isinstance(entries, dict):
            entries = [
                {"user_id": uid, **data} if isinstance(data, dict)
                else {"user_id": uid, "total_xp": data}
                for uid, data in entries.items()
            ]
    else:
        try:
            dialect = csv.Sniffer().sniff(payload[:2048], delimiters=",;")
        except csv.Error:
            dialect = csv.excel
        entries = list(csv.DictReader(io.StringIO(payload), dialect=dialect))
    if not isinstance(entries, list) or not 1 <= len(entries) <= MAX_MEMBERS:
        raise ImportErrorData("Entre 1 et 1000 membres requis.")
    return entries


def parse_bot_export(payload: bytes | str, filename: str = "import.csv") -> list[ImportedMember]:
    """xp seul = XP total ; level + xp = XP dans ce niveau."""
    out, seen = [], set()
    for index, record in enumerate(_rows(payload, filename), 1):
        if not isinstance(record, dict):
            raise ImportErrorData(f"Ligne {index} invalide.")
        data = {_key(k): v for k, v in record.items()}
        for group_name in ("economy", "levels", "stats", "profile"):
            group = data.get(group_name)
            if isinstance(group, dict):
                for k, v in group.items():
                    data.setdefault(_key(k), v)
        uid = next((data[k] for k in ("userid", "discordid", "memberid", "id", "user")
                    if k in data), None)
        user_id = _snowflake(uid)
        if user_id in seen:
            raise ImportErrorData(f"Doublon : {user_id}.")
        seen.add(user_id)
        def field(key):
            return next((data[k] for k in FIELDS[key] if k in data and data[k] not in ("", None)), None)
        values = {}
        for key in ("cash", "bank", "messages", "voice_seconds", "reputation"):
            raw = field(key)
            if raw is not None:
                values[key] = _number(raw, key, MAX_BALANCE if key in {"cash", "bank"} else MAX_STAT)
        total, level, xp = field("total_xp"), field("level"), field("xp")
        if total is not None:
            values["total_xp"] = _number(total, "total_xp", MAX_XP)
        elif level is not None:
            lv = _number(level, "level", 2500)
            current = _number(xp, "xp", MAX_XP) if xp is not None else 0
            values["total_xp"] = stats_service.total_xp_for(lv, current)
        elif xp is not None:
            values["total_xp"] = _number(xp, "xp", MAX_XP)
        if "total_xp" in values and values["total_xp"] > MAX_XP:
            raise ImportErrorData(f"XP trop élevé à la ligne {index}.")
        if not values:
            raise ImportErrorData(f"Aucune donnée reconnue à la ligne {index}.")
        out.append(ImportedMember(user_id, **values))
    return sorted(out, key=lambda r: r.user_id)


def _entries(member):
    return (
        ("economy", ("cash", "bank"), (member.cash, member.bank), MAX_BALANCE),
        ("levels", ("xp", "level"), (member.total_xp, member.total_xp), MAX_XP),
        ("message_counts", ("count",), (member.messages,), MAX_STAT),
        ("voice_totals", ("seconds",), (member.voice_seconds,), MAX_STAT),
        ("profiles", ("reputation",), (member.reputation,), MAX_STAT),
    )


async def _execute(conn, backend, sql, args=(), fetch=False):
    if backend == "postgres":
        counter = iter(range(1, 100))
        sql = "".join("$" + str(next(counter)) if char == "?" else char for char in sql)
        return await conn.fetchrow(sql, *args) if fetch else await conn.execute(sql, *args)
    cursor = await conn.execute(sql, args)
    return await cursor.fetchone() if fetch else cursor


async def _apply_members(conn, backend, guild_id, members, mode):
    for member in members:
        for table, columns, imported, limit in _entries(member):
            if all(v is None for v in imported):
                continue
            names = ",".join(columns)
            before = await _execute(
                conn, backend,
                f"SELECT {names} FROM {table} WHERE guild_id=? AND user_id=?"
                + (" FOR UPDATE" if backend == "postgres" else ""),
                (guild_id, member.user_id), fetch=True,
            )
            prior = tuple(int(v or 0) for v in before) if before else (0,) * len(columns)
            if table == "levels":
                previous_total = stats_service.total_xp_for(prior[1], prior[0])
                total = imported[0] + previous_total if mode == "add" else imported[0]
                if total > MAX_XP:
                    raise ImportErrorData(f"XP trop élevé : {member.user_id}.")
                level, xp, _ = stats_service.calculate_level_from_total_xp(total)
                new = (xp, level)
            else:
                new = tuple(
                    old if incoming is None else
                    (old + incoming if mode == "add" else incoming)
                    for old, incoming in zip(prior, imported)
                )
                if any(v > limit for v in new):
                    raise ImportErrorData(f"Montant trop élevé : {member.user_id}.")
            setters = ",".join(f"{col}=excluded.{col}" for col in columns)
            placeholders = ",".join("?" for _ in range(len(columns) + 2))
            await _execute(
                conn, backend,
                f"INSERT INTO {table} (guild_id,user_id,{names}) VALUES ({placeholders}) "
                f"ON CONFLICT(guild_id,user_id) DO UPDATE SET {setters}",
                (guild_id, member.user_id, *new),
            )


async def apply_bot_import(bot, guild_id, actor_id, members, mode, source):
    """Transaction indivisible et digest anti-import répété sur chaque serveur."""
    if mode not in {"add", "replace"} or not 1 <= len(members) <= MAX_MEMBERS:
        raise ImportErrorData("Paramètres d'import invalides.")
    digest = hashlib.sha256(json.dumps(
        [asdict(m) for m in members], sort_keys=True, separators=(",", ":")
    ).encode()).hexdigest()
    lock = _LOCKS.setdefault(int(guild_id), asyncio.Lock())
    async with lock:
        backend = getattr(bot.db, "backend", "sqlite")
        if backend == "postgres":
            import asyncpg
            from database.db import _postgres_url, _postgres_schema
            url = _postgres_url()
            if not url:
                raise ImportErrorData("Connexion PostgreSQL manquante.")
            conn = await asyncpg.connect(
                url, server_settings={"search_path": f'"{_postgres_schema(bot.db.path)}"'},
            )
            tx = conn.transaction()
            await tx.start()
        else:
            conn = await aiosqlite.connect(bot.db.path, timeout=20)
            await conn.execute("BEGIN IMMEDIATE")
        try:
            id_column = (
                "BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY"
                if backend == "postgres" else "INTEGER PRIMARY KEY AUTOINCREMENT"
            )
            await _execute(conn, backend, (
                "CREATE TABLE IF NOT EXISTS bot_migration_batches ("
                f"id {id_column}, guild_id BIGINT NOT NULL, "
                "digest TEXT NOT NULL, source TEXT, mode TEXT, actor_id BIGINT, "
                "members INTEGER, created_at BIGINT, UNIQUE(guild_id,digest))"
            ))
            already = await _execute(
                conn, backend,
                "SELECT 1 FROM bot_migration_batches WHERE guild_id=? AND digest=?",
                (guild_id, digest), fetch=True,
            )
            if already:
                raise ImportErrorData("Cet export a déjà été importé sur ce serveur.")
            await _apply_members(conn, backend, guild_id, members, mode)
            await _execute(
                conn, backend,
                "INSERT INTO bot_migration_batches "
                "(guild_id,digest,source,mode,actor_id,members,created_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (guild_id, digest, source[:120], mode, actor_id, len(members), int(time.time())),
            )
            if backend == "postgres":
                await tx.commit()
            else:
                await conn.commit()
        except Exception:
            if backend == "postgres":
                await tx.rollback()
            else:
                await conn.rollback()
            raise
        finally:
            await conn.close()
        stats_service.invalidate_rank_cache(bot, guild_id)
        return len(members)


def _is_admin(interaction, guild_id, user_id):
    m = interaction.user
    return bool(
        interaction.guild_id == guild_id and interaction.guild
        and m.id == user_id and
        (interaction.guild.owner_id == m.id or
         getattr(m.guild_permissions, "administrator", False))
    )


def _preview(members, filename):
    fields = (
        ("Économie", ("cash", "bank")), ("XP / Niveaux", ("total_xp",)),
        ("Messages", ("messages",)), ("Vocal", ("voice_seconds",)),
        ("Réputation", ("reputation",)),
    )
    summary = "\n".join(
        f"**{label}** : {sum(any(getattr(m, key) is not None for key in keys) for m in members)} membre(s)"
        for label, keys in fields
        if any(any(getattr(m, key) is not None for key in keys) for m in members)
    )
    return discord.Embed(
        title="Aperçu de l'import d'un bot",
        description=(
            f"{len(members)} membre(s) · {discord.utils.escape_markdown(filename[:80])}\n"
            f"{summary}\n\n**Ajouter** cumule, **Remplacer** remplace les colonnes présentes.\n"
            "Aucun changement avant confirmation."
        ),
        colour=0x5865F2,
    )


class ImportPreview(discord.ui.View):
    def __init__(self, bot, guild_id, user_id, members, filename, mode=None):
        super().__init__(timeout=600)
        self.bot, self.guild_id, self.user_id = bot, guild_id, user_id
        self.members, self.filename, self.mode = members, filename, mode
        self.done = False

    async def interaction_check(self, interaction):
        if self.done or not _is_admin(interaction, self.guild_id, self.user_id):
            await interaction.response.send_message("Import indisponible.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Ajouter", style=discord.ButtonStyle.primary)
    async def add(self, interaction, _):
        await interaction.response.edit_message(
            embed=discord.Embed(title="Confirmer l'ajout", description=f"Ajouter les données de {len(self.members)} membres ?"),
            view=ImportPreview(self.bot, self.guild_id, self.user_id, self.members, self.filename, "add"),
        )

    @discord.ui.button(label="Remplacer", style=discord.ButtonStyle.secondary)
    async def replace(self, interaction, _):
        await interaction.response.edit_message(
            embed=discord.Embed(title="Confirmer le remplacement", description=f"Remplacer les valeurs présentes de {len(self.members)} membres ?"),
            view=ImportPreview(self.bot, self.guild_id, self.user_id, self.members, self.filename, "replace"),
        )

    @discord.ui.button(label="Confirmer l'import", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction, _):
        if self.mode not in {"add", "replace"}:
            return await interaction.response.send_message("Sélectionne Ajouter ou Remplacer.", ephemeral=True)
        self.done = True
        await interaction.response.defer()
        try:
            count = await apply_bot_import(
                self.bot, self.guild_id, self.user_id, self.members, self.mode, self.filename,
            )
        except ImportErrorData as exc:
            return await interaction.edit_original_response(
                embed=discord.Embed(title="Import refusé", description=str(exc)), view=None,
            )
        except Exception:
            logger.exception("Migration bot refusée serveur=%s", self.guild_id)
            return await interaction.edit_original_response(
                embed=discord.Embed(title="Erreur d'import", description="Aucune écriture partielle validée."), view=None,
            )
        await interaction.edit_original_response(
            embed=discord.Embed(
                title="Données importées",
                description=f"{count} membres transférés avec succès.",
                colour=0x23A559,
            ),
            view=None,
        )

    @discord.ui.button(label="Annuler", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction, _):
        self.done = True
        await interaction.response.edit_message(
            embed=discord.Embed(title="Import annulé", description="Aucune donnée modifiée."),
            view=None,
        )


class ImportModal(discord.ui.Modal, title="Importer les données d'un bot"):
    def __init__(self, bot, guild_id, user_id):
        super().__init__()
        self.bot, self.guild_id, self.user_id = bot, guild_id, user_id
        self.payload = discord.ui.TextInput(
            label="CSV ou JSON (4000 caractères max.)",
            placeholder="user_id,cash,bank,level,xp\n123456789012345678,2000,0,12,80",
            style=discord.TextStyle.paragraph, max_length=4000,
        )
        self.add_item(self.payload)

    async def on_submit(self, interaction):
        if not _is_admin(interaction, self.guild_id, self.user_id):
            return await interaction.response.send_message("Administrateur requis.", ephemeral=True)
        try:
            members = parse_bot_export(str(self.payload.value), "saisie.csv")
        except ImportErrorData as exc:
            return await interaction.response.send_message(str(exc), ephemeral=True)
        return await interaction.response.send_message(
            embed=_preview(members, "Saisie manuelle"),
            view=ImportPreview(self.bot, self.guild_id, self.user_id, members, "saisie.csv"),
            ephemeral=True,
        )


class ImportEntry(discord.ui.View):
    def __init__(self, bot, guild_id, user_id):
        super().__init__(timeout=300)
        self.bot, self.guild_id, self.user_id = bot, guild_id, user_id

    async def interaction_check(self, interaction):
        if not _is_admin(interaction, self.guild_id, self.user_id):
            await interaction.response.send_message("Administrateur requis.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Coller CSV / JSON", style=discord.ButtonStyle.primary)
    async def paste(self, interaction, _):
        await interaction.response.send_modal(ImportModal(self.bot, self.guild_id, self.user_id))

    @discord.ui.button(label="Importer un fichier", style=discord.ButtonStyle.secondary)
    async def file(self, interaction, _):
        await interaction.response.send_message(
            "Envoie un fichier CSV ou JSON autorisé en MP à SentriX (512 Ko max.) dans les trois minutes.",
            ephemeral=True,
        )
        def check(message):
            return message.guild is None and message.author.id == self.user_id and len(message.attachments or ()) == 1
        try:
            message = await self.bot.wait_for("message", check=check, timeout=180)
            attachment = message.attachments[0]
            if not attachment.filename.casefold().endswith((".csv", ".json")):
                raise ImportErrorData("Format CSV ou JSON requis.")
            if attachment.size > MAX_FILE_BYTES:
                raise ImportErrorData("Fichier trop volumineux.")
            members = parse_bot_export(await attachment.read(), attachment.filename)
            await interaction.followup.send(
                embed=_preview(members, attachment.filename),
                view=ImportPreview(self.bot, self.guild_id, self.user_id, members, attachment.filename),
                ephemeral=True,
            )
        except asyncio.TimeoutError:
            await interaction.followup.send("Temps écoulé. Relance /setup.", ephemeral=True)
        except ImportErrorData as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
        except (discord.HTTPException, OSError):
            await interaction.followup.send("Fichier illisible.", ephemeral=True)


async def open_import_panel(bot, interaction, guild_id):
    if not _is_admin(interaction, guild_id, interaction.user.id):
        return await interaction.response.send_message("Seuls les administrateurs peuvent importer.", ephemeral=True)
    return await interaction.response.send_message(
        embed=discord.Embed(
            title="Importer les données d'un autre bot",
            description=(
                "**Économie, XP, niveaux, messages, vocal et réputation**.\n\n"
                "Export CSV ou JSON autorisé avec les ID Discord.\n"
                "Colonnes possibles : user_id,cash,bank,level,xp,messages,voice_seconds,reputation.\n"
                "Les colonnes absentes restent inchangées. Confirmation avant import.\n"
                "Impossible de lire la base privée d'un autre bot sans son export."
            ),
            colour=0x5865F2,
        ),
        view=ImportEntry(bot, guild_id, interaction.user.id),
        ephemeral=True,
    )
