"""Métadonnées de permissions lisibles utilisées par +help et les erreurs SentriX."""
from __future__ import annotations

from discord.ext import commands

PERMISSION_LABELS = {
    "administrator": "Administrateur",
    "manage_guild": "Gérer le serveur",
    "manage_messages": "Gérer les messages",
    "moderate_members": "Modérer les membres",
    "ban_members": "Bannir des membres",
    "kick_members": "Expulser des membres",
    "manage_channels": "Gérer les salons",
    "manage_roles": "Gérer les rôles",
    "manage_webhooks": "Gérer les webhooks",
    "manage_events": "Gérer les événements",
    "manage_nicknames": "Gérer les pseudos",
    "mention_everyone": "Mentionner @everyone/@here et les rôles",
    "move_members": "Déplacer des membres",
    "mute_members": "Rendre muets des membres",
    "deafen_members": "Mettre en sourdine des membres",
}

OWNER_COGS = {"Owner"}
ADMIN_COGS = {
    "Configuration", "Logs", "ServerBuilder", "Automod", "Security", "SecurityTools",
    "SentriXSetup", "Notifications", "ProofVerification",
}

PUBLIC_COMMAND_FALLBACKS = {"proof", "proofstatus"}

COMMAND_PERMISSION_FALLBACKS = {
    "ban": "ban_members",
    "tempban": "ban_members",
    "unban": "ban_members",
    "kick": "kick_members",
    "mute": "moderate_members",
    "timeout": "moderate_members",
    "unmute": "moderate_members",
    "untimeout": "moderate_members",
    "warn": "moderate_members",
    "clear": "manage_messages",
    "purge": "manage_messages",
    "slowmode": "manage_channels",
    "lock": "manage_channels",
    "unlock": "manage_channels",
    "role": "manage_roles",
    "roleall": "manage_roles",
    "nick": "manage_nicknames",
    "setup": "administrator",
    "ticketsetup": "administrator",
    "logsetup": "administrator",
    "aisetup": "administrator",
    "shopsetup": "administrator",
    "gamesetup": "administrator",
    "statsconfig": "administrator",
    "designsetup": "administrator",
    "notifs-ping": "administrator",
    "notifs-remove": "administrator",
    "proofsetup": "administrator",
    "proofexample": "administrator",
    "proofexample-remove": "administrator",
    "proofexamples": "administrator",
    "proofpanel": "administrator",
    "proofreset": "administrator",
}

EXAMPLES = {
    "ban": "{prefix}ban @Utilisateur Spam",
    "kick": "{prefix}kick @Utilisateur Insultes répétées",
    "mute": "{prefix}mute @Utilisateur 10m Spam",
    "timeout": "{prefix}timeout @Utilisateur 10m Spam",
    "warn": "{prefix}warn @Utilisateur Publicité",
    "clear": "{prefix}clear 20",
    "balance": "{prefix}balance",
    "profil": "{prefix}profil",
    "profile": "{prefix}profile",
    "me": "{prefix}me",
    "setup": "{prefix}setup",
    "help": "{prefix}help ban",
    "proof": "{prefix}proof",
    "proofstatus": "{prefix}proofstatus",
    "proofsetup": "{prefix}proofsetup",
    "proofexample": "{prefix}proofexample Confirmation",
    "proofpanel": "{prefix}proofpanel",
}


def permission_label(key: str) -> str:
    return PERMISSION_LABELS.get(key, key.replace("_", " ").capitalize())


def command_requirement(command: commands.Command) -> str:
    cog_name = getattr(command.cog, "qualified_name", "") if command.cog else ""
    if cog_name in OWNER_COGS:
        return "Propriétaire global SentriX"

    labels: list[str] = []
    for predicate in getattr(command, "checks", ()):
        label = getattr(predicate, "_sentrix_permission_label", None)
        if label and label not in labels:
            labels.append(str(label))

    if labels:
        return " ou ".join(labels)

    name = command.qualified_name.casefold().split()[0]
    if name in PUBLIC_COMMAND_FALLBACKS:
        return "Aucune permission spéciale"

    permission = COMMAND_PERMISSION_FALLBACKS.get(name)
    if permission:
        return permission_label(permission)

    if cog_name in ADMIN_COGS:
        return "Administrateur"
    return "Aucune permission spéciale"


def command_example(command: commands.Command, prefix: str = "+") -> str:
    key = command.qualified_name.casefold()
    root = key.split()[0]
    template = EXAMPLES.get(key) or EXAMPLES.get(root)
    if template:
        return template.format(prefix=prefix)

    usage = command.usage or getattr(command, "signature", "") or ""
    usage = str(usage).strip()
    return f"{prefix}{command.qualified_name}" + (f" {usage}" if usage else "")