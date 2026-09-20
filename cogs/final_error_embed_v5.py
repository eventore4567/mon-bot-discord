"""V5 — autorité finale des erreurs utilisateur SentriX.

Une commande qui a déjà produit une réponse ne doit pas recevoir une deuxième carte
d'erreur. Les erreurs remplacent donc la réponse existante lorsque c'est possible ; un
follow-up n'est utilisé que lorsqu'aucune réponse originale exploitable n'existe.
"""
from __future__ import annotations

import logging
from types import MethodType

import discord

import config as _config
from utils import sentrix_panels as panels
from discord.ext import commands

from . import final_interaction_policy as policy
from core.errors import pipeline as error_pipeline

logger = logging.getLogger("bot.final-error-embed-v5")

BAR = ""
# Ces deux couleurs etaient figees en dur et datent d'avant l'unification de la
# palette. Comme ce module rend TOUS les messages d'erreur du bot, chaque refus,
# chaque cooldown et chaque erreur interne sortait encore a l'ancienne teinte
# pendant que le reste du bot affichait la nouvelle. Source unique desormais.
ERROR_COLOR = int(_config.COLOR_ERROR)
WARNING_COLOR = int(_config.COLOR_WARNING)
FOOTER = "SentriX • Réponse rapide et sécurisée"
from utils.error_texts import CHECK_FALLBACK as _CHECK_FALLBACK  # noqa: E402
_ALLOWED = discord.AllowedMentions(everyone=False, users=False, roles=False, replied_user=False)

# Un message d'erreur qui reste affiché indéfiniment finit par encombrer le
# salon : la personne corrige, réessaie, et l'ancien message traîne encore.
# 30 secondes laissent le temps de lire une erreur détaillée (syntaxe,
# permissions, sections explicatives) sans devenir un déchet permanent.
_DUREE_AFFICHAGE = 30
# Une simple faute de frappe ne doit pas polluer le salon aussi longtemps qu'une
# vraie erreur détaillée. Les réponses "commande introuvable" restent juste assez
# longtemps pour être lues puis disparaissent automatiquement.
_DUREE_COMMANDE_INTROUVABLE = 8


async def _effacer_plus_tard(message: discord.Message | None) -> None:
    """Programme la suppression pour les surfaces sans delete_after natif.

    Messageable.send, InteractionResponse.send_message et Message.edit
    acceptent delete_after directement. edit_original_response et
    Webhook.send ne l'acceptent pas : on programme la suppression à la main
    sur le message qu'ils renvoient.
    """
    if not isinstance(message, discord.Message):
        return
    try:
        await message.delete(delay=_DUREE_AFFICHAGE)
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        pass


def _clip(value: object, limit: int = 3900) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(1, limit - 1)].rstrip() + "…"


def _panel(title: str, description: str, *, warning: bool = False) -> discord.Embed:
    embed = discord.Embed(
        title=_clip(title, 256) or "Erreur de commande",
        description=_clip(description),
        colour=discord.Colour(WARNING_COLOR if warning else ERROR_COLOR),
    )
    embed.set_footer(text=FOOTER)
    return embed


def _panneau(
    titre: str,
    resume: str,
    *,
    kind: str = "danger",
    sections: "list[panels.Section] | tuple" = (),
    boutons: "list[panels.Bouton] | tuple" = (),
) -> panels.Panneau:
    """Panneau d'erreur composé : bannière en tête, résumé, puis sections.

    L'embed d'erreur affichait un titre et un pavé de texte. Le pavé contenait
    pourtant plusieurs informations de nature différente — ce qui s'est passé,
    ce qu'il faut faire, quelles commandes essayer — noyées dans un paragraphe.
    Chacune devient une section, avec son filet et son en-tête.
    """
    return panels.Panneau(
        titre=_clip(titre, 200) or "Erreur de commande",
        sous_titre=_clip(resume, 380),
        kind=kind,
        sections=list(sections),
        boutons=list(boutons),
        pied=FOOTER,
    )


