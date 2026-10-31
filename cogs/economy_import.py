"""Import d'exports économiques externes dans SentriX.

Un export fourni par un administrateur est requis. Aucun accès aux données privées
des bots tiers. L'aperçu ne modifie rien, puis l'import est transactionnel et audité.
"""
from __future__ import annotations

import asyncio
import csv
import hashlib
import io
import json
import logging
import time
from dataclasses import dataclass

import aiosqlite
import discord

logger = logging.getLogger("bot.economy-import")

MAX_FILE_BYTES = 512 * 1024
MAX_MEMBERS = 1000
MAX_AMOUNT = 10**12
FILENAME_EXTENSIONS = (".csv", ".json")
_USER_FIELDS = ("userid", "discordid", "memberid", "id", "user", "membre")
_CASH_FIELDS = ("cash", "wallet", "balance", "money", "coins", "argent", "pieces", "points")
_BANK_FIELDS = ("bank", "banque", "bankbalance", "savings")
_INSTALLED = False


class ImportErrorData(ValueError):
    """Format invalide, données incompatibles ou import déjà réalisé."""


@dataclass(frozen=True)
class MemberBalance:
    user_id: int
    cash: int
    bank: int


def _key(value: object) -> str:
    return "".join(ch for ch in str(value).lower() if ch.isalnum())


def _field(record: dict, names: tuple[str, ...]):
    normal = {_key(key): value for key, value in record.items()}
    for name in names:
        if name in normal:
            return normal[name]
    return None


def _number(raw: object, label: str) -> int:
    if isinstance(raw, bool) or raw is None:
        raise ImportErrorData(f"{label} : nombre entier obligatoire.")
    text = str(raw).strip().replace(" ", "").replace("_", "")
    if not text.isdecimal():
        raise ImportErrorData(f"{label} : montant non valide ({str(raw)[:30]}).")
    value = int(text)
    if value > MAX_AMOUNT:
        raise ImportErrorData(f"{label} : le montant dépasse la limite autorisée.")
    return value


def _snowflake(raw: object) -> int:
    if isinstance(raw, bool) or raw is None:
        raise ImportErrorData("Identifiant Discord manquant.")
    text = str(raw).strip()
    if not text.isdecimal() or not (15 <= len(text) <= 22):
        raise ImportErrorData("Chaque membre doit avoir un identifiant Discord numérique (15 à 22 chiffres).")
    return int(text)


def parse_export(payload: bytes | str, filename: str = "export.csv") -> list[MemberBalance]:
    """Accepte CSV (séparateur virgule/point-virgule) ou JSON standard.

    CSV : user_id,cash,bank. JSON : une liste de ces objets ou un conteneur
    members/users/balances/data. Les champs peuvent avoir des alias usuels.
    """
    if isinstance(payload, bytes):
        if len(payload) > MAX_FILE_BYTES:
            raise ImportErrorData("Fichier trop volumineux (limite : 512 Ko).")
        try:
            text = payload.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ImportErrorData("Le fichier doit être encodé en UTF-8.") from exc
    else:
        text = payload.lstrip("\ufeff")
        if len(text.encode("utf-8")) > MAX_FILE_BYTES:
            raise ImportErrorData("Fichier trop volumineux (limite : 512 Ko).")
    if not text.strip():
        raise ImportErrorData("Fichier vide.")
    if filename.lower().endswith(".json") or text.lstrip().startswith(("{", "[")):
        try:
            entries = json.loads(text)
        except (ValueError, TypeError) as exc:
            raise ImportErrorData("JSON invalide.") from exc
        if isinstance(entries, dict):
            for key in ("members", "users", "balances", "data"):
                if key in entries:
                    entries = entries[key]
                    break
        if isinstance(entries, dict):
            entries = [
                {"user_id": user_id, **value} if isinstance(value, dict)
                else {"user_id": user_id, "cash": value}
                for user_id, value in entries.items()
            ]
    else:
        try:
            dialect = csv.Sniffer().sniff(text[:2048], delimiters=",;")
        except csv.Error:
            dialect = csv.excel
        try:
            entries = list(csv.DictReader(io.StringIO(text), dialect=dialect))
        except csv.Error as exc:
            raise ImportErrorData("CSV invalide.") from exc
    if not isinstance(entries, list) or not entries:
        raise ImportErrorData("Aucun membre trouvé dans l'export.")
    if len(entries) > MAX_MEMBERS:
        raise ImportErrorData(f"Trop de membres (maximum {MAX_MEMBERS} par fichier).")

    balances: list[MemberBalance] = []
    seen: set[int] = set()
    for index, entry in enumerate(entries, 1):
        if not isinstance(entry, dict):
            raise ImportErrorData(f"Ligne {index} : objet attendu.")
        user_id = _snowflake(_field(entry, _USER_FIELDS))
        if user_id in seen:
            raise ImportErrorData(f"Doublon : identifiant {user_id}.")
        seen.add(user_id)
        cash_raw = _field(entry, _CASH_FIELDS)
        bank_raw = _field(entry, _BANK_FIELDS)
        if cash_raw is None and bank_raw is None:
            raise ImportErrorData(f"Ligne {index} : colonne argent ou banque manquante.")
        cash = _number(cash_raw, "Argent") if cash_raw is not None else 0
        bank = _number(bank_raw, "Banque") if bank_raw is not None else 0
        balances.append(MemberBalance(user_id, cash, bank))
    return sorted(balances, key=lambda entry: entry.user_id)


