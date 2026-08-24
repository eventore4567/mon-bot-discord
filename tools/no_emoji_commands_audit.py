#!/usr/bin/env python3
"""Audit du thème global des commandes SentriX V2.

Historique : ce fichier interdisait autrefois tous les emojis. Le langage visuel actuel
autorise au contraire de petits pictogrammes fonctionnels, comme sur le nouveau bot.
On conserve le nom du script pour ne pas casser les workflows existants, mais l'audit
vérifie désormais la cohérence du renderer central sans importer le bot de production.
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
    from utils import command_style_v2, premium_style

    command_style_v2.install()

    # Carte standard : le vrai titre doit rester visible, avec la signature courte V2.
    card = discord.Embed(
        title="Membre banni",
        description="Le membre a été banni avec succès.",
    )
    card.add_field(name="Raison", value="Spam", inline=False)
    command_style_v2.style_embed(
        card,
        category="moderation",
        kind="danger",
    )

    if not str(card.title or "").startswith("✦ "):
        errors.append(f"titre V2 absent: {card.title!r}")
    if "membre banni" not in str(card.title or "").casefold():
        errors.append(f"le vrai titre de commande est perdu: {card.title!r}")
    if int(card.colour.value if card.colour else 0) != command_style_v2.COLORS["danger"]:
        errors.append("une erreur/modération forte n'utilise pas le rouge V2")
    if card.timestamp is None:
        errors.append("timestamp absent de la carte V2")
    if "SentriX" not in str(card.footer.text or ""):
        errors.append(f"footer de marque absent: {card.footer.text!r}")

    success = discord.Embed(title="Configuration enregistrée", description="Tout est prêt.")
    command_style_v2.style_embed(success, category="configuration", kind="success")
    if int(success.colour.value if success.colour else 0) != command_style_v2.COLORS["success"]:
        errors.append("une réussite n'utilise pas le vert V2")

    info = discord.Embed(title="Profil", description="Aperçu du membre")
    command_style_v2.style_embed(info, category="profile", kind="info")
    if not str(info.title or "").startswith("✦ "):
        errors.append("les cartes d'information n'utilisent pas le repère ✦")

    # Composants : utile = conservé ; hiérarchie visuelle = cohérente.
    view = discord.ui.View(timeout=None)
    open_button = discord.ui.Button(
        label="Ouvrir",
        emoji="🎫",
        style=discord.ButtonStyle.secondary,
        custom_id="ticket:open",
    )
    save_button = discord.ui.Button(
        label="Enregistrer",
        emoji="✅",
        style=discord.ButtonStyle.secondary,
        custom_id="setup:save",
    )
    delete_button = discord.ui.Button(
        label="Supprimer",
        emoji="🗑️",
        style=discord.ButtonStyle.secondary,
        custom_id="ticket:delete",
    )
    neutral_button = discord.ui.Button(
        label="Retour",
        style=discord.ButtonStyle.primary,
        custom_id="nav:back",
    )
    for button in (open_button, save_button, delete_button, neutral_button):
        view.add_item(button)

    command_style_v2.style_view(view)

    if open_button.style is not discord.ButtonStyle.primary:
        errors.append("une action principale n'est pas violette/primaire")
    if save_button.style is not discord.ButtonStyle.success:
        errors.append("une validation n'est pas verte")
    if delete_button.style is not discord.ButtonStyle.danger:
        errors.append("une action destructive n'est pas rouge")
    if neutral_button.style is not discord.ButtonStyle.secondary:
        errors.append("une navigation neutre n'est pas secondaire")
    if open_button.emoji is None or save_button.emoji is None or delete_button.emoji is None:
        errors.append("les pictogrammes fonctionnels ont été supprimés")

    # Le moteur historique doit pointer vers le même renderer, sans wrapper de transport.
    if premium_style.style_embed is not command_style_v2.style_embed:
        errors.append("premium_style.style_embed n'est pas branché sur V2")
    if premium_style.style_view is not command_style_v2.style_view:
        errors.append("premium_style.style_view n'est pas branché sur V2")

    runtime_path = ROOT / "cogs" / "command_no_emoji_runtime.py"
    runtime_source = runtime_path.read_text(encoding="utf-8")
    if "command_style_v2.install(bot)" not in runtime_source:
        errors.append("la couche de compatibilité n'active pas command_style_v2")
    forbidden_transport_patches = (
        "commands.Context.send =",
        "discord.abc.Messageable.send =",
        "discord.InteractionResponse.send_message =",
        "discord.InteractionResponse.edit_message =",
        "discord.Interaction.edit_original_response =",
        "discord.Webhook.send =",
    )
    for marker in forbidden_transport_patches:
        if marker in runtime_source:
            errors.append(f"ancien monkeypatch de transport encore présent: {marker}")

    for error in errors:
        print(f"[ERROR] {error}")
    if errors:
        print(f"ECHEC: {len(errors)} probleme(s) de style commandes V2")
        return 1

    print("OK: thème global SentriX V2 — titres courts, palette premium, composants cohérents et pictogrammes utiles")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
