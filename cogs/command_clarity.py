"""Rend l'aide des commandes SentriX beaucoup plus simple à comprendre.

Le but n'est pas de renommer les commandes ni de modifier leur logique. Cette couche
transforme uniquement leur présentation dans +help : titre humain, phrase claire,
syntaxe lisible, exemple concret et explication des paramètres.

La génération est automatique à partir du registre actif. Une future commande bénéficie
donc du même rendu sans devoir être ajoutée manuellement ici.
"""
from __future__ import annotations

import logging
import re
from typing import Any

import discord
from discord.ext import commands

from utils import embeds
from utils import sentrix_panels as panels

logger = logging.getLogger("bot.command-clarity")
_INSTALLED = False


# Les noms très courts / techniques ont droit à un libellé humain explicite. Pour toutes
# les autres commandes, le titre est dérivé de leur description réelle.
FRIENDLY_TITLES: dict[str, str] = {
    "ai": "Parler avec l'IA de SentriX",
    "sentrix": "Poser une question à SentriX",
    "aidiag": "Vérifier si l'IA fonctionne",
    "aisetup": "Configurer l'intelligence artificielle",
    "bl": "Bloquer un utilisateur sur tout le bot",
    "unbl": "Débloquer un utilisateur du bot",
    "blinfo": "Voir une blacklist utilisateur",
    "editbl": "Modifier une blacklist utilisateur",
    "rps": "Jouer à Pierre • Feuille • Ciseaux",
    "afk": "Signaler que tu es absent",
    "create-logs": "Créer automatiquement les salons de logs",
    "logs-status": "Vérifier si les logs fonctionnent",
    "logsetup": "Configurer les logs un par un",
    "setup": "Configurer SentriX sur le serveur",
    "ticketsetup": "Configurer le système de tickets",
    "ticket": "Ouvrir un ticket",
    "giveaway-create": "Créer un giveaway",
    "giveaway-end": "Terminer un giveaway",
    "giveaway-reroll": "Choisir un nouveau gagnant",
    "guess-number": "Lancer une partie de nombre mystère",
    "tictactoe": "Jouer au morpion",
    "math-quiz": "Lancer un quiz de maths",
    "economyleaderboard": "Voir le classement d'argent",
    "leaderboard-levels": "Voir le classement des niveaux",
    "rolepanel": "Créer le panneau de rôles",
    "rolepanel-refresh": "Actualiser le panneau de rôles",
    "security-check": "Faire un diagnostic de sécurité",
    "permission-audit": "Vérifier les permissions dangereuses",
    "automod-status": "Voir l'état de l'AutoMod",
    "server-backup": "Sauvegarder la configuration du serveur",
    "server-restore": "Restaurer une sauvegarde du serveur",
    "bot-status": "Voir l'état de SentriX",
    "command-stats": "Voir les commandes les plus utilisées",
    "voice-time": "Voir le temps passé en vocal",
    "notifs-ping": "Créer une notification de publication",
    "notifs-list": "Voir les notifications configurées",
    "embed": "Créer un embed avec l'éditeur SentriX",
    "diagnostic": "Vérifier la configuration du serveur",
}