def _digest(balances: list[MemberBalance]) -> str:
    canonical = [[item.user_id, item.cash, item.bank] for item in balances]
    raw = json.dumps(canonical, separators=(",", ":")).encode("ascii")
    return hashlib.sha256(raw).hexdigest()


def _admin(interaction: discord.Interaction, guild_id: int, author_id: int) -> bool:
    member = interaction.user
    return bool(
        interaction.guild_id == guild_id
        and member.id == author_id
        and interaction.guild
        and (interaction.guild.owner_id == member.id or getattr(member.guild_permissions, "administrator", False))
    )


async def apply_import(bot, guild_id: int, author_id: int,
                       balances: list[MemberBalance], mode: str, source: str) -> tuple[int, int]:
    """Applique 1 fichier, une seule fois, dans une transaction SQLite indépendante.

    Le verrou économique est partagé avec /pay, /daily, /work et les achats.
    La connexion indépendante évite qu'un commit d'un autre cog interrompe l'import.
    """
    if mode not in {"replace", "add"} or not balances or len(balances) > MAX_MEMBERS:
        raise ImportErrorData("Paramètres d'import invalides.")
    digest = _digest(balances)
    db = bot.db
    async with db._economy_lock:
        if db.backend == "postgres":
            return await _apply_postgres_import(db, guild_id, author_id, balances, mode, source, digest)
        async with aiosqlite.connect(db.path, timeout=15) as conn:
            await conn.execute("PRAGMA busy_timeout=15000")
            try:
                await conn.execute("BEGIN IMMEDIATE")
                await conn.execute(
                    "CREATE TABLE IF NOT EXISTS economy_import_batches ("
                    "id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER NOT NULL, "
                    "digest TEXT NOT NULL, source TEXT NOT NULL, mode TEXT NOT NULL, "
                    "author_id INTEGER NOT NULL, member_count INTEGER NOT NULL, created_at INTEGER NOT NULL, "
                    "UNIQUE(guild_id, digest))"
                )
                await conn.execute(
                    "CREATE TABLE IF NOT EXISTS economy_import_rows ("
                    "batch_id INTEGER NOT NULL, user_id INTEGER NOT NULL, "
                    "old_cash INTEGER, old_bank INTEGER, new_cash INTEGER NOT NULL, "
                    "new_bank INTEGER NOT NULL, PRIMARY KEY(batch_id, user_id))"
                )
                old = await conn.execute(
                    "SELECT id FROM economy_import_batches WHERE guild_id=? AND digest=?",
                    (guild_id, digest),
                )
                if await old.fetchone():
                    raise ImportErrorData("Cet export a déjà été importé sur ce serveur. Aucun solde modifié.")
                created_at = int(time.time())
                cur = await conn.execute(
                    "INSERT INTO economy_import_batches "
                    "(guild_id,digest,source,mode,author_id,member_count,created_at) VALUES (?,?,?,?,?,?,?)",
                    (guild_id, digest, source[:120], mode, author_id, len(balances), created_at),
                )
                batch_id = cur.lastrowid
                total_delta = 0
                for item in balances:
                    cursor = await conn.execute(
                        "SELECT cash, bank FROM economy WHERE guild_id=? AND user_id=?",
                        (guild_id, item.user_id),
                    )
                    existing = await cursor.fetchone()
                    previous_cash = int(existing[0] or 0) if existing else 0
                    previous_bank = int(existing[1] or 0) if existing else 0
                    cash = item.cash + (previous_cash if mode == "add" else 0)
                    bank = item.bank + (previous_bank if mode == "add" else 0)
                    if cash > MAX_AMOUNT or bank > MAX_AMOUNT:
                        raise ImportErrorData(f"Solde trop élevé pour {item.user_id}, import annulé.")
                    await conn.execute(
                        "INSERT INTO economy (guild_id,user_id,cash,bank) VALUES (?,?,?,?) "
                        "ON CONFLICT(guild_id,user_id) DO UPDATE SET cash=excluded.cash,bank=excluded.bank",
                        (guild_id, item.user_id, cash, bank),
                    )
                    await conn.execute(
                        "INSERT INTO economy_import_rows "
                        "(batch_id,user_id,old_cash,old_bank,new_cash,new_bank) VALUES (?,?,?,?,?,?)",
                        (batch_id, item.user_id, previous_cash if existing else None,
                         previous_bank if existing else None, cash, bank),
                    )
                    delta = cash + bank - previous_cash - previous_bank
                    total_delta += delta
                    await conn.execute(
                        "INSERT INTO economy_transactions "
                        "(guild_id,sender_id,receiver_id,transaction_type,amount,created_at,reason) "
                        "VALUES (?,?,?,?,?,?,?)",
                        (guild_id, author_id, item.user_id, "external_import", delta, created_at,
                         f"Import #{batch_id} ({mode})"),
                    )
                await conn.commit()
                return batch_id, total_delta
            except Exception:
                await conn.rollback()
                raise