def _aide(prefix: str, commande: str = "") -> panels.Section:
    """Section « où aller ensuite », présente sur toutes les erreurs bloquantes."""
    cible = f"{prefix}help {commande}".strip()
    return panels.Section(
        "Besoin d'aide",
        [panels.Ligne("Documentation", f"`{cible}`", indice="Syntaxe exacte, exemples et permissions requises.")],
    )


def _prefix(ctx: commands.Context) -> str:
    return str(getattr(ctx, "clean_prefix", None) or "+")


def _usage(ctx: commands.Context) -> str:
    command = getattr(ctx, "command", None)
    if command is None:
        return f"{_prefix(ctx)}help"
    signature = str(getattr(command, "signature", "") or "").strip()
    base = f"{_prefix(ctx)}{command.qualified_name}"
    return f"{base} {signature}".strip()


def _libelles(permissions) -> str:
    """Noms de permissions en francais.

    discord.py renvoie « ban_members » ; l'afficher tel quel oblige le lecteur a
    traduire lui-meme. access_matrix.permission_label porte deja les libelles utilises
    partout ailleurs dans SentriX : on les reutilise au lieu d'en inventer d'autres.
    """
    from utils.access_matrix import permission_label

    noms = [permission_label(str(p)) for p in (permissions or ())]
    if not noms:
        return "une permission supplémentaire"
    if len(noms) == 1:
        return noms[0]
    return ", ".join(noms[:-1]) + f" et {noms[-1]}"


# Code d'erreur Discord « Onboarding channels must be readable by everyone ».
_ONBOARDING_CHANNEL_ERROR = 350003


def _texte_discord(exc: discord.HTTPException) -> str:
    """Phrase courte pour un refus Discord (jamais de panneau pour un simple 4xx)."""
    if getattr(exc, "code", None) == _ONBOARDING_CHANNEL_ERROR:
        return "Ce salon fait partie de l'onboarding du serveur : Discord impose qu'il reste visible par tous."
    if isinstance(exc, discord.Forbidden):
        return "Discord a refusé l'action : vérifiez que le rôle SentriX est placé au-dessus du membre ou du rôle visé et qu'il possède la permission nécessaire."
    texte = str(getattr(exc, "text", "") or "").strip()
    return f"Discord a refusé la requête{f' : {texte}' if texte else ''}."


