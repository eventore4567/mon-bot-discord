"""Routeur canonique et robuste de la famille de commandes ``+create``.

Une seule racine ``create`` existe dans SentriX :
- ``+create sentrix`` construit/répare l'espace officiel SentriX ;
- ``+create server`` ouvre le constructeur général existant ;
- ``+create-server`` reste disponible directement.

Le routeur appelle les services internes directement. Il n'invoque jamais une autre
commande décorée via ``ctx.invoke`` et n'appelle jamais le callback ``create`` du builder
SentriX : cela évite les conflits de registre et les wrappers de commande imbriqués.
"""
from __future__ import annotations

import logging

import discord
from discord.ext import commands

from utils import checks, embeds
from .create_sentrix import CreateSentrix as SentriXBuilder

logger = logging.getLogger("bot.create-router")


# Le nom de cog "CreateSentrix" appartient a cogs/create_sentrix.py. Le partager
# faisait echouer le chargement de create_sentrix (Cog named ... already loaded).
class CreateRouter(commands.Cog, name="CreateRouter"):
    """Racine unique des commandes ``+create``."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.builder = SentriXBuilder(bot)
        self._sentrix_canonical_create_router = True

    @staticmethod
    def _info(text: str, *, title: str = "Création SentriX") -> discord.Embed:
        return embeds.info(text, title=title)

    @staticmethod
    def _error(text: str, *, title: str = "Création impossible") -> discord.Embed:
        return embeds.error(text, title=title)

    async def _edit_or_send(
        self,
        ctx: commands.Context,
        message: discord.Message | None,
        embed: discord.Embed,
    ) -> None:
        if message is not None:
            try:
                await message.edit(content=None, embed=embed, view=None)
                return
            except (discord.NotFound, discord.Forbidden, discord.HTTPException, TypeError):
                logger.warning("Édition du message +create impossible ; nouvel envoi.", exc_info=True)
        await ctx.send(embed=embed)

    @commands.group(name="create", invoke_without_command=True)
    @checks.is_owner_or_admin_for("configuration")
    async def create(self, ctx: commands.Context):
        """Choisir le constructeur à lancer."""
        if ctx.invoked_subcommand is not None:
            return
        await ctx.send(
            embed=self._info(
                "`+create sentrix` — crée ou répare le serveur support professionnel SentriX.\n"
                "`+create server` — ouvre le constructeur général de serveur.\n"
                "`+create-server` — syntaxe historique, toujours disponible."
            )
        )

    @create.command(name="sentrix")
    @checks.is_owner_or_admin_for("configuration")
    async def create_sentrix(self, ctx: commands.Context):
        """Créer ou réparer le serveur support professionnel SentriX."""
        guild = ctx.guild
        if guild is None or not isinstance(ctx.author, discord.Member):
            return await ctx.send(
                embed=self._error("Cette commande doit être utilisée dans un serveur Discord.")
            )

        try:
            if not await self.builder._authorized(ctx):
                return await ctx.send(
                    embed=self._error("Cette commande est réservée aux administrateurs du serveur.")
                )
        except Exception as error:
            logger.exception("Vérification d'accès +create sentrix impossible guild=%s", guild.id)
            return await ctx.send(
                embed=self._error(
                    f"La vérification des permissions a échoué : `{type(error).__name__}`."
                )
            )

        me = guild.me
        if me is None:
            return await ctx.send(
                embed=self._error("SentriX n'est pas correctement présent sur ce serveur.")
            )
        if not me.guild_permissions.administrator:
            return await ctx.send(
                embed=self._error(
                    "Donnez temporairement la permission **Administrateur** à SentriX, placez son rôle "
                    "assez haut, puis relancez `+create sentrix`."
                )
            )

        lock = self.builder._lock_for(guild.id)
        if lock.locked():
            return await ctx.send(
                embed=self._info(
                    "Une création/réparation SentriX est déjà en cours sur ce serveur.",
                    title="Installation déjà en cours",
                )
            )

        progress: discord.Message | None = None
        async with lock:
            try:
                # IMPORTANT : embed explicite. Le précédent chemin envoyait du texte brut,
                # qui passait par plusieurs wrappers de rendu et pouvait lever un TypeError
                # avant même l'entrée dans le try du constructeur historique.
                progress = await ctx.send(
                    embed=self._info(
                        "Je vérifie les rôles, salons, permissions, logs, messages et tickets. "
                        "La commande est relançable et réutilise les éléments déjà présents.",
                        title="Installation SentriX en cours",
                    )
                )

                # Appel du SERVICE, pas du callback d'une Command discord.py décorée.
                result = await self.builder._build(guild, ctx.author)

                warnings = list(result.get("warnings") or [])
                warning_text = (
                    "\n**À vérifier :** " + ", ".join(str(item) for item in warnings)
                    if warnings
                    else ""
                )
                summary = embeds.success(
                    "Le serveur SentriX a été créé/réparé avec succès.\n\n"
                    f"**Rôles :** {result.get('roles_created', 0)} créé(s) / {result.get('roles_total', 0)} prévu(s)\n"
                    f"**Catégories :** {result.get('categories_created', 0)} créée(s) / {result.get('categories_total', 0)} prévue(s)\n"
                    f"**Salons :** {result.get('channels_created', 0)} nouveau(x)\n"
                    f"**Logs :** {result.get('logs_ready', 0)} catégorie(s) reliée(s)\n"
                    f"**Tickets :** {'prêts' if result.get('ticket_ready') else 'à vérifier'}"
                    f"{warning_text}",
                    title="Installation SentriX terminée",
                )
                await self._edit_or_send(ctx, progress, summary)
                return

            except discord.Forbidden as error:
                logger.exception("+create sentrix refusé par Discord guild=%s", guild.id)
                await self._edit_or_send(
                    ctx,
                    progress,
                    self._error(
                        f"Discord a refusé une action. Vérifiez que SentriX possède **Administrateur** et que son rôle est placé au-dessus des rôles qu'il doit gérer. Erreur : `{type(error).__name__}`."
                    ),
                )
                return
            except discord.HTTPException as error:
                logger.exception("+create sentrix erreur HTTP guild=%s", guild.id)
                detail = str(error).replace("\n", " ")[:220]
                await self._edit_or_send(
                    ctx,
                    progress,
                    self._error(
                        "Discord a interrompu l'installation. Les éléments déjà créés seront réutilisés "
                        "au prochain essai. "
                        f"Détail : `{type(error).__name__}: {detail}`"
                    ),
                )
                return
            except Exception as error:
                # Le vrai type + message est maintenant journalisé et affiché. Plus de
                # « NoneType: None » impossible à diagnostiquer.
                logger.exception(
                    "+create sentrix erreur interne guild=%s type=%s detail=%s",
                    guild.id,
                    type(error).__name__,
                    str(error)[:500],
                )
                detail = str(error).replace("\n", " ")[:220] or "aucun détail fourni"
                await self._edit_or_send(
                    ctx,
                    progress,
                    self._error(
                        "La création a rencontré une erreur interne avant la fin. "
                        "Aucun verrou définitif n'a été posé et la commande peut être relancée.\n\n"
                        f"**Erreur réelle :** `{type(error).__name__}: {detail}`"
                    ),
                )
                return

    @create.command(name="server", aliases=["serveur"])
    @checks.is_owner_or_admin_for("configuration")
    async def create_server(self, ctx: commands.Context):
        """Alias espacé et robuste de ``+create-server``."""
        command = self.bot.get_command("create-server")
        if command is None:
            logger.error("+create server demandé mais +create-server est absent du registre.")
            return await ctx.send(
                embed=self._error(
                    "Le constructeur général n'est pas chargé. Le module `ServerBuilder` est absent."
                )
            )

        callback = getattr(command, "callback", None)
        cog = getattr(command, "cog", None)
        if callback is None or cog is None:
            logger.error(
                "+create-server présent mais callback/cog invalide callback=%s cog=%s",
                bool(callback),
                bool(cog),
            )
            return await ctx.send(
                embed=self._error("Le constructeur général est chargé mais son exécuteur est invalide.")
            )

        try:
            # Le routeur possède déjà le check configuration. Appeler directement le
            # callback évite ctx.invoke() et ses couches imbriquées qui provoquaient des
            # erreurs de routage dans la famille +create.
            await callback(cog, ctx)
        except Exception as error:
            logger.exception(
                "+create server erreur guild=%s type=%s detail=%s",
                getattr(getattr(ctx, "guild", None), "id", None),
                type(error).__name__,
                str(error)[:500],
            )
            detail = str(error).replace("\n", " ")[:220] or "aucun détail fourni"
            await ctx.send(
                embed=self._error(
                    f"Le constructeur général a rencontré `{type(error).__name__}: {detail}`."
                )
            )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Conserve le comportement spécial du salon 🤖・sentrix-chat."""
        listener = getattr(self.builder, "on_message", None)
        if listener is None:
            return
        await listener(message)


