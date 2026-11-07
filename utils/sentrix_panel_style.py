"""Bandeau fin et icônes d’application pour les centres interactifs SentriX."""

import discord

from utils import sentrix_emojis as icons

# Asset public versionné : aucune pièce jointe consommée ou supprimée au clic.
STRIP_URL = "https://raw.githubusercontent.com/eventore4567/mon-bot-discord/dashboard-refonte-2026-09/assets/sentrix/ui-strip-v1.png"


def banner(box):
    gallery = discord.ui.MediaGallery()
    gallery.add_item(media=STRIP_URL)
    box.add_item(gallery)


def decorate_controls(view):
    hints = (
        (("fermer", "annuler", "supprimer"), "close"),
        (("retour", "toutes les protections"), "return"),
        (("statistique", "classement"), "trophy"),
        (("sanction", "protection", "activer"), "security"),
        (("confiance", "rôle", "rejoindre", "adversaire"), "users"),
        (("sauvegarde", "restauration"), "backup"),
        (("texte", "message", "aperçu"), "message"),
        (("jouer", "lancer", "jeu"), "gamepad"),
    )
    for item in view.walk_children():
        if isinstance(item, discord.ui.Button) and item.emoji is None:
            label = str(item.label or "").casefold()
            key = next(
                (key for terms, key in hints if any(t in label for t in terms)),
                "settings",
            )
            item.emoji = icons.partiel(key)