async def _apply_postgres_import(db, guild_id: int, author_id: int,
                                 balances: list[MemberBalance], mode: str,
                                 source: str, digest: str) -> tuple[int, int]:
    """Même opération atomique sur le backend principal PostgreSQL de Railway.

    Une connexion indépendante évite de partager la transaction du bot principal
    (logs, commandes, configuration) et préserve le search_path multi-instance.
    """
    import asyncpg

    from database.db import _postgres_schema, _postgres_url

    database_url = _postgres_url()
    if not database_url:
        raise RuntimeError("La connexion PostgreSQL n'est pas configurée.")
    schema = _postgres_schema(db.path)
    conn = await asyncpg.connect(
        database_url, server_settings={"search_path": f'"{schema}"'}
    )
    try:
        async with conn.transaction():
            await conn.execute(
                "CREATE TABLE IF NOT EXISTS economy_import_batches ("
                "id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY, "
                "guild_id BIGINT NOT NULL, digest TEXT NOT NULL, "
                "source TEXT NOT NULL, mode TEXT NOT NULL, author_id BIGINT NOT NULL, "
                "member_count BIGINT NOT NULL, created_at BIGINT NOT NULL, "
                "UNIQUE(guild_id, digest))"
            )
            await conn.execute(
                "CREATE TABLE IF NOT EXISTS economy_import_rows ("
                "batch_id BIGINT NOT NULL, user_id BIGINT NOT NULL, "
                "old_cash BIGINT, old_bank BIGINT, new_cash BIGINT NOT NULL, "
                "new_bank BIGINT NOT NULL, PRIMARY KEY(batch_id, user_id))"
            )
            existing_batch = await conn.fetchval(
                "SELECT id FROM economy_import_batches WHERE guild_id=$1 AND digest=$2",
                guild_id, digest,
            )
            if existing_batch is not None:
                raise ImportErrorData(
                    "Cet export a déjà été importé sur ce serveur. Aucun solde modifié."
                )
            created_at = int(time.time())
            batch_id = await conn.fetchval(
                "INSERT INTO economy_import_batches "
                "(guild_id,digest,source,mode,author_id,member_count,created_at) "
                "VALUES ($1,$2,$3,$4,$5,$6,$7) RETURNING id",
                guild_id, digest, source[:120], mode, author_id, len(balances), created_at,
            )
            total_delta = 0
            for item in balances:
                previous = await conn.fetchrow(
                    "SELECT cash, bank FROM economy WHERE guild_id=$1 AND user_id=$2 FOR UPDATE",
                    guild_id, item.user_id,
                )
                old_cash = int(previous["cash"] or 0) if previous else 0
                old_bank = int(previous["bank"] or 0) if previous else 0
                cash = item.cash + (old_cash if mode == "add" else 0)
                bank = item.bank + (old_bank if mode == "add" else 0)
                if cash > MAX_AMOUNT or bank > MAX_AMOUNT:
                    raise ImportErrorData(f"Solde trop élevé pour {item.user_id}, import annulé.")
                await conn.execute(
                    "INSERT INTO economy (guild_id,user_id,cash,bank) VALUES ($1,$2,$3,$4) "
                    "ON CONFLICT(guild_id,user_id) DO UPDATE "
                    "SET cash=EXCLUDED.cash, bank=EXCLUDED.bank",
                    guild_id, item.user_id, cash, bank,
                )
                await conn.execute(
                    "INSERT INTO economy_import_rows "
                    "(batch_id,user_id,old_cash,old_bank,new_cash,new_bank) "
                    "VALUES ($1,$2,$3,$4,$5,$6)",
                    batch_id, item.user_id,
                    old_cash if previous else None, old_bank if previous else None,
                    cash, bank,
                )
                delta = cash + bank - old_cash - old_bank
                total_delta += delta
                await conn.execute(
                    "INSERT INTO economy_transactions "
                    "(guild_id,sender_id,receiver_id,transaction_type,amount,created_at,reason) "
                    "VALUES ($1,$2,$3,$4,$5,$6,$7)",
                    guild_id, author_id, item.user_id, "external_import", delta,
                    created_at, f"Import #{batch_id} ({mode})",
                )
            return int(batch_id), total_delta
    finally:
        await conn.close()

