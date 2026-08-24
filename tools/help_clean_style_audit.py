#!/usr/bin/env python3
"""Audit léger de l'interface +help avec le thème SentriX V2.

L'ancien test exigeait zéro emoji. Le nouveau design autorise de petits pictogrammes
fonctionnels et laisse la couche centrale convertir les titres historiques en cartes V2.
Ce test reste indépendant du token Discord et de la base de données.
"""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def run() -> int:
    errors: list[str] = []

    import discord
    from utils import command_style_v2

    command_style_v2.install()

    help_path = ROOT / "cogs" / "help_clean_style.py"
    source = help_path.read_text(encoding="utf-8")

    # Garde-fous de structure : +help reste paginé et searchable au lieu de devenir un
    # énorme dump de commandes dans un seul message.
    required_markers = (
        "def _help_home(",
        "def _category_pages(",
        "def _all_pages(",
        "CleanHelpSearchModal",
        "discord.ui.Select",
        "discord.ui.Button",
    )
    for marker in required_markers:
        if marker not in source:
            errors.append(f"fonctionnalité +help manquante: {marker}")

    # Simulation de l'accueil avant/après renderer final. Les anciens titres du help sont
    # volontairement acceptés en entrée : le thème global doit les rendre modernes.
    home = discord.Embed(
        title="SENTRIX / AIDE",
        description=(
            "**119 commandes** • préfixe `+`\n"
            "Choisis une catégorie ci-dessous ou utilise la recherche.\n\n"
            "Accès rapides : `+profile`  `+ticket`  `+daily`  `+setup`"
        ),
    )
    home.set_footer(text="SentriX • 12 catégories")
    command_style_v2.style_embed(home, category="utility", kind="info")

    if not str(home.title or "").startswith("✦ "):
        errors.append(f"titre accueil non V2: {home.title!r}")
    if len(str(home.title or "")) > 256:
        errors.append("titre +help trop long")
    if len(str(home.description or "")) > 4096:
        errors.append("description +help trop longue")
    if "SentriX" not in str(home.footer.text or ""):
        errors.append("footer SentriX absent sur +help")
    if home.timestamp is None:
        errors.append("timestamp absent de +help")

    # Menu représentatif : un pictogramme par option est autorisé et doit être conservé.
    select = discord.ui.Select(
        placeholder="Choisis une catégorie…",
        options=[
            discord.SelectOption(label="Modération", value="moderation", emoji="🛡️", description="Sanctions et gestion"),
            discord.SelectOption(label="Tickets", value="tickets", emoji="🎫", description="Support du serveur"),
            discord.SelectOption(label="Profil", value="profile", emoji="⚡", description="XP, niveau et activité"),
        ],
    )
    view = discord.ui.View(timeout=None)
    view.add_item(select)
    view.add_item(discord.ui.Button(label="Retour", style=discord.ButtonStyle.primary, custom_id="help:back"))
    command_style_v2.style_view(view)

    if len(select.options) > 25:
        errors.append("plus de 25 options dans le menu +help")
    for option in select.options:
        if not option.label or len(option.label) > 100:
            errors.append(f"label option +help invalide: {option.label!r}")
        if option.description and len(option.description) > 100:
            errors.append(f"description option +help trop longue: {option.label!r}")
        if option.emoji is None:
            errors.append(f"pictogramme fonctionnel supprimé: {option.label!r}")

    buttons = [item for item in view.children if isinstance(item, discord.ui.Button)]
    for button in buttons:
        if button.label and len(button.label) > 80:
            errors.append(f"bouton +help trop long: {button.label!r}")

    for error in errors:
        print(f"[ERROR] {error}")
    if errors:
        print(f"ECHEC: {len(errors)} probleme(s) de style +help V2")
        return 1

    print("OK: +help reste compact, navigable et compatible avec le thème premium SentriX V2")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
