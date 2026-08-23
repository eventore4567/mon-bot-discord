"""Routeur canonique de la famille de commandes ``+create``.

Une seule racine ``create`` doit exister dans SentriX. Ce module remplace les anciennes
implémentations concurrentes et expose :
- ``+create sentrix`` : construit/répare le serveur support officiel SentriX ;
- ``+create server`` : ouvre le constructeur général existant ;
- ``+create-server`` reste disponible via le Cog ServerBuilder original.

Le constructeur SentriX est utilisé comme service interne : son ancienne commande top-level
n'est jamais enregistrée dans le bot.
"""
from __future__ import annotations

import logging

import discord
from discord.ext import commands

from utils import checks
from .create_sentrix import CreateSentrix as SentriXBuilder

logger = logging.getLogger("bot.create-router")


class CreateRouter(commands.Cog, name="CreateSentrix"):
    """Racine unique des commandes ``+create``."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.builder = SentriXBuilder(bot)
        self._sentrix_canonical_create_router = True

    @commands.group(name="create", invoke_without_command=True)
    @checks.is_owner_or_admin_for("configuration")
    async def create(self, ctx: commands.Context):
        """Choisir le constructeur à lancer."""
        if ctx.invoked_subcommand is not None:
            return
        await ctx.send(
            "**Création SentriX**\n"
            "`+create sentrix` — crée/répare le serveur support professionnel SentriX.\n"
            "`+create server` — ouvre le constructeur général de serveur."
        )

    @create.command(name="sentrix")
    @checks.is_owner_or_admin_for("configuration")
    async def create_sentrix(self, ctx: commands.Context):
        """Créer ou réparer le serveur support professionnel SentriX."""
        # Le callback du builder est appelé comme service interne. Il conserve son verrou,
        # ses contrôles Administrateur et surtout son try/except détaillé de construction.
        command = self.builder.create
        callback = getattr(command, "callback", None)
        if callback is None:
            logger.error("Builder SentriX sans callback disponible.")
            return await ctx.send(
                "Le constructeur SentriX n'a pas pu démarrer. Le module interne est indisponible."
            )
        await callback(self.builder, ctx, template="sentrix")

    @create.command(name="server", aliases=["serveur"])
    @checks.is_owner_or_admin_for("configuration")
    async def create_server(self, ctx: commands.Context):
        """Alias espacé de la commande historique ``+create-server``."""
        command = self.bot.get_command("create-server")
        if command is None:
            logger.error("+create server demandé mais +create-server est absent du registre.")
            return await ctx.send(
                "Le constructeur général n'est pas chargé. Réessaie après le redémarrage de SentriX."
            )

        # Aucun argument n'est nécessaire pour create-server. Le sous-ordre possède déjà
        # le même contrôle de permission configuration ; ctx.invoke évite de dupliquer
        # l'implémentation du constructeur général.
        await ctx.invoke(command)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # Conserve le comportement spécial de #🤖・sentrix-chat du builder sans enregistrer
        # son ancienne commande top-level ``create``.
        listener = getattr(self.builder, "on_message", None)
        if listener is None:
            return
        await listener(message)


async def install(bot: commands.Bot) -> None:
    """Supprime toute ancienne racine ``create`` puis installe le routeur canonique."""
    current = bot.get_command("create")
    current_cog = bot.get_cog("CreateSentrix")

    if (
        current is not None
        and current_cog is not None
        and getattr(current_cog, "_sentrix_canonical_create_router", False)
        and getattr(current, "cog", None) is current_cog
    ):
        return

    # Retirer d'abord le Cog historique supprime aussi ses listeners et ses commandes.
    if current_cog is not None:
        try:
            await bot.remove_cog("CreateSentrix")
        except Exception:
            logger.exception("Impossible de retirer l'ancien Cog CreateSentrix.")

    # Filet de sécurité si une ancienne commande a été ajoutée manuellement sans son Cog.
    stale = bot.get_command("create")
    if stale is not None:
        removed = bot.remove_command("create")
        logger.warning(
            "Ancienne racine +create supprimée avant installation canonique : %s",
            getattr(removed, "qualified_name", getattr(stale, "qualified_name", "create")),
        )

    await bot.add_cog(CreateRouter(bot))

    root = bot.get_command("create")
    sentrix = bot.get_command("create sentrix")
    server = bot.get_command("create server")
    if not isinstance(root, commands.Group) or sentrix is None or server is None:
        raise RuntimeError(
            "Registre +create incomplet après installation canonique "
            f"(root={bool(root)}, sentrix={bool(sentrix)}, server={bool(server)})."
        )

    logger.info(
        "Routeur +create actif : +create sentrix, +create server et +create-server coexistants."
    )


async def setup(bot: commands.Bot) -> None:
    await install(bot)


__all__ = ["CreateRouter", "install", "setup"]