# Vocabulaire affiché aux utilisateurs. Les paramètres internes restent inchangés.
PARAMETER_LABELS: dict[str, tuple[str, str]] = {
    "membre": ("membre", "le membre concerné"),
    "member": ("membre", "le membre concerné"),
    "utilisateur": ("utilisateur", "l'utilisateur concerné"),
    "user": ("utilisateur", "l'utilisateur concerné"),
    "target": ("cible", "la personne ou l'élément concerné"),
    "cible": ("cible", "la personne ou l'élément concerné"),
    "role": ("rôle", "le rôle Discord à utiliser"),
    "rôle": ("rôle", "le rôle Discord à utiliser"),
    "salon": ("salon", "le salon Discord à utiliser"),
    "channel": ("salon", "le salon Discord à utiliser"),
    "raison": ("raison", "la raison de l'action"),
    "reason": ("raison", "la raison de l'action"),
    "duree": ("durée", "la durée, par exemple 10m ou 2h"),
    "durée": ("durée", "la durée, par exemple 10m ou 2h"),
    "duration": ("durée", "la durée, par exemple 10m ou 2h"),
    "time": ("durée", "la durée de l'action"),
    "montant": ("montant", "le nombre de pièces ou la somme"),
    "amount": ("montant", "le nombre de pièces ou la somme"),
    "nombre": ("nombre", "le nombre à utiliser"),
    "count": ("nombre", "le nombre à utiliser"),
    "texte": ("texte", "le texte à envoyer ou traiter"),
    "text": ("texte", "le texte à envoyer ou traiter"),
    "message": ("message", "le message à envoyer ou traiter"),
    "url": ("lien", "le lien complet à utiliser"),
    "lien": ("lien", "le lien complet à utiliser"),
    "niveau": ("niveau", "le niveau concerné"),
    "level": ("niveau", "le niveau concerné"),
    "prefixe": ("préfixe", "le nouveau préfixe du bot"),
    "préfixe": ("préfixe", "le nouveau préfixe du bot"),
    "prefix": ("préfixe", "le nouveau préfixe du bot"),
    "commande": ("commande", "le nom de la commande"),
    "command": ("commande", "le nom de la commande"),
    "choix": ("choix", "le choix à utiliser"),
    "choice": ("choix", "le choix à utiliser"),
    "question": ("question", "ta question pour SentriX"),
    "prompt": ("demande", "ce que tu veux demander à l'IA"),
    "recherche": ("recherche", "les mots à rechercher"),
    "query": ("recherche", "les mots à rechercher"),
    "nom": ("nom", "le nom à utiliser"),
    "name": ("nom", "le nom à utiliser"),
    "emoji": ("emoji", "l'emoji concerné"),
}

EXAMPLE_VALUES: dict[str, str] = {
    "membre": "@Membre",
    "member": "@Membre",
    "utilisateur": "@Membre",
    "user": "@Membre",
    "target": "@Membre",
    "cible": "@Membre",
    "role": "@Rôle",
    "rôle": "@Rôle",
    "salon": "#salon",
    "channel": "#salon",
    "raison": "spam",
    "reason": "spam",
    "duree": "10m",
    "durée": "10m",
    "duration": "10m",
    "time": "10m",
    "montant": "100",
    "amount": "100",
    "nombre": "10",
    "count": "10",
    "texte": '"Bonjour à tous"',
    "text": '"Bonjour à tous"',
    "message": '"Bonjour à tous"',
    "url": "https://exemple.com",
    "lien": "https://exemple.com",
    "niveau": "10",
    "level": "10",
    "prefixe": "!",
    "préfixe": "!",
    "prefix": "!",
    "commande": "ban",
    "command": "ban",
    "choix": "1",
    "choice": "1",
    "question": '"Comment améliorer mon serveur ?"',
    "prompt": '"Un logo futuriste violet"',
    "recherche": "ticket",
    "query": "ticket",
    "nom": "VIP",
    "name": "VIP",
    "emoji": "🔥",
}

_VERB_REWRITES = (
    ("Afficher ", "Affiche "),
    ("Définir ", "Configure "),
    ("Configurer ", "Configure "),
    ("Créer ", "Crée "),
    ("Supprimer ", "Supprime "),
    ("Ajouter ", "Ajoute "),
    ("Retirer ", "Retire "),
    ("Changer ", "Change "),
    ("Activer ", "Active "),
    ("Désactiver ", "Désactive "),
    ("Diagnostiquer ", "Vérifie "),
    ("Lister ", "Affiche "),
)


def _root_name(command: commands.Command) -> str:
    qualified = str(getattr(command, "qualified_name", "") or "").strip().casefold()
    return qualified.split(" ", 1)[0] if qualified else str(getattr(command, "name", "commande")).casefold()


def _clean_description(command: commands.Command) -> str:
    raw = re.sub(r"\s+", " ", str(getattr(command, "description", "") or "")).strip()
    if not raw or raw.casefold() in {"aucune description.", "pas de description.", "aucune description"}:
        return "Utilise cette commande pour gérer cette fonction de SentriX."
    raw = raw.rstrip(" .") + "."
    for before, after in _VERB_REWRITES:
        if raw.startswith(before):
            raw = after + raw[len(before):]
            break
    return raw