def _texte_erreur_prefix(ctx: commands.Context, error: commands.CommandError) -> str | None:
    """Une erreur SIMPLE (syntaxe, permission, refus Discord…) = UNE phrase.

    Retourne None uniquement pour une erreur technique inattendue, seule à mériter
    un panneau (avec référence de support)."""
    base = getattr(error, "original", error)
    prefix = _prefix(ctx)
    usage = _usage(ctx)

    if isinstance(base, commands.CommandNotFound):
        typed = str(getattr(ctx, "invoked_with", "") or "").strip()
        suggestions: list[str] = []
        try:
            from . import command_response_guard as guard

            suggestions = guard._command_suggestions(getattr(ctx, "bot", None), ctx, typed)
        except Exception:
            logger.debug("Suggestions de commandes indisponibles.", exc_info=True)
        texte = f"Commande introuvable : `{prefix}{typed}`."
        if suggestions:
            texte += " Vouliez-vous dire " + " ou ".join(f"`{prefix}{nom}`" for nom in suggestions[:2]) + " ?"
        else:
            texte += f" Voir `{prefix}help`."
        return texte
    # Textes partagés avec le transport slash (utils/error_texts.py) : permission exacte,
    # message d'un BotPermissionError conservé, argument fautif nommé.
    from utils import error_texts

    parametre = getattr(getattr(ctx, "current_parameter", None), "name", None)
    partage = error_texts.user_error_text(base, usage=usage, param_name=parametre)
    if partage is not None:
        return partage
    if isinstance(base, commands.CheckFailure):
        # Check nu sans raison : demandée à la matrice / aux systèmes coupés par
        # l'appelant asynchrone (prefix_error) ; ici on ne conclut jamais « permission ».
        return error_texts.CHECK_FALLBACK
    if isinstance(base, commands.MissingRequiredArgument):
        return f"Usage : `{usage}`"
    if isinstance(base, commands.TooManyArguments):
        return f"Trop d'arguments. Usage : `{usage}`"
    introuvables = {
        commands.MemberNotFound: "Membre introuvable : indiquez une mention, un pseudo ou un identifiant.",
        commands.UserNotFound: "Utilisateur introuvable : indiquez une mention, un pseudo ou un identifiant.",
        commands.RoleNotFound: "Rôle introuvable : indiquez une mention, un nom ou un identifiant.",
        commands.ChannelNotFound: "Salon introuvable : indiquez une mention, un nom ou un identifiant.",
        commands.MessageNotFound: "Message introuvable : indiquez un identifiant ou un lien de message.",
    }
    for type_erreur, texte in introuvables.items():
        if isinstance(base, type_erreur):
            return texte
    if isinstance(base, commands.RangeError):
        minimum, maximum = getattr(base, "minimum", None), getattr(base, "maximum", None)
        if minimum is not None and maximum is not None:
            return f"La valeur doit être comprise entre {minimum} et {maximum}. Usage : `{usage}`"
        return f"Valeur hors limites. Usage : `{usage}`"
    if isinstance(base, (commands.BadUnionArgument, commands.BadArgument, commands.ConversionError, commands.UserInputError)):
        return f"Argument invalide. Usage : `{usage}`"
    if isinstance(base, commands.CommandOnCooldown):
        return f"Commande en attente : réessayez dans {max(1, round(float(base.retry_after)))} s."
    if isinstance(base, commands.MaxConcurrencyReached):
        return "Cette commande est déjà en cours. Terminez-la avant de recommencer."
    if isinstance(base, commands.MissingPermissions):
        return f"Il vous faut la permission **{_libelles(base.missing_permissions)}** pour cette commande."
    if isinstance(base, commands.BotMissingPermissions):
        return f"Il manque à SentriX la permission **{_libelles(base.missing_permissions)}**."
    if isinstance(base, commands.NoPrivateMessage):
        return "Cette commande s'utilise dans un salon de serveur."
    if isinstance(base, commands.PrivateMessageOnly):
        return "Cette commande s'utilise en message privé avec SentriX."
    cls = type(base).__name__
    if cls == "RuntimeRateLimitError":
        secondes = max(1, round(float(getattr(base, "retry_after", 1.0) or 1.0)))
        return f"Fonction temporairement limitée : réessayez dans {secondes} s."
    if isinstance(base, discord.HTTPException):
        return _texte_discord(base)
    return None


def _texte_erreur_slash(error: discord.app_commands.AppCommandError) -> str | None:
    """Même règle pour les commandes slash natives."""
    original = getattr(error, "original", error)
    app = discord.app_commands
    if isinstance(error, app.CommandOnCooldown):
        return f"Commande en attente : réessayez dans {max(1, round(float(error.retry_after)))} s."
    if isinstance(error, app.MissingPermissions):
        from utils.error_texts import missing_permissions_text
        return missing_permissions_text(error.missing_permissions)
    if isinstance(error, app.BotMissingPermissions):
        from utils.error_texts import bot_missing_permissions_text
        return bot_missing_permissions_text(error.missing_permissions)
    if isinstance(error, (app.TransformerError, app.CommandSignatureMismatch)):
        return "Une des options fournies est invalide."
    from utils import error_texts

    for candidate in (error, original):
        partage = error_texts.user_error_text(candidate)
        if partage is not None:
            return partage
    if isinstance(error, app.CheckFailure) or isinstance(original, commands.CheckFailure):
        texte = error_texts.check_failure_message(error) or error_texts.check_failure_message(original)
        # Jamais « pas la permission » pour un check muet : le vrai motif est demandé à
        # la matrice par slash_error ; ici le dernier recours n'accuse pas une permission.
        return texte or error_texts.CHECK_FALLBACK
    if isinstance(original, commands.CommandError):
        # Passerelle V95/V98 : l'erreur d'origine est une erreur commands.py classique.
        class _Ctx:  # usage minimal pour _usage()/_prefix()
            command = None
            clean_prefix = "/"
            invoked_with = ""
            bot = None
        return _texte_erreur_prefix(_Ctx(), original)  # type: ignore[arg-type]
    if isinstance(original, discord.HTTPException):
        return _texte_discord(original)
    return None


