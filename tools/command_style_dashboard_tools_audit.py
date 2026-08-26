#!/usr/bin/env python3
"""Audit ciblé du rework visuel global et des outils serveur dashboard."""
from __future__ import annotations

import asyncio
import inspect
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import discord

from utils import premium_style
from web import dashboard_server_tools


async def main() -> int:
    errors: list[str] = []

    class FakeCommand:
        cog_name = "Moderation"
        qualified_name = "ban"

    embed = discord.Embed(title="Membre banni", description="La sanction a été appliquée.")
    embed.add_field(name="membre", value="Test", inline=True)
    styled = premium_style.style_embed(embed, command=FakeCommand())
    if styled.title != "SentriX • Modération":
        errors.append(f"titre canonique inattendu: {styled.title!r}")
    if "La sanction a été appliquée." not in str(styled.description or ""):
        errors.append("le détail métier original n'est pas conservé dans la description")
    if not styled.fields or styled.fields[0].name != "membre":
        errors.append("les noms de champs ne sont pas harmonisés en sections sobres")

    specialized = discord.Embed(title="SENTRIX / COMMANDES", description="Catalogue")
    premium_style.style_embed(specialized, command=FakeCommand())
    if specialized.title != "SentriX • Commandes":
        errors.append("un centre SentriX spécialisé a perdu son titre")

    view = discord.ui.View(timeout=None)
    save = discord.ui.Button(label="Enregistrer", style=discord.ButtonStyle.success)
    wipe = discord.ui.Button(label="Wipe serveur", style=discord.ButtonStyle.success)
    view.add_item(save)
    view.add_item(wipe)
    premium_style.style_view(view)
    if save.style is not discord.ButtonStyle.primary:
        errors.append("les actions principales doivent utiliser le style primaire, pas une rangée verte")
    if wipe.style is not discord.ButtonStyle.danger:
        errors.append("le wipe doit rester une action destructive rouge")

    source = inspect.getsource(dashboard_server_tools)
    required = (
        "/api/guilds/{guild_id}/server-tools/create",
        "/api/guilds/{guild_id}/server-tools/wipe",
        "cog.build_server(guild, template_key, actor)",
        "user_id != int(guild.owner_id)",
        "typed_name != guild.name",
        "server_tool_lock",
    )
    for marker in required:
        if marker not in source:
            errors.append(f"garde dashboard manquante: {marker}")

    if "<dialog class=\"sx-wipe-dialog\"" not in dashboard_server_tools.SERVER_TOOLS_JS:
        errors.append("confirmation visuelle du wipe absente du dashboard")
    if "Configurer avec ce modèle" not in dashboard_server_tools.SERVER_TOOLS_JS:
        errors.append("bouton create-server dashboard absent")

    view.stop()

    if errors:
        for error in errors:
            print(f"[ERROR] {error}")
        print(f"ECHEC: {len(errors)} problème(s)")
        return 1

    print("OK: style global SentriX et outils create-server/wipe dashboard validés")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