def _embed(title: str, content: str, color: int = 0x5865F2) -> discord.Embed:
    result = discord.Embed(title=title, description=content, colour=color)
    result.set_footer(text="SentriX • Transfert de données")
    return result


class ImportPreviewView(discord.ui.View):
    def __init__(self, bot, guild_id: int, author_id: int,
                 balances: list[MemberBalance], source: str):
        super().__init__(timeout=600)
        self.bot = bot
        self.guild_id = guild_id
        self.author_id = author_id
        self.balances = balances
        self.source = source

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not _admin(interaction, self.guild_id, self.author_id):
            await interaction.response.send_message("Seul l'administrateur ayant ouvert l'import peut agir.", ephemeral=True)
            return False
        return True

    def preview(self) -> discord.Embed:
        examples = "\n".join(
            f"<@{row.user_id}> : {row.cash:,} espèces, {row.bank:,} banque".replace(",", " ")
            for row in self.balances[:4]
        )
        content = (
            f"**{len(self.balances)} membres**\n"
            f"Portefeuilles : **{sum(r.cash for r in self.balances):,}**\n"
            f"Banques : **{sum(r.bank for r in self.balances):,}**\n\n"
            f"**Aperçu**\n{examples}\n\n"
            "**Ajouter** cumule les montants avec ceux de SentriX.\n"
            "**Remplacer** applique les soldes importés, sans changer les cooldowns."
        ).replace(",", " ")
        return _embed("Aperçu de l'import", content)

    @discord.ui.button(label="Ajouter aux soldes", style=discord.ButtonStyle.primary)
    async def add(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._ask(interaction, "add")

    @discord.ui.button(label="Remplacer les soldes", style=discord.ButtonStyle.secondary)
    async def replace(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._ask(interaction, "replace")

    @discord.ui.button(label="Annuler", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(embed=_embed("Import annulé", "Aucune donnée modifiée."), view=None)

    async def _ask(self, interaction: discord.Interaction, mode: str):
        view = ImportConfirmView(self.bot, self.guild_id, self.author_id,
                                 self.balances, self.source, mode)
        verb = "ajouter" if mode == "add" else "remplacer"
        await interaction.response.edit_message(
            embed=_embed("Confirmation requise",
                         f"Vous allez **{verb}** les montants de **{len(self.balances)} membres**.\n"
                         "Cette action modifie des soldes réels. Confirmer ?",
                         0xF0B232), view=view)


class ImportConfirmView(discord.ui.View):
    def __init__(self, bot, guild_id: int, author_id: int, balances: list[MemberBalance],
                 source: str, mode: str):
        super().__init__(timeout=180)
        self.bot = bot
        self.guild_id = guild_id
        self.author_id = author_id
        self.balances = balances
        self.source = source
        self.mode = mode
        self.executed = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not _admin(interaction, self.guild_id, self.author_id) or self.executed:
            await interaction.response.send_message("Confirmation indisponible.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Confirmer l'import", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.executed = True
        self.stop()
        await interaction.response.defer()
        try:
            batch_id, delta = await apply_import(
                self.bot, self.guild_id, self.author_id, self.balances, self.mode, self.source
            )
        except ImportErrorData as exc:
            return await interaction.edit_original_response(
                embed=_embed("Import refusé", str(exc), 0xF0B232), view=None
            )
        except Exception:
            logger.exception("Echec import economie serveur=%s admin=%s", self.guild_id, self.author_id)
            return await interaction.edit_original_response(
                embed=_embed("Import impossible", "Erreur technique. Aucun import partiel n'a été validé.", 0xF23F43),
                view=None,
            )
        await interaction.edit_original_response(
            embed=_embed("Import terminé",
                         f"**{len(self.balances)} membres transférés**.\n"
                         f"Variation totale des soldes : **{delta:,}** pièces.\n"
                         f"Reçu d'audit : **#{batch_id}**.\n"
                         "La sauvegarde des anciens soldes est conservée en base.".replace(",", " "),
                         0x23A559),
            view=None,
        )

    @discord.ui.button(label="Retour", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=_embed("Import annulé", "Aucune donnée modifiée."), view=None
        )


class PasteExportModal(discord.ui.Modal, title="Importer des soldes"):
    def __init__(self, bot, guild_id: int, author_id: int):
        super().__init__()
        self.bot = bot
        self.guild_id = guild_id
        self.author_id = author_id
        self.payload = discord.ui.TextInput(
            label="CSV ou JSON (max. 4000 caractères)",
            placeholder="user_id,cash,bank\n123456789012345678,100000,0",
            style=discord.TextStyle.paragraph, max_length=4000,
        )
        self.add_item(self.payload)

    async def on_submit(self, interaction: discord.Interaction):
        if not _admin(interaction, self.guild_id, self.author_id):
            return await interaction.response.send_message("Accès administrateur requis.", ephemeral=True)
        try:
            balances = parse_export(self.payload.value, "texte.csv")
        except ImportErrorData as exc:
            return await interaction.response.send_message(str(exc), ephemeral=True)
        preview = ImportPreviewView(self.bot, self.guild_id, self.author_id, balances, "Saisie manuelle")
        await interaction.response.send_message(embed=preview.preview(), view=preview, ephemeral=True)


class ImportEntryView(discord.ui.View):
    def __init__(self, bot, guild_id: int, author_id: int):
        super().__init__(timeout=300)
        self.bot = bot
        self.guild_id = guild_id
        self.author_id = author_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not _admin(interaction, self.guild_id, self.author_id):
            await interaction.response.send_message("Accès administrateur requis.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Coller CSV / JSON", style=discord.ButtonStyle.primary)
    async def paste(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(
            PasteExportModal(self.bot, self.guild_id, self.author_id)
        )

    @discord.ui.button(label="Envoyer un fichier en MP", style=discord.ButtonStyle.secondary)
    async def file(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "Envoie maintenant en **message privé à SentriX** un fichier .csv ou .json "
            "(512 Ko maximum). Vous avez trois minutes pour l'envoyer.\n"
            "Exemple CSV : user_id,cash,bank", ephemeral=True
        )
        await self._receive_file(interaction)

    async def _receive_file(self, interaction: discord.Interaction):
        def check(message: discord.Message):
            return (
                message.guild is None
                and message.author.id == self.author_id
                and bool(message.attachments)
            )
        try:
            message = await self.bot.wait_for("message", check=check, timeout=180)
            if len(message.attachments) != 1:
                raise ImportErrorData("Envoie un seul fichier.")
            attachment = message.attachments[0]
            if not attachment.filename.lower().endswith(FILENAME_EXTENSIONS):
                raise ImportErrorData("Format accepté : CSV ou JSON uniquement.")
            if attachment.size > MAX_FILE_BYTES:
                raise ImportErrorData("Fichier trop volumineux (512 Ko maximum).")
            payload = await attachment.read()
            balances = parse_export(payload, attachment.filename)
            preview = ImportPreviewView(self.bot, self.guild_id, self.author_id, balances, attachment.filename)
            await interaction.followup.send(embed=preview.preview(), view=preview, ephemeral=True)
        except asyncio.TimeoutError:
            await interaction.followup.send("Temps écoulé. Recommencez depuis /setup.", ephemeral=True)
        except ImportErrorData as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
        except (discord.HTTPException, OSError):
            await interaction.followup.send("Impossible de lire le fichier joint.", ephemeral=True)


async def open_import_panel(bot, interaction: discord.Interaction, guild_id: int) -> None:
    if not _admin(interaction, guild_id, interaction.user.id):
        return await interaction.response.send_message(
            "Seuls les administrateurs du serveur peuvent importer de l'argent.", ephemeral=True
        )
    view = ImportEntryView(bot, guild_id, interaction.user.id)
    embed = _embed(
        "Importer les données d'un autre bot",
        "Utilisez un export autorisé au format **CSV ou JSON** contenant les identifiants Discord.\n"
        "**Colonnes :** user_id, cash, bank (ou balance pour l'argent).\n\n"
        "Vous pourrez voir les soldes avant de choisir **Ajouter** ou **Remplacer**.\n"
        "Aucun accès direct à la base d'un autre bot.",
    )
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


def install_for_bot(bot) -> None:
    """Ajoute le bouton au vrai /setup final, sans remplacer ses autres réglages."""
    global _INSTALLED
    if _INSTALLED:
        return
    from cogs.configuration import SetupView

    if getattr(SetupView, "_sentrix_economy_import_installed", False):
        _INSTALLED = True
        return

    original_render = SetupView.render_page

    def render_with_import(view):
        result = original_render(view)
        page = getattr(view, "page", None)
        in_economy = getattr(view, "_v116_module", None) == "economy" and page == 116
        # En repli pour les versions de /setup sans module Economie.
        home = page == -1
        if (in_economy or home) and len(view.children) < 25:
            button = discord.ui.Button(
                label="Importer des données" if in_economy else "Importer l'économie",
                style=discord.ButtonStyle.secondary,
                custom_id="sentrix:economy:import:open",
            )

            async def callback(interaction: discord.Interaction):
                await open_import_panel(view.bot, interaction, view.guild_id)
            button.callback = callback
            try:
                view.add_item(button)
            except ValueError:
                logger.warning("Panneau /setup plein : bouton d'import non ajouté.")
        return result

    SetupView.render_page = render_with_import
    SetupView._sentrix_economy_import_installed = True
    _INSTALLED = True
    logger.info("Import economie externe disponible dans /setup.")