async def install(bot: commands.Bot) -> None:
    """Supprime toute ancienne racine ``create`` puis installe le routeur canonique."""
    current = bot.get_command("create")
    installed = bot.get_cog("CreateRouter")

    if (
        current is not None
        and installed is not None
        and getattr(installed, "_sentrix_canonical_create_router", False)
        and getattr(current, "cog", None) is installed
    ):
        return

    # Le routeur prend la racine +create au cog historique, qui garde son propre nom.
    legacy_cog = bot.get_cog("CreateSentrix")
    if legacy_cog is not None:
        try:
            await bot.remove_cog("CreateSentrix")
        except Exception:
            logger.exception("Impossible de retirer l'ancien Cog CreateSentrix.")

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
    legacy = bot.get_command("create-server")
    if not isinstance(root, commands.Group) or sentrix is None or server is None or legacy is None:
        raise RuntimeError(
            "Registre +create incomplet après installation canonique "
            f"(root={bool(root)}, sentrix={bool(sentrix)}, server={bool(server)}, legacy={bool(legacy)})."
        )

    logger.info(
        "Routeur +create actif et vérifié : +create sentrix, +create server et +create-server."
    )


async def setup(bot: commands.Bot) -> None:
    await install(bot)


__all__ = ["CreateRouter", "install", "setup"]