def _prefix_error_panel(ctx: commands.Context, error: commands.CommandError) -> panels.Panneau:
    """Panneau compact réservé aux erreurs TECHNIQUES inattendues.

    Toutes les erreurs simples (syntaxe, permission, cible introuvable, refus
    Discord…) sont rendues en une phrase par ``_texte_erreur_prefix`` : ce
    panneau n'apparaît que lorsqu'un vrai bug a interrompu la commande, avec la
    référence enregistrée côté serveur.
    """
    base = getattr(error, "original", error)
    commande = str(getattr(getattr(ctx, "command", None), "qualified_name", "") or "")

    # Seul cas qui journalisait auparavant zero trace exploitable côté serveur —
    # voir docs/core-v2-audit-technical-debt.md §2. core.errors.pipeline.report()
    # écrit la trace complète dans les logs et retourne une référence courte,
    # affichée ici, à recouper avec les logs si le problème persiste.
    entree = error_pipeline.report(
        base,
        command=commande or "inconnue",
        transport="prefix",
        guild_id=ctx.guild.id if getattr(ctx, "guild", None) else None,
        user_id=getattr(getattr(ctx, "author", None), "id", None),
    )
    return _panneau(
        "Erreur de commande",
        "Une erreur technique a interrompu la commande. Réessayez ; si le problème persiste, communiquez cette référence au support.",
        sections=[
            panels.Section(
                "Détails",
                [
                    panels.Ligne("Référence", entree.code),
                    panels.Ligne("Commande", f"`{_usage(ctx)}`"),
                ],
            ),
        ],
    )


def _slash_error_panel(
    error: discord.app_commands.AppCommandError,
    *,
    command: str | None = None,
    guild_id: int | None = None,
    user_id: int | None = None,
) -> panels.Panneau:
    """Meme composition que les erreurs prefixees : une commande slash qui echoue
    ne doit pas ressembler a autre chose qu'une commande prefixee qui echoue.

    ``command``/``guild_id``/``user_id`` sont optionnels (rétrocompatibles avec
    tout appelant existant qui ne passe que ``error``) — utilisés uniquement pour
    enrichir la référence d'erreur du repli générique ci-dessous."""
    original = getattr(error, "original", error)

    entree = error_pipeline.report(
        original,
        command=command or "inconnue",
        transport="slash",
        guild_id=guild_id,
        user_id=user_id,
    )
    return _panneau(
        "Erreur de commande",
        "Une erreur technique a interrompu la commande. Réessayez ; si le problème persiste, communiquez cette référence au support.",
        sections=[
            panels.Section(
                "Détails",
                [
                    panels.Ligne("Référence", entree.code),
                    panels.Ligne("Commande", f"`/{command}`" if command else "`/help`"),
                ],
            ),
        ],
    )


