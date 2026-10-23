"""Afficher les permissions réelles d'un salon, rôle par rôle.

Demandé par Jayden le 2026-10-23 : voir, dans SentriX, les permissions des
salons et des rôles.

``+channelinfo`` n'en donnait qu'un résumé — privé ou public, le nombre de
règles personnalisées — ce qui ne dit jamais QUI peut faire QUOI. Discord,
lui, oblige à ouvrir les réglages du salon puis chaque rôle un par un.

Ce module affiche la liste des dérogations : pour chaque rôle ou membre
ayant une règle sur le salon, ce qui est explicitement autorisé et ce qui
est explicitement refusé. Les permissions laissées neutres ne sont pas
listées : sur 59 permissions, en afficher 55 « non définies » noierait les
trois qui comptent.
"""
from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from utils import access_matrix, checks, embeds
from utils import sentrix_panels as panels

logger = logging.getLogger("bot.salon-permissions")

#: Au-delà, le message dépasserait les limites de Discord. On tronque en le
#: disant, plutôt que de laisser l'API refuser le message entier.
MAX_CIBLES = 12
MAX_PERMS_PAR_CIBLE = 10


def _libelle(nom: str) -> str:
    return access_matrix.permission_label(nom)


def _nom_cible(cible: discord.Role | discord.Member | discord.Object) -> str:
    if isinstance(cible, discord.Role):
        return "@everyone" if cible.is_default() else cible.mention
    return getattr(cible, "mention", None) or f"`{getattr(cible, 'id', '?')}`"


def resume_derogation(overwrite: discord.PermissionOverwrite) -> tuple[list[str], list[str]]:
    """Sépare ce qui est explicitement autorisé de ce qui est refusé.

    ``PermissionOverwrite`` rend trois états : True, False et None. Seuls les
    deux premiers sont des décisions ; None veut dire « on n'y touche pas »,
    et l'afficher reviendrait à lister 55 lignes sans information.
    """
    autorise: list[str] = []
    refuse: list[str] = []
    for nom, valeur in overwrite:
        if valeur is True:
            autorise.append(_libelle(nom))
        elif valeur is False:
            refuse.append(_libelle(nom))
    return sorted(autorise), sorted(refuse)


def _ligne_cible(cible, overwrite) -> str | None:
    autorise, refuse = resume_derogation(overwrite)
    if not autorise and not refuse:
        return None
    morceaux = []
    if autorise:
        visibles = autorise[:MAX_PERMS_PAR_CIBLE]
        reste = len(autorise) - len(visibles)
        morceaux.append("✅ " + ", ".join(visibles) + (f" (+{reste})" if reste else ""))
    if refuse:
        visibles = refuse[:MAX_PERMS_PAR_CIBLE]
        reste = len(refuse) - len(visibles)
        morceaux.append("❌ " + ", ".join(visibles) + (f" (+{reste})" if reste else ""))
    return f"{_nom_cible(cible)}\n" + "\n".join(morceaux)


class SalonPermissions(commands.Cog):
    """Lecture seule : ce module n'écrit jamais de permission."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.hybrid_command(
        name="salon-permissions",
        aliases=["permsalon", "channel-perms"],
        description="Afficher les permissions réelles d'un salon, rôle par rôle.",
    )
    @app_commands.describe(salon="Le salon à inspecter (par défaut, celui où vous êtes)")
    @commands.guild_only()
    @checks.has_permission_or_modrole("manage_channels")
    async def salon_permissions(
        self, ctx: commands.Context, salon: discord.abc.GuildChannel | None = None
    ):
        salon = salon or ctx.channel
        try:
            derogations = list(salon.overwrites.items())
        except Exception:
            logger.exception("Lecture des dérogations impossible (salon=%s).", getattr(salon, "id", "?"))
            return await panels.envoyer(ctx, panels.depuis_embed(
                embeds.error("Impossible de lire les permissions de ce salon.")
            ))

        everyone = salon.overwrites_for(ctx.guild.default_role)
        prive = everyone.view_channel is False
        entete = (
            f"{'🔒 **Salon privé**' if prive else '🌐 **Visible par tout le monde**'} · "
            f"{len(derogations)} règle(s) personnalisée(s)"
        )

        lignes: list[str] = []
        ignorees = 0
        for cible, overwrite in derogations:
            if len(lignes) >= MAX_CIBLES:
                ignorees += 1
                continue
            ligne = _ligne_cible(cible, overwrite)
            if ligne:
                lignes.append(ligne)

        if not lignes:
            corps = (
                f"{entete}\n\n"
                "Aucune dérogation : ce salon suit exactement les permissions des rôles du serveur."
            )
        else:
            corps = entete + "\n\n" + "\n\n".join(lignes)
            if ignorees:
                corps += f"\n\n*{ignorees} cible(s) supplémentaire(s) non affichée(s).*"

        await panels.envoyer(ctx, panels.depuis_embed(embeds.info(
            corps, title=f"Permissions de #{getattr(salon, 'name', salon)}"
        )))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SalonPermissions(bot))
