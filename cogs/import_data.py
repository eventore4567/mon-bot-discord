"""Explicit, validated migration of exported XP and economy records.

Never reads another bot's private database or API. Import is limited to a JSON
file supplied by a server manager, with a preview and confirmation.
"""
from __future__ import annotations

import json
import logging

import discord
from discord.ext import commands
from . import language_runtime
from utils import sentrix_panels as panels

logger = logging.getLogger("bot.import-data")
MAX_UPLOAD_SIZE = 1024 * 1024
MAX_USERS = 5000
# UnbelievaBoat peut avoir des soldes bien au-dessus de 10**12.
# SQLite utilise des INTEGER signés 64 bits. Garder 4e18 par portefeuille
# et par banque garantit que (cash + bank) reste dans cet espace.
MAX_XP_VALUE = 10 ** 12
MAX_CURRENCY_VALUE = 4_000_000_000_000_000_000
MAX_VALUE = MAX_XP_VALUE  # Compatibilité de l'ancien importeur.


class BalanceOverflowError(ValueError):
    """Soldes au-delà de SQLite : adaptation EXPLICITE, jamais silencieuse."""

    def __init__(self, maximum: int, divisor: int):
        self.maximum = maximum
        self.divisor = divisor
        super().__init__(
            "Un ou plusieurs soldes dépassent la capacité exacte de SentriX. "
            f"Conversion proposée : division de TOUS les soldes par {divisor:,} "
            "(avec arrondi inférieur), uniquement après confirmation."
        )


def _currency_divisor(maximum: int) -> int:
    factor = 1
    while maximum // factor > MAX_CURRENCY_VALUE:
        factor *= 10
    return factor


def parse_export(raw: bytes, *, scale_currency: bool = False) -> list[dict]:
    """Validate entire JSON before a write. Optionally scale oversized money.

    Exact cash/bank values are preserved whenever they fit SQLite. Oversized
    values require an explicit UI opt-in; never auto-truncate or silently cap.
    """
    if len(raw) > MAX_UPLOAD_SIZE:
        raise ValueError("File exceeds the 1 MB limit.")
    try:
        payload = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError("The file must be valid UTF-8 JSON.") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("users"), list):
        raise ValueError('Expected a JSON object with a "users" array.')
    rows = payload["users"]
    if not 1 <= len(rows) <= MAX_USERS:
        raise ValueError("The export must contain between 1 and 5000 users.")
    seen = set()
    cleaned = []
    maximum_money = 0
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            raise ValueError(f"Invalid record at position {index}.")
        try:
            user_id = int(row.get("id", row.get("user_id")))
        except (ValueError, TypeError, OverflowError) as exc:
            raise ValueError(f"Missing or invalid user ID at position {index}.") from exc
        if user_id <= 0 or user_id >= 2 ** 64 or user_id in seen:
            raise ValueError(f"Invalid or duplicate user ID at position {index}.")
        seen.add(user_id)
        values = {"id": user_id}
        for key in ("level", "xp", "cash", "bank"):
            if key not in row:
                continue
            value = row[key]
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{key} must be an integer (user {user_id}).")
            if value < 0 or (key == "level" and value > 100000) or (
                key == "xp" and value > MAX_XP_VALUE
            ):
                raise ValueError(f"{key} is outside the allowed range (user {user_id}).")
            values[key] = value
            if key in ("cash", "bank"):
                maximum_money = max(maximum_money, value)
        if len(values) == 1:
            raise ValueError(f"User {user_id} has no supported data.")
        cleaned.append(values)

    factor = _currency_divisor(maximum_money)
    if factor > 1:
        if not scale_currency:
            raise BalanceOverflowError(maximum_money, factor)
        for row in cleaned:
            for field in ("cash", "bank"):
                if field in row:
                    row[field] //= factor
    return cleaned


