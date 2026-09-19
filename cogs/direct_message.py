"""Message privé à UN membre, au nom du serveur (``+dm`` / ``+mp``).

Réservé au propriétaire du serveur et au propriétaire de SentriX. La diffusion à tout
le serveur a été retirée : ce module ne contient volontairement aucun
moteur d'envoi en masse. Le Dashboard (web/dm_panel.py) réutilise :func:`envoyer_prive`
pour offrir exactement le même envoi depuis le navigateur.
"""
from __future__ import annotations

import discord
from discord.ext import commands

from utils import sentrix_panels as panels

LONGUEUR_MAX = 3500
APERCU_MAX = 1200


def panneau_prive(guild: discord.Guild, contenu: str) -> panels.Panneau:
    """Ce que le membre reçoit : bannière en haut, provenance claire, puis le texte."""
    return panels.Panneau(
        titre=f"Message de {guild.name}",
        sous_titre="Message envoyé par l'équipe du serveur.",
        kind="brand",
        vignette=guild.icon.url if guild.icon else None,
        sections=[panels.Section("Message", texte=contenu)],
        pied=f"Message de SentriX • {guild.name}",
    )


async def envoyer_prive(guild: discord.Guild, membre: discord.Member, contenu: str) -> str:
    """Envoie le message et retourne ``envoye``, ``dm_ferme`` ou ``echec``."""
    try:
        await panels.envoyer(membre, panneau_prive(guild, contenu))
    except discord.Forbidden:
        return "dm_ferme"
    except discord.HTTPException:
        return "echec"
    return "envoye"


async def peut_ecrire_au_nom_du_serveur(bot: commands.Bot, guild: discord.Guild | None, user: discord.abc.User) -> bool:
    if guild is None:
        return False
    if await bot.is_owner(user):
        return True
    return guild.owner_id == user.id


class DirectMessage(commands.Cog, name="DirectMessage"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.command(name="dm", aliases=["mp"])
    @commands.guild_only()
    async def dm(self, ctx: commands.Context, membre: discord.Member, *, message: str) -> None:
        """Écrit à UN membre en privé au nom du serveur.

        Volontairement en préfixe seul : le budget slash est saturé (100/100) et
        `+dm` ne mérite pas d'évincer une commande déjà exposée.
        """
        if not await peut_ecrire_au_nom_du_serveur(self.bot, ctx.guild, ctx.author):
            return await panels.texte_court(ctx, "Écrire au nom du serveur en privé est réservé à son propriétaire.", ephemere=True)
        if membre.bot:
            return await panels.texte_court(ctx, "Les bots ne reçoivent pas de message privé.", ephemere=True)
        contenu = message.strip()
        if not contenu:
            return await panels.texte_court(ctx, "Indiquez le texte à envoyer.", ephemere=True)
        if len(contenu) > LONGUEUR_MAX:
            return await panels.texte_court(ctx, f"Message trop long : {len(contenu)} caractères (maximum {LONGUEUR_MAX}).", ephemere=True)

        resultat = await envoyer_prive(ctx.guild, membre, contenu)
        if resultat == "envoye":
            texte = f"Message privé envoyé à {membre.mention}."
        elif resultat == "dm_ferme":
            texte = f"{membre.mention} n'accepte pas les messages privés de ce serveur."
        else:
            texte = f"Discord a refusé l'envoi à {membre.mention}."
        await panels.texte_court(ctx, texte)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(DirectMessage(bot))
