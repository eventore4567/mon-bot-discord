"""Compteur communautaire infini : +infinit.

Un même membre ne peut pas valider deux nombres consécutifs. Les erreurs sont supprimées
après un court délai, le prochain nombre est rappelé puis le rappel disparaît après 10 s.
L'état est stocké en SQLite afin de survivre aux redémarrages.
"""
from __future__ import annotations

import asyncio
import time

import discord
from discord.ext import commands

from utils import checks


SCHEMA = """
CREATE TABLE IF NOT EXISTS infinite_counter_config (
    guild_id INTEGER PRIMARY KEY,
    channel_id INTEGER NOT NULL,
    next_number INTEGER NOT NULL DEFAULT 1,
    last_user_id INTEGER,
    enabled INTEGER NOT NULL DEFAULT 1,
    updated_at INTEGER NOT NULL
)
"""


class StartNumberModal(discord.ui.Modal, title="Compteur infini — nombre de départ"):
    start = discord.ui.TextInput(label="Premier nombre attendu", placeholder="1", default="1", max_length=30)

    def __init__(self, owner: "InfiniteSetupView"):
        super().__init__()
        self.owner = owner
        self.start.default = str(owner.start_number)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            value = int(str(self.start.value).strip())
        except ValueError:
            return await interaction.response.send_message("Le nombre de départ doit être un entier.", ephemeral=True)
        if value < 1:
            return await interaction.response.send_message("Le compteur doit commencer à 1 ou plus.", ephemeral=True)
        self.owner.start_number = value
        await self.owner.refresh(interaction)


class CounterChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, owner: "InfiniteSetupView"):
        self.owner = owner
        super().__init__(
            placeholder="Choisir le salon du compteur",
            min_values=1,
            max_values=1,
            channel_types=[discord.ChannelType.text, discord.ChannelType.news],
            row=1,
        )

    async def callback(self, interaction: discord.Interaction):
        self.owner.channel_id = self.values[0].id
        await self.owner.refresh(interaction)


