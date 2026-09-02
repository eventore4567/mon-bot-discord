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

logger = logging.getLogger("bot.final-error-embed-v5")

BAR = "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
# Ces deux couleurs etaient figees en dur et datent d'avant l'unification de la
# palette. Comme ce module rend TOUS les messages d'erreur du bot, chaque refus,
# chaque cooldown et chaque erreur interne sortait encore a l'ancienne teinte
# pendant que le reste du bot affichait la nouvelle. Source unique desormais.
ERROR_COLOR = int(_config.COLOR_ERROR)
WARNING_COLOR = int(_config.COLOR_WARNING)
FOOTER = "SentriX • Réponse rapide et sécurisée"
_ALLOWED = discord.AllowedMentions(everyone=False, users=False, roles=False, replied_user=False)


def _clip(value: object, limit: int = 3900) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(1, limit - 1)].rstrip() + "…"


def _panel(title: str, description: str, *, warning: bool = False) -> discord.Embed:
    embed = discord.Embed(
        title=_clip(title, 256) or "Erreur de commande",
        description=f"{BAR}\n{_clip(description)}",
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


def _prefix_error_panel(ctx: commands.Context, error: commands.CommandError) -> panels.Panneau:
    """Panneau composé pour une erreur de commande préfixée.

    Chaque cas expose désormais ses informations en SECTIONS séparées plutôt qu'en
    un paragraphe unique : ce qui bloque, ce qu'il faut essayer, où trouver la
    syntaxe. La bannière porte l'intention avant même la lecture du titre.
    """
    base = getattr(error, "original", error)
    prefix = _prefix(ctx)
    commande = str(getattr(getattr(ctx, "command", None), "qualified_name", "") or "")

    if isinstance(base, commands.CommandNotFound):
        typed = str(getattr(ctx, "invoked_with", "") or "").strip()
        # Renvoyer vers +help alors qu'on CONNAIT les commandes proches n'aide
        # personne : taper « +sticky » doit proposer sticky-set / sticky-off. La
        # recherche vit dans command_response_guard, on la reutilise.
        suggestions: list[str] = []
        try:
            from . import command_response_guard as guard

            suggestions = guard._command_suggestions(getattr(ctx, "bot", None), ctx, typed)
        except Exception:
            logger.debug("Suggestions de commandes indisponibles.", exc_info=True)

        sections = []
        if suggestions:
            sections.append(
                panels.Section(
                    "Vouliez-vous dire",
                    [
                        panels.Ligne(f"{prefix}{nom}", "Commande existante")
                        for nom in suggestions[:3]
                    ],
                )
            )
        sections.append(_aide(prefix, suggestions[0] if suggestions else ""))
        return _panneau(
            "Commande introuvable",
            f"`{prefix}{typed}` n'existe pas.",
            sections=sections,
            boutons=[panels.Bouton("Voir toutes les commandes", custom_id="sentrix:erreur:help")],
        )

    if isinstance(base, commands.MissingRequiredArgument):
        nom = str(getattr(getattr(base, "param", None), "name", "argument") or "argument")
        return _panneau(
            "Argument manquant",
            f"L'argument **{nom}** est obligatoire.",
            kind="warning",
            sections=[
                panels.Section("Syntaxe attendue", [panels.Ligne("Commande", f"`{_usage(ctx)}`")]),
                _aide(prefix, commande),
            ],
        )

    if isinstance(base, commands.TooManyArguments):
        return _panneau(
            "Trop d'arguments",
            "Cette commande attend moins de valeurs que ce qui a été fourni.",
            kind="warning",
            sections=[
                panels.Section("Syntaxe attendue", [panels.Ligne("Commande", f"`{_usage(ctx)}`")]),
                _aide(prefix, commande),
            ],
        )

    introuvables = {
        commands.MemberNotFound: ("Utilisateur introuvable", "ce membre", "une mention, un pseudo ou un identifiant"),
        commands.UserNotFound: ("Utilisateur introuvable", "cet utilisateur", "une mention, un pseudo ou un identifiant"),
        commands.RoleNotFound: ("Rôle introuvable", "ce rôle", "une mention, un nom ou un identifiant"),
        commands.ChannelNotFound: ("Salon introuvable", "ce salon", "une mention, un nom ou un identifiant"),
        commands.MessageNotFound: ("Message introuvable", "ce message", "un identifiant ou un lien de message"),
    }
    for type_erreur, (titre, quoi, accepte) in introuvables.items():
        if isinstance(base, type_erreur):
            return _panneau(
                titre,
                f"SentriX n'a pas trouvé {quoi} sur ce serveur.",
                sections=[
                    panels.Section(
                        "Formats acceptés",
                        [panels.Ligne("Vous pouvez donner", accepte)],
                    ),
                    panels.Section("Syntaxe attendue", [panels.Ligne("Commande", f"`{_usage(ctx)}`")]),
                ],
            )

    if isinstance(base, (commands.BadUnionArgument, commands.BadArgument, commands.ConversionError)):
        return _panneau(
            "Argument invalide",
            "Une des valeurs fournies n'a pas le format attendu.",
            kind="warning",
            sections=[
                panels.Section("Syntaxe attendue", [panels.Ligne("Commande", f"`{_usage(ctx)}`")]),
                _aide(prefix, commande),
            ],
        )

    if isinstance(base, commands.CommandOnCooldown):
        secondes = max(0.1, float(base.retry_after))
        return _panneau(
            "Commande en attente",
            f"Cette commande est limitée pour éviter les abus.",
            kind="warning",
            sections=[
                panels.Section(
                    "Délai restant",
                    [
                        panels.Ligne(
                            "Réessayez dans",
                            f"**{secondes:.1f} s**",
                            indice="Le compteur repart à chaque utilisation réussie.",
                        )
                    ],
                )
            ],
        )

    if isinstance(base, commands.MissingPermissions):
        requise = _libelles(base.missing_permissions)
        return _panneau(
            "Permission insuffisante",
            "Vous n'avez pas le droit d'utiliser cette commande ici.",
            sections=[
                panels.Section("Permission requise", [panels.Ligne("Il vous faut", f"**{requise}**")]),
                panels.Section(
                    "Comment l'obtenir",
                    [
                        panels.Ligne("Par un administrateur", "Paramètres du serveur › Rôles"),
                        panels.Ligne("Ou via SentriX", f"`{prefix}setup` › Permissions"),
                    ],
                ),
            ],
        )

    if isinstance(base, commands.BotMissingPermissions):
        requise = _libelles(base.missing_permissions)
        return _panneau(
            "SentriX n'a pas les permissions",
            "L'action a été refusée par Discord, pas par SentriX.",
            sections=[
                panels.Section("Permission manquante", [panels.Ligne("SentriX a besoin de", f"**{requise}**")]),
                panels.Section(
                    "Comment la donner",
                    [
                        panels.Ligne("1", "Paramètres du serveur › Rôles"),
                        panels.Ligne("2", "Ouvrez le rôle **SentriX**"),
                        panels.Ligne("3", f"Activez **{requise}**, puis relancez la commande"),
                    ],
                ),
            ],
        )

    if isinstance(base, commands.NoPrivateMessage):
        return _panneau(
            "Serveur requis",
            "Cette commande a besoin d'un serveur pour savoir sur quoi agir.",
            kind="warning",
            sections=[panels.Section("Où l'utiliser", [panels.Ligne("Lieu", "Dans un salon d'un serveur où SentriX est présent")])],
        )

    if isinstance(base, commands.PrivateMessageOnly):
        return _panneau(
            "Message privé requis",
            "Cette commande ne fonctionne qu'en conversation privée avec SentriX.",
            kind="warning",
            sections=[panels.Section("Où l'utiliser", [panels.Ligne("Lieu", "Dans vos messages privés avec SentriX")])],
        )

    cls = type(base).__name__
    if cls == "BotBlacklistedError":
        raison = str(getattr(base, "reason", "") or "Aucune raison fournie")
        return _panneau(
            "Accès refusé",
            "Vous n'êtes pas autorisé à utiliser SentriX.",
            sections=[panels.Section("Raison", [panels.Ligne("Motif enregistré", raison)])],
        )

    if cls == "BotPermissionError" or isinstance(base, commands.CheckFailure):
        message = str(getattr(base, "message", "") or "Vous n'êtes pas autorisé à utiliser cette commande.")
        return _panneau(
            "Accès refusé",
            message,
            sections=[
                panels.Section(
                    "Que faire",
                    [panels.Ligne("Demandez au staff", f"Un administrateur peut ouvrir l'accès via `{prefix}setup` › Permissions")],
                )
            ],
        )

    if isinstance(base, discord.Forbidden):
        return _panneau(
            "Discord a refusé l'action",
            "SentriX a bien reçu la commande, mais Discord a bloqué l'exécution.",
            sections=[
                panels.Section(
                    "Causes possibles",
                    [
                        panels.Ligne("Hiérarchie", "Le rôle **SentriX** est placé sous le rôle ou le membre visé"),
                        panels.Ligne("Permission", "Une permission manque sur ce salon ou sur le serveur"),
                    ],
                ),
                panels.Section(
                    "Correction",
                    [panels.Ligne("À faire", "Remontez le rôle **SentriX** dans Paramètres du serveur › Rôles")],
                ),
            ],
        )

    return _panneau(
        "Erreur de commande",
        "Une erreur technique a interrompu la commande.",
        sections=[
            panels.Section(
                "Ce qui s'est passé",
                [
                    panels.Ligne("Effet sur le serveur", "**Aucun** — rien n'a été modifié"),
                    panels.Ligne("Signalement", "L'erreur a été enregistrée automatiquement"),
                ],
            ),
            panels.Section("Ce que vous pouvez faire", [panels.Ligne("Vérifiez la syntaxe", f"`{_usage(ctx)}`")]),
            _aide(prefix, commande),
        ],
    )


def _slash_error_panel(error: discord.app_commands.AppCommandError) -> panels.Panneau:
    """Meme composition que les erreurs prefixees : une commande slash qui echoue
    ne doit pas ressembler a autre chose qu'une commande prefixee qui echoue."""
    original = getattr(error, "original", error)

    if isinstance(error, discord.app_commands.CommandOnCooldown):
        secondes = max(0.1, float(error.retry_after))
        return _panneau(
            "Commande en attente",
            "Cette commande est limitée pour éviter les abus.",
            kind="warning",
            sections=[
                panels.Section(
                    "Délai restant",
                    [panels.Ligne("Réessayez dans", f"**{secondes:.1f} s**")],
                )
            ],
        )

    if isinstance(error, discord.app_commands.MissingPermissions):
        requise = _libelles(error.missing_permissions)
        return _panneau(
            "Permission insuffisante",
            "Vous n'avez pas le droit d'utiliser cette commande ici.",
            sections=[
                panels.Section("Permission requise", [panels.Ligne("Il vous faut", f"**{requise}**")]),
                panels.Section(
                    "Comment l'obtenir",
                    [panels.Ligne("Par un administrateur", "Paramètres du serveur › Rôles")],
                ),
            ],
        )

    if isinstance(error, discord.app_commands.BotMissingPermissions):
        requise = _libelles(error.missing_permissions)
        return _panneau(
            "SentriX n'a pas les permissions",
            "L'action a été refusée par Discord, pas par SentriX.",
            sections=[
                panels.Section("Permission manquante", [panels.Ligne("SentriX a besoin de", f"**{requise}**")]),
                panels.Section(
                    "Comment la donner",
                    [panels.Ligne("À faire", f"Activez **{requise}** sur le rôle SentriX, puis relancez")],
                ),
            ],
        )

    if isinstance(error, (discord.app_commands.TransformerError,
                          discord.app_commands.CommandSignatureMismatch)):
        return _panneau(
            "Argument invalide",
            "Une valeur fournie n'a pas le format attendu par cette commande.",
            kind="warning",
            sections=[
                panels.Section(
                    "Que faire",
                    [panels.Ligne("Vérifiez", "Le type de chaque option proposée par Discord")],
                )
            ],
        )

    cls = type(original).__name__
    if cls == "BotBlacklistedError":
        raison = str(getattr(original, "reason", "") or "Aucune raison fournie")
        return _panneau(
            "Accès refusé",
            "Vous n'êtes pas autorisé à utiliser SentriX.",
            sections=[panels.Section("Raison", [panels.Ligne("Motif enregistré", raison)])],
        )

    if cls == "BotPermissionError" or isinstance(error, discord.app_commands.CheckFailure):
        message = str(getattr(original, "message", "") or "Vous n'êtes pas autorisé à utiliser cette commande.")
        return _panneau("Accès refusé", message)

    return _panneau(
        "Erreur de commande",
        "Une erreur technique inattendue a interrompu la commande.",
        sections=[
            panels.Section(
                "Ce qui s'est passé",
                [
                    panels.Ligne("Effet sur le serveur", "**Aucun** — rien n'a été modifié"),
                    panels.Ligne("Signalement", "L'erreur a été enregistrée automatiquement"),
                ],
            ),
            panels.Section(
                "Ce que vous pouvez faire",
                [panels.Ligne("Réessayez", "Après avoir vérifié les options de la commande")],
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
    kwargs = {"view": panneau, "allowed_mentions": _ALLOWED}
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


async def _replace_prefix_response(ctx: commands.Context, panneau: panels.Panneau) -> bool:
    """Remplace la derniere reponse d'une commande au lieu d'en creer une deuxieme."""
    message = getattr(ctx, "_sentrix_last_response", None)
    if not isinstance(message, discord.Message):
        return False
    raw_edit = policy._unwrap(discord.Message.edit)
    try:
        await raw_edit(
            message,
            content=None,
            embeds=[],
            view=panneau,
            attachments=panneau.fichiers(),
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
        await raw_edit(interaction, content=None, embeds=[], view=panneau,
                       attachments=panneau.fichiers())
        return

    if not interaction.response.is_done():
        raw_response = policy._unwrap(discord.InteractionResponse.send_message)
        kwargs = {"view": panneau, "ephemeral": True, "allowed_mentions": _ALLOWED}
        fichiers = panneau.fichiers()
        if fichiers:
            kwargs["files"] = fichiers
        await raw_response(interaction.response, **kwargs)
        return

    # Une reponse normale existe deja. La remplacer evite le couple « resultat +
    # erreur » qui faisait croire a une double reponse de SentriX.
    try:
        await raw_edit(interaction, content=None, embeds=[], view=panneau,
                       attachments=panneau.fichiers())
        return
    except discord.NotFound:
        # Pas de message original : dans ce cas seulement, un follow-up ne duplique rien.
        raw_webhook = policy._unwrap(discord.Webhook.send)
        kwargs = {"view": panneau, "ephemeral": True, "allowed_mentions": _ALLOWED, "wait": True}
        fichiers = panneau.fichiers()
        if fichiers:
            kwargs["files"] = fichiers
        await raw_webhook(interaction.followup, **kwargs)


def install(bot: commands.Bot) -> None:
    async def prefix_error(self: commands.Bot, ctx: commands.Context, error: commands.CommandError):
        panel = _prefix_error_panel(ctx, error)
        try:
            if getattr(ctx, "_sentrix_response_sent", False):
                replaced = await _replace_prefix_response(ctx, panel)
                if not replaced:
                    logger.warning(
                        "Erreur après réponse pour +%s : deuxième message supprimé pour éviter un doublon.",
                        getattr(getattr(ctx, "command", None), "qualified_name", "commande"),
                    )
                return
            await _raw_prefix_send(ctx, panel)
        except Exception:
            logger.exception("V5 : impossible d’envoyer l’erreur préfixée en embed natif.")

    prefix_error._sentrix_final_error_embed_v5 = True
    bot.on_command_error = MethodType(prefix_error, bot)

    async def slash_error(interaction: discord.Interaction, error: discord.app_commands.AppCommandError):
        panel = _slash_error_panel(error)
        try:
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