def _component_error_panel(item: object | None) -> panels.Panneau:
    """Panneau affiche quand un bouton, un menu ou un formulaire echoue.

    Sans lui, discord.ui.View.on_error se contente de journaliser : le membre voit
    le « L'interaction a échoué » generique de Discord, sans savoir si l'action a
    ete faite ni quoi tenter.
    """
    libelle = str(getattr(item, "label", "") or getattr(item, "placeholder", "") or "").strip()
    quoi = f"**{_clip(libelle, 60)}**" if libelle else "cette action"
    return _panneau(
        "Action interrompue",
        f"Une erreur technique a interrompu {quoi}.",
        sections=[
            panels.Section(
                "État",
                [
                    panels.Ligne("Enregistré", "**Rien** — aucune modification n'a été appliquée"),
                    panels.Ligne("Panneau", "Il peut être rouvert sans risque"),
                ],
            ),
            panels.Section(
                "Que faire",
                [panels.Ligne("Relancez la commande", "Pour rouvrir le panneau depuis le début")],
            ),
        ],
    )


def _rembobiner(fichier: discord.File | None) -> None:
    """Un discord.File deja consomme repartirait vide au second essai."""
    try:
        if fichier is not None:
            fichier.reset(seek=True)
    except Exception:
        logger.debug("Rembobinage de la bannière impossible.", exc_info=True)


async def _raw_prefix_send(ctx: commands.Context, panneau: panels.Panneau) -> None:
    """Envoie le panneau d'erreur en repondant au message d'origine.

    La banniere part dans le MEME message que le panneau : c'est une piece jointe
    referencee par la MediaGallery du conteneur, pas un second envoi.
    """
    raw_send = policy._unwrap(discord.abc.Messageable.send)
    kwargs = {"view": panneau, "allowed_mentions": _ALLOWED, "delete_after": _DUREE_AFFICHAGE}
    fichiers = panneau.fichiers()
    if fichiers:
        kwargs["files"] = fichiers
    message = getattr(ctx, "message", None)
    if message is not None:
        kwargs["reference"] = discord.MessageReference(
            message_id=message.id,
            channel_id=ctx.channel.id,
            guild_id=ctx.guild.id if ctx.guild else None,
            fail_if_not_exists=False,
        )
        kwargs["mention_author"] = False
    try:
        sent = await raw_send(ctx.channel, **kwargs)
    except discord.HTTPException:
        kwargs.pop("reference", None)
        kwargs.pop("mention_author", None)
        for fichier in kwargs.get("files", []):
            _rembobiner(fichier)
        sent = await raw_send(ctx.channel, **kwargs)
    ctx._sentrix_response_sent = True
    if sent is not None:
        ctx._sentrix_last_response = sent


async def _texte_prefix_send(
    ctx: commands.Context,
    texte: str,
    *,
    supprimer_apres: float = _DUREE_AFFICHAGE,
) -> None:
    """Erreur simple = une ligne de texte dans le salon de la commande (jamais de carte)."""
    raw_send = policy._unwrap(discord.abc.Messageable.send)
    message = getattr(ctx, "_sentrix_last_response", None)
    if isinstance(message, discord.Message) and getattr(message.channel, "id", None) == getattr(ctx.channel, "id", None):
        raw_edit = policy._unwrap(discord.Message.edit)
        try:
            await raw_edit(
                message,
                content=texte[:1900],
                embeds=[],
                view=None,
                attachments=[],
                allowed_mentions=_ALLOWED,
                delete_after=supprimer_apres,
            )
            return
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            logger.debug("Impossible de remplacer la réponse préfixée par le texte d'erreur.", exc_info=True)
    sent = await raw_send(
        ctx.channel,
        content=texte[:1900],
        allowed_mentions=_ALLOWED,
        delete_after=supprimer_apres,
    )
    ctx._sentrix_response_sent = True
    if sent is not None:
        ctx._sentrix_last_response = sent