class InfiniteSetupView(discord.ui.View):
    def __init__(self, cog: "InfiniteCounter", ctx: commands.Context):
        super().__init__(timeout=300)
        self.cog = cog
        self.ctx = ctx
        self.author_id = ctx.author.id
        self.channel_id: int | None = None
        self.start_number = 1
        self.message: discord.Message | None = None
        self.add_item(CounterChannelSelect(self))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Ce setup ne vous appartient pas.", ephemeral=True)
            return False
        return True

    def embed(self) -> discord.Embed:
        channel = self.ctx.guild.get_channel(self.channel_id) if self.channel_id else None
        e = discord.Embed(
            title="SentriX — Compteur infini",
            description=(
                "Les membres doivent écrire `1`, `2`, `3`… sans fin. Un membre ne peut jamais "
                "valider deux nombres à la suite. Une erreur ne remet pas le compteur à zéro."
            ),
            colour=discord.Colour.blurple(),
        )
        e.add_field(name="Salon", value=channel.mention if channel else "**À configurer**", inline=True)
        e.add_field(name="Premier nombre", value=str(self.start_number), inline=True)
        e.add_field(
            name="Erreurs",
            value="Message invalide supprimé après quelques secondes • rappel supprimé après 10 secondes.",
            inline=False,
        )
        e.set_footer(text="SentriX • Progression sauvegardée après chaque nombre valide")
        return e

    async def refresh(self, interaction: discord.Interaction):
        await interaction.response.edit_message(embed=self.embed(), view=self)

    @discord.ui.button(label="Nombre de départ", style=discord.ButtonStyle.secondary, row=0)
    async def start_button(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await interaction.response.send_modal(StartNumberModal(self))

    @discord.ui.button(label="Activer", style=discord.ButtonStyle.success, row=0)
    async def activate(self, interaction: discord.Interaction, _button: discord.ui.Button):
        if not self.channel_id:
            return await interaction.response.send_message("Choisissez d’abord le salon du compteur.", ephemeral=True)
        await self.cog.configure(self.ctx.guild.id, self.channel_id, self.start_number)
        for child in self.children:
            child.disabled = True
        self.stop()
        channel = self.ctx.guild.get_channel(self.channel_id)
        await interaction.response.edit_message(
            embed=discord.Embed(
                title="Compteur infini activé",
                description=f"Salon : {channel.mention if channel else self.channel_id}\nPremier nombre attendu : **{self.start_number}**",
                colour=discord.Colour.green(),
            ),
            view=self,
        )

    @discord.ui.button(label="Annuler", style=discord.ButtonStyle.danger, row=0)
    async def cancel(self, interaction: discord.Interaction, _button: discord.ui.Button):
        for child in self.children:
            child.disabled = True
        self.stop()
        await interaction.response.edit_message(
            embed=discord.Embed(title="Configuration annulée", description="Aucun réglage n’a été modifié.", colour=discord.Colour.dark_grey()),
            view=self,
        )


class InfiniteCounter(commands.Cog, name="InfiniteCounter"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._locks: dict[int, asyncio.Lock] = {}

    async def cog_load(self):
        await self.bot.db.execute(SCHEMA)

    def _lock(self, guild_id: int) -> asyncio.Lock:
        lock = self._locks.get(guild_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[guild_id] = lock
        return lock

    async def configure(self, guild_id: int, channel_id: int, start_number: int = 1):
        await self.bot.db.execute(
            "INSERT INTO infinite_counter_config (guild_id,channel_id,next_number,last_user_id,enabled,updated_at) "
            "VALUES (?,?,?,NULL,1,?) ON CONFLICT(guild_id) DO UPDATE SET "
            "channel_id=excluded.channel_id,next_number=excluded.next_number,last_user_id=NULL,enabled=1,updated_at=excluded.updated_at",
            (guild_id, channel_id, start_number, int(time.time())),
        )

    async def _invalid(self, message: discord.Message, text: str):
        async def delete_message():
            await asyncio.sleep(2)
            try:
                await message.delete()
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass

        asyncio.create_task(delete_message())
        try:
            await message.channel.send(text, delete_after=10, allowed_mentions=discord.AllowedMentions.none())
        except (discord.Forbidden, discord.HTTPException):
            pass

    @commands.group(name="infinit", aliases=["infinite", "compteur-infini"], invoke_without_command=True)
    @commands.guild_only()
    @checks.is_owner_or_admin()
    async def infinit(self, ctx: commands.Context):
        """Ouvre le setup interactif du compteur infini."""
        view = InfiniteSetupView(self, ctx)
        msg = await ctx.send(embed=view.embed(), view=view)
        view.message = msg

    @infinit.command(name="status", aliases=["etat", "état"])
    @checks.is_owner_or_admin()
    async def infinit_status(self, ctx: commands.Context):
        row = await self.bot.db.fetchone("SELECT * FROM infinite_counter_config WHERE guild_id=?", (ctx.guild.id,))
        if row is None:
            return await ctx.send("Le compteur infini n’est pas configuré sur ce serveur.")
        channel = ctx.guild.get_channel(int(row["channel_id"]))
        last = f"<@{row['last_user_id']}>" if row["last_user_id"] else "personne"
        await ctx.send(
            embed=discord.Embed(
                title="Compteur infini — état",
                description=(
                    f"**État :** {'ACTIF' if row['enabled'] else 'INACTIF'}\n"
                    f"**Salon :** {channel.mention if channel else 'introuvable'}\n"
                    f"**Prochain nombre :** {row['next_number']}\n"
                    f"**Dernier joueur :** {last}"
                ),
                colour=discord.Colour.blurple(),
            )
        )

    @infinit.command(name="stop", aliases=["off", "desactiver", "désactiver"])
    @checks.is_owner_or_admin()
    async def infinit_stop(self, ctx: commands.Context):
        await self.bot.db.execute("UPDATE infinite_counter_config SET enabled=0,updated_at=? WHERE guild_id=?", (int(time.time()), ctx.guild.id))
        await ctx.send("Compteur infini désactivé. La progression reste enregistrée.")

    @infinit.command(name="resume", aliases=["on", "reprendre"])
    @checks.is_owner_or_admin()
    async def infinit_resume(self, ctx: commands.Context):
        row = await self.bot.db.fetchone("SELECT 1 FROM infinite_counter_config WHERE guild_id=?", (ctx.guild.id,))
        if row is None:
            return await ctx.send("Configurez d’abord le compteur avec `+infinit`.")
        await self.bot.db.execute("UPDATE infinite_counter_config SET enabled=1,updated_at=? WHERE guild_id=?", (int(time.time()), ctx.guild.id))
        await ctx.send("Compteur infini réactivé avec la progression sauvegardée.")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or message.guild is None:
            return
        row = await self.bot.db.fetchone(
            "SELECT * FROM infinite_counter_config WHERE guild_id=? AND enabled=1", (message.guild.id,)
        )
        if row is None or int(row["channel_id"]) != message.channel.id:
            return

        async with self._lock(message.guild.id):
            # Relire sous verrou : deux messages arrivés quasi simultanément ne doivent pas
            # valider le même nombre.
            row = await self.bot.db.fetchone(
                "SELECT * FROM infinite_counter_config WHERE guild_id=? AND enabled=1", (message.guild.id,)
            )
            if row is None or int(row["channel_id"]) != message.channel.id:
                return
            expected = int(row["next_number"])
            content = message.content.strip()
            if not content.isdigit() or int(content) != expected:
                return await self._invalid(message, f"Mauvais nombre. Le prochain nombre est **{expected}**.")
            if row["last_user_id"] and int(row["last_user_id"]) == message.author.id:
                return await self._invalid(
                    message,
                    f"Tu ne peux pas compter deux fois à la suite. Quelqu’un d’autre doit envoyer **{expected}**.",
                )
            await self.bot.db.execute(
                "UPDATE infinite_counter_config SET next_number=?,last_user_id=?,updated_at=? WHERE guild_id=?",
                (expected + 1, message.author.id, int(time.time()), message.guild.id),
            )
