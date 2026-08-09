#!/usr/bin/env python3
"""Audit de la politique SentriX sans emoji décoratif dans les commandes."""
from __future__ import annotations

import asyncio
import inspect
import os
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _assert_clean_text(runtime, errors: list[str]) -> None:
    samples = (
        "✅ Terminé",
        "❌ Erreur",
        "⚠️ Attention",
        "🛡️ Sécurité",
        "💰 Argent",
        "📈 Niveaux",
        "🎮 Jeux",
        "<:check:123456789012345678> Validé",
        "<a:loading:123456789012345678> Chargement",
    )
    for sample in samples:
        cleaned = runtime.clean_text(sample)
        if runtime.has_emoji(cleaned):
            errors.append(f"clean_text conserve un emoji: {sample!r} -> {cleaned!r}")


def _assert_clean_objects(runtime, discord, errors: list[str]) -> None:
    embed = discord.Embed(title="✅ Test", description="🛡️ Protection active")
    embed.add_field(name="💰 Argent", value="📈 100 points", inline=False)
    embed.set_footer(text="⚠️ SentriX")
    embed.set_author(name="👑 Administration")
    cleaned = runtime.clean_embed(embed)
    texts = [cleaned.title, cleaned.description]
    texts.extend(field.name for field in cleaned.fields)
    texts.extend(field.value for field in cleaned.fields)
    texts.extend((cleaned.footer.text, cleaned.author.name))
    if any(runtime.has_emoji(value) for value in texts if value):
        errors.append("clean_embed conserve un emoji décoratif")

    view = discord.ui.View(timeout=None)
    button = discord.ui.Button(label="✅ Confirmer", emoji="✅")
    select = discord.ui.Select(
        placeholder="🛡️ Choisir",
        options=[discord.SelectOption(label="💰 Option", value="one", emoji="📈")],
    )
    view.add_item(button)
    view.add_item(select)
    runtime.clean_view(view)

    if button.emoji is not None or runtime.has_emoji(button.label):
        errors.append("bouton encore décoré par un emoji")
    if runtime.has_emoji(select.placeholder):
        errors.append("placeholder de select encore décoré par un emoji")
    for option in select.options:
        if option.emoji is not None or runtime.has_emoji(option.label) or runtime.has_emoji(option.description):
            errors.append("option de select encore décorée par un emoji")


async def run() -> int:
    errors: list[str] = []

    with tempfile.TemporaryDirectory(prefix="sentrix-no-emoji-") as temp_dir:
        os.environ.setdefault("DISCORD_TOKEN", "ci.fake.token")
        os.environ["DATABASE_PATH"] = str(pathlib.Path(temp_dir) / "no-emoji.db")

        import discord
        from discord.ext import commands
        import cogs
        import main
        from cogs import command_no_emoji_runtime as runtime
        from cogs import embed_builder

        _assert_clean_text(runtime, errors)
        _assert_clean_objects(runtime, discord, errors)

        bot = main.BotAllInOne()
        await bot.db.connect()
        loaded = 0
        for extension in main.EXTENSIONS:
            try:
                await bot.load_extension(extension)
                loaded += 1
            except Exception as exc:
                errors.append(f"extension {extension}: {type(exc).__name__}: {exc}")

        bot._prune_redundant_commands()

        if not getattr(bot, "_sentrix_no_emoji_commands", False):
            errors.append("marqueur global no-emoji absent sur le bot")
        if not getattr(commands.Context.send, "_sentrix_no_emoji_commands", False):
            errors.append("Context.send n'est pas protégé par le filtre no-emoji")
        if not getattr(discord.abc.Messageable.send, "_sentrix_no_emoji_commands", False):
            errors.append("Messageable.send n'est pas protégé pendant les commandes")
        if not getattr(discord.InteractionResponse.send_message, "_sentrix_no_emoji_commands", False):
            errors.append("InteractionResponse.send_message n'est pas protégé")
        if not getattr(discord.InteractionResponse.edit_message, "_sentrix_no_emoji_commands", False):
            errors.append("InteractionResponse.edit_message n'est pas protégé")
        if not getattr(discord.Interaction.edit_original_response, "_sentrix_no_emoji_commands", False):
            errors.append("edit_original_response n'est pas protégé")
        if not getattr(discord.Webhook.send, "_sentrix_no_emoji_commands", False):
            errors.append("followups application/Webhook.send non protégés")

        # Les métadonnées visibles dans le catalogue doivent elles aussi être propres.
        for command in bot.walk_commands():
            for attr in ("help", "brief", "description", "usage"):
                value = getattr(command, attr, None)
                if isinstance(value, str) and runtime.has_emoji(value):
                    errors.append(f"emoji dans métadonnée {command.qualified_name}.{attr}")
                    break

        # Le bouton Annuler de +embed avait historiquement un cercle puis une croix emoji.
        # Il doit désormais être uniquement textuel.
        dummy = type("DummyBot", (), {})()
        cogs._install_embed_component_fix(dummy)
        view = embed_builder.EmbedBuilderView(None, embed_builder.EmbedDraft(), 1)
        cancel = next(item for item in view.children if getattr(item, "label", None) == "Annuler")
        if cancel.emoji is not None:
            errors.append(f"+embed Annuler conserve un emoji: {cancel.emoji!r}")

        current = asyncio.current_task()
        pending = [task for task in asyncio.all_tasks() if task is not current and not task.done()]
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

        close_db = getattr(bot.db, "close", None)
        if close_db:
            result = close_db()
            if inspect.isawaitable(result):
                await result

    print(f"No-emoji commands audit: {loaded}/{len(main.EXTENSIONS)} extensions chargees")
    for error in errors:
        print(f"[ERROR] {error}")
    if errors:
        print(f"ECHEC: {len(errors)} probleme(s) no-emoji")
        return 1

    print("OK: toutes les commandes SentriX passent par le verrou final sans emoji decoratif")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