class BalanceScaleConsent(discord.ui.View):
    """Two-stage confirmation: choose conversion, then preview, then import."""

    def __init__(self, bot, guild_id: int, author_id: int, raw: bytes, divisor: int,
                 maximum: int, english: bool):
        super().__init__(timeout=180)
        self.bot = bot
        self.guild_id = guild_id
        self.author_id = author_id
        self.raw = raw
        self.divisor = divisor
        self.maximum = maximum
        self.english = english
        self.used = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if (self.used or interaction.guild_id != self.guild_id
                or interaction.user.id != self.author_id
                or not isinstance(interaction.user, discord.Member)
                or not interaction.user.guild_permissions.manage_guild):
            await interaction.response.send_message(
                "Cette conversion ne vous appartient pas ou a déjà été traitée.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="Adapter les soldes et voir l'aperçu",
                       style=discord.ButtonStyle.primary)
    async def convert(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.used = True
        self.stop()
        await interaction.response.defer(ephemeral=True, thinking=True)
        # The explicit click enables scaling. A SECOND confirmation is still
        # necessary to write to the database.
        rows = parse_export(self.raw, scale_currency=True)
        embed, confirm = await _preview_records(
            self.bot, self.guild_id, self.author_id, rows,
            scaled_by=self.divisor, english=self.english,
        )
        await panels.envoyer(
            interaction.followup,
            panels.avec_composants(panels.depuis_embed(embed), confirm),
            ephemere=True,
        )

    @discord.ui.button(label="Annuler", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.used = True
        self.stop()
        await interaction.response.edit_message(view=None)


class ImportConfirm(discord.ui.View):
    def __init__(self, bot, guild_id: int, author_id: int, records: list[dict], english: bool):
        super().__init__(timeout=180)
        self.bot = bot
        self.guild_id = guild_id
        self.author_id = author_id
        self.records = records
        self.english = english
        self._submitted = False
        # Decorated callbacks (self.merge/self.replace/self.cancel) are methods,
        # not Button objects in discord.py. Update the actual View children.
        labels = {
            "Add missing": "Add missing" if english else "Ajouter les absents",
            "Replace imported fields": "Replace imported fields" if english else "Remplacer les champs importés",
            "Cancel": "Cancel" if english else "Annuler",
        }
        for item in self.children:
            if isinstance(item, discord.ui.Button) and item.label in labels:
                item.label = labels[item.label]

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if self._submitted:
            await interaction.response.send_message(
                "This import has already been confirmed or cancelled." if self.english
                else "Cette importation a déjà été confirmée ou annulée.",
                ephemeral=True,
            )
            return False
        user = interaction.user
        if (interaction.guild is None or interaction.guild.id != self.guild_id
                or user.id != self.author_id
                or not isinstance(user, discord.Member)
                or not user.guild_permissions.manage_guild):
            await interaction.response.send_message(
                "This confirmation belongs to a server manager." if self.english
                else "Confirmation réservée au gestionnaire du serveur.", ephemeral=True
            )
            return False
        return True

    async def apply(self, interaction: discord.Interaction, *, replace: bool) -> None:
        # The source view is embedded in a Components V2 panel; stopping only
        # the source view does not unregister the panel's buttons. Guard against
        # double-clicks independently of Discord message updates.
        if self._submitted:
            return await interaction.response.send_message(
                "Import already processed." if self.english else
                "Importation déjà traitée.", ephemeral=True,
            )
        self._submitted = True
        await interaction.response.defer(ephemeral=True, thinking=True)
        changed = 0
        try:
            for row in self.records:
                user_id = row["id"]
                if "xp" in row or "level" in row:
                    columns = [k for k in ("xp", "level") if k in row]
                    values = [row[k] for k in columns]
                    updates = ", ".join(f"{k}=excluded.{k}" for k in columns)
                    sql = (
                        "INSERT INTO levels (guild_id,user_id," + ",".join(columns)
                        + ") VALUES (" + ",".join("?" for _ in range(2 + len(columns))) + ") "
                        + ("ON CONFLICT(guild_id,user_id) DO UPDATE SET " + updates if replace
                           else "ON CONFLICT(guild_id,user_id) DO NOTHING")
                    )
                    await self.bot.db.execute(sql, (self.guild_id, user_id, *values))
                if "cash" in row or "bank" in row:
                    columns = [k for k in ("cash", "bank") if k in row]
                    values = [row[k] for k in columns]
                    updates = ", ".join(f"{k}=excluded.{k}" for k in columns)
                    sql = (
                        "INSERT INTO economy (guild_id,user_id," + ",".join(columns)
                        + ") VALUES (" + ",".join("?" for _ in range(2 + len(columns))) + ") "
                        + ("ON CONFLICT(guild_id,user_id) DO UPDATE SET " + updates if replace
                           else "ON CONFLICT(guild_id,user_id) DO NOTHING")
                    )
                    await self.bot.db.execute(sql, (self.guild_id, user_id, *values))
                changed += 1
        except Exception:
            logger.exception("Import failed after %s records (guild=%s)", changed, self.guild_id)
            await interaction.followup.send(
                f"Import interrupted after {changed} records. Earlier writes may have been saved; check logs."
                if self.english else
                f"Import interrompu après {changed} entrées. Des données ont pu être enregistrées ; vérifiez les logs.",
                ephemeral=True,
            )
            self.stop()
            return
        for item in self.children:
            item.disabled = True
        self.stop()
        await interaction.followup.send(
            f"Import finished: {changed} records processed. Mode: {'replace' if replace else 'add missing'}."
            if self.english else
            f"Import terminé : {changed} entrées traitées. Mode : {'remplacement' if replace else 'ajout des absents'}.",
            ephemeral=True,
        )

    @discord.ui.button(label="Add missing", style=discord.ButtonStyle.success)
    async def merge(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.apply(interaction, replace=False)

    @discord.ui.button(label="Replace imported fields", style=discord.ButtonStyle.danger)
    async def replace(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.apply(interaction, replace=True)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self._submitted = True
        self.stop()
        await interaction.response.edit_message(view=None)



async def preview_attachment(bot, guild_id: int, author_id: int, attachment: discord.Attachment):
    """Shared preview path for +import-data and the /setup upload modal."""
    if (not str(attachment.filename).lower().endswith(".json")
            or attachment.size > MAX_UPLOAD_SIZE):
        raise ValueError("Le fichier doit être un JSON de 1 Mo maximum.")
    try:
        raw = await attachment.read()
    except (discord.HTTPException, OSError) as exc:
        raise ValueError("Impossible de lire la pièce jointe.") from exc
    english = await language_runtime.get_language(bot, guild_id) == language_runtime.LANG_EN
    try:
        records = parse_export(raw)
    except BalanceOverflowError as exc:
        fmt = lambda n: f"{n:,}".replace(",", " ")
        description = (
            f"Le plus grand solde est de **{fmt(exc.maximum)}** pièces. "
            "Le stocker directement ferait dépasser la capacité des entiers SQLite.\n"
            f"Vous pouvez diviser **tous** les soldes cash et banque par "
            f"**{fmt(exc.divisor)}**, avec arrondi inférieur. "
            "Les montants sont donc modifiés, pas seulement affichés autrement.\n"
            "Aucune donnée ne sera modifiée sans les deux validations successives. "
            "Conservez le fichier d'export original."
        )
        embed = discord.Embed(title="Soldes trop élevés · Conversion facultative",
                              description=description, colour=discord.Colour.orange())
        return embed, BalanceScaleConsent(
            bot, guild_id, author_id, raw, exc.divisor, exc.maximum, english,
        )
    return await _preview_records(bot, guild_id, author_id, records, english=english)


async def _preview_records(bot, guild_id: int, author_id: int, records: list[dict],
                           *, scaled_by: int = 1, english: bool | None = None):
    if english is None:
        english = await language_runtime.get_language(bot, guild_id) == language_runtime.LANG_EN
    levels = sum("xp" in row or "level" in row for row in records)
    economy = sum("cash" in row or "bank" in row for row in records)
    description = (
        f"{len(records)} users · {levels} XP/level records · {economy} economy records.\n"
        "**Add missing** keeps current data. **Replace** overwrites only fields included in this file.\n"
        "No changes are made until you explicitly confirm. Back up the database first."
        if english else
        f"{len(records)} utilisateurs · {levels} entrées XP/niveaux · {economy} entrées économie.\n"
        "**Ajouter les absents** conserve les données actuelles. **Remplacer** modifie uniquement les champs présents dans le fichier.\n"
        "Aucune donnée n'est modifiée avant confirmation. Sauvegardez la base avant l'import."
    )
    if scaled_by > 1:
        description += (
            "\n**Avertissement :** tous les soldes cash/banque de cet export ont été "
            f"divisés par **{scaled_by:,}** (arrondi inférieur). "
            "Les valeurs originales ne seront pas restaurées par SentriX."
        )
    embed = discord.Embed(
        title="Data import · Preview" if english else "Importation · Aperçu",
        description=description,
        colour=discord.Colour.blurple(),
    )
    return embed, ImportConfirm(bot, guild_id, author_id, records, english)


class ImportFileModal(discord.ui.Modal):
    """Private, native Discord 2.7 file upload from within the setup panel."""

    def __init__(self, bot, guild_id: int, author_id: int, english: bool):
        super().__init__(
            title="Import data from another bot" if english else "Importer les données d'un bot",
            timeout=300,
        )
        self.bot = bot
        self.guild_id = int(guild_id)
        self.author_id = int(author_id)
        self.english = english
        self.upload = discord.ui.FileUpload(required=True, min_values=1, max_values=1)
        self.add_item(discord.ui.Label(
            text="JSON export" if english else "Fichier d'export JSON",
            description="One file · max 1 MB" if english else "Un fichier · 1 Mo maximum",
            component=self.upload,
        ))

    async def on_submit(self, interaction: discord.Interaction) -> None:
        member = interaction.user
        if (
            interaction.guild is None
            or interaction.guild.id != self.guild_id
            or member.id != self.author_id
            or not isinstance(member, discord.Member)
            or not member.guild_permissions.manage_guild
        ):
            return await interaction.response.send_message(
                "Manage Server is required." if self.english
                else "Permission Gérer le serveur requise.",
                ephemeral=True,
            )
        if not self.upload.values:
            return await interaction.response.send_message(
                "No file was attached." if self.english else "Aucun fichier joint.",
                ephemeral=True,
            )
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            embed, view = await preview_attachment(
                self.bot, self.guild_id, self.author_id, self.upload.values[0],
            )
        except ValueError as exc:
            return await interaction.followup.send(
                f"Invalid export: {exc}" if self.english else f"Export invalide : {exc}",
                ephemeral=True,
            )
        await panels.envoyer(
            interaction.followup,
            panels.avec_composants(panels.depuis_embed(embed), view),
            ephemere=True,
        )


class ImportSetupView(discord.ui.View):
    """Mini assistant opened inside the active V116 setup."""

    def __init__(self, bot, guild_id: int, author_id: int):
        super().__init__(timeout=300)
        self.bot = bot
        self.guild_id = int(guild_id)
        self.author_id = int(author_id)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        user = interaction.user
        if (interaction.guild_id != self.guild_id or user.id != self.author_id
                or not isinstance(user, discord.Member)
                or not user.guild_permissions.manage_guild):
            await interaction.response.send_message(
                "Ce mini-setup est réservé au gestionnaire du serveur.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Choisir le fichier JSON", style=discord.ButtonStyle.primary)
    async def choose_file(self, interaction: discord.Interaction, button: discord.ui.Button):
        english = (await language_runtime.get_language(self.bot, self.guild_id)
                   == language_runtime.LANG_EN)
        await interaction.response.send_modal(
            ImportFileModal(self.bot, self.guild_id, self.author_id, english))

    @discord.ui.button(label="Format du fichier", style=discord.ButtonStyle.secondary)
    async def format_info(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "Fichier JSON de 1 Mo maximum. Exemple :\n"
            '```json\n{"users":[{"id":"123456789012345678","xp":250,"level":3,"cash":1000,"bank":200}]}\n```\n'
            "Cet import utilise uniquement un export fourni par un administrateur.",
            ephemeral=True,
        )

    @discord.ui.button(label="Fermer", style=discord.ButtonStyle.secondary)
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        await interaction.response.edit_message(content="Importation fermée.", view=None)



class ImportData(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(name="import-data")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    async def import_data(self, ctx: commands.Context, file: discord.Attachment = None):
        """Keep the historical command; /setup uses the same preview workflow."""
        if file is None:
            english = await language_runtime.get_language(self.bot, ctx.guild.id) == language_runtime.LANG_EN
            return await ctx.send(
                "Open /setup > Levels or Economy > Import data, or attach a JSON file to +import-data."
                if english else
                "Ouvrez /setup > Niveaux ou Économie > Importer des données. "
                "Vous pouvez aussi joindre un JSON au message +import-data.",
                allowed_mentions=discord.AllowedMentions.none(),
                delete_after=30,
            )
        try:
            embed, view = await preview_attachment(
                self.bot, ctx.guild.id, ctx.author.id, file,
            )
        except ValueError as exc:
            return await ctx.send(f"Export invalide : {exc}")
        await panels.envoyer(
            ctx, panels.avec_composants(panels.depuis_embed(embed), view),
            allowed_mentions=discord.AllowedMentions.none(),
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(ImportData(bot))
