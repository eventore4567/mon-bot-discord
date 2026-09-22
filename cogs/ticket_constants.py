"""Constantes UI et validation du système de tickets."""

import re

import discord

TEXT_STYLES = {"court": discord.TextStyle.short, "long": discord.TextStyle.paragraph}
BUTTON_STYLES = {
    "bleu": discord.ButtonStyle.primary,
    "gris": discord.ButtonStyle.secondary,
    "vert": discord.ButtonStyle.success,
    "rouge": discord.ButtonStyle.danger,
}
BUTTON_STYLE_NAMES = list(BUTTON_STYLES.keys())
DEFAULT_BUTTON_STYLE = "bleu"

STAFF_BUTTONS = {
    "claim": ("Prendre en charge", "🙋"),
    "unclaim": ("Abandonner", "↩️"),
    "add": ("Ajouter un membre", "➕"),
    "remove": ("Retirer un membre", "➖"),
    "rename": ("Renommer", "✏️"),
    "transfer": ("Transférer", "🔀"),
    "note": ("Ajouter une note", "📝"),
    "bump": ("Relancer", "🔔"),
    "close": ("Fermer", "🔒"),
}
DEFAULT_ENABLED_BUTTONS = {"claim", "add", "remove", "rename", "note", "close"}

CUSTOM_COMPONENT_EMOJI_RE = re.compile(r"^<a?:[A-Za-z0-9_]{2,32}:[0-9]{15,22}>$")
