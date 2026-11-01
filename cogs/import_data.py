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
MAX_VALUE = 10 ** 12


def parse_export(raw: bytes) -> list[dict]:
    if len(raw) > MAX_UPLOAD_SIZE:
        raise ValueError("File exceeds the 1 MB limit.")
    try:
        payload = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("The file must be valid UTF-8 JSON.") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("users"), list):
        raise ValueError('Expected a JSON object with a "users" array.')
    rows = payload["users"]
    if not 1 <= len(rows) <= MAX_USERS:
        raise ValueError("The export must contain between 1 and 5000 users.")
    seen = set()
    cleaned = []
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            raise ValueError(f"Invalid record at position {index}.")
        try:
            user_id = int(row.get("id", row.get("user_id")))
        except (ValueError, TypeError) as exc:
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
            if value < 0 or value > (100000 if key == "level" else MAX_VALUE):
                raise ValueError(f"{key} is outside the allowed range (user {user_id}).")
            values[key] = value
        if len(values) == 1:
            raise ValueError(f"User {user_id} has no supported data.")
        cleaned.append(values)
    return cleaned


class ImportConfirm(discord.ui.View):
    def __init__(self, bot, guild_id: int, author_id: int, records: list[dict], english: bool):
        super().__init__(timeout=180)
        self.bot = bot
        self.guild_id = guild_id
        self.author_id = author_id
        self.records = records
        self.english = english
        self.merge.label = "Add missing" if english else "Ajouter les absents"
        self.replace.label = "Replace imported fields" if english else "Remplacer les champs importés"
        self.cancel.label = "Cancel" if english else "Annuler"

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
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
        self.stop()
        await interaction.response.edit_message(view=None)


class ImportData(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.hybrid_command(name="import-data", description="Preview and import a JSON export (XP and economy).")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    async def import_data(self, ctx: commands.Context, file: discord.Attachment):
        english = await language_runtime.get_language(self.bot, ctx.guild.id) == language_runtime.LANG_EN
        if not file.filename.lower().endswith(".json") or file.size > MAX_UPLOAD_SIZE:
            return await ctx.send("Attach a JSON file of up to 1 MB." if english else
                                  "Joignez un fichier JSON de 1 Mo maximum.")
        try:
            records = parse_export(await file.read())
        except ValueError as exc:
            return await ctx.send(f"Invalid export: {exc}" if english else f"Export invalide : {exc}")
        levels = sum("xp" in row or "level" in row for row in records)
        economy = sum("cash" in row or "bank" in row for row in records)
        description = (
            f"{len(records)} users · {levels} XP/level records · {economy} economy records.\n"
            "**Add missing** leaves existing records unchanged. **Replace** changes only fields present in the file.\n"
            "Level formulas may differ between bots. Check values before confirming."
            if english else
            f"{len(records)} utilisateurs · {levels} entrées XP/niveaux · {economy} entrées économie.\n"
            "**Ajouter les absents** conserve les données existantes. **Remplacer** modifie seulement les champs fournis.\n"
            "Les calculs de niveau peuvent différer selon les bots. Vérifiez les valeurs."
        )
        embed = discord.Embed(title="Data import · Preview" if english else
                               "Importation · Aperçu", description=description, color=discord.Colour.blurple())
        view = ImportConfirm(self.bot, ctx.guild.id, ctx.author.id, records, english)
        await panels.envoyer(ctx, panels.avec_composants(panels.depuis_embed(embed), view), allowed_mentions=discord.AllowedMentions.none())


async def setup(bot: commands.Bot):
    await bot.add_cog(ImportData(bot))