def friendly_title(command: commands.Command) -> str:
    root = _root_name(command)
    if root in FRIENDLY_TITLES:
        return FRIENDLY_TITLES[root]

    description = _clean_description(command).rstrip(".")
    if description and description != "Utilise cette commande pour gérer cette fonction de SentriX":
        title = description
    else:
        words = str(getattr(command, "qualified_name", "commande")).replace("-", " ").replace("_", " ")
        title = f"Utiliser {words}"

    if len(title) > 68:
        title = title[:65].rstrip() + "…"
    return title[0].upper() + title[1:] if title else "Commande SentriX"


def friendly_summary(command: commands.Command) -> str:
    summary = _clean_description(command)
    # Évite de répéter exactement le titre lorsque la description est très courte.
    if len(summary) > 150:
        summary = summary[:147].rstrip() + "…"
    return summary


def _parameter_name(name: str) -> str:
    key = str(name or "paramètre").casefold().strip().replace("-", "_")
    label = PARAMETER_LABELS.get(key)
    if label:
        return label[0]
    return key.replace("_", " ")


def _parameter_explanation(name: str) -> str:
    key = str(name or "paramètre").casefold().strip().replace("-", "_")
    label = PARAMETER_LABELS.get(key)
    if label:
        return label[1]
    return f"la valeur à utiliser pour « {_parameter_name(name)} »"


def command_usage(command: commands.Command, prefix: str) -> str:
    parts = [f"{prefix}{command.qualified_name}"]
    for name, parameter in getattr(command, "clean_params", {}).items():
        if name in {"ctx", "context", "interaction", "self"}:
            continue
        display = _parameter_name(name)
        parts.append(f"<{display}>" if getattr(parameter, "required", False) else f"[{display}]")
    return " ".join(parts)


def example_usage(command: commands.Command, prefix: str) -> str:
    parts = [f"{prefix}{command.qualified_name}"]
    optional_added = 0
    for name, parameter in getattr(command, "clean_params", {}).items():
        if name in {"ctx", "context", "interaction", "self"}:
            continue
        key = str(name).casefold().replace("-", "_")
        required = bool(getattr(parameter, "required", False))
        # Les paramètres obligatoires sont tous montrés. Pour les facultatifs, un seul
        # exemple suffit afin de garder une commande prête à copier et facile à lire.
        if not required and optional_added >= 1:
            continue
        value = EXAMPLE_VALUES.get(key, _parameter_name(name))
        if not required:
            optional_added += 1
        parts.append(value)
    return " ".join(parts)


def parameter_lines(command: commands.Command) -> list[str]:
    lines: list[str] = []
    for name, parameter in getattr(command, "clean_params", {}).items():
        if name in {"ctx", "context", "interaction", "self"}:
            continue
        required = bool(getattr(parameter, "required", False))
        status = "obligatoire" if required else "facultatif"
        lines.append(
            f"• **{_parameter_name(name)}** — {_parameter_explanation(name)} · *{status}*"
        )
    return lines


def _compact_line(utility: Any, command: commands.Command, prefix: str, slash_names: set[str], number: int | None = None) -> str:
    title = friendly_title(command)
    usage = command_usage(command, prefix)
    summary = friendly_summary(command)
    index = f"`{number:02d}` " if number is not None else ""
    badges: list[str] = []
    if utility.is_staff_command(command):
        badges.append("🔒 staff")
    if command.qualified_name in slash_names:
        badges.append("`/` disponible")
    badge_text = f"  ·  {' · '.join(badges)}" if badges else ""
    return f"{index}**{title}**\n`{usage}`{badge_text}\n└ {summary}"


def _related_commands(bot: commands.Bot, command: commands.Command, is_staff: bool, utility: Any, help_complete: Any) -> list[commands.Command]:
    category = help_complete._category_for(command).key
    result: list[commands.Command] = []
    for candidate in bot.walk_commands():
        if candidate is command or getattr(candidate, "hidden", False):
            continue
        if not is_staff and utility.is_staff_command(candidate):
            continue
        if help_complete._category_for(candidate).key != category:
            continue
        result.append(candidate)
        if len(result) >= 5:
            break
    return result


