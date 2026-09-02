from __future__ import annotations

import asyncio

import discord
from discord import app_commands
from discord.ext import commands

from utils import embeds as sentrix_embeds
from utils.command_style_v2 import style_embed


def _sentrix_panel(title: str, description: str, *, kind: str = "info") -> discord.Embed:
    panel = discord.Embed(title=title, description=description)
    return style_embed(panel, category="utility", kind=kind)


def embed(title: str, description: str) -> discord.Embed:
    return _sentrix_panel(title, description, kind="info")


def error(title: str, description: str) -> discord.Embed:
    return _sentrix_panel(title, description, kind="danger")


def success(title: str, description: str) -> discord.Embed:
    return _sentrix_panel(title, description, kind="success")


def warning(title: str, description: str) -> discord.Embed:
    return _sentrix_panel(title, description, kind="warning")


SEND_DELAY_SECONDS = 0.75
PROGRESS_EVERY = 25


class BroadcastConfirmView(discord.ui.View):
    def __init__(
        self,
        cog: "Broadcast",
        *,
        owner_id: int,
        guild: discord.Guild,
        content: str,
        recipients: list[discord.Member],
    ) -> None:
        super().__init__(timeout=120)
        self.cog = cog
        self.owner_id = owner_id
        self.guild = guild
        self.content = content
        self.recipients = recipients
        self.message: discord.Message | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                embed=error(
                    "Confirmation privée",
                    "Seule la personne qui a lancé la commande peut confirmer cette diffusion.",
                ),
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(
        label="Envoyer",
        style=discord.ButtonStyle.primary,
    )
    async def confirm(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        if self.guild.id in self.cog.active_guilds:
            await interaction.response.send_message(
                embed=error(
                    "Diffusion déjà en cours",
                    "Une autre diffusion privée est déjà en cours sur ce serveur.",
                ),
                ephemeral=True,
            )
            return

        for item in self.children:
            item.disabled = True

        await interaction.response.edit_message(
            embed=warning(
                "Diffusion lancée",
                f"Envoi vers **{len(self.recipients)} membre(s)** non-bot.\n"
                "Le bot respecte un délai entre les messages pour suivre les limites de Discord.",
            ),
            view=self,
        )

        self.cog.active_guilds.add(self.guild.id)
        asyncio.create_task(
            self.cog.run_broadcast(
                interaction=interaction,
                guild=self.guild,
                recipients=self.recipients,
                content=self.content,
            )
        )

    @discord.ui.button(
        label="Annuler",
        style=discord.ButtonStyle.secondary,
    )
    async def cancel(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            embed=embed(
                "Diffusion annulée",
                "Aucun message privé n'a été envoyé.",
            ),
            view=self,
        )
        self.stop()

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(
                    embed=embed(
                        "Confirmation expirée",
                        "La diffusion n'a pas été lancée.",
                    ),
                    view=self,
                )
            except discord.HTTPException:
                pass


class Broadcast(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.active_guilds: set[int] = set()

    async def _can_broadcast(self, ctx: commands.Context) -> bool:
        if not ctx.guild:
            return False
        if await self.bot.is_owner(ctx.author):
            return True
        return ctx.guild.owner_id == ctx.author.id

    async def run_broadcast(
        self,
        *,
        interaction: discord.Interaction,
        guild: discord.Guild,
        recipients: list[discord.Member],
        content: str,
    ) -> None:
        sent = 0
        failed = 0

        try:
            for index, member in enumerate(recipients, start=1):
                dm_embed = embed(
                    "Message de SentriX",
                    f"**Serveur :** {guild.name}\n\n{content}",
                )
                if guild.icon:
                    dm_embed.set_thumbnail(url=guild.icon.url)
                dm_embed.set_image(url=sentrix_embeds.SENTRIX_BANNER_URL)
                dm_embed.set_footer(
                    text=f"Message envoyé par l'équipe de {guild.name} • SentriX"
                )

                try:
                    await member.send(embed=dm_embed)
                    sent += 1
                except (discord.Forbidden, discord.HTTPException):
                    failed += 1

                if index < len(recipients):
                    await asyncio.sleep(SEND_DELAY_SECONDS)

                if index % PROGRESS_EVERY == 0:
                    try:
                        await interaction.edit_original_response(
                            embed=warning(
                                "Diffusion en cours",
                                f"Progression : **{index}/{len(recipients)}**\n"
                                f"Envoyés : **{sent}**\n"
                                f"Échecs / MP fermés : **{failed}**",
                            )
                        )
                    except discord.HTTPException:
                        pass

            try:
                await interaction.edit_original_response(
                    embed=success(
                        "Diffusion terminée",
                        f"**{sent}** message(s) envoyé(s).\n"
                        f"**{failed}** échec(s) (MP fermés, blocage ou erreur Discord).\n"
                        f"**{len(recipients)}** membre(s) traité(s).",
                    )
                )
            except discord.HTTPException:
                pass
        finally:
            self.active_guilds.discard(guild.id)

    @commands.hybrid_command(
        name="dmall",
        description="Envoie une annonce privée à tous les membres non-bot du serveur.",
    )
    @commands.guild_only()
    @app_commands.describe(message="Texte à envoyer aux membres")
    async def dmall(
        self,
        ctx: commands.Context,
        *,
        message: str,
    ) -> None:
        assert ctx.guild is not None

        if not await self._can_broadcast(ctx):
            await ctx.send(
                embed=error(
                    "Permission refusée",
                    "Cette commande est réservée au propriétaire du serveur "
                    "ou au propriétaire du bot.",
                ),
                ephemeral=bool(ctx.interaction),
            )
            return

        if ctx.guild.id in self.active_guilds:
            await ctx.send(
                embed=error(
                    "Diffusion déjà en cours",
                    "Attends la fin de la diffusion actuelle avant d'en lancer une autre.",
                ),
                ephemeral=bool(ctx.interaction),
            )
            return

        content = message.strip()
        if not content:
            await ctx.send(
                embed=error("Message vide", "Ajoute le texte que tu veux envoyer."),
                ephemeral=bool(ctx.interaction),
            )
            return
        if len(content) > 3500:
            await ctx.send(
                embed=error(
                    "Message trop long",
                    "Le texte doit faire **3 500 caractères maximum**.",
                ),
                ephemeral=bool(ctx.interaction),
            )
            return

        recipients = [
            member
            for member in ctx.guild.members
            if not member.bot and member.id != self.bot.user.id
        ]

        if not recipients:
            await ctx.send(
                embed=error("Aucun destinataire", "Aucun membre non-bot n'a été trouvé."),
                ephemeral=bool(ctx.interaction),
            )
            return

        preview = embed(
            "Confirmer la diffusion privée",
            f"Le message sera envoyé à **{len(recipients)} membre(s)** non-bot.\n\n"
            f"**Aperçu :**\n{content[:1200]}"
            + ("\n…" if len(content) > 1200 else "")
            + "\n\n"
            "Les membres qui ont fermé leurs MP ne recevront rien. "
            "Discord peut appliquer un délai supplémentaire aux diffusions importantes.",
        )
        view = BroadcastConfirmView(
            self,
            owner_id=ctx.author.id,
            guild=ctx.guild,
            content=content,
            recipients=recipients,
        )
        sent_message = await ctx.send(
            embed=preview,
            view=view,
            ephemeral=bool(ctx.interaction),
        )
        if isinstance(sent_message, discord.Message):
            view.message = sent_message


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Broadcast(bot))