async def _texte_slash_send(interaction: discord.Interaction, texte: str) -> None:
    texte = texte[:1900]
    raw_edit = policy._unwrap(discord.Interaction.edit_original_response)
    if not interaction.response.is_done():
        raw_response = policy._unwrap(discord.InteractionResponse.send_message)
        await raw_response(interaction.response, content=texte, ephemeral=True, allowed_mentions=_ALLOWED)
        return
    try:
        await raw_edit(interaction, content=texte, embeds=[], view=None, attachments=[])
    except discord.NotFound:
        raw_webhook = policy._unwrap(discord.Webhook.send)
        await raw_webhook(interaction.followup, content=texte, ephemeral=True, allowed_mentions=_ALLOWED)


async def _replace_prefix_response(ctx: commands.Context, panneau: panels.Panneau) -> bool:
    """Remplace la derniere reponse d'une commande au lieu d'en creer une deuxieme."""
    message = getattr(ctx, "_sentrix_last_response", None)
    if not isinstance(message, discord.Message):
        return False
    # Jamais une réponse envoyée AILLEURS (le MP de sanction au membre, par exemple) :
    # l'erreur remplacerait le message privé du membre au lieu de répondre au modérateur.
    if getattr(message.channel, "id", None) != getattr(ctx.channel, "id", None):
        return False
    raw_edit = policy._unwrap(discord.Message.edit)
    try:
        await raw_edit(
            message,
            content=None,
            embeds=[],
            view=panneau,
            attachments=panneau.fichiers(),
            delete_after=_DUREE_AFFICHAGE,
        )
        return True
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        logger.debug("Impossible de remplacer la réponse préfixée existante.", exc_info=True)
        return False


async def _raw_slash_send(interaction: discord.Interaction, panneau: panels.Panneau) -> None:
    response_type = getattr(interaction.response, "type", None)
    deferred = response_type in {
        discord.InteractionResponseType.deferred_channel_message,
        discord.InteractionResponseType.deferred_message_update,
    }
    raw_edit = policy._unwrap(discord.Interaction.edit_original_response)

    if interaction.response.is_done() and deferred:
        message = await raw_edit(interaction, content=None, embeds=[], view=panneau,
                                 attachments=panneau.fichiers())
        await _effacer_plus_tard(message)
        return

    if not interaction.response.is_done():
        raw_response = policy._unwrap(discord.InteractionResponse.send_message)
        kwargs = {
            "view": panneau,
            "ephemeral": True,
            "allowed_mentions": _ALLOWED,
            "delete_after": _DUREE_AFFICHAGE,
        }
        fichiers = panneau.fichiers()
        if fichiers:
            kwargs["files"] = fichiers
        await raw_response(interaction.response, **kwargs)
        return

    # Une vraie réponse existe déjà : ne jamais la remplacer par une erreur tardive.
    # Les échecs de logs/cleanup après une action réussie ne doivent pas transformer
    # visuellement un « Succès » en « Erreur ». Les erreurs avant résultat passent par
    # le chemin deferred ci-dessus et restent donc affichées normalement.
    logger.warning(
        "Erreur slash après réponse déjà envoyée : résultat utilisateur conservé (%s).",
        getattr(getattr(interaction, "command", None), "qualified_name", "commande"),
    )
    return