def install(bot: commands.Bot) -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    from . import help_complete, utility

    # Les listes de catégories et les résultats de recherche utilisent tous cette fonction.
    # Une seule substitution suffit donc pour rendre TOUT le catalogue plus lisible.
    help_complete._compact_command_line = _compact_line

    def format_command_line(command: commands.Command, prefix: str, slash_names: set[str]) -> str:
        return _compact_line(utility, command, prefix, slash_names)

    utility.format_command_line = format_command_line

    help_command = bot.get_command("help")
    if help_command is None:
        logger.warning("Command clarity chargé avant +help ; aucun callback à améliorer.")
        return

    original_callback = help_command.callback

    async def clearer_help_callback(cog, ctx: commands.Context, *, commande: str = None):
        if not commande:
            return await original_callback(cog, ctx, commande=commande)

        prefix = bot.command_prefix
        if callable(prefix):
            conf = await bot.db.get_guild_config(ctx.guild.id) if ctx.guild else None
            prefix = conf["prefix"] if conf and conf["prefix"] else "+"
        prefix = str(prefix)

        is_staff = await cog._user_is_staff(ctx)
        cmd = bot.get_command(str(commande).strip())
        if not cmd or (utility.is_staff_command(cmd) and not is_staff):
            try:
                from . import command_response_guard
                suggestions = command_response_guard._command_suggestions(bot, str(commande).strip())
            except Exception:
                suggestions = []
            suggestion_text = ""
            if suggestions:
                suggestion_text = "\n\nTu voulais peut-être dire : " + ", ".join(
                    f"`{prefix}{name}`" for name in suggestions[:3]
                )
            return await panels.envoyer(ctx, panels.depuis_embed(embeds.error(f"Je ne trouve pas la commande `{commande}` ou vous n'avez pas accès à son aide.{suggestion_text}\n\nTapez `{prefix}help` pour revenir au catalogue.")))

        slash_names = utility.slash_command_names(bot)
        title = friendly_title(cmd)
        summary = friendly_summary(cmd)
        syntax = command_usage(cmd, prefix)
        example = example_usage(cmd, prefix)
        category = help_complete._category_for(cmd)

        e = embeds.brand(f"📘 {title}", summary)
        if bot.user:
            e.set_thumbnail(url=bot.user.display_avatar.url)

        e.add_field(name="⌨️ Syntaxe", value=f"`{syntax}`", inline=False)
        e.add_field(
            name="🧪 Exemple concret",
            value=f"`{example}`\n*Vous pouvez remplacer les valeurs de l'exemple par les tiennes.*",
            inline=False,
        )

        params = parameter_lines(cmd)
        if params:
            e.add_field(name='🧩 Ce que vous devez mettre', value="\n".join(params)[:1024], inline=False)
        else:
            e.add_field(name="🧩 Paramètres", value='Aucun : vous pouvez lancer la commande directement.', inline=False)

        access_parts = [category.label]
        access_parts.append("🔒 Staff uniquement" if utility.is_staff_command(cmd) else "👤 Utilisable par les membres")
        access_parts.append("`/` + préfixe" if cmd.qualified_name in slash_names else f"préfixe `{prefix}`")
        e.add_field(name="🔐 Accès", value=" • ".join(access_parts), inline=False)

        aliases = list(getattr(cmd, "aliases", ()) or ())
        if aliases:
            e.add_field(
                name="🔁 Autres noms acceptés",
                value=", ".join(f"`{prefix}{alias}`" for alias in aliases[:12]),
                inline=False,
            )

        related = _related_commands(bot, cmd, is_staff, utility, help_complete)
        if related:
            e.add_field(
                name="🔗 Commandes proches",
                value=" • ".join(f"`{prefix}{item.qualified_name}`" for item in related),
                inline=False,
            )

        e.set_footer(text=f"Astuce : {prefix}help <commande> donne toujours une fiche comme celle-ci.")
        return await panels.envoyer(ctx, panels.depuis_embed(e))

    clearer_help_callback.__name__ = getattr(original_callback, "__name__", "help_cmd")
    clearer_help_callback.__doc__ = getattr(original_callback, "__doc__", None)
    help_command.callback = clearer_help_callback
    help_command._sentrix_clarity_callback = True

    _INSTALLED = True
    logger.info("Clarté des commandes activée : titres humains, syntaxe, exemples et paramètres sur tout +help.")
