"""`/classement` — un seul écran pour tous les classements (10/11/2026).

« Fais un classement invitations et un classement vocal. » Le classement des
invitations existait depuis des mois (`/invite-leaderboard`) et n'a servi à
personne en trente jours : il était introuvable parmi les commandes. Le vocal
n'existait nulle part en classement.

Plutôt que deux commandes de plus, une seule : `/classement`, avec un menu qui
change de catégorie sans réécrire la commande. Niveaux, messages, vocal,
invitations, économie — toutes sur les données déjà enregistrées.
"""
from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from utils import classements, sentrix_emojis as icons, sentrix_panels as panels

logger = logging.getLogger("bot.classements")

CHOIX = [
    app_commands.Choice(name=c.titre, value=c.cle) for c in classements.CATEGORIES
]


async def construire(bot, guild, auteur_id: int, cle: str) -> panels.Panneau:
    categorie = classements.PAR_CLE.get(cle, classements.PAR_CLE[classements.DEFAUT])
    lignes = classements.sans_les_bots(guild, await classements.lire(bot, guild.id, categorie.cle))
    if not lignes:
        sections = [panels.Section(
            "Personne au classement",
            texte=f"{categorie.description} : aucune donnée enregistrée pour l'instant sur ce serveur.",
        )]
    else:
        sections = [
            panels.Section("Top 10", texte="\n".join(classements.lignes_du_top(categorie, lignes))),
            panels.Section("Votre rang", texte=classements.ma_position(categorie, lignes, auteur_id)),
        ]
    panneau = panels.Panneau(
        titre=icons.titre(categorie.icone, f"Classement · {categorie.titre}"),
        sous_titre=f"{len(lignes)} membre{'s' if len(lignes) > 1 else ''} classé{'s' if len(lignes) > 1 else ''}",
        kind="brand",
        sections=sections,
        pied="",
    )
    panneau.add_item(_menu(bot, guild, auteur_id, categorie.cle))
    return panneau


def _menu(bot, guild, auteur_id: int, actuelle: str) -> discord.ui.ActionRow:
    menu = discord.ui.Select(
        placeholder="Changer de classement",
        options=[
            discord.SelectOption(
                label=c.titre, value=c.cle, description=c.description[:100],
                default=c.cle == actuelle, emoji=icons.partiel(c.icone),
            )
            for c in classements.CATEGORIES
        ],
    )

    async def choisir(interaction: discord.Interaction):
        if interaction.user.id != auteur_id:
            # Le classement n'est pas privé : qui veut le sien relance la commande.
            return await interaction.response.send_message(
                "Lancez `/classement` pour voir votre propre rang.", ephemeral=True,
            )
        await interaction.response.defer()
        suivant = await construire(bot, guild, auteur_id, menu.values[0])
        await interaction.edit_original_response(
            view=suivant, attachments=suivant.fichiers() if hasattr(suivant, "fichiers") else [],
            allowed_mentions=discord.AllowedMentions.none(),
        )

    menu.callback = choisir
    return discord.ui.ActionRow(menu)


class Classements(commands.Cog, name="Classements"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.hybrid_command(
        name="classement",
        description="Classements du serveur : niveaux, messages, vocal, invitations, économie.",
    )
    @app_commands.describe(categorie="Le classement à afficher")
    @app_commands.choices(categorie=CHOIX)
    async def classement(self, ctx: commands.Context, categorie: str | None = None):
        if ctx.interaction:
            await ctx.defer()
        cle = str(getattr(categorie, "value", categorie) or classements.DEFAUT)
        panneau = await construire(self.bot, ctx.guild, ctx.author.id, cle)
        await panels.envoyer(ctx, panneau, allowed_mentions=discord.AllowedMentions.none())


async def setup(bot: commands.Bot):
    await bot.add_cog(Classements(bot))