def install(bot: commands.Bot) -> None:
    async def prefix_error(self: commands.Bot, ctx: commands.Context, error: commands.CommandError):
        base = getattr(error, "original", error)
        if (
            isinstance(base, commands.MissingRequiredArgument)
            and ctx.command is not None
            and ctx.command.qualified_name == "tictactoe"
            and getattr(base.param, "name", "") == "adversaire"
        ):
            # docs/core-v2-audit-technical-debt.md §3 : ce matchmaking vivait dans
            # cogs/bot_excellence_runtime.py::improved_error_handler, un patch de
            # classe (cls.on_command_error) définitivement masqué par le
            # remplacement d'instance ci-dessous (bot.on_command_error =
            # MethodType(prefix_error, bot)) — +tictactoe sans argument affichait
            # donc "Argument manquant" au lieu de chercher un adversaire.
            try:
                from .bot_excellence_runtime import _matchmake_tictactoe

                return await _matchmake_tictactoe(ctx)
            except Exception:
                logger.exception("V5 : matchmaking +tictactoe indisponible, repli sur le panneau d'erreur standard.")

        texte = _texte_erreur_prefix(ctx, error)
        if texte == _CHECK_FALLBACK and isinstance(base, commands.CheckFailure):
            try:
                from utils.error_texts import explain_check_failure

                texte = await explain_check_failure(
                    self, command=ctx.command, author=getattr(ctx, "author", None), guild=getattr(ctx, "guild", None),
                )
            except Exception:
                logger.debug("Explication du refus impossible.", exc_info=True)
        try:
            if texte is not None:
                duree = _DUREE_COMMANDE_INTROUVABLE if isinstance(base, commands.CommandNotFound) else _DUREE_AFFICHAGE
                await _texte_prefix_send(ctx, texte, supprimer_apres=duree)
                return
            panel = _prefix_error_panel(ctx, error)
            if getattr(ctx, "_sentrix_response_sent", False):
                logger.warning(
                    "Erreur après réponse pour +%s : réponse déjà envoyée conservée.",
                    getattr(getattr(ctx, "command", None), "qualified_name", "commande"),
                )
                return
            await _raw_prefix_send(ctx, panel)
        except Exception:
            logger.exception("V5 : impossible d’envoyer l’erreur préfixée en embed natif.")

    prefix_error._sentrix_final_error_embed_v5 = True
    bot.on_command_error = MethodType(prefix_error, bot)

    async def slash_error(interaction: discord.Interaction, error: discord.app_commands.AppCommandError):
        command = getattr(interaction, "command", None)
        texte = _texte_erreur_slash(error)
        if texte == _CHECK_FALLBACK:
            try:
                from utils.error_texts import explain_check_failure

                texte = await explain_check_failure(
                    bot, command=command, author=getattr(interaction, "user", None), guild=getattr(interaction, "guild", None),
                )
            except Exception:
                logger.debug("Explication du refus slash impossible.", exc_info=True)
        try:
            if texte is not None:
                await _texte_slash_send(interaction, texte)
                return
            panel = _slash_error_panel(
                error,
                command=getattr(command, "qualified_name", None),
                guild_id=interaction.guild_id,
                user_id=getattr(interaction.user, "id", None),
            )
            await _raw_slash_send(interaction, panel)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException, discord.ClientException):
            logger.exception("V5 : impossible d’envoyer l’erreur slash en embed natif.")

    slash_error._sentrix_final_error_embed_v5 = True
    bot.tree.on_error = slash_error

    # Boutons, menus et formulaires : discord.ui n'affiche RIEN par defaut, il
    # journalise. On branche sur les classes de base, donc les vues qui definissent
    # deja leur propre on_error gardent le leur — l'heritage s'en charge.
    if not getattr(discord.ui.View.on_error, "_sentrix_final_error_embed_v5", False):

        async def component_error(self, interaction, error, item=None):
            logger.exception("V5 : erreur dans un composant.", exc_info=error)
            try:
                await _raw_slash_send(interaction, _component_error_panel(item))
            except (discord.NotFound, discord.Forbidden, discord.HTTPException,
                    discord.ClientException):
                logger.exception("V5 : impossible d'afficher l'erreur de composant.")

        async def view_error(self, interaction, error, item):
            await component_error(self, interaction, error, item)

        async def modal_error(self, interaction, error):
            await component_error(self, interaction, error, None)

        view_error._sentrix_final_error_embed_v5 = True
        modal_error._sentrix_final_error_embed_v5 = True
        discord.ui.View.on_error = view_error
        discord.ui.Modal.on_error = modal_error

    logger.info("V5 erreurs actif : réponse existante remplacée, aucune carte d'erreur en doublon.")


__all__ = [
    "install",
    "_panel",
    "_prefix_error_panel",
    "_slash_error_panel",
    "_component_error_panel",
    "_replace_prefix_response",
]
